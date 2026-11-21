"""Retrieval-augmented generation over the store knowledge base (data/kb/*.md).

Each step is one lesson of the LangChain course:
  document loader   KnowledgeBaseLoader reads the Markdown files into Documents
  text splitter     one chunk per "## section", keeping topic and section as citation metadata
  embeddings        FastEmbedEmbeddings: a small local model (ONNX), so no API and no cost
  vector store      Chroma (in-memory), searched by cosine similarity
  retrievers        keyword, BM25, vector, and "hybrid" = BM25 + vector fused with reciprocal rank
                    fusion; an optional cross-encoder reranks the fused candidates

The FAQ agent only sees the chunks this module returns, and cites them as "[Topic > Section]".
"""

import math
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from langchain_chroma import Chroma
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi

STOPWORDS = frozenset(
    [
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "does",
        "for",
        "from",
        "has",
        "have",
        "how",
        "i",
        "if",
        "in",
        "is",
        "it",
        "its",
        "my",
        "of",
        "on",
        "or",
        "so",
        "that",
        "the",
        "their",
        "there",
        "this",
        "to",
        "was",
        "we",
        "what",
        "when",
        "where",
        "which",
        "who",
        "will",
        "with",
        "you",
        "your",
    ]
)
MODES = ("keyword", "bm25", "vector", "hybrid")


def tokenize(text: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS and len(t) > 1]


# ---------- 1. document loader ----------
class KnowledgeBaseLoader(BaseLoader):
    """Loads every Markdown file of a folder as one Document."""

    def __init__(self, directory: str | Path):
        self.directory = Path(directory)

    def lazy_load(self) -> Iterator[Document]:
        for path in sorted(self.directory.glob("*.md")):
            yield Document(page_content=path.read_text(encoding="utf-8"), metadata={"source": path.name})


# ---------- 2. text splitter ----------
def split_documents(docs: list[Document], max_chars: int = 900) -> list[Document]:
    """One chunk per '## section'. The topic and section are prepended to the text (so the embedding
    knows what the chunk is about) and kept as metadata (so the answer can cite it)."""
    by_header = MarkdownHeaderTextSplitter(headers_to_split_on=[("#", "topic"), ("##", "section")])
    long_text = RecursiveCharacterTextSplitter(chunk_size=max_chars, chunk_overlap=100)
    chunks: list[Document] = []
    for doc in docs:
        for part in by_header.split_text(doc.page_content):
            topic, section = part.metadata.get("topic", ""), part.metadata.get("section", "")
            if not section:
                continue
            for piece in long_text.split_text(part.page_content):
                chunks.append(
                    Document(
                        page_content=f"{topic} - {section}: {piece}",
                        metadata={
                            "source": doc.metadata["source"],
                            "topic": topic,
                            "section": section,
                            "id": f"{topic} > {section}",
                            "text": piece,
                        },
                    )
                )
    return chunks


