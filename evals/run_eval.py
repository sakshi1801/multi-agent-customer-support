"""Run the evaluation.

    python -m evals.run_eval routing --provider groq --model openai/gpt-oss-120b --label baseline
    python -m evals.run_eval e2e     --provider groq --model openai/gpt-oss-120b --label baseline
    python -m evals.run_eval routing --router keyword --label keyword-rules      # offline, no model

routing  The REAL supervisor with fake (free, deterministic) specialists: measures only the routing
         decision, at a fraction of the token cost. Covers all dataset cases.
e2e      The whole system with real specialists on the cases that have end-to-end checks: right
         agents, right facts, no data leaks, correct database state.

Runs are resumable: finished cases are saved to evals/results/*.jsonl as they complete, and a rerun
only does the missing ones (or the ones that failed because the API was unavailable).
"""

import argparse
import re
import subprocess
import sys
import time

from app import config
from app.graph import build_graph, make_llm_planner, make_llm_router
from app.testing import FakeSpecialistLLM, keyword_router
from evals import harness, metrics


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9.]+", "-", text.lower()).strip("-")


def _git_commit() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            cwd=harness.ROOT,
            check=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["routing", "e2e"])
    ap.add_argument("--provider", default=None, help="groq | openrouter | custom | openai | azure")
    ap.add_argument("--model", default=None, help="model name (default: the provider's configured model)")
    ap.add_argument("--router", choices=["llm", "keyword"], default="llm", help="keyword = offline baseline")
    ap.add_argument(
        "--supervisor",
        choices=["loop", "plan"],
        default="loop",
        help="loop = ask after every step, plan = ask once",
    )
    ap.add_argument("--label", default="baseline", help="name for this run, e.g. baseline or after-rag")
    ap.add_argument("--category", default=None, help="only cases of this category")
    ap.add_argument("--limit", type=int, default=None, help="only the first N cases (after filtering)")
    ap.add_argument("--max-tokens", type=int, default=140_000, help="stop after this many tokens this run")
    ap.add_argument("--tpm", type=int, default=6500, help="tokens-per-minute budget used for pacing")
    args = ap.parse_args(argv)

    cases = harness.load_dataset()
    if args.mode == "e2e":
        cases = [c for c in cases if "e2e" in c]
    if args.category:
        cases = [c for c in cases if c["category"] == args.category]
    if args.limit:
        cases = cases[: args.limit]

    keyword = args.router == "keyword"
    if keyword:
        provider, model = "none", "keyword-rules"
        llm = FakeSpecialistLLM()
        router = harness.TrackedRouter(keyword_router)
    else:
        provider = args.provider or config.get_provider()
        llm = config.build_llm(provider, model=args.model, max_retries=6)
        model = getattr(llm, "model_name", None) or getattr(llm, "model", None) or args.model or "?"
        router = harness.TrackedRouter(
            make_llm_planner(llm) if args.supervisor == "plan" else make_llm_router(llm)
        )
    # Routing mode: real supervisor, fake specialists. e2e mode: real model everywhere.
    specialists = FakeSpecialistLLM() if args.mode == "routing" else llm
    if args.supervisor == "plan" and not keyword:
        graph = build_graph(llm=specialists, planner=router, mode="plan")
    else:
        graph = build_graph(llm=specialists, router=router, mode="loop")

    stem = f"{args.mode}__{provider}__{_slug(str(model))}__{_slug(args.label)}"
    if args.supervisor == "plan":
        stem += "__plan"
    out = harness.RESULTS / f"{stem}.jsonl"
    done = harness.load_done(out)
    todo = [c for c in cases if c["id"] not in done]
    print(f"{stem}: {len(cases)} cases, {len(done)} already done, {len(todo)} to run")

    pacer = harness.Pacer(args.tpm, estimate=1300 if args.mode == "routing" else 3200)
    used = 0
    for i, case in enumerate(todo, 1):
        if used >= args.max_tokens:
            print(f"stopping: reached --max-tokens {args.max_tokens}; run again later to continue")
            break
        pacer.wait()
        try:
            row = harness.run_case(graph, router, case)
        except harness.QuotaExhausted as exc:
            print(f"stopping: daily quota used up ({exc}). Run the same command again after the reset.")
            break
        if args.mode == "e2e":
            row["checks"] = harness.check_answer(case, row)
        harness.append_row(out, row)
        tokens = row["input_tokens"] + row["output_tokens"]
        pacer.record(tokens)
        used += tokens
        ok = row["route_ok"] and (row.get("checks", {}).get("answer_ok", True))
        print(
            f"[{i}/{len(todo)}] {case['id']:<20} {'ok  ' if ok else 'FAIL'} "
            f"{'ERROR ' + row['error'][:60] if row['error'] else ''} "
            f"calls={row['llm_calls']} tokens={tokens} {row['latency_s']}s"
        )

    rows = list(harness.load_done(out).values())
    if not rows:
        print("no finished cases yet")
        return 1
    meta = {
        "Run": args.label,
        "Provider / model": f"{provider} / {model}",
        "Supervisor": args.supervisor,
        "Reasoning effort": config.os.getenv("LLM_REASONING_EFFORT") or "default",
        "Cases finished": f"{len(rows)} of {len(cases)}",
        "Commit": _git_commit(),
        "Date": time.strftime("%Y-%m-%d"),
    }
    if args.mode == "routing":
        report = metrics.render_routing("Routing evaluation", meta, metrics.routing_metrics(rows))
    else:
        report = metrics.render_e2e("End-to-end evaluation", meta, metrics.e2e_metrics(rows))
    (harness.RESULTS / f"{stem}.md").write_text(report, encoding="utf-8", newline="\n")
    print("\n" + report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
