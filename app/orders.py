"""Order operations, always scoped to ONE customer.

Every query filters on customer_email, and that email comes from the authenticated session, never
from the LLM. An order that belongs to someone else is reported exactly like one that does not
exist, so the system also does not reveal which order IDs are real.
"""

from app import db

NOT_SIGNED_IN = {"error": "The customer is not signed in. Ask them to log in to see or change orders."}


def _not_found(order_id: str) -> dict:
    return {"error": f"No order {order_id.strip().upper()} was found on this customer's account."}


def lookup(customer_email: str, order_id: str) -> dict:
    if not customer_email:
        return NOT_SIGNED_IN
    with db.connect() as conn:
        row = conn.execute(
            "SELECT order_id, item, status, total, eta FROM orders WHERE order_id = ? AND customer_email = ?",
            (order_id.strip().upper(), customer_email),
        ).fetchone()
    return dict(row) if row else _not_found(order_id)


def list_for(customer_email: str) -> list[dict]:
    if not customer_email:
        return [NOT_SIGNED_IN]
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT order_id, item, status, total, eta FROM orders WHERE customer_email = ? ORDER BY order_id",
            (customer_email,),
        ).fetchall()
    return [dict(r) for r in rows] or [{"error": "This customer has no orders."}]


def cancel(customer_email: str, order_id: str) -> dict:
    """Cancel an order that belongs to the customer, only while it is still 'processing'."""
    if not customer_email:
        return NOT_SIGNED_IN
    oid = order_id.strip().upper()
    with db.connect() as conn:
        row = conn.execute(
            "SELECT status FROM orders WHERE order_id = ? AND customer_email = ?", (oid, customer_email)
        ).fetchone()
        if not row:
            return _not_found(order_id)
        if row["status"] != "processing":
            return {"error": f"Cannot cancel: order is already '{row['status']}'."}
        conn.execute(
            "UPDATE orders SET status = 'cancelled' WHERE order_id = ? AND customer_email = ?",
            (oid, customer_email),
        )
    return {"order_id": oid, "status": "cancelled"}
