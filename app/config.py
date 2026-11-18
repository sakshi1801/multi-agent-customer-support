"""LLM + environment configuration.

Uses Azure OpenAI when AZURE_OPENAI_ENDPOINT is set, otherwise plain OpenAI.
LangSmith tracing turns on automatically when LANGSMITH_TRACING=true and
LANGSMITH_API_KEY are in your .env (no code changes needed).
"""
import os

from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "data/support.db")
FAQ_PATH = os.getenv("FAQ_PATH", "data/faq.md")


def get_llm():
    """Return a chat model. Imported lazily so tests never need an API key."""
    if os.getenv("AZURE_OPENAI_ENDPOINT"):
        from langchain_openai import AzureChatOpenAI

        return AzureChatOpenAI(
            azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o-mini"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21"),
            temperature=0,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), temperature=0)
