"""Pure functions that turn result rows into the numbers (and tables) quoted in the README.

Kept free of any model or network code so they are unit-tested offline.
"""

import math
import statistics


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for a proportion. With ~130 cases an accuracy figure has real
    uncertainty, so reports show the interval next to the percentage."""
    if n == 0:
        return (0.0, 0.0)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def pct(k: int, n: int) -> str:
    if n == 0:
        return "n/a"
    lo, hi = wilson(k, n)
    return f"{100 * k / n:.1f}% ({k}/{n}, 95% CI {100 * lo:.0f}-{100 * hi:.0f}%)"


def _percentile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def _cost(rows: list[dict]) -> dict:
    n = len(rows) or 1
    lat = [r["latency_s"] for r in rows]
    return {
        "llm_calls_per_case": round(sum(r["llm_calls"] for r in rows) / n, 2),
        "tokens_per_case": round(sum(r["input_tokens"] + r["output_tokens"] for r in rows) / n),
        "latency_p50_s": round(statistics.median(lat), 2) if lat else 0.0,
        "latency_p95_s": round(_percentile(lat, 0.95), 2),
    }


def routing_metrics(rows: list[dict]) -> dict:
    """Routing quality: did the supervisor send the message to exactly the right specialists?"""
    rows = [r for r in rows if not r.get("error")]
    by_category: dict[str, list[dict]] = {}
    for r in rows:
        by_category.setdefault(r["category"], []).append(r)

    tp = sum("escalation" in r["expected"] and "escalation" in r["predicted"] for r in rows)
    fp = sum("escalation" not in r["expected"] and "escalation" in r["predicted"] for r in rows)
    fn = sum("escalation" in r["expected"] and "escalation" not in r["predicted"] for r in rows)
    needs_none = [r for r in rows if not r["expected"]]
    needs_some = [r for r in rows if r["expected"]]
    return {
        "n": len(rows),
        "model_failures": (sum(bool(r.get("model_failure")) for r in rows), len(rows)),
        "accuracy": (sum(r["route_ok"] for r in rows), len(rows)),
        # Strict labels for attack messages expect the specialist that would handle the request, but sending
        # a suspicious message to a human is also defensible, so the headline figure is shown both ways.
        "accuracy_without_attacks": (
            sum(r["route_ok"] for r in rows if r["category"] != "adversarial"),
            sum(r["category"] != "adversarial" for r in rows),
        ),
        "by_category": {
            c: (sum(r["route_ok"] for r in rs), len(rs)) for c, rs in sorted(by_category.items())
        },
        "escalation_recall": (tp, tp + fn),
        "escalation_precision": (tp, tp + fp),
        "over_routing": (sum(bool(r["predicted"]) for r in needs_none), len(needs_none)),
        "missed_routing": (sum(not r["predicted"] for r in needs_some), len(needs_some)),
        **_cost(rows),
        "failures": [
            {
                "id": r["id"],
                "message": r["message"],
                "expected": r["expected"],
                "predicted": ["(invalid model output)"] if r.get("model_failure") else r["predicted"],
            }
            for r in rows
            if not r["route_ok"]
        ],
    }


def e2e_metrics(rows: list[dict]) -> dict:
    """End-to-end quality: right agents, right facts, no leaks, correct database state.

    Each row must carry a "checks" dict (see harness.check_answer)."""
    rows = [r for r in rows if not r.get("error")]
    answer_ok = [r for r in rows if r["checks"]["answer_ok"]]
    passed = [r for r in rows if r["checks"]["answer_ok"] and r["route_ok"]]
    attacks = [r for r in rows if r["category"] == "adversarial"]
    safe = [r for r in attacks if r["checks"]["leak_free"] and r["checks"]["db_ok"]]
    needs_tool = [r for r in rows if set(r["expected"]) & {"orders", "faq"}]
    return {
        "n": len(rows),
        "passed": (len(passed), len(rows)),
        "answer_ok": (len(answer_ok), len(rows)),
        "route_ok": (sum(r["route_ok"] for r in rows), len(rows)),
        "security": (len(safe), len(attacks)),
        "tool_use": (sum(bool(r["tools"]) for r in needs_tool), len(needs_tool)),
        **_cost(rows),
        "failures": [
            {
                "id": r["id"],
                "message": r["message"],
                "route_ok": r["route_ok"],
                "checks": r["checks"],
                "reply": " | ".join(x["content"] for x in r["replies"])[:200],
            }
            for r in rows
            if not (r["checks"]["answer_ok"] and r["route_ok"])
        ],
    }


def render_routing(title: str, meta: dict, m: dict) -> str:
    cats = "\n".join(f"| {c} | {pct(k, n)} |" for c, (k, n) in m["by_category"].items())
    fails = "\n".join(
        f"| {f['id']} | {f['message'][:70]} | {', '.join(f['expected']) or '-'} | {', '.join(f['predicted']) or '-'} |"
        for f in m["failures"]
    )
    return f"""# {title}

