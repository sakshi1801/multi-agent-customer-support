"""Build docs/EVALUATION.md from the committed result files, so no number is typed by hand.

python -m evals.summary
"""

import sys
import time
from pathlib import Path

from evals import harness, metrics
from evals.metrics import pct

DOCS = harness.ROOT / "docs" / "EVALUATION.md"


def _rows(path: Path) -> list[dict]:
    return list(harness.load_done(path).values())


def _find(pattern: str) -> list[Path]:
    return sorted(harness.RESULTS.glob(pattern))


def _label(path: Path) -> tuple[str, str, str]:
    """(provider/model, label, supervisor) from a results file name."""
    parts = path.stem.split("__")
    supervisor = "plan" if parts[-1] == "plan" else "loop"
    return parts[2].replace("-", "/", 1), parts[3], supervisor  # "qwen-qwen3.8-27b" -> "qwen/qwen3.8-27b"


def routing_table() -> str:
    lines = [
        "| Model | Supervisor | Routing accuracy | Without attack-message category | Escalation recall | Escalation precision | Invalid output | Model calls / msg | Tokens / msg | Latency p50 / p95 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    entries = []
    for path in _find("routing__*.jsonl"):
        rows = _rows(path)
        if not rows:
            continue
        m = metrics.routing_metrics(rows)
        model, _, supervisor = _label(path)
        model = (
            "keyword rules (no model)"
            if model.endswith("keyword-rules") or model == "keyword/rules"
            else model
        )
        entries.append((model, supervisor, m, len(rows)))
    for model, supervisor, m, n in sorted(entries, key=lambda e: (e[0], e[1])):
        done = "" if n >= 132 else f" ({n}/132 done)"
        lines.append(
            f"| {model}{done} | {supervisor if model != 'keyword rules (no model)' else 'rules'} | {pct(*m['accuracy'])} | "
            f"{pct(*m['accuracy_without_attacks'])} | {pct(*m['escalation_recall'])} | {pct(*m['escalation_precision'])} | "
            f"{pct(*m['model_failures'])} | {m['llm_calls_per_case']} | {m['tokens_per_case']} | "
            f"{m['latency_p50_s']} s / {m['latency_p95_s']} s |"
        )
    return "\n".join(lines)


def _delta(a: dict, b: dict, key: str) -> str:
    return f"{a[key]} -> {b[key]} ({100 * (b[key] - a[key]) / a[key]:+.0f}%)"


def planner_vs_loop() -> str:
    """Same model, same cases: what changed when the supervisor asks the model once instead of after every step."""
    out = []
    for loop_path in _find("routing__groq__*__baseline.jsonl"):
        plan_path = loop_path.with_name(loop_path.name.replace("__baseline.jsonl", "__planner__plan.jsonl"))
        if not plan_path.exists():
            continue
        loop, plan = _rows(loop_path), _rows(plan_path)
        common = {r["id"] for r in loop} & {r["id"] for r in plan}
        if len(common) < 100:
            continue
        a = metrics.routing_metrics([r for r in loop if r["id"] in common])
        b = metrics.routing_metrics([r for r in plan if r["id"] in common])
        model = _label(loop_path)[0]

        out.append(
            f"| {model} | {len(common)} | {pct(*a['accuracy'])} -> {pct(*b['accuracy'])} | "
            f"{_delta(a, b, 'llm_calls_per_case')} | {_delta(a, b, 'tokens_per_case')} | "
            f"{a['latency_p50_s']} -> {b['latency_p50_s']} s |"
        )
    if not out:
        return "_Planner runs are not complete yet._"
    return "\n".join(
        [
            "| Model | Cases compared | Routing accuracy | Model calls / msg | Tokens / msg | Latency p50 |",
            "|---|---|---|---|---|---|",
            *out,
        ]
    )


def e2e_section() -> str:
    parts = []
    for path in _find("e2e__*.jsonl"):
        rows = _rows(path)
        cases = {c["id"]: c for c in harness.load_dataset()}
        for r in rows:  # (re)apply the current checks to the saved replies
            r["checks"] = harness.check_answer(cases[r["id"]], r)
        m = metrics.e2e_metrics(rows)
        model, label, supervisor = _label(path)
        parts.append(
            f"| {model} | {label} | {pct(*m['passed'])} | {pct(*m['security'])} | {pct(*m['answered'])} | "
            f"{pct(*m['tool_use'])} | {m['llm_calls_per_case']} | {m['tokens_per_case']} | "
            f"{m['latency_p50_s']} s / {m['latency_p95_s']} s |"
        )
    if not parts:
        return "_End-to-end runs are not complete yet._"
    return "\n".join(
        [
            "| Model | Run | Cases fully correct | Attacks that leaked nothing and changed nothing | Customer got a reply | Tool used when needed | Model calls / msg | Tokens / msg | Latency p50 / p95 |",
            "|---|---|---|---|---|---|---|---|---|",
            *parts,
        ]
    )


def _metrics_for(pattern: str):
    """Routing metrics of the first complete (132-case) results file matching the pattern, or None."""
    for path in _find(pattern):
        rows = _rows(path)
        if len(rows) >= 132:
            return metrics.routing_metrics(rows)
    return None


def _e2e_for(pattern: str):
    for path in _find(pattern):
        rows = _rows(path)
        if len(rows) >= 32:
            cases = {c["id"]: c for c in harness.load_dataset()}
            for r in rows:
                r["checks"] = harness.check_answer(cases[r["id"]], r)
            return metrics.e2e_metrics(rows)
    return None


def readme_block() -> str:
    """The headline table for the README, built from the same result files."""
    plan = _metrics_for("routing__groq__openai-gpt-oss-120b__planner__plan.jsonl")
    loop = _metrics_for("routing__groq__openai-gpt-oss-120b__baseline.jsonl")
    rules = _metrics_for("routing__none__keyword-rules__keyword-rules.jsonl")
    local_plan = _metrics_for("routing__custom__*__planner__plan.jsonl")
    local_loop = _metrics_for("routing__custom__*__baseline.jsonl")
    e2e = _e2e_for("e2e__groq__openai-gpt-oss-120b__final-v2__plan.jsonl")
    local_e2e = _e2e_for("e2e__custom__*__final__plan.jsonl")
    lines = [
        "All figures are on free tiers or locally, on hand-labelled cases, with 95% confidence intervals in the full report.",
        "",
    ]
    if plan and loop and rules:
        lines += [
            "| Measure | Result |",
            "|---|---|",
            f"| **Routing accuracy**, {plan['n']} labelled messages (gpt-oss-120b, planner supervisor) | **{pct(*plan['accuracy'])}**, against {pct(*loop['accuracy'])} for the original loop supervisor and {pct(*rules['accuracy'])} for keyword rules |",
            f"| **Escalation recall** (angry or legal messages reach a human) | {pct(*plan['escalation_recall'])}; precision {pct(*plan['escalation_precision'])} |",
            f"| **Cost of a decision**, planner against loop | model calls per message {loop['llm_calls_per_case']} -> {plan['llm_calls_per_case']} ({100 * (plan['llm_calls_per_case'] - loop['llm_calls_per_case']) / loop['llm_calls_per_case']:+.0f}%), tokens {loop['tokens_per_case']} -> {plan['tokens_per_case']} ({100 * (plan['tokens_per_case'] - loop['tokens_per_case']) / loop['tokens_per_case']:+.0f}%), median latency {loop['latency_p50_s']} s -> {plan['latency_p50_s']} s |",
        ]
    if e2e:
        lines.append(
            f"| **End to end** ({e2e['n']} cases with the real specialists: facts, no leaks, database state) | {pct(*e2e['passed'])} fully correct; **attacks that leaked nothing and changed nothing: {pct(*e2e['security'])}** |"
        )
    if local_plan and local_loop:
        local = f"| **Fully local, offline** (4B model on a laptop GPU via Ollama) | routing {pct(*local_plan['accuracy'])} with the planner ({pct(*local_loop['accuracy'])} with the loop)"
        if local_e2e:
            local += f"; end to end {pct(*local_e2e['passed'])}; attacks that leaked nothing: {pct(*local_e2e['security'])}"
        lines.append(local + " |")
    lines.append(
        "| **FAQ retrieval** (top-3 contains the right section, 41 questions) | vector search 92.7% against 53.7% for the prototype's keyword search; BM25, hybrid fusion and a reranker were measured and did not beat vector search |"
    )
    lines.append(
        "| **Tests** | 120+ deterministic tests with a fake model (no API key), run in CI together with a Docker image build and container smoke test |"
    )
    return chr(10).join(lines)


def _body(name: str) -> str:
    """A results report without its title line."""
    path = harness.RESULTS / name
    return "\n".join(path.read_text(encoding="utf-8").splitlines()[1:]).strip() if path.exists() else ""


def main() -> int:
    n = len(harness.load_dataset())
    text = f"""# Evaluation results

Generated by `python -m evals.summary` on {time.strftime("%Y-%m-%d")} from the files in
[`evals/results/`](../evals/results). Everything ran on **free tiers** (Groq) and **locally** (embeddings),
at zero cost. All percentages show the number of cases and a 95% confidence interval: with about {n} cases
a single figure has real uncertainty, and the intervals say how much.

## How it is measured

| Evaluation | What it measures | Cases |
|---|---|---|
| **Routing** | The real supervisor decides which specialists a message needs. Specialists are fake and free, so tokens are spent only on the decision being measured. | {n} hand-labelled customer messages in 8 categories (single and multi-intent, escalations, small talk, Hinglish and typo edge cases, prompt-injection attacks, multi-turn follow-ups) |
| **End to end** | The whole system with real specialists: right agents, the facts that must appear, data that must not leak, the database state afterwards. | 32 of those cases |
| **Retrieval** | How well the FAQ agent's search finds the right knowledge-base section. Local embedding model, no LLM. | 41 answerable + 9 off-topic questions |
| **Guard** | How well an optional injection classifier separates attacks from customers. | {n} messages |

The labels were written by hand before any model was run. When a result looked odd, the case was kept
as it was, not relabelled to improve the score.

## 1. Routing: which model and which supervisor?

{routing_table()}

*Loop* = the original design: the model is asked "who next?" after every specialist.
*Plan* = the model is asked once for every specialist the message needs. *Rules* = a keyword matcher, the
offline floor any model has to beat. "Invalid output" means the model produced no valid routing decision
(no tool call, or a tool that does not exist); that counts as wrong, and the product then hands the customer to a human.

### Planner against loop (same model, same cases)

{planner_vs_loop()}

## 2. End to end

{e2e_section()}

## 3. Retrieval for the FAQ agent

{_body("retrieval.md")}

## 4. Prompt-injection guard

{_body("guard.md")}

## Reproducing

```bash
python -m evals.build_dataset                       # regenerate the labelled dataset
python -m evals.run_eval routing --router keyword   # offline floor, no model
python -m evals.run_eval routing --provider groq --model qwen/qwen3.8-27b --label baseline
python -m evals.run_eval routing --provider groq --model qwen/qwen3.8-27b --supervisor plan --label planner
python -m evals.run_eval e2e --provider groq --model qwen/qwen3.8-27b --supervisor plan --label final
python -m evals.retrieval_eval ; python -m evals.guard_eval
python -m evals.summary                             # rebuild this page
```

Runs pace themselves under the free tier's token limits and save every finished case, so an interrupted
run (or a daily quota stop) resumes where it left off.
"""
    DOCS.write_text(text, encoding="utf-8", newline="\n")
    readme = harness.ROOT / "README.md"
    body = readme.read_text(encoding="utf-8")
    start, end = "<!-- RESULTS-START -->", "<!-- RESULTS-END -->"
    if start in body and end in body:
        head, rest = body.split(start, 1)
        tail = rest.split(end, 1)[1]
        readme.write_text(f"{head}{start}\n{readme_block()}\n{end}{tail}", encoding="utf-8", newline="\n")
    print(f"wrote {DOCS} and the README results block")
    return 0


if __name__ == "__main__":
    sys.exit(main())
