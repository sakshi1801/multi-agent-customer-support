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

LangSmith tracing turns on automatically when LANGSMITH_TRACING=true and
LANGSMITH_API_KEY are in your .env (no code changes needed).
"""

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/support.db")
FAQ_PATH = os.getenv("FAQ_PATH", "data/faq.md")


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


def get_llm():
    """Return a chat model. Imported lazily so tests never need an API key."""
    provider = get_provider()

    if provider == "azure":
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            temperature=0,
        )

    from langchain_openai import ChatOpenAI

    if provider in COMPATIBLE_PROVIDERS:
        # Same OpenAI client, different base URL. The model must support tool calling
        # (the supervisor gets its routing decision through a tool call).
        p = COMPATIBLE_PROVIDERS[provider]
        base_url = p.base_url or os.environ["LLM_BASE_URL"]
        model = os.getenv(p.model_env) or p.default_model
        if not model:
            raise ValueError(f"Set {p.model_env} for the {provider!r} provider")
        # Local servers such as Ollama ignore the key, but the client requires a non-empty one.
        api_key = os.getenv(p.key_env) or "not-needed"
        return ChatOpenAI(model=model, api_key=api_key, base_url=base_url, temperature=0)

    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
