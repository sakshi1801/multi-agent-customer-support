"""Shared fixtures: temp DB, a rule-based fake LLM (no API key needed) and a keyword router."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import auth, config, db  # noqa: E402
from app.graph import build_graph  # noqa: E402
from app.main import create_app  # noqa: E402
from app.testing import FakeSpecialistLLM, keyword_router  # noqa: E402,F401


@pytest.fixture(autouse=True)
def fast_hashing(monkeypatch):
    """Password hashing is deliberately slow; make it cheap in tests."""
    monkeypatch.setattr(auth, "PBKDF2_ITERATIONS", 1_000)
    monkeypatch.setenv("TOKEN_SECRET", "test-secret")
    monkeypatch.setenv("AGENT_API_KEY", "test-agent-key")


@pytest.fixture(autouse=True)
def offline_retrieval(monkeypatch):
    """Tests never download an embedding model: hashed bag-of-words embeddings and a low cutoff."""
    monkeypatch.setattr(config, "RAG_EMBEDDINGS", "hash")
    monkeypatch.setattr(config, "RAG_MIN_SIMILARITY", 0.15)
    monkeypatch.setattr(config, "RAG_MODE", "vector")
    monkeypatch.setattr(config, "KB_DIR", str(ROOT / "data" / "kb"))


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "test.db"))
    db.init_db()
    return config.DB_PATH


@pytest.fixture()
def graph(temp_db):
    return build_graph(llm=FakeSpecialistLLM(), router=keyword_router)


@pytest.fixture()
def client(graph):
    with TestClient(create_app(graph=graph)) as c:
        yield c


AGENT_HEADERS = {"X-API-Key": "test-agent-key"}


def login(client, email: str) -> dict:
    """Headers for a logged-in demo customer."""
    r = client.post("/auth/login", json={"email": email, "password": db.DEMO_PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
