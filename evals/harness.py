"""Shared machinery for the evaluation runs: dataset loading, token pacing, case execution, checks.

Design goals, driven by running on free API tiers (about 8K tokens per minute, 200K per day):
  * pace requests so the per-minute token cap is not hit,
  * save every finished case immediately, so a rate-limit stop or a crash loses nothing (resumable),
  * never count an API outage as a wrong answer: such cases are recorded as errors and retried.
"""

import json
import tempfile
import time
import unicodedata
import uuid
from pathlib import Path

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, HumanMessage

from app import auth, config, db
from app.graph import SPECIALIST_ERROR_REPLY

ROOT = Path(__file__).resolve().parent.parent
DATASET = Path(__file__).with_name("dataset.jsonl")
RESULTS = Path(__file__).with_name("results")


# Failures that are the MODEL's fault, not the infrastructure's: it was asked for a routing decision and
# did not produce a valid one (no tool call, or a tool name that does not exist). These are results, so they
# count against the model; they are not retried like a rate-limit error would be.
MODEL_FAILURE_SIGNS = (
    "tool choice is required",
    "unknown tool type",
    "outputparserexception",
    "did not call",
)


def is_model_failure(error: str | None) -> bool:
    return bool(error) and any(sign in error.lower() for sign in MODEL_FAILURE_SIGNS)


def as_model_failure(row: dict) -> dict:
    """Turn an error row caused by invalid model output into a scored, failed routing decision."""
    return {
        **row,
        "model_failure": True,
        "route_ok": False,
        "model_failure_detail": row["error"][:160],
        "error": None,
    }


class QuotaExhausted(Exception):
    """The provider says the daily quota is used up. Stop and resume after the reset."""


def load_dataset(path: Path = DATASET) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def normalize(text: str) -> str:
    """Lowercase and unify look-alike characters (models print non-breaking hyphens and spaces)."""
    text = unicodedata.normalize("NFKC", text)
    for dash in "‐‑‒–—−":
        text = text.replace(dash, "-")
    return " ".join(text.lower().split())


# ---------- token pacing ----------
class Pacer:
    """Keeps token use under a per-minute budget by sleeping before a case when needed."""

    def __init__(self, tokens_per_minute: int = 6500, estimate: int = 1500):
        self.limit, self.estimate, self.log = tokens_per_minute, estimate, []

    def wait(self) -> None:
        while True:
            now = time.time()
            self.log = [(t, k) for t, k in self.log if now - t < 60]
            if not self.log or sum(k for _, k in self.log) + self.estimate <= self.limit:
                return
            time.sleep(max(0.5, 60 - (now - self.log[0][0]) + 0.2))

    def record(self, tokens: int) -> None:
        self.log.append((time.time(), tokens))


# ---------- measuring one case ----------
class Recorder(BaseCallbackHandler):
    """Counts model calls and tokens and remembers which tools were called."""

    def __init__(self):
        self.llm_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.tools: list[str] = []

    def on_chat_model_start(self, serialized, messages, **kwargs):
        # The routing evaluation uses a fake (free) specialist model; only real calls cost anything.
        if (kwargs.get("invocation_params") or {}).get("_type") != "fake-specialist":
            self.llm_calls += 1

    def on_llm_end(self, response, **kwargs):
        for generations in response.generations:
            for g in generations:
                usage = getattr(getattr(g, "message", None), "usage_metadata", None)
                if usage:
                    self.input_tokens += usage.get("input_tokens", 0)
                    self.output_tokens += usage.get("output_tokens", 0)

    def on_tool_start(self, serialized, input_str, **kwargs):
        self.tools.append((serialized or {}).get("name") or kwargs.get("name") or "?")

    @property
    def tokens(self) -> int:
        return self.input_tokens + self.output_tokens


class TrackedRouter:
    """Wraps a router so an API failure is recorded instead of being mistaken for a routing choice
    (the graph itself turns a router exception into an escalation)."""

    def __init__(self, router):
        self.router, self.error = router, None

    def __call__(self, messages):
        try:
            return self.router(messages)
        except Exception as exc:
            self.error = exc
            raise


