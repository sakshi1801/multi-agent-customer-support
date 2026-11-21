# Resume text for this project

Every number below comes from a committed result file (see [EVALUATION.md](EVALUATION.md)). Use only the
bullets you can explain in an interview; [INTERVIEW_NOTES.md](INTERVIEW_NOTES.md) has the answers.

## The project entry (recommended)

**Multi-Agent Customer Support System** | Python, LangGraph, LangChain, FastAPI, Chroma, Ollama/Groq, Docker, GitHub Actions | [GitHub](https://github.com/sakshi1801/multi-agent-customer-support)

- Built a LangGraph **supervisor** that routes customer messages to Orders (tool calling), FAQ (RAG with cited sources) and Escalation agents, with **human-in-the-loop** handoff (`interrupt()` + persistent checkpointer) and a FastAPI service with a demo UI.
- Evaluated on a **132-case hand-labelled set**: **92.4% routing accuracy** and **100% escalation recall (25/25)**, against 72.0% for a keyword baseline; replacing a step-by-step supervisor with a **single-call planner** cut model calls **44%** (1.78 to 1.0), tokens **50%** and median latency **48%**, and raised accuracy from 87.1%.
- **Red-teamed my own system**: found that prompt injection could read another customer's orders, and fixed it by enforcing authorization in the tool layer (identity injected from a signed token, hidden from the model); **all 9 attack cases leaked nothing end to end**, including on a 4B local model, backed by a security test suite and a mutation check.
- Built **RAG** over a 41-section knowledge base (Chroma, local ONNX embeddings): **92.7% top-3 retrieval vs 53.7%** for the original keyword search; benchmarked BM25, hybrid fusion and a cross-encoder reranker and kept the best.
- Ran the whole project at **zero cost** (Groq free tier, OpenRouter free models, local Ollama): a rate-limit-aware, resumable evaluation harness, provider fallbacks, a Dockerised build with CI image build and smoke test, and 120+ deterministic tests.

Shorter version (three bullets) if space is tight: keep bullets 2, 3 and 4.

## Edits to the rest of the resume

These are about accuracy: a recruiter or interviewer may ask about every claim.

1. **Project heading.** The current line says *Python, LangGraph, FastAPI, Azure OpenAI, LangSmith*. This project
   uses neither Azure OpenAI nor LangSmith results. Drop both from this project's list (or only add them back
   after a real run). *Groq, Ollama, Chroma, Docker, GitHub Actions* are accurate.
2. **"In progress".** Rename the section from *AI Projects (In Progress)* once you are comfortable with the
   project; the code, tests, evaluation and CI are done.
3. **Summary line.** *"multi-agent systems (LangGraph), RAG and LangSmith evaluation in Python on Azure"*:
   change to match what exists, for example *"multi-agent systems (LangGraph), RAG and measured evaluation in
   Python"*. Keep "Azure" only if you deploy there. The Azure AI-103 certificate (in progress) is a separate claim and fine.
4. **Skills.** Add *Ollama, Groq, Chroma, FastEmbed, evaluation harnesses* under GenAI. *LangSmith* and *RAGAS*
   are listed in the skills section: keep them only if you have used them (this project did not).
5. **Add the live link** when the demo is hosted (see [DEPLOY.md](DEPLOY.md)): a working URL is worth more than any bullet.

## Numbers to quote, and where they come from

| Claim | Source file |
|---|---|
| 92.4% routing, 100% escalation recall, 89.3% precision | `evals/results/routing__groq__openai-gpt-oss-120b__planner__plan.md` |
| 87.1% for the loop supervisor, 1.78 calls, 950 tokens, 1.44 s | `evals/results/routing__groq__openai-gpt-oss-120b__baseline.md` |
| 72.0% keyword baseline | `evals/results/routing__none__keyword-rules__keyword-rules.md` |
| 92.7% vs 53.7% retrieval | `evals/results/retrieval.md` |
| 9 of 9 attacks, end to end | `evals/results/e2e__*` (hosted and local) |
| 4B local model: 84.8% planner, 53.0% loop | `evals/results/routing__custom__*` |

Rerun any of them with the commands at the bottom of [EVALUATION.md](EVALUATION.md); the figures are dated and tied to a git commit.
