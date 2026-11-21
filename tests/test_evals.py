"""Tests for the evaluation harness itself: if the measuring stick is wrong, every number is wrong."""

import json

import pytest

from app.graph import build_graph
from app.testing import FakeSpecialistLLM
from evals import build_dataset, harness, metrics, run_eval

AGENTS = {"orders", "faq", "escalation"}


@pytest.fixture()
def cases():
    return harness.load_dataset()


# ---------- the dataset ----------
def test_dataset_file_matches_its_source():
    assert harness.load_dataset() == json.loads(json.dumps(build_dataset.build(), ensure_ascii=False))


def test_dataset_is_well_formed(cases):
    assert len(cases) >= 130
    assert len({c["id"] for c in cases}) == len(cases)
    for c in cases:
        assert set(c["expected_agents"]) <= AGENTS and c["expected_agents"] == sorted(c["expected_agents"])
        assert c["customer"] in (None, "asha@example.com", "ravi@example.com", "meera@example.com")
        assert c["message"].strip()
        for turn in c["history"]:
            assert turn["role"] in ("human", "ai")
            assert turn["role"] == "human" or turn["name"] in AGENTS | {"human_agent"}


def test_dataset_covers_every_category_with_enough_cases(cases):
    counts = {}
    for c in cases:
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    expected = {
        "orders",
        "faq",
        "multi_intent",
        "escalation",
        "no_specialist",
        "edge",
        "adversarial",
        "multi_turn",
    }
    assert set(counts) == expected
    assert min(counts.values()) >= 8
    assert any(len(c["expected_agents"]) == 2 for c in cases)  # multi-intent cases exist


def test_e2e_subset_has_checks_and_security_cases(cases):
    e2e = [c for c in cases if "e2e" in c]
    assert 25 <= len(e2e) <= 40
    assert sum(c["category"] == "adversarial" for c in e2e) >= 6
    for c in e2e:
        assert set(c["e2e"]) <= {"must_include", "must_not_include", "db"}


# ---------- numbers ----------
def test_wilson_interval():
    assert metrics.wilson(0, 0) == (0.0, 0.0)
    lo, hi = metrics.wilson(5, 10)
    assert 0.23 < lo < 0.25 and 0.75 < hi < 0.77
    lo, hi = metrics.wilson(100, 100)
    assert hi > 0.999 and lo > 0.95
    assert metrics.pct(95, 132).startswith("72.0% (95/132")


def _row(cid, category, expected, predicted, **extra):
    base = {
        "id": cid,
        "category": category,
        "message": "m",
        "expected": expected,
        "predicted": predicted,
        "route_ok": expected == predicted,
        "llm_calls": 2,
        "input_tokens": 400,
        "output_tokens": 60,
        "latency_s": 1.0,
        "replies": [],
        "tools": [],
        "db": {},
        "error": None,
    }
    return {**base, **extra}


def test_routing_metrics_counts():
    rows = [
        _row("a", "orders", ["orders"], ["orders"]),
        _row("b", "escalation", ["escalation"], ["escalation"]),
        _row("c", "escalation", ["escalation"], []),  # missed escalation
        _row("d", "no_specialist", [], ["faq"]),  # over-routing
        _row("e", "faq", ["faq"], ["faq", "escalation"]),  # false escalation
        _row("f", "faq", ["faq"], ["faq"], error="API down"),  # outage: must not be scored at all
    ]
    m = metrics.routing_metrics(rows)
    assert m["n"] == 5 and m["accuracy"] == (2, 5)
    assert m["escalation_recall"] == (1, 2) and m["escalation_precision"] == (1, 2)
    assert m["over_routing"] == (1, 1) and m["missed_routing"] == (1, 4)
    assert m["tokens_per_case"] == 460 and m["llm_calls_per_case"] == 2.0
    assert {f["id"] for f in m["failures"]} == {"c", "d", "e"}


# ---------- answer checks ----------
def test_check_answer_normalises_and_detects_leaks_and_db():
    case = {
        "e2e": {
            "must_include": [["shipped"], ["2026-11-22", "nov 22"]],
            "must_not_include": ["usb-c hub"],
            "db": {"ORD-1002": "processing"},
        }
    }
    good = {
        "replies": [{"agent": "orders", "content": "Shipped, arriving 2026‑11‑22."}],
        "db": {"ORD-1002": "processing"},
    }
    assert harness.check_answer(case, good)["answer_ok"]  # non-breaking hyphens are normalised
    leak = {**good, "replies": [{"agent": "orders", "content": "Shipped nov 22. Also your USB‑C Hub"}]}
    assert harness.check_answer(case, leak)["leaked"] == ["usb-c hub"]
    wrong_db = {**good, "db": {"ORD-1002": "cancelled"}}
    r = harness.check_answer(case, wrong_db)
    assert r["include_ok"] and r["leak_free"] and not r["db_ok"] and not r["answer_ok"]
    assert harness.check_answer({}, good)["answer_ok"]  # no checks -> passes


