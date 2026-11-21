"""Plan-mode supervisor (one model call decides every specialist) and replies that need no specialist."""

import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableLambda

from app.graph import Plan, build_graph, make_llm_planner, normalize_plan, small_talk_reply
from app.testing import FakeSpecialistLLM
from tests.conftest import login


def agents(resp) -> list[str]:
    return [r["agent"] for r in resp["replies"]]


def run(graph, text, email="asha@example.com", thread="t"):
    out = graph.invoke(
        {
            "messages": [HumanMessage(text)],
            "hops": 0,
            "visited": [],
            "plan": [],
            "planned": False,
            "customer_email": email,
        },
        {"configurable": {"thread_id": thread}},
    )
    return out


# ---------- plan normalisation ----------
@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        (["faq", "orders"], ["faq", "orders"]),
        (["escalation", "orders"], ["orders", "escalation"]),  # a human takes over last
        (["orders", "orders", "faq", "orders"], ["orders", "faq"]),  # repeats dropped
        (["orders", "wizard", "FINISH"], ["orders"]),  # unknown names dropped
        ([], []),
    ],
)
def test_normalize_plan(raw, clean):
    assert normalize_plan(raw) == clean


# ---------- plan mode ----------
def test_plan_mode_asks_the_planner_once_and_runs_every_specialist(temp_db):
    calls = []

    def planner(messages):
        calls.append(len(messages))
        return ["orders", "faq"]

    g = build_graph(llm=FakeSpecialistLLM(), planner=planner)
    out = run(g, "Status of ORD-1001 and what is your return policy?")
    assert out["visited"] == ["orders", "faq"]
    assert len(calls) == 1  # loop mode would have asked the model three times


def test_plan_mode_escalation_goes_last_and_pauses(temp_db):
    g = build_graph(llm=FakeSpecialistLLM(), planner=lambda m: ["escalation", "orders"])
    run(g, "My order ORD-1001 is broken and I want a human", thread="esc")
    snap = g.get_state({"configurable": {"thread_id": "esc"}})
    assert snap.values["visited"] == ["orders", "escalation"]
    assert snap.next  # waiting for the human


def test_plan_mode_planner_failure_escalates(temp_db):
    def broken(messages):
        raise RuntimeError("model is down")

    g = build_graph(llm=FakeSpecialistLLM(), planner=broken)
    out = run(g, "Where is ORD-1001?", thread="down")
    assert out["ticket_id"] is not None


def test_plan_resets_between_messages_of_the_same_conversation(temp_db):
    plans = iter([["orders"], ["faq"]])
    g = build_graph(llm=FakeSpecialistLLM(), planner=lambda m: next(plans))
    first = run(g, "Where is ORD-1001?", thread="same")
    second = run(g, "And your return policy?", thread="same")
    assert first["visited"] == ["orders"] and second["visited"] == ["faq"]


def test_llm_planner_is_a_runnable_chain_with_structured_output():
    class StubLLM:
        def with_structured_output(self, schema, method=None):
            assert schema is Plan and method == "function_calling"
            return RunnableLambda(lambda _prompt: Plan(agents=["faq", "orders"]))

    assert make_llm_planner(StubLLM())([HumanMessage("x")]) == ["faq", "orders"]


def test_mode_must_be_known(temp_db):
    with pytest.raises(ValueError, match="mode"):
        build_graph(llm=FakeSpecialistLLM(), mode="chaos")


# ---------- replies that need no specialist ----------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hi", "Hello!"),
        ("hello there!", "Hello!"),
        ("Good morning", "Hello!"),
        ("thank you so much", "welcome"),
        ("Thanks, that's all I needed.", "welcome"),
        ("bye", "Goodbye"),
        ("What's the weather in Gurugram today?", "only help with this store"),
        ("Tell me a joke.", "only help with this store"),
    ],
)
def test_small_talk_reply(text, expected):
    assert expected in small_talk_reply(text)


def test_greeting_gets_an_answer_through_the_api(client):
    r = client.post("/chat", json={"message": "Hi"}).json()
    assert agents(r) == ["assistant"] and "Hello!" in r["replies"][0]["content"]
    assert r["status"] == "answered"


def test_a_real_question_does_not_get_the_small_talk_reply(client):
    h = login(client, "asha@example.com")
    r = client.post("/chat", json={"message": "Where is ORD-1001?"}, headers=h).json()
    assert agents(r) == ["orders"]  # no 'assistant' reply tacked on


def test_planner_that_skips_the_tool_call_means_no_specialist():
    class SilentLLM:
        def with_structured_output(self, schema, method=None):
            return RunnableLambda(lambda _prompt: None)

    assert make_llm_planner(SilentLLM())([HumanMessage("Hi")]) == []