# ---------- 3. embeddings ----------
class FastEmbedEmbeddings(Embeddings):
    """LangChain Embeddings interface around a small local ONNX model (downloaded on first use)."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        self.model_name = model_name
        self._model = None

    @property
    def model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(self.model_name)
        return self._model

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [v.tolist() for v in self.model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        # bge models are trained with this instruction in front of search queries
        return next(
            iter(self.model.embed(["Represent this sentence for searching relevant passages: " + text]))
        ).tolist()


class CrossEncoderReranker:
    """Re-scores (query, passage) pairs jointly. Slower than embeddings, so it only sees the few
    candidates that retrieval already found."""

    def __init__(self, model_name: str = "Xenova/ms-marco-MiniLM-L-6-v2"):
        from fastembed.rerank.cross_encoder import TextCrossEncoder

        self.model = TextCrossEncoder(model_name)

    def rerank(self, query: str, docs: list[Document]) -> list[Document]:
        scores = list(self.model.rerank(query, [d.metadata["text"] for d in docs]))
        return [d for _, d in sorted(zip(scores, docs, strict=True), key=lambda p: -p[0])]


# ---------- 4. vector store + retrievers ----------
@dataclass
class Hit:
    doc: Document
    score: float  # cosine similarity for vector search, mode-specific otherwise


class KnowledgeBase:
    def __init__(
        self, chunks: list[Document], embeddings: Embeddings, reranker: CrossEncoderReranker | None = None
    ):
        self.chunks = chunks
        self.reranker = reranker
        self.store = Chroma.from_documents(
            chunks,
            embeddings,
            collection_name=f"kb-{uuid.uuid4().hex[:8]}",
            collection_metadata={"hnsw:space": "cosine"},
        )
        self._bm25 = BM25Okapi([tokenize(c.page_content) for c in chunks])

    # -- individual retrievers --
    def keyword(self, query: str, k: int) -> list[Hit]:
        """The original prototype's search: count shared words (title words count triple)."""
        q = set(tokenize(query))
        scored = []
        for c in self.chunks:
            score = 3 * len(q & set(tokenize(c.metadata["section"] + " " + c.metadata["topic"])))
            score += len(q & set(tokenize(c.metadata["text"])))
            if score:
                scored.append(Hit(c, float(score)))
        return sorted(scored, key=lambda h: -h.score)[:k]

    def bm25(self, query: str, k: int) -> list[Hit]:
        scores = self._bm25.get_scores(tokenize(query))
        ranked = sorted(zip(scores, self.chunks, strict=True), key=lambda p: -p[0])
        return [Hit(c, float(s)) for s, c in ranked[:k] if s > 0]

    def vector(self, query: str, k: int) -> list[Hit]:
        results = self.store.similarity_search_with_score(query, k=k)
        return [Hit(c, 1.0 - float(distance)) for c, distance in results]  # cosine distance -> similarity

    def hybrid(self, query: str, k: int, pool: int = 10, rrf_k: int = 60) -> list[Hit]:
        """Reciprocal rank fusion: a chunk's score is the sum of 1/(rrf_k + rank) over both rankings,
        so something both retrievers like beats something only one of them likes."""
        fused: dict[str, float] = {}
        docs: dict[str, Document] = {}
        for ranking in (self.bm25(query, pool), self.vector(query, pool)):
            for rank, hit in enumerate(ranking):
                key = hit.doc.metadata["id"]
                docs[key] = hit.doc
                fused[key] = fused.get(key, 0.0) + 1.0 / (rrf_k + rank + 1)
        ranked = sorted(fused, key=lambda key: -fused[key])
        return [Hit(docs[key], fused[key]) for key in ranked[:k]]

    # -- the entry point the agent uses --
    def search(self, query: str, k: int = 3, mode: str = "hybrid", min_similarity: float = 0.0) -> list[Hit]:
        """Top-k chunks. If the best vector similarity is below min_similarity the question is not
        about anything in the knowledge base, so nothing is returned (the agent then says it is not sure)."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}")
        if min_similarity and (not (top := self.vector(query, 1)) or top[0].score < min_similarity):
            return []
        if self.reranker and mode in ("vector", "hybrid"):
            candidates = [h.doc for h in getattr(self, mode)(query, 8)]
            return [Hit(d, 1.0 / (i + 1)) for i, d in enumerate(self.reranker.rerank(query, candidates)[:k])]
        return getattr(self, mode)(query, k)


def build_kb(directory: str | Path, embeddings: Embeddings, reranker=None) -> KnowledgeBase:
    chunks = split_documents(list(KnowledgeBaseLoader(directory).lazy_load()))
    if not chunks:
        raise ValueError(f"No knowledge-base sections found in {directory}")
    return KnowledgeBase(chunks, embeddings, reranker)


@lru_cache(maxsize=2)
def get_kb(directory: str, embeddings_name: str, rerank: bool) -> KnowledgeBase:
    """The shared knowledge base, built once per process."""
    if embeddings_name == "hash":  # offline stand-in used by the tests and CI
        from app.testing import HashEmbeddings

        embeddings: Embeddings = HashEmbeddings()
    else:
        embeddings = FastEmbedEmbeddings()
    return build_kb(directory, embeddings, CrossEncoderReranker() if rerank else None)


def reciprocal_rank(hits: list[Hit], expected: set[str]) -> float:
    """1/rank of the first hit whose id is expected (0 if none): the building block of MRR."""
    for rank, hit in enumerate(hits, 1):
        if hit.doc.metadata["id"] in expected:
            return 1.0 / rank
    return 0.0


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0