# ---------- running and resuming ----------
def test_keyword_baseline_runs_and_resumes(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(harness, "RESULTS", tmp_path)
    assert run_eval.main(["routing", "--router", "keyword", "--label", "t"]) == 0
    out = next(tmp_path.glob("*.jsonl"))
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 132 and all(not r["error"] for r in rows)
    assert metrics.routing_metrics(rows)["accuracy"] == (95, 132)  # deterministic rules, deterministic number
    assert (tmp_path / (out.stem + ".md")).exists()

    capsys.readouterr()
    run_eval.main(["routing", "--router", "keyword", "--label", "t"])
    assert "0 to run" in capsys.readouterr().out  # nothing is redone


def _case(**over):
    return {
        "id": "x",
        "category": "orders",
        "message": "Where is ORD-1001?",
        "customer": "asha@example.com",
        "history": [],
        "expected_agents": ["orders"],
        **over,
    }


def test_api_outage_is_an_error_not_a_wrong_answer(temp_db):
    def down(messages):
        raise RuntimeError("503 service unavailable")

    tracked = harness.TrackedRouter(down)
    graph = build_graph(llm=FakeSpecialistLLM(), router=tracked)
    row = harness.run_case(graph, tracked, _case())
    assert row["error"] and "503" in row["error"]  # recorded as an error, so it will be retried
    assert row["id"] not in {r["id"] for r in [row] if not r["error"]}


def test_daily_quota_stops_the_run(temp_db):
    def quota(messages):
        raise RuntimeError("Rate limit reached for model on tokens per day (TPD): Limit 200000")

    tracked = harness.TrackedRouter(quota)
    graph = build_graph(llm=FakeSpecialistLLM(), router=tracked)
    with pytest.raises(harness.QuotaExhausted):
        harness.run_case(graph, tracked, _case(message="hi", customer=None, expected_agents=[]))


def test_errors_are_not_counted_as_done(tmp_path):
    path = tmp_path / "r.jsonl"
    harness.append_row(path, {"id": "a", "error": None})
    harness.append_row(path, {"id": "b", "error": "429"})
    assert set(harness.load_done(path)) == {"a"}


def test_pacer_waits_only_when_the_minute_budget_is_full(monkeypatch):
    now = [1000.0]
    slept = []
    monkeypatch.setattr(harness.time, "time", lambda: now[0])
    monkeypatch.setattr(harness.time, "sleep", lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    p = harness.Pacer(tokens_per_minute=1000, estimate=300)
    p.wait()
    assert not slept  # empty window
    p.record(800)
    p.wait()  # 800 + 300 > 1000: must wait for the old entry to leave the window
    assert slept and sum(slept) >= 59
    slept.clear()
    p.wait()
    assert not slept


def test_history_is_replayed_into_the_conversation(cases):
    follow_up = next(c for c in cases if c["category"] == "multi_turn")
    msgs = harness.initial_messages(follow_up)
    assert msgs[-1].content == follow_up["message"] and len(msgs) == len(follow_up["history"]) + 1


# ---------- model failures are results, outages are retried ----------
def test_invalid_model_output_is_scored_as_a_failure_not_retried(tmp_path):
    bad = {
        "id": "a",
        "category": "orders",
        "message": "m",
        "expected": ["orders"],
        "predicted": ["escalation"],
        "route_ok": False,
        "llm_calls": 1,
        "input_tokens": 1,
        "output_tokens": 1,
        "latency_s": 1.0,
        "replies": [],
        "tools": [],
        "db": {},
        "error": "OpenAIInvalidRequestError: Error code: 400 - Tool choice is required, but model did not call a tool",
    }
    outage = {**bad, "id": "b", "error": "RateLimitError: 429 Too Many Requests"}
    parse = {**bad, "id": "c", "error": "OutputParserException: Unknown tool type: 'functions.Route'"}
    path = tmp_path / "r.jsonl"
    for row in (bad, outage, parse):
        harness.append_row(path, row)
    done = harness.load_done(path)
    assert set(done) == {"a", "c"}  # the outage will be retried; the model failures are final
    assert done["a"]["model_failure"] and done["a"]["route_ok"] is False and done["a"]["error"] is None
    m = metrics.routing_metrics(list(done.values()))
    assert m["model_failures"] == (2, 2) and m["accuracy"] == (0, 2)
    assert m["failures"][0]["predicted"] == ["(invalid model output)"]


def test_is_model_failure_only_matches_invalid_output():
    assert harness.is_model_failure("OutputParserException: bad")
    assert not harness.is_model_failure("RateLimitError: 429")
    assert not harness.is_model_failure("specialist call failed")
    assert not harness.is_model_failure(None)


def test_signed_in_customer_must_not_be_told_to_log_in():
    row = {"replies": [{"agent": "orders", "content": "Please log in to view your orders."}], "db": {}}
    assert not harness.check_answer({"customer": "ravi@example.com"}, row)["login_ok"]
    assert not harness.check_answer({"customer": "ravi@example.com"}, row)["answer_ok"]
    assert harness.check_answer({"customer": None}, row)["answer_ok"]  # an anonymous visitor may be asked
