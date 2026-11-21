"""Provider selection in app.config.get_llm (no network calls: models are only constructed)."""

import pytest
from langchain_openai import ChatOpenAI

from app import config

PROVIDER_VARS = (
    "LLM_PROVIDER",
    "AZURE_OPENAI_ENDPOINT",
    "GROQ_API_KEY",
    "GROQ_MODEL",
    "OPENROUTER_API_KEY",
    "OPENROUTER_MODEL",
    "LLM_BASE_URL",
    "LLM_API_KEY",
    "LLM_MODEL",
    "OPENAI_MODEL",
    "LLM_FALLBACKS",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for var in PROVIDER_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-openai")


def test_defaults_to_openai():
    llm = config.get_llm()
    assert config.get_provider() == "openai"
    assert isinstance(llm, ChatOpenAI)
    assert llm.model_name == "gpt-4o-mini"
    assert llm.openai_api_base is None  # api.openai.com


def test_openrouter_key_switches_base_url_and_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "nvidia/nemotron-3.5-super-vl:free")
    llm = config.get_llm()
    assert config.get_provider() == "openrouter"
    assert llm.openai_api_base == config.OPENROUTER_BASE_URL
    assert llm.model_name == "nvidia/nemotron-3.5-super-vl:free"
    assert llm.openai_api_key.get_secret_value() == "sk-or-test"  # not the OpenAI key


def test_groq_key_selects_groq_with_default_model(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    llm = config.get_llm()
    assert config.get_provider() == "groq"
    assert llm.openai_api_base == config.GROQ_BASE_URL
    assert llm.model_name == "openai/gpt-oss-120b"
    assert llm.openai_api_key.get_secret_value() == "gsk-test"


def test_groq_wins_over_openrouter_when_both_keys_are_set(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert config.get_provider() == "groq"


def test_llm_provider_overrides_auto_detection(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("LLM_PROVIDER", "OpenRouter")  # case-insensitive
    assert config.get_llm().openai_api_base == config.OPENROUTER_BASE_URL


def test_unknown_llm_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "nope")
    with pytest.raises(ValueError, match="not one of"):
        config.get_provider()


def test_custom_base_url_for_local_ollama(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("LLM_MODEL", "qwen3:4b")
    llm = config.get_llm()
    assert config.get_provider() == "custom"
    assert llm.openai_api_base == "http://localhost:11434/v1"
    assert llm.model_name == "qwen3:4b"


def test_custom_provider_requires_a_model(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    with pytest.raises(ValueError, match="LLM_MODEL"):
        config.get_llm()


def test_azure_takes_priority_over_other_keys(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    assert config.get_provider() == "azure"


# ---------- fallbacks (Runnables: .with_fallbacks) ----------
def test_no_fallbacks_returns_the_plain_model(monkeypatch):
    assert isinstance(config.get_llm(), ChatOpenAI)


def test_fallbacks_wrap_the_main_model(monkeypatch):
    from langchain_core.runnables import RunnableWithFallbacks

    monkeypatch.setenv("GROQ_API_KEY", "gsk-test")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv(
        "LLM_FALLBACKS", "openrouter, openrouter ,groq"
    )  # duplicates and the main one are dropped
    assert config.get_fallback_providers() == ["openrouter"]
    llm = config.get_llm()
    assert isinstance(llm, RunnableWithFallbacks)
    assert llm.runnable.openai_api_base == config.GROQ_BASE_URL
    assert [f.openai_api_base for f in llm.fallbacks] == [config.OPENROUTER_BASE_URL]


def test_unknown_fallback_provider_is_rejected(monkeypatch):
    monkeypatch.setenv("LLM_FALLBACKS", "groq,mystery")
    with pytest.raises(ValueError, match="mystery"):
        config.get_fallback_providers()
