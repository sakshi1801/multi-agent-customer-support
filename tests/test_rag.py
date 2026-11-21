"""The RAG pipeline: loader -> splitter -> embeddings -> vector store -> retrievers (offline, hash embeddings)."""

import pytest

from app import rag
from app.testing import HashEmbeddings
from evals.retrieval_cases import CASES

KB_DIR = rag.Path(__file__).resolve().parent.parent / "data" / "kb"


@pytest.fixture(scope="module")
def kb():
    return rag.build_kb(KB_DIR, HashEmbeddings())


def test_loader_reads_every_markdown_file():
    docs = list(rag.KnowledgeBaseLoader(KB_DIR).lazy_load())
    assert {d.metadata["source"] for d in docs} >= {"shipping.md", "returns.md", "payments.md", "warranty.md"}
    assert all(d.page_content.startswith("# ") for d in docs)


def test_splitter_makes_one_cited_chunk_per_section(kb):
    ids = [c.metadata["id"] for c in kb.chunks]
    assert len(ids) == len(set(ids)) >= 40  # unique id per section
    chunk = next(c for c in kb.chunks if c.metadata["id"] == "Returns > Return window")
    assert chunk.metadata["topic"] == "Returns" and chunk.metadata["section"] == "Return window"
    assert chunk.page_content.startswith("Returns - Return window:")  # heading is part of what gets embedded
    assert "30 days" in chunk.metadata["text"] and "#" not in chunk.metadata["text"]


def test_every_answerable_question_in_the_eval_set_points_at_a_real_section(kb):
    ids = {c.metadata["id"] for c in kb.chunks}
    for question, expected in CASES:
        assert expected is None or set(expected) <= ids, question


def test_facts_the_end_to_end_checks_rely_on_are_in_the_knowledge_base(kb):
    text = " ".join(c.metadata["text"] for c in kb.chunks).lower()
    for fact in [
        "30 days",
        "3-5 business days",
        "over $50",
        "visa",
        "upi",
        "5-7 business days",
        "1-year",
        "9am to 6pm",
    ]:
        assert fact in text, fact


def test_each_retrieval_mode_returns_ranked_hits(kb):
    for mode in rag.MODES:
        hits = kb.search("How long do I have to return something?", k=3, mode=mode)
        assert 1 <= len(hits) <= 3, mode
        assert any(h.doc.metadata["id"] == "Returns > Return window" for h in hits), mode


def test_unknown_mode_is_rejected(kb):
    with pytest.raises(ValueError, match="mode"):
        kb.search("x", mode="magic")


def test_similarity_cutoff_returns_nothing_for_off_topic_questions(kb):
    assert kb.search("zzzz qqqq xxxx", k=3, mode="vector", min_similarity=0.15) == []
    assert kb.search("return window days", k=3, mode="vector", min_similarity=0.15)


def test_reciprocal_rank_fusion_prefers_what_both_retrievers_like(kb):
    q = "refund after returning an item"
    fused = [h.doc.metadata["id"] for h in kb.hybrid(q, 3)]
    bm = [h.doc.metadata["id"] for h in kb.bm25(q, 10)]
    vec = [h.doc.metadata["id"] for h in kb.vector(q, 10)]
    both = [i for i in fused if i in bm and i in vec]
    assert both and fused[0] in both  # the top fused hit appears in both rankings


def test_reciprocal_rank_metric():
    hit = lambda i: rag.Hit(rag.Document(page_content="", metadata={"id": i}), 1.0)  # noqa: E731
    assert rag.reciprocal_rank([hit("a"), hit("b")], {"b"}) == 0.5
    assert rag.reciprocal_rank([hit("a")], {"z"}) == 0.0


def test_cosine():
    assert rag.cosine([1, 0], [1, 0]) == 1.0
    assert rag.cosine([1, 0], [0, 1]) == 0.0
    assert rag.cosine([0, 0], [1, 1]) == 0.0


def test_empty_knowledge_base_is_an_error(tmp_path):
    with pytest.raises(ValueError, match="No knowledge-base"):
        rag.build_kb(tmp_path, HashEmbeddings())
