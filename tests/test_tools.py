from app import auth, db, orders, tools


# ---------- orders: every operation is scoped to one customer ----------
def test_lookup_own_order_is_case_insensitive(temp_db):
    out = orders.lookup("asha@example.com", "ord-1001")
    assert out["status"] == "shipped" and out["item"] == "Wireless Mouse"


def test_lookup_hides_other_customers_orders(temp_db):
    out = orders.lookup("ravi@example.com", "ORD-1002")  # belongs to Asha
    assert "error" in out and "Wireless" not in str(out) and "USB-C" not in str(out)


def test_missing_and_foreign_orders_look_identical(temp_db):
    """No oracle: an attacker cannot tell which order IDs exist."""
    foreign = orders.lookup("ravi@example.com", "ORD-1002")["error"]
    missing = orders.lookup("ravi@example.com", "ORD-9999")["error"]
    assert foreign.replace("ORD-1002", "X") == missing.replace("ORD-9999", "X")


def test_list_only_returns_own_orders(temp_db):
    out = orders.list_for("asha@example.com")
    assert [o["order_id"] for o in out] == ["ORD-1001", "ORD-1002"]


def test_cancel_only_when_processing(temp_db):
    assert orders.cancel("asha@example.com", "ORD-1002")["status"] == "cancelled"
    assert "error" in orders.cancel("asha@example.com", "ORD-1001")  # already shipped
    assert "error" in orders.cancel("asha@example.com", "ORD-0000")  # does not exist


def test_cannot_cancel_someone_elses_order(temp_db):
    assert "error" in orders.cancel("ravi@example.com", "ORD-1002")
    assert orders.lookup("asha@example.com", "ORD-1002")["status"] == "processing"  # untouched


def test_anonymous_customer_gets_nothing(temp_db):
    for out in (orders.lookup("", "ORD-1001"), orders.cancel("", "ORD-1002")):
        assert "not signed in" in out["error"]
    assert "not signed in" in orders.list_for("")[0]["error"]


# ---------- tool schema: the LLM must not be able to choose the customer ----------
def test_llm_visible_schema_has_no_identity_argument():
    for t in tools.ORDER_TOOLS:
        args = set(t.tool_call_schema.model_json_schema().get("properties", {}))
        assert args <= {"order_id"}, f"{t.name} exposes {args}"


# ---------- FAQ and tickets ----------
def test_search_faq_cites_the_section_it_used(temp_db):
    out = tools.search_faq.invoke({"query": "what is your return policy, how many days"})
    window = next(o for o in out if o["source"] == "Returns > Return window")  # (ranking quality: evals/)
    assert "30 days" in window["content"]
    assert len(out) <= 3 and all({"source", "content"} <= set(o) for o in out)


def test_search_faq_says_nothing_matches_for_off_topic_questions(temp_db):
    assert "error" in tools.search_faq.invoke({"query": "zzzz qqqq xxxx"})[0]


def test_ticket_roundtrip_keeps_thread_id(temp_db):
    t = tools.create_ticket("Item arrived broken", "a@b.com", thread_id="thread-1")
    assert t["status"] == "open"
    tools.resolve_ticket(t["ticket_id"], "Replacement sent")
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM tickets WHERE ticket_id = ?", (t["ticket_id"],)).fetchone()
    assert row["status"] == "resolved" and row["resolution"] == "Replacement sent"
    assert row["thread_id"] == "thread-1"


# ---------- auth helpers ----------
def test_password_hashing_and_verification():
    stored = auth.hash_password("s3cret")
    assert auth.verify_password("s3cret", stored)
    assert not auth.verify_password("wrong", stored)
    assert not auth.verify_password("anything", None)  # unknown user


def test_token_roundtrip_and_tampering():
    token = auth.create_token("asha@example.com")
    assert auth.verify_token(token) == "asha@example.com"
    payload, signature = token.split(".")
    assert auth.verify_token(f"{payload}.{signature[:-2]}xx") is None  # bad signature
    assert auth.verify_token("garbage") is None
    assert auth.verify_token(auth.create_token("asha@example.com", ttl=-1)) is None  # expired


def test_token_signed_with_another_secret_is_rejected(monkeypatch):
    token = auth.create_token("asha@example.com")
    monkeypatch.setenv("TOKEN_SECRET", "a-different-secret")
    assert auth.verify_token(token) is None


def test_old_database_without_thread_id_is_migrated(tmp_path, monkeypatch):
    import sqlite3

    path = str(tmp_path / "old.db")
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE tickets (ticket_id INTEGER PRIMARY KEY, customer_email TEXT, summary TEXT, status TEXT, resolution TEXT)"
    )
    conn.commit()
    conn.close()
    db.init_db(path)
    with db.connect(path) as c:
        assert "thread_id" in {r["name"] for r in c.execute("PRAGMA table_info(tickets)")}
