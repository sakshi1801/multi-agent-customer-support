from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from app.graph import MAX_HOPS, Route, build_graph, make_llm_router
from tests.conftest import AGENT_HEADERS, FakeSpecialistLLM, login


def agents(resp) -> list[str]:
    return [r["agent"] for r in resp["replies"]]


# ---------- routing to a single specialist ----------
def test_order_status_goes_to_orders_agent(client):
    h = login(client, "asha@example.com")
    r = client.post("/chat", json={"message": "Where is ORD-1001?"}, headers=h).json()
    assert r["status"] == "answered"
    assert agents(r) == ["orders"]
    assert "shipped" in r["replies"][0]["content"]


def test_policy_question_works_without_login(client):
    r = client.post("/chat", json={"message": "What is your return policy?"}).json()
    assert agents(r) == ["faq"]
    assert "30 days" in r["replies"][0]["content"]


def test_orders_agent_uses_the_logged_in_customer(client):
    h = login(client, "ravi@example.com")
    r = client.post("/chat", json={"message": "Show me my orders"}, headers=h).json()
    assert agents(r) == ["orders"]
    assert "ORD-1003" in r["replies"][0]["content"]
    assert "ORD-1001" not in r["replies"][0]["content"]  # Asha's


def test_cancel_processing_order(client):
    h = login(client, "asha@example.com")
    r = client.post("/chat", json={"message": "Please cancel ORD-1002"}, headers=h).json()
    assert "cancelled" in r["replies"][0]["content"]


def test_anonymous_user_cannot_see_orders(client):
    r = client.post("/chat", json={"message": "Where is ORD-1001?"}).json()
    assert "not signed in" in r["replies"][0]["content"]
    assert "Wireless Mouse" not in r["replies"][0]["content"]


# ---------- multi-agent in one turn ----------
def test_two_part_question_visits_both_specialists(client):
    h = login(client, "meera@example.com")
    r = client.post(
        "/chat", json={"message": "Status of ORD-1005, and what is the shipping policy?"}, headers=h
    ).json()
    assert agents(r) == ["orders", "faq"]


# ---------- human-in-the-loop escalation ----------
def test_escalation_pauses_then_human_reply_resumes(client):
    h = login(client, "asha@example.com")
    r = client.post("/chat", json={"message": "This is unacceptable, I want a human"}, headers=h).json()
    assert r["status"] == "waiting_for_human"
    assert agents(r) == ["escalation"]
    ticket_id = r["ticket_id"]
    assert ticket_id is not None

    open_tickets = client.get("/tickets", headers=AGENT_HEADERS).json()
    assert [t["ticket_id"] for t in open_tickets] == [ticket_id]  # created exactly once
    assert open_tickets[0]["thread_id"] == r["thread_id"]  # F2: the human can find the conversation
    assert open_tickets[0]["customer_email"] == "asha@example.com"

    done = client.post(
        f"/tickets/{ticket_id}/reply",
        json={"reply": "Sorry! We're sending a replacement."},
        headers=AGENT_HEADERS,
    ).json()
    assert done["status"] == "answered"
    assert agents(done) == ["escalation", "human_agent"]
    assert "replacement" in done["replies"][-1]["content"]
    assert client.get("/tickets", headers=AGENT_HEADERS).json() == []  # resolved


def test_chat_on_waiting_thread_is_rejected(client):
    r = client.post("/chat", json={"message": "I want a human now"}).json()
    again = client.post("/chat", json={"message": "hello?", "thread_id": r["thread_id"]})
    assert again.status_code == 409


def test_reply_to_unknown_ticket_404(client):
    assert client.post("/tickets/999/reply", json={"reply": "hi"}, headers=AGENT_HEADERS).status_code == 404


def test_cannot_reply_twice_to_the_same_ticket(client):
    r = client.post("/chat", json={"message": "I want a human"}).json()
    url = f"/tickets/{r['ticket_id']}/reply"
    assert client.post(url, json={"reply": "first"}, headers=AGENT_HEADERS).status_code == 200
    assert client.post(url, json={"reply": "second"}, headers=AGENT_HEADERS).status_code == 404


# ---------- F3: per-turn state is reset ----------
def test_ticket_id_does_not_leak_into_later_turns(client):
    h = login(client, "asha@example.com")
    esc = client.post("/chat", json={"message": "I want a human"}, headers=h).json()
    client.post(f"/tickets/{esc['ticket_id']}/reply", json={"reply": "done"}, headers=AGENT_HEADERS)
    later = client.post(
        "/chat", json={"message": "Where is ORD-1001?", "thread_id": esc["thread_id"]}, headers=h
    ).json()
    assert agents(later) == ["orders"]
    assert later["ticket_id"] is None


