"""Compare the retrievers on the knowledge base, offline and free (no LLM, only the local embedding model).

    python -m evals.retrieval_eval            # writes evals/results/retrieval.md

Metrics, for the 41 questions that have an answer in the knowledge base:
  hit@1   the first result is a section that answers the question
  hit@3   one of the first three results is
  MRR     mean of 1/rank of the first correct result (1.0 = always first)
and for the 9 questions that have NO answer in the knowledge base:
  abstain the retriever returned nothing, so the agent will say "I'm not sure"
"""

import sys
import time

from app import rag
from evals import harness
from evals.metrics import pct
from evals.retrieval_cases import CASES

KB_DIR = str(harness.ROOT / "data" / "kb")


def evaluate(kb: rag.KnowledgeBase, mode: str, min_similarity: float = 0.0, k: int = 3) -> dict:
    answerable = [(q, set(exp)) for q, exp in CASES if exp]
    unanswerable = [q for q, exp in CASES if not exp]
    hit1 = hit3 = 0
    rr = 0.0
    start = time.time()
    for q, expected in answerable:
        hits = kb.search(q, k, mode, min_similarity)
        ids = [h.doc.metadata["id"] for h in hits]
        hit1 += bool(ids[:1]) and ids[0] in expected
        hit3 += any(i in expected for i in ids[:3])
        rr += rag.reciprocal_rank(hits, expected)
    abstained = sum(not kb.search(q, k, mode, min_similarity) for q in unanswerable)
    wrongly_abstained = sum(not kb.search(q, k, mode, min_similarity) for q, _ in answerable)
    ms = (time.time() - start) * 1000 / len(CASES)
    return {
        "hit1": (hit1, len(answerable)),
        "hit3": (hit3, len(answerable)),
        "mrr": rr / len(answerable),
        "abstain": (abstained, len(unanswerable)),
        "wrong_abstain": (wrongly_abstained, len(answerable)),
        "ms": ms,
    }


def main() -> int:
    embeddings = rag.FastEmbedEmbeddings()
    kb = rag.build_kb(KB_DIR, embeddings)
    kb_rerank = rag.build_kb(KB_DIR, embeddings, rag.CrossEncoderReranker())

    # How well separated are real matches from off-topic questions? (best cosine similarity per question)
    best = [(kb.vector(q, 1)[0].score, bool(exp)) for q, exp in CASES]
    in_scope = sorted(s for s, ok in best if ok)
    off_topic = sorted(s for s, ok in best if not ok)

    rows = []
    for name, base, mode, threshold in [
        ("Keyword overlap (the original prototype)", kb, "keyword", 0.0),
        ("BM25", kb, "bm25", 0.0),
        ("Vector (bge-small embeddings, Chroma)", kb, "vector", 0.0),
        ("Hybrid (BM25 + vector, reciprocal rank fusion)", kb, "hybrid", 0.0),
        ("Hybrid + cross-encoder rerank", kb_rerank, "hybrid", 0.0),
        ("Vector + cross-encoder rerank", kb_rerank, "vector", 0.0),
    ]:
        rows.append((name, evaluate(base, mode, threshold)))

    # Choose the abstain threshold from the data: the highest cutoff that never rejects an answerable question
    # (the in-scope question with the lowest best-similarity sets the ceiling).
    threshold = round(in_scope[0] - 0.02, 2)
    with_cutoff = evaluate(kb, "vector", threshold)

    lines = [
        "# Retrieval evaluation",
        "",
        f"- **Knowledge base**: {len(kb.chunks)} sections from {len(set(c.metadata['source'] for c in kb.chunks))} files",
        f"- **Questions**: {sum(1 for _, e in CASES if e)} answerable + {sum(1 for _, e in CASES if not e)} off-topic",
        f"- **Embedding model**: {embeddings.model_name} (local, free) | **Reranker**: Xenova/ms-marco-MiniLM-L-6-v2",
        f"- **Date**: {time.strftime('%Y-%m-%d')}",
        "",
        "| Retriever | hit@1 | hit@3 | MRR |",
        "|---|---|---|---|",
    ]
    for name, m in rows:
        lines.append(f"| {name} | {pct(*m['hit1'])} | {pct(*m['hit3'])} | {m['mrr']:.3f} |")
    lines += [
        "",
        '## Saying "I\'m not sure" for off-topic questions',
        "",
        f"Best cosine similarity of in-scope questions: min {in_scope[0]:.2f}, median {in_scope[len(in_scope) // 2]:.2f}. "
        f"Off-topic questions: median {off_topic[len(off_topic) // 2]:.2f}, max {off_topic[-1]:.2f}.",
        "",
        "| Retriever | Off-topic questions that retrieve nothing | Answerable questions wrongly rejected |",
        "|---|---|---|",
    ]
    for name, m in rows:
        lines.append(f"| {name} (no cutoff) | {pct(*m['abstain'])} | {pct(*m['wrong_abstain'])} |")
    lines.append(
        f"| **Vector with a similarity cutoff of {threshold}** | **{pct(*with_cutoff['abstain'])}** | "
        f"{pct(*with_cutoff['wrong_abstain'])} |"
    )
    lines += [
        "",
        f"Recommended cutoff: **{threshold}** (rejects nothing that has an answer). Average search time: {with_cutoff['ms']:.0f} ms.",
    ]
    report = "\n".join(lines) + "\n"
    out = harness.RESULTS / "retrieval.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8", newline="\n")
    print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
