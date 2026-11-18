from langchain_core.messages import HumanMessage

from app.graph import MAX_HOPS, Route, build_graph, make_llm_router
from tests.conftest import FakeSpecialistLLM


def agents(resp) -> list[str]:
    return [r["agent"] for r in resp["replies"]]


# ---------- routing to a single specialist ----------
def test_order_status_goes_to_orders_agent(client):
    r = client.post("/chat", json={"message": "Where is ORD-1001?"}).json()
    assert r["status"] == "answered"
    assert agents(r) == ["orders"]
    assert "shipped" in r["replies"][0]["content"]


def test_policy_question_goes_to_faq_agent(client):
    r = client.post("/chat", json={"message": "What is your return policy?"}).json()
    assert agents(r) == ["faq"]
    assert "30 days" in r["replies"][0]["content"]


def test_orders_agent_uses_customer_email_when_no_order_id(client):
    r = client.post(
        "/chat", json={"message": "Show me my orders", "customer_email": "Ravi@Example.com"}
    ).json()
    assert agents(r) == ["orders"]
    assert "ORD-1003" in r["replies"][0]["content"]


def test_cancel_processing_order(client):
    r = client.post("/chat", json={"message": "Please cancel ORD-1002"}).json()
    assert "cancelled" in r["replies"][0]["content"]


# ---------- multi-agent in one turn ----------
def test_two_part_question_visits_both_specialists(client):
    r = client.post(
        "/chat", json={"message": "Status of ORD-1005, and what is the shipping policy?"}
    ).json()
    assert agents(r) == ["orders", "faq"]


# ---------- human-in-the-loop escalation ----------
def test_escalation_pauses_then_human_reply_resumes(client):
    r = client.post(
        "/chat",
        json={"message": "This is unacceptable, I want a human", "customer_email": "asha@example.com"},
    ).json()
    assert r["status"] == "waiting_for_human"
    assert agents(r) == ["escalation"]
    tid, ticket_id = r["thread_id"], r["ticket_id"]
    assert ticket_id is not None

    open_tickets = client.get("/tickets").json()
    assert [t["ticket_id"] for t in open_tickets] == [ticket_id]  # created exactly once

    done = client.post(f"/tickets/{tid}/reply", json={"reply": "Sorry! We're sending a replacement."}).json()
    assert done["status"] == "answered"
    assert agents(done) == ["escalation", "human_agent"]
    assert "replacement" in done["replies"][-1]["content"]
    assert client.get("/tickets").json() == []  # resolved


def test_chat_on_waiting_thread_is_rejected(client):
    r = client.post("/chat", json={"message": "I want a human now"}).json()
    again = client.post("/chat", json={"message": "hello?", "thread_id": r["thread_id"]})
    assert again.status_code == 409


def test_reply_to_unknown_thread_404(client):
    assert client.post("/tickets/nope/reply", json={"reply": "hi"}).status_code == 404


# ---------- conversation memory & safety ----------
def test_same_thread_only_returns_latest_turn_replies(client):
    first = client.post("/chat", json={"message": "Where is ORD-1001?"}).json()
    second = client.post(
        "/chat", json={"message": "And what is the return policy?", "thread_id": first["thread_id"]}
    ).json()
    assert agents(second) == ["faq"]


def test_hop_limit_prevents_infinite_loops(temp_db):
    looping = build_graph(llm=FakeSpecialistLLM(), router=lambda msgs: "orders")
    out = looping.invoke(
        {"messages": [HumanMessage("Where is ORD-1001?")], "hops": 0, "customer_email": ""},
        {"configurable": {"thread_id": "loop"}},
    )
    assert out["hops"] == MAX_HOPS


def test_empty_message_rejected(client):
    assert client.post("/chat", json={"message": ""}).status_code == 422


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---------- the real LLM router code path (structured output) ----------
def test_llm_router_returns_structured_choice():
    class StubStructured:
        def invoke(self, messages):
            return Route(next="faq")

    class StubLLM:
        def with_structured_output(self, schema):
            assert schema is Route
            return StubStructured()

    route = make_llm_router(StubLLM())
    assert route([HumanMessage("what is the warranty?")]) == "faq"