# ---------- conversation memory & safety ----------
def test_same_thread_only_returns_latest_turn_replies(client):
    h = login(client, "asha@example.com")
    first = client.post("/chat", json={"message": "Where is ORD-1001?"}, headers=h).json()
    second = client.post(
        "/chat",
        json={"message": "And what is the return policy?", "thread_id": first["thread_id"]},
        headers=h,
    ).json()
    assert agents(second) == ["faq"]


def test_supervisor_never_runs_a_specialist_twice_per_message(temp_db):
    """F12: a router that keeps choosing 'orders' must not produce duplicate replies."""
    looping = build_graph(llm=FakeSpecialistLLM(), router=lambda msgs: "orders")
    out = looping.invoke(
        {
            "messages": [HumanMessage("Where is ORD-1001?")],
            "hops": 0,
            "visited": [],
            "customer_email": "asha@example.com",
        },
        {"configurable": {"thread_id": "loop"}},
    )
    assert out["visited"] == ["orders"]
    assert [m.name for m in out["messages"] if getattr(m, "name", None)] == ["orders"]
    assert out["hops"] <= MAX_HOPS


def test_empty_message_rejected(client):
    assert client.post("/chat", json={"message": ""}).status_code == 422


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


# ---------- failure handling (F4) ----------
def test_router_failure_escalates_instead_of_crashing(temp_db):
    def broken_router(messages):
        raise RuntimeError("model is down")

    g = build_graph(llm=FakeSpecialistLLM(), router=broken_router)
    out = g.invoke(
        {"messages": [HumanMessage("Where is ORD-1001?")], "hops": 0, "visited": [], "customer_email": ""},
        {"configurable": {"thread_id": "t"}},
    )
    assert out["ticket_id"] is not None  # a human will pick it up
    assert g.get_state({"configurable": {"thread_id": "t"}}).next  # paused for the human


def test_specialist_failure_gives_a_polite_reply(temp_db):
    class BrokenLLM(FakeSpecialistLLM):
        def _generate(self, *args, **kwargs):
            raise RuntimeError("rate limited")

    g = build_graph(llm=BrokenLLM(), router=lambda m: "orders" if len(m) < 2 else "FINISH")
    out = g.invoke(
        {
            "messages": [HumanMessage("Where is ORD-1001?")],
            "hops": 0,
            "visited": [],
            "customer_email": "a@b.c",
        },
        {"configurable": {"thread_id": "t"}},
    )
    assert "couldn't look that up" in out["messages"][-1].content


def test_unexpected_graph_error_returns_503_not_a_stack_trace(temp_db):
    from fastapi.testclient import TestClient

    from app.main import create_app

    class ExplodingGraph:
        def get_state(self, config):
            from types import SimpleNamespace

            return SimpleNamespace(values={}, next=())

        def invoke(self, *a, **k):
            raise RuntimeError("boom with secrets")

    with TestClient(create_app(graph=ExplodingGraph())) as c:
        r = c.post("/chat", json={"message": "hi"})
    assert r.status_code == 503
    assert "boom" not in r.text


# ---------- the real LLM router code path (structured output) ----------
def test_llm_router_returns_structured_choice():
    seen = {}

    class StubLLM:
        def with_structured_output(self, schema, method=None):
            assert schema is Route
            assert method == "function_calling"  # portable across providers
            return RunnableLambda(lambda prompt_value: seen.setdefault("out", Route(next="faq")))

    route = make_llm_router(StubLLM())
    assert route([HumanMessage("what is the warranty?")]) == "faq"


# ---------- F6: paused conversations survive a restart ----------
def test_paused_escalation_survives_a_restart(tmp_path, temp_db):
    import sqlite3

    from fastapi.testclient import TestClient
    from langgraph.checkpoint.sqlite import SqliteSaver

    from app.main import create_app
    from tests.conftest import keyword_router

    checkpoints = str(tmp_path / "checkpoints.db")

    def new_process():  # a fresh graph over the same files, like restarting the server
        conn = sqlite3.connect(checkpoints, check_same_thread=False)
        g = build_graph(llm=FakeSpecialistLLM(), router=keyword_router, checkpointer=SqliteSaver(conn))
        return TestClient(create_app(graph=g))

    with new_process() as before:
        r = before.post("/chat", json={"message": "I want a human"}).json()
        assert r["status"] == "waiting_for_human"

    with new_process() as after:  # the first "server" is gone
        done = after.post(
            f"/tickets/{r['ticket_id']}/reply", json={"reply": "Back online, sorry!"}, headers=AGENT_HEADERS
        ).json()
    assert done["status"] == "answered" and "Back online" in done["replies"][-1]["content"]
