"""LLM + environment configuration.

Supported providers (all speak the OpenAI chat API, so one client covers them):

  azure       Azure OpenAI                      AZURE_OPENAI_ENDPOINT, AZURE_OPENAI_API_KEY, AZURE_OPENAI_DEPLOYMENT
  groq        Groq (free tier available)        GROQ_API_KEY, GROQ_MODEL
  openrouter  OpenRouter (":free" models)       OPENROUTER_API_KEY, OPENROUTER_MODEL
  custom      any OpenAI-compatible server,     LLM_BASE_URL, LLM_API_KEY, LLM_MODEL
              e.g. Ollama or Gemini
  openai      OpenAI                            OPENAI_API_KEY, OPENAI_MODEL

Set LLM_PROVIDER to pick one explicitly (handy when several keys are in .env).
Otherwise the first configured provider in the order above is used.

LLM_FALLBACKS (comma-separated provider names, e.g. "openrouter,custom") lists providers to try when
the main one fails, for example when a free tier is rate-limited. This is the LangChain Runnables
`.with_fallbacks()` pattern: the same call is retried on the next model in the list.

LangSmith tracing turns on automatically when LANGSMITH_TRACING=true and
LANGSMITH_API_KEY are in your .env (no code changes needed).
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/support.db")
GUARD = os.getenv(
    "GUARD", ""
)  # "promptguard" = refuse blunt prompt injection (Llama Prompt Guard 2 on Groq, free)
GUARD_THRESHOLD = float(os.getenv("GUARD_THRESHOLD", "0.5"))
SUPERVISOR_MODE = os.getenv(
    "SUPERVISOR_MODE", "plan"
)  # "plan" (ask once; measured better) or "loop" (ask after every step)
KB_DIR = os.getenv("KB_DIR", "data/kb")  # knowledge-base Markdown files for the FAQ agent (RAG)
# Retrieval settings, chosen from evals/results/retrieval.md: plain vector search beat BM25 and hybrid fusion,
# and a cosine-similarity cutoff makes the agent say "not sure" for questions the knowledge base cannot answer.
RAG_EMBEDDINGS = os.getenv("RAG_EMBEDDINGS", "fastembed")  # "hash" = offline stand-in used by tests and CI
RAG_MODE = os.getenv("RAG_MODE", "vector")  # keyword | bm25 | vector | hybrid
RAG_MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.53"))
RAG_RERANK = os.getenv("RAG_RERANK", "0") == "1"
CHECKPOINT_PATH = os.getenv("CHECKPOINT_PATH", "data/checkpoints.db")  # conversation state (LangGraph)


@dataclass(frozen=True)
class CompatibleProvider:
    """An OpenAI-compatible endpoint: where to send requests and which env vars configure it."""

    base_url: str | None  # None -> read from LLM_BASE_URL
    key_env: str
    model_env: str
    default_model: str | None


OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
GROQ_BASE_URL = "https://api.groq.com/openai/v1"

COMPATIBLE_PROVIDERS = {
    "groq": CompatibleProvider(GROQ_BASE_URL, "GROQ_API_KEY", "GROQ_MODEL", "openai/gpt-oss-120b"),
    "openrouter": CompatibleProvider(
        OPENROUTER_BASE_URL, "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "openai/gpt-4o-mini"
    ),
    "custom": CompatibleProvider(None, "LLM_API_KEY", "LLM_MODEL", None),
}
PROVIDERS = ("azure", *COMPATIBLE_PROVIDERS, "openai")


def get_provider() -> str:
    """Name of the LLM provider the current environment selects."""
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit:
        if explicit not in PROVIDERS:
            raise ValueError(f"LLM_PROVIDER={explicit!r} is not one of {', '.join(PROVIDERS)}")
        return explicit
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        return "azure"
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
    if os.getenv("LLM_BASE_URL"):
        return "custom"
    return "openai"


def get_fallback_providers() -> list[str]:
    """Providers named in LLM_FALLBACKS, validated and without duplicates of the main provider."""
    main = get_provider()
    names = [n.strip().lower() for n in os.getenv("LLM_FALLBACKS", "").split(",") if n.strip()]
    unknown = [n for n in names if n not in PROVIDERS]
    if unknown:
        raise ValueError(f"LLM_FALLBACKS has unknown provider(s): {', '.join(unknown)}")
    return [n for i, n in enumerate(names) if n != main and n not in names[:i]]


def get_llm():
    """Return the chat model: the main provider, wrapped with the configured fallbacks.

    Imported lazily so tests never need an API key.
    """
    primary = build_llm(get_provider())
    fallbacks = [build_llm(name) for name in get_fallback_providers()]
    return primary.with_fallbacks(fallbacks) if fallbacks else primary


def build_llm(provider: str, model: str | None = None, max_retries: int | None = None):
    """Construct the chat model for one named provider.

    model        overrides the model name from the environment (used by the evaluation runs)
    max_retries  how often the client retries rate-limit and server errors before giving up
                 (default: LLM_MAX_RETRIES, else 2). LLM_REASONING_EFFORT=low|medium|high is passed
                 to reasoning models such as gpt-oss: "low" gives much cheaper routing decisions.
    """
    retries = max_retries if max_retries is not None else int(os.getenv("LLM_MAX_RETRIES", "2"))
    effort = os.getenv("LLM_REASONING_EFFORT") or None
    if provider == "azure":
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_deployment=model or os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            temperature=0,
            max_retries=retries,
        )

    from langchain_openai import ChatOpenAI

    if provider in COMPATIBLE_PROVIDERS:
        # Same OpenAI client, different base URL. The model must support tool calling
        # (the supervisor gets its routing decision through a tool call).
        p = COMPATIBLE_PROVIDERS[provider]
        base_url = p.base_url or os.environ["LLM_BASE_URL"]
        name = model or os.getenv(p.model_env) or p.default_model
        if not name:
            raise ValueError(f"Set {p.model_env} for the {provider!r} provider")
        # Local servers such as Ollama ignore the key, but the client requires a non-empty one.
        api_key = os.getenv(p.key_env) or "not-needed"
        return ChatOpenAI(
            model=name,
            api_key=api_key,
            base_url=base_url,
            temperature=0,
            max_retries=retries,
            reasoning_effort=effort,
        )

    return ChatOpenAI(
        model=model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0, max_retries=retries
    )