def fresh_database() -> str:
    """A brand-new seeded database for every case, so cancellations never leak between cases."""
    auth.PBKDF2_ITERATIONS = 1_000  # demo passwords are not used by the evaluation; keep seeding fast
    config.DB_PATH = str(Path(tempfile.mkdtemp(prefix="evaldb-")) / "eval.db")
    db.init_db()
    return config.DB_PATH


def initial_messages(case: dict) -> list:
    msgs = []
    for turn in case.get("history", []):
        if turn["role"] == "human":
            msgs.append(HumanMessage(turn["content"]))
        else:
            msgs.append(AIMessage(content=turn["content"], name=turn["name"]))
    msgs.append(HumanMessage(case["message"]))
    return msgs


def run_case(graph, tracked: TrackedRouter, case: dict) -> dict:
    """Run one dataset case through the graph and collect what happened."""
    fresh_database()
    tracked.error = None
    rec = Recorder()
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}, "callbacks": [rec]}
    start = time.time()
    error = None
    try:
        graph.invoke(
            {
                "messages": initial_messages(case),
                "hops": 0,
                "visited": [],
                "plan": [],
                "planned": False,
                "ticket_id": None,
                "customer_email": case.get("customer") or "",
            },
            cfg,
        )
    except Exception as exc:  # the graph catches model errors itself; this is anything else
        error = f"{type(exc).__name__}: {exc}"
    latency = time.time() - start

    values = graph.get_state(cfg).values if error is None else {}
    messages = values.get("messages", [])
    last_human = max((i for i, m in enumerate(messages) if isinstance(m, HumanMessage)), default=-1)
    replies = [
        {"agent": m.name, "content": str(m.content)}
        for m in messages[last_human + 1 :]
        if isinstance(m, AIMessage) and m.name
    ]
    if tracked.error is not None:
        error = f"{type(tracked.error).__name__}: {tracked.error}"
    elif any(r["content"] == SPECIALIST_ERROR_REPLY for r in replies):
        error = "specialist call failed (see server log); treated as an outage, not a wrong answer"
    if error and "per day" in error.lower():  # e.g. "Rate limit reached ... on tokens per day (TPD)"
        raise QuotaExhausted(error[:300])

    model_failed = is_model_failure(error)
    with db.connect() as conn:  # (a bare sqlite3.connect() context manager would never close it)
        statuses = {r["order_id"]: r["status"] for r in conn.execute("SELECT order_id, status FROM orders")}
    expected = sorted(case["expected_agents"])
    predicted = sorted(set(values.get("visited", [])))
    row = {
        "id": case["id"],
        "category": case["category"],
        "message": case["message"],
        "expected": expected,
        "predicted": predicted,
        "route_ok": predicted == expected,
        "replies": replies,
        "tools": rec.tools,
        "llm_calls": rec.llm_calls,
        "input_tokens": rec.input_tokens,
        "output_tokens": rec.output_tokens,
        "latency_s": round(latency, 2),
        "db": statuses,
        "error": error,
    }
    return as_model_failure(row) if model_failed else row


# ---------- end-to-end answer checks ----------
def check_answer(case: dict, row: dict) -> dict:
    """Rule-based checks of the final answer. Returns which checks passed; absent checks pass."""
    e2e = case.get("e2e", {})
    text = normalize(" ".join(r["content"] for r in row["replies"]))
    include_ok = all(any(normalize(alt) in text for alt in group) for group in e2e.get("must_include", []))
    leaked = [s for s in e2e.get("must_not_include", []) if normalize(s) in text]
    db_ok = all(row["db"].get(order) == status for order, status in e2e.get("db", {}).items())
    return {
        "include_ok": include_ok,
        "leak_free": not leaked,
        "leaked": leaked,
        "db_ok": db_ok,
        "answer_ok": include_ok and not leaked and db_ok,
    }


# ---------- resumable result files ----------
def load_done(path: Path) -> dict[str, dict]:
    """Latest row per case id; a case counts as done only if it finished without an error."""
    rows: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                rows[row["id"]] = row
    rows = {k: as_model_failure(v) if is_model_failure(v.get("error")) else v for k, v in rows.items()}
    return {k: v for k, v in rows.items() if not v.get("error")}


def append_row(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
