"""Tools the specialist agents can call.

Playlist lesson "Tools / Tool Calling": a tool is a function plus a schema the LLM sees. Here the
order tools take the customer from the graph state (`runtime.state`), NOT from an argument. The
`runtime` parameter is injected by LangChain and hidden from the model's schema, so the model
cannot choose, change or invent whose orders it reads.
"""

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

from app import config, db, orders, rag


def _customer(runtime: ToolRuntime) -> str:
    return (runtime.state.get("customer_email") or "").strip().lower()


# ---------- Orders agent tools ----------
@tool
def get_order_status(order_id: str, runtime: ToolRuntime) -> dict:
    """Look up one of the signed-in customer's orders by ID (e.g. ORD-1001).
    Returns item, status, total and ETA."""
    return orders.lookup(_customer(runtime), order_id)


@tool
def list_customer_orders(runtime: ToolRuntime) -> list[dict]:
    """List all orders of the signed-in customer. Takes no arguments."""
    return orders.list_for(_customer(runtime))


@tool
def cancel_order(order_id: str, runtime: ToolRuntime) -> dict:
    """Cancel one of the signed-in customer's orders. Only allowed while its status is 'processing'."""
    return orders.cancel(_customer(runtime), order_id)


# ---------- FAQ agent tool (RAG) ----------
@tool
def search_faq(query: str) -> list[dict]:
    """Search the store's knowledge base (shipping, returns, refunds, orders, payments, warranty,
    account, contact). Returns the best-matching sections, each with the name to cite."""
    kb = rag.get_kb(config.KB_DIR, config.RAG_EMBEDDINGS, config.RAG_RERANK)
    hits = kb.search(query, k=3, mode=config.RAG_MODE, min_similarity=config.RAG_MIN_SIMILARITY)
    if not hits:
        return [{"error": "No matching knowledge-base entry."}]
    return [{"source": h.doc.metadata["id"], "content": h.doc.metadata["text"]} for h in hits]


# ---------- Escalation (plain functions, not LLM tools: the graph decides when to escalate) ----------
def create_ticket(summary: str, customer_email: str = "", thread_id: str | None = None) -> dict:
    """Open a ticket for a human agent and remember which conversation to resume when they reply."""
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (customer_email, summary, thread_id) VALUES (?, ?, ?)",
            (customer_email or None, summary, thread_id),
        )
        ticket_id = cur.lastrowid
    return {"ticket_id": ticket_id, "status": "open"}


def resolve_ticket(ticket_id: int, resolution: str) -> None:
    with db.connect() as conn:
        conn.execute(
            "UPDATE tickets SET status = 'resolved', resolution = ? WHERE ticket_id = ?",
            (resolution, ticket_id),
        )


ORDER_TOOLS = [get_order_status, list_customer_orders, cancel_order]
FAQ_TOOLS = [search_faq]
