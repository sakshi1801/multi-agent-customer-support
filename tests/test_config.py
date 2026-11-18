"""Provider selection in app.config.get_llm (no network calls: models are only constructed)."""

import pytest
from langchain_openai import ChatOpenAI

from app import config

PROVIDER_VARS = ("AZURE_OPENAI_ENDPOINT", "OPENROUTER_API_KEY", "OPENROUTER_MODEL", "OPENAI_MODEL")


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
    monkeypatch.setenv("OPENROUTER_MODEL", "anthropic/claude-haiku-4.5")
    llm = config.get_llm()
    assert config.get_provider() == "openrouter"
    assert llm.openai_api_base == config.OPENROUTER_BASE_URL
    assert llm.model_name == "anthropic/claude-haiku-4.5"
    assert llm.openai_api_key.get_secret_value() == "sk-or-test"  # not the OpenAI key


def test_openrouter_default_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert config.get_llm().model_name == "openai/gpt-4o-mini"


def test_azure_takes_priority_over_openrouter(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")
    assert config.get_provider() == "azure"
