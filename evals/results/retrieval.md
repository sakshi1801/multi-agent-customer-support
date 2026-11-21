# Retrieval evaluation

- **Knowledge base**: 41 sections from 7 files
- **Questions**: 41 answerable + 9 off-topic
- **Embedding model**: BAAI/bge-small-en-v1.5 (local, free) | **Reranker**: Xenova/ms-marco-MiniLM-L-6-v2
- **Date**: 2026-11-21

| Retriever | hit@1 | hit@3 | MRR |
|---|---|---|---|
| Keyword overlap (the original prototype) | 29.3% (12/41, 95% CI 18-44%) | 53.7% (22/41, 95% CI 39-68%) | 0.402 |
| BM25 | 24.4% (10/41, 95% CI 14-39%) | 48.8% (20/41, 95% CI 34-64%) | 0.354 |
| Vector (bge-small embeddings, Chroma) | 75.6% (31/41, 95% CI 61-86%) | 92.7% (38/41, 95% CI 81-97%) | 0.833 |
| Hybrid (BM25 + vector, reciprocal rank fusion) | 48.8% (20/41, 95% CI 34-64%) | 82.9% (34/41, 95% CI 69-91%) | 0.630 |
| Hybrid + cross-encoder rerank | 75.6% (31/41, 95% CI 61-86%) | 82.9% (34/41, 95% CI 69-91%) | 0.785 |
| Vector + cross-encoder rerank | 75.6% (31/41, 95% CI 61-86%) | 85.4% (35/41, 95% CI 72-93%) | 0.793 |

## Saying "I'm not sure" for off-topic questions

Best cosine similarity of in-scope questions: min 0.55, median 0.70. Off-topic questions: median 0.47, max 0.55.

| Retriever | Off-topic questions that retrieve nothing | Answerable questions wrongly rejected |
|---|---|---|
| Keyword overlap (the original prototype) (no cutoff) | 88.9% (8/9, 95% CI 56-98%) | 9.8% (4/41, 95% CI 4-23%) |
| BM25 (no cutoff) | 88.9% (8/9, 95% CI 56-98%) | 9.8% (4/41, 95% CI 4-23%) |
| Vector (bge-small embeddings, Chroma) (no cutoff) | 0.0% (0/9, 95% CI 0-30%) | 0.0% (0/41, 95% CI 0-9%) |
| Hybrid (BM25 + vector, reciprocal rank fusion) (no cutoff) | 0.0% (0/9, 95% CI 0-30%) | 0.0% (0/41, 95% CI 0-9%) |
| Hybrid + cross-encoder rerank (no cutoff) | 0.0% (0/9, 95% CI 0-30%) | 0.0% (0/41, 95% CI 0-9%) |
| Vector + cross-encoder rerank (no cutoff) | 0.0% (0/9, 95% CI 0-30%) | 0.0% (0/41, 95% CI 0-9%) |
| **Vector with a similarity cutoff of 0.53** | **66.7% (6/9, 95% CI 35-88%)** | 0.0% (0/41, 95% CI 0-9%) |

Recommended cutoff: **0.53** (rejects nothing that has an answer). Average search time: 31 ms.
