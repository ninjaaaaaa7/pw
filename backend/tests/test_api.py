"""Integration tests for the FastAPI endpoints (demo mode, no network)."""

import pytest
from fastapi.testclient import TestClient

from app import ai_assistant
from app.main import RateLimiter, app, rate_limiter

ORIGIN = "http://localhost:3000"


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr(ai_assistant.settings, "gemini_api_key", "")
    rate_limiter.reset()
    ai_assistant.cache.clear()
    with TestClient(app) as test_client:
        yield test_client


def test_health(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["ai_enabled"] is False
    assert body["model"]


def test_sample_document(client):
    body = client.get("/api/sample").json()
    assert "document_text" in body and len(body["document_text"]) > 500
    assert body["user_role"]


def test_assess_is_deterministic_and_explainable(client):
    sample = client.get("/api/sample").json()
    first = client.post("/api/assess", json=sample).json()
    second = client.post("/api/assess", json=sample).json()
    assert first == second
    assert 0 <= first["risk_score"] <= 100
    assert first["clauses"] and all(c["excerpt"] for c in first["clauses"])


def test_analyze_document_returns_four_cards_in_demo_mode(client):
    sample = client.get("/api/sample").json()
    response = client.post("/api/analyze-document", json=sample)
    assert response.status_code == 200
    body = response.json()
    assert set(body) >= {
        "executive_summary",
        "risk_flags",
        "user_obligations",
        "lawyer_questions",
        "analysis",
        "mode",
        "disclaimer",
    }
    assert body["mode"] == "demo"
    assert len(body["lawyer_questions"]) == 3
    assert body["risk_flags"][0]["severity"] in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"document_text": ""},
        {"document_text": "   \n  "},
        {"document_text": "x" * (ai_assistant.settings.max_document_chars + 1)},
        {"document_text": "valid text here", "user_role": "r" * 61},
    ],
)
def test_analyze_document_rejects_invalid_payloads(client, payload):
    assert client.post("/api/analyze-document", json=payload).status_code == 422


def test_rate_limit_returns_429(client, monkeypatch):
    monkeypatch.setattr("app.main.rate_limiter", RateLimiter(limit=2))
    body = {"document_text": "Tenant shall pay rent monthly."}
    assert client.post("/api/analyze-document", json=body).status_code == 200
    assert client.post("/api/analyze-document", json=body).status_code == 200
    blocked = client.post("/api/analyze-document", json=body)
    assert blocked.status_code == 429
    assert blocked.headers["Retry-After"] == "60"


def test_rate_limiter_window_expires():
    limiter = RateLimiter(limit=1, window_seconds=10)
    assert limiter.allow("ip", now=0.0)
    assert not limiter.allow("ip", now=5.0)
    assert limiter.allow("ip", now=11.0)


def test_rate_limiter_evicts_idle_clients():
    limiter = RateLimiter(limit=5, window_seconds=10)
    for i in range(RateLimiter.SWEEP_EVERY - 1):
        limiter.allow(f"client-{i}", now=0.0)
    assert len(limiter._hits) == RateLimiter.SWEEP_EVERY - 1
    # The sweep call lands well outside the window: every idle client is dropped.
    limiter.allow("fresh", now=100.0)
    assert set(limiter._hits) == {"fresh"}


def test_security_headers_present(client):
    response = client.get("/api/health")
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Cache-Control"] == "no-store"


def test_cors_allows_configured_origin_only(client):
    ok = client.options(
        "/api/analyze-document",
        headers={"Origin": ORIGIN, "Access-Control-Request-Method": "POST"},
    )
    assert ok.status_code == 200
    assert ok.headers["access-control-allow-origin"] == ORIGIN

    denied = client.options(
        "/api/analyze-document",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert "access-control-allow-origin" not in denied.headers


def test_openapi_documents_the_endpoints(client):
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/api/health", "/api/sample", "/api/assess", "/api/analyze-document"} <= set(paths)