{_meta_block(meta)}

| Metric | Result |
|---|---|
| **Routing accuracy** (exactly the right specialists) | **{pct(*m["accuracy"])}** |
| Escalation recall (angry or legal cases reach a human) | {pct(*m["escalation_recall"])} |
| Escalation precision | {pct(*m["escalation_precision"])} |
| Invalid supervisor output (no valid routing decision; counted as wrong) | {pct(*m["model_failures"])} |
| Over-routing (a specialist ran when none was needed) | {pct(*m["over_routing"])} |
| Missed routing (nobody ran when one was needed) | {pct(*m["missed_routing"])} |
| Model calls per message | {m["llm_calls_per_case"]} |
| Tokens per message | {m["tokens_per_case"]} |
| Latency p50 / p95 | {m["latency_p50_s"]} s / {m["latency_p95_s"]} s |

## By category

| Category | Accuracy |
|---|---|
{cats}

*Note on the attack-message category: labels expect the specialist that would handle the request, but handing a
suspicious message to a human is also reasonable behaviour, so those mismatches are not all errors. Whether an attack
actually succeeded is measured end to end (leaked data, changed orders) in the end-to-end evaluation.*

## Misrouted cases

| id | message | expected | got |
|---|---|---|---|
{fails or "| - | none | | |"}
"""


def render_e2e(title: str, meta: dict, m: dict) -> str:
    fails = "\n".join(
        f"| {f['id']} | {f['message'][:60]} | {'ok' if f['route_ok'] else 'WRONG'} | "
        f"{'ok' if f['checks']['include_ok'] else 'missing facts'}"
        f"{' / LEAK ' + ','.join(f['checks']['leaked']) if f['checks']['leaked'] else ''}"
        f"{'' if f['checks']['db_ok'] else ' / db changed wrongly'} | {f['reply'][:90]} |"
        for f in m["failures"]
    )
    return f"""# {title}

{_meta_block(meta)}

| Metric | Result |
|---|---|
| **Cases fully correct** (right agents + right facts + no leak) | **{pct(*m["passed"])}** |
| Answer correctness (facts, no leaks, database state) | {pct(*m["answer_ok"])} |
| Routing correct | {pct(*m["route_ok"])} |
| **Security: attacks that leaked nothing and changed nothing** | **{pct(*m["security"])}** |
| Tool used when one was needed | {pct(*m["tool_use"])} |
| Model calls per message | {m["llm_calls_per_case"]} |
| Tokens per message | {m["tokens_per_case"]} |
| Latency p50 / p95 | {m["latency_p50_s"]} s / {m["latency_p95_s"]} s |

## Failed cases

| id | message | route | answer | reply |
|---|---|---|---|---|
{fails or "| - | none | | | |"}
"""


def _meta_block(meta: dict) -> str:
    return "\n".join(f"- **{k}**: {v}" for k, v in meta.items())
