"""Tools the specialist agents can call. Plain functions + @tool decorator."""
import re
from pathlib import Path

from langchain_core.tools import tool

from app import config, db


# ---------- Orders agent tools ----------
@tool
def get_order_status(order_id: str) -> dict:
    """Look up one order by its ID (e.g. ORD-1001). Returns item, status, total and ETA."""
    with db.connect() as conn:
        row = conn.execute(
            "SELECT * FROM orders WHERE order_id = ?", (order_id.strip().upper(),)
        ).fetchone()
    return dict(row) if row else {"error": f"No order found with ID {order_id}"}


@tool
def list_customer_orders(email: str) -> list[dict]:
    """List all orders placed by a customer email address."""
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT * FROM orders WHERE customer_email = ? ORDER BY order_id",
            (email.strip().lower(),),
        ).fetchall()
    return [dict(r) for r in rows] or [{"error": f"No orders found for {email}"}]


@tool
def cancel_order(order_id: str) -> dict:
    """Cancel an order. Only allowed while the order status is 'processing'."""
    oid = order_id.strip().upper()
    with db.connect() as conn:
        row = conn.execute("SELECT status FROM orders WHERE order_id = ?", (oid,)).fetchone()
        if not row:
            return {"error": f"No order found with ID {order_id}"}
        if row["status"] != "processing":
            return {"error": f"Cannot cancel: order is already '{row['status']}'."}
        conn.execute("UPDATE orders SET status = 'cancelled' WHERE order_id = ?", (oid,))
    return {"order_id": oid, "status": "cancelled"}


# ---------- FAQ agent tool ----------
def _load_faq_sections() -> list[tuple[str, str]]:
    text = Path(config.FAQ_PATH).read_text(encoding="utf-8")
    parts = re.split(r"^# (.+)$", text, flags=re.MULTILINE)
    # parts = ['', title1, body1, title2, body2, ...]
    return [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts) - 1, 2)]


def _tokens(s: str) -> set[str]:
    return set(re.findall(r"[a-z]{3,}", s.lower()))


@tool
def search_faq(query: str) -> list[dict]:
    """Search the store's policy FAQ (shipping, returns, cancellations, payments,
    warranty, contact). Returns the best-matching sections."""
    q = _tokens(query)
    scored = []
    for title, body in _load_faq_sections():
        score = len(q & _tokens(title)) * 3 + len(q & _tokens(body))
        if score:
            scored.append((score, {"section": title, "content": body}))
    scored.sort(key=lambda x: -x[0])
    return [item for _, item in scored[:2]] or [{"error": "No matching FAQ entry."}]


# ---------- Escalation tool ----------
@tool
def create_escalation_ticket(summary: str, customer_email: str = "") -> dict:
    """Create a ticket for a human support agent. Use when the customer is upset,
    asks for a human, or the issue can't be solved with the other tools."""
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO tickets (customer_email, summary) VALUES (?, ?)",
            (customer_email or None, summary),
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
