"""FastAPI service exposing the support graph.

POST /auth/login               customer logs in -> signed bearer token
POST /chat                     customer sends a message (token optional: anonymous users get the FAQ only)
GET  /tickets                  open tickets, for the human-agent dashboard        [X-API-Key]
POST /tickets/{id}/reply       a human agent answers an escalated ticket          [X-API-Key]
GET  /health
"""

import logging
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import auth, config, db
from app.graph import build_graph

logger = logging.getLogger(__name__)


# ---------- schemas (structured outputs) ----------
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, description="Reuse to continue a conversation")


class AgentReply(BaseModel):
    agent: str
    content: str


class ChatResponse(BaseModel):
    thread_id: str
    status: str  # 'answered' | 'waiting_for_human'
    replies: list[AgentReply]
    ticket_id: int | None = None


class HumanReply(BaseModel):
    reply: str = Field(min_length=1, max_length=2000)


class Ticket(BaseModel):
    ticket_id: int
    customer_email: str | None
    summary: str
    status: str
    thread_id: str | None


# ---------- dependencies ----------
def current_customer(authorization: str | None = Header(default=None)) -> str:
    """Email of the logged-in customer, or '' for an anonymous visitor. A bad token is rejected."""
    if not authorization:
        return ""
    scheme, _, token = authorization.partition(" ")
    email = auth.verify_token(token) if scheme.lower() == "bearer" else None
    if not email:
        raise HTTPException(401, "Invalid or expired token. Please log in again.")
    return email


def require_agent_key(x_api_key: str | None = Header(default=None)) -> None:
    if not auth.agent_key_matches(x_api_key):
        # Same answer whether the key is wrong, missing, or not configured on the server.
        raise HTTPException(401, "A valid X-API-Key header is required.")


# ---------- helpers ----------
def _replies_since_last_customer_message(messages: list) -> list[AgentReply]:
    last_human = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    return [
        AgentReply(agent=m.name, content=str(m.content))
        for m in messages[last_human + 1 :]
        if isinstance(m, AIMessage) and m.name
    ]


def _response(graph, config_: dict, thread_id: str) -> ChatResponse:
    snap = graph.get_state(config_)
    return ChatResponse(
        thread_id=thread_id,
        status="waiting_for_human" if snap.next else "answered",
        replies=_replies_since_last_customer_message(snap.values.get("messages", [])),
        ticket_id=snap.values.get("ticket_id"),
    )


def _sqlite_graph():
    """Graph whose conversation state lives in SQLite, so paused escalations survive a restart."""
    Path(config.CHECKPOINT_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.CHECKPOINT_PATH, check_same_thread=False)
    return build_graph(checkpointer=SqliteSaver(conn))


def create_app(graph=None) -> FastAPI:
    """App factory. Pass a pre-built graph in tests; otherwise one is built at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db()
        app.state.graph = graph or _sqlite_graph()
        yield

    app = FastAPI(title="Multi-Agent Customer Support", version="1.1.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/auth/login", response_model=TokenResponse)
    def login(body: LoginRequest):
        email = body.email.strip().lower()
        with db.connect() as conn:
            row = conn.execute("SELECT password_hash FROM customers WHERE email = ?", (email,)).fetchone()
        if not auth.verify_password(body.password, row["password_hash"] if row else None):
            raise HTTPException(401, "Wrong email or password.")
        return TokenResponse(access_token=auth.create_token(email))

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest, customer_email: str = Depends(current_customer)):
        g = app.state.graph
        thread_id = req.thread_id or str(uuid.uuid4())
        run_config = {"configurable": {"thread_id": thread_id}}

        snap = g.get_state(run_config)
        if snap.values.get("messages") and snap.values.get("customer_email", "") != customer_email:
            raise HTTPException(403, "This conversation belongs to someone else.")
        if snap.next:
            raise HTTPException(409, "This conversation is waiting for a human agent to reply.")

        try:
            g.invoke(
                {
                    "messages": [HumanMessage(req.message)],
                    # Per-message state is reset on every turn.
                    "hops": 0,
                    "visited": [],
                    "ticket_id": None,
                    "customer_email": customer_email,
                },
                run_config,
            )
        except Exception as exc:
            logger.exception("chat failed")
            raise HTTPException(
                503, "The assistant is temporarily unavailable. Please try again shortly."
            ) from exc
        return _response(g, run_config, thread_id)

    @app.get("/tickets", response_model=list[Ticket], dependencies=[Depends(require_agent_key)])
    def open_tickets():
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT ticket_id, customer_email, summary, status, thread_id "
                "FROM tickets WHERE status = 'open' ORDER BY ticket_id"
            ).fetchall()
        return [dict(r) for r in rows]

    @app.post(
        "/tickets/{ticket_id}/reply",
        response_model=ChatResponse,
        dependencies=[Depends(require_agent_key)],
    )
    def human_reply(ticket_id: int, body: HumanReply):
        g = app.state.graph
        with db.connect() as conn:
            row = conn.execute(
                "SELECT thread_id FROM tickets WHERE ticket_id = ? AND status = 'open'", (ticket_id,)
            ).fetchone()
        if not row or not row["thread_id"]:
            raise HTTPException(404, "No open ticket with that ID.")
        run_config = {"configurable": {"thread_id": row["thread_id"]}}
        if not g.get_state(run_config).next:
            raise HTTPException(409, "This ticket's conversation is no longer waiting for a reply.")
        g.invoke(Command(resume=body.reply), run_config)
        return _response(g, run_config, row["thread_id"])

    return app


app = create_app()
