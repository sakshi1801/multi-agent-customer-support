from app import db, tools


def test_get_order_status_found(temp_db):
    out = tools.get_order_status.invoke({"order_id": "ord-1001"})  # case-insensitive
    assert out["status"] == "shipped" and out["item"] == "Wireless Mouse"


def test_get_order_status_not_found(temp_db):
    assert "error" in tools.get_order_status.invoke({"order_id": "ORD-9999"})


def test_list_customer_orders(temp_db):
    out = tools.list_customer_orders.invoke({"email": "Asha@Example.com"})
    assert [o["order_id"] for o in out] == ["ORD-1001", "ORD-1002"]


def test_cancel_only_when_processing(temp_db):
    assert tools.cancel_order.invoke({"order_id": "ORD-1002"})["status"] == "cancelled"
    assert "error" in tools.cancel_order.invoke({"order_id": "ORD-1001"})  # already shipped
    assert "error" in tools.cancel_order.invoke({"order_id": "ORD-0000"})  # does not exist


def test_search_faq_returns_relevant_section(temp_db):
    out = tools.search_faq.invoke({"query": "what is your return policy"})
    assert out[0]["section"] == "Returns"
    assert "30 days" in out[0]["content"]


def test_search_faq_no_match(temp_db):
    assert "error" in tools.search_faq.invoke({"query": "zzzz qqqq"})[0]


def test_escalation_ticket_roundtrip(temp_db):
    t = tools.create_escalation_ticket.invoke({"summary": "Item arrived broken", "customer_email": "a@b.com"})
    assert t["status"] == "open"
    tools.resolve_ticket(t["ticket_id"], "Replacement sent")
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (t["ticket_id"],)).fetchone()
    assert row["status"] == "resolved" and row["resolution"] == "Replacement sent"
