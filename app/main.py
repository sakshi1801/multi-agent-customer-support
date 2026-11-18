"""FastAPI service exposing the support graph.

POST /chat                  customer sends a message
POST /tickets/{thread}/reply  a human agent answers an escalated thread
GET  /tickets               open tickets (for a human-agent dashboard)
GET  /health
"""

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command
from pydantic import BaseModel, Field

from app import db
from app.graph import build_graph


# ---------- schemas (structured outputs) ----------
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    thread_id: str | None = Field(default=None, description="Reuse to continue a conversation")
    customer_email: str = ""


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


# ---------- helpers ----------
def _replies_since_last_customer_message(messages: list) -> list[AgentReply]:
    last_human = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    return [
        AgentReply(agent=m.name, content=str(m.content))
        for m in messages[last_human + 1 :]
        if isinstance(m, AIMessage) and m.name
    ]


def _response(graph, config: dict, thread_id: str) -> ChatResponse:
    snap = graph.get_state(config)
    waiting = bool(snap.next)
    return ChatResponse(
        thread_id=thread_id,
        status="waiting_for_human" if waiting else "answered",
        replies=_replies_since_last_customer_message(snap.values.get("messages", [])),
        ticket_id=snap.values.get("ticket_id"),
    )


def create_app(graph=None) -> FastAPI:
    """App factory. Pass a pre-built graph in tests; otherwise one is built at startup."""

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init_db()
        app.state.graph = graph or build_graph()
        yield

    app = FastAPI(title="Multi-Agent Customer Support", version="1.0.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest):
        g = app.state.graph
        thread_id = req.thread_id or str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}

        if g.get_state(config).next:
            raise HTTPException(409, "This conversation is waiting for a human agent to reply.")

        g.invoke(
            {
                "messages": [HumanMessage(req.message)],
                "hops": 0,  # reset the hop counter for every new customer message
                "customer_email": req.customer_email.strip().lower(),
            },
            config,
        )
        return _response(g, config, thread_id)

    @app.post("/tickets/{thread_id}/reply", response_model=ChatResponse)
    def human_reply(thread_id: str, body: HumanReply):
        g = app.state.graph
        config = {"configurable": {"thread_id": thread_id}}
        if not g.get_state(config).next:
            raise HTTPException(404, "No conversation is waiting for a human reply on this thread.")
        g.invoke(Command(resume=body.reply), config)
        return _response(g, config, thread_id)

    @app.get("/tickets")
    def open_tickets():
        with db.connect() as conn:
            rows = conn.execute("SELECT * FROM tickets WHERE status = 'open' ORDER BY ticket_id").fetchall()
        return [dict(r) for r in rows]

    return app


app = create_app()
