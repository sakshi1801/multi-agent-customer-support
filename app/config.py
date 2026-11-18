"""LLM + environment configuration.

Provider is picked from the environment, first match wins:
  1. Azure OpenAI  when AZURE_OPENAI_ENDPOINT is set
  2. OpenRouter    when OPENROUTER_API_KEY is set (OpenAI-compatible API, any hosted model)
  3. OpenAI        otherwise (OPENAI_API_KEY)

LangSmith tracing turns on automatically when LANGSMITH_TRACING=true and
LANGSMITH_API_KEY are in your .env (no code changes needed).
"""

import os

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/support.db")
FAQ_PATH = os.getenv("FAQ_PATH", "data/faq.md")

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def get_provider() -> str:
    """Name of the LLM provider the current environment selects."""
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        return "azure"
    if os.getenv("OPENROUTER_API_KEY"):
        return "openrouter"
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

    if provider == "openrouter":
        # OpenRouter speaks the OpenAI API, so ChatOpenAI works with a different base URL.
        # The model must support tool calling and structured output (e.g. openai/gpt-4o-mini).
        return ChatOpenAI(
            model=os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini"),
            api_key=os.environ["OPENROUTER_API_KEY"],
            base_url=OPENROUTER_BASE_URL,
            temperature=0,
        )

    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
