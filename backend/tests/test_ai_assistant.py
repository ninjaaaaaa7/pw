"""Tests for the generative layer: prompt grounding, demo mode, fallback, cache."""

import httpx
import pytest

from app import ai_assistant
from app.clause_engine import analyze_document
from app.models import AnalyzeRequest
from app.sample_data import SAMPLE_DOCUMENT

VALID_MODEL_JSON = {
    "executive_summary": "A one-sided contractor agreement.",
    "risk_flags": [
        {
            "category": "indemnification",
            "severity": "CRITICAL",
            "title": "Indemnification",
            "explanation": "Uncapped.",
        }
    ],
    "user_obligations": ["Deliver work on time."],
    "lawyer_questions": ["Q1?", "Q2?", "Q3?", "Q4 should be dropped?"],
}


@pytest.fixture(autouse=True)
def _fresh_cache():
    ai_assistant.cache.clear()
    yield
    ai_assistant.cache.clear()


def _request(role: str = "Contractor") -> AnalyzeRequest:
    return AnalyzeRequest(document_text=SAMPLE_DOCUMENT, user_role=role, language="English")


def test_prompt_is_grounded_in_analysis():
    req = _request(role="freelance designer")
    analysis = analyze_document(req.document_text)
    prompt = ai_assistant.build_prompt(analysis, req)
    assert ai_assistant.SYSTEM_INSTRUCTIONS in prompt
    assert "freelance designer" in prompt
    assert f"{analysis.risk_score}/100" in prompt
    for clause in analysis.clauses:
        assert clause.title in prompt
    assert "<document>" in prompt and req.document_text in prompt


def test_prompt_asks_for_document_specific_risks_when_rules_find_nothing():
    req = AnalyzeRequest(document_text="It is prayed that the Hon'ble Court grant bail to the applicant.")
    analysis = analyze_document(req.document_text)
    assert analysis.clauses == []
    prompt = ai_assistant.build_prompt(analysis, req)
    assert "none of the tracked risk categories were found" in prompt
    assert "category `other`" in prompt
    assert "list up to 5 such risks" in prompt


def test_demo_response_is_complete_and_deterministic():
    req = _request()
    analysis = analyze_document(req.document_text)
    first = ai_assistant.demo_response(analysis, req)
    second = ai_assistant.demo_response(analysis, req)
    assert first == second
    assert first.mode == "demo"
    assert first.executive_summary
    assert len(first.lawyer_questions) == 3
    assert [f.category for f in first.risk_flags] == [c.category for c in analysis.clauses]
    assert first.user_obligations == analysis.obligations


def test_demo_response_for_benign_text_still_has_three_questions():
    req = AnalyzeRequest(document_text="The parties will meet monthly to review progress together.")
    response = ai_assistant.demo_response(analyze_document(req.document_text), req)
    assert response.risk_flags == []
    assert len(response.lawyer_questions) == 3


async def test_run_analysis_without_key_uses_demo(monkeypatch):
    monkeypatch.setattr(ai_assistant.settings, "gemini_api_key", "")
    response = await ai_assistant.run_analysis(_request())
    assert response.mode == "demo"


async def test_run_analysis_live_path(monkeypatch):
    monkeypatch.setattr(ai_assistant.settings, "gemini_api_key", "test-key")

    async def fake_call(_prompt: str) -> dict:
        return VALID_MODEL_JSON

    monkeypatch.setattr(ai_assistant, "_call_gemini", fake_call)
    response = await ai_assistant.run_analysis(_request())
    assert response.mode == "live"
    assert response.executive_summary == "A one-sided contractor agreement."
    assert len(response.lawyer_questions) == 3  # capped at three
    assert response.analysis.risk_level == "CRITICAL"  # deterministic part is untouched


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("boom"),
        ValueError("not json"),
        KeyError("candidates"),
    ],
)
async def test_run_analysis_falls_back_on_model_failure(monkeypatch, failure):
    monkeypatch.setattr(ai_assistant.settings, "gemini_api_key", "test-key")

    async def failing_call(_prompt: str) -> dict:
        raise failure

    monkeypatch.setattr(ai_assistant, "_call_gemini", failing_call)
    response = await ai_assistant.run_analysis(_request())
    assert response.mode == "demo"
    assert response.executive_summary


async def test_run_analysis_falls_back_on_schema_violation(monkeypatch):
    monkeypatch.setattr(ai_assistant.settings, "gemini_api_key", "test-key")

    async def bad_shape(_prompt: str) -> dict:
        return {"executive_summary": "x", "risk_flags": [{"severity": "EXTREME"}]}

    monkeypatch.setattr(ai_assistant, "_call_gemini", bad_shape)
    response = await ai_assistant.run_analysis(_request())
    assert response.mode == "demo"


async def test_live_results_are_cached_but_demo_results_are_not(monkeypatch):
    monkeypatch.setattr(ai_assistant.settings, "gemini_api_key", "test-key")
    calls = 0

    async def counting_call(_prompt: str) -> dict:
        nonlocal calls
        calls += 1
        return VALID_MODEL_JSON

    monkeypatch.setattr(ai_assistant, "_call_gemini", counting_call)
    await ai_assistant.run_analysis(_request())
    await ai_assistant.run_analysis(_request())
    assert calls == 1  # second identical request served from cache
    await ai_assistant.run_analysis(_request(role="Company"))
    assert calls == 2  # different user context -> different cache key

    ai_assistant.cache.clear()

    async def failing(_prompt: str) -> dict:
        raise httpx.ReadTimeout("slow")

    monkeypatch.setattr(ai_assistant, "_call_gemini", failing)
    assert (await ai_assistant.run_analysis(_request())).mode == "demo"
    monkeypatch.setattr(ai_assistant, "_call_gemini", counting_call)
    assert (await ai_assistant.run_analysis(_request())).mode == "live"


async def test_gemini_key_is_sent_in_header_not_url(monkeypatch):
    monkeypatch.setattr(ai_assistant.settings, "gemini_api_key", "secret-key")
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["header"] = request.headers.get("x-goog-api-key")
        body = {"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}}]}
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(ai_assistant, "_client", httpx.AsyncClient(transport=transport))
    result = await ai_assistant._call_gemini("hello")
    assert result == {"ok": True}
    assert captured["header"] == "secret-key"
    assert "secret-key" not in captured["url"]


def test_describe_failure_surfaces_api_message_without_secrets():
    request = httpx.Request("POST", "https://example.invalid/v1beta/models/x:generateContent")
    response = httpx.Response(
        400, request=request, json={"error": {"message": "API key not valid", "status": "INVALID_ARGUMENT"}}
    )
    exc = httpx.HTTPStatusError("bad", request=request, response=response)
    assert ai_assistant._describe_failure(exc) == "HTTP 400 - API key not valid"

    plain = httpx.Response(502, request=request, text="<html>bad gateway</html>")
    exc2 = httpx.HTTPStatusError("bad", request=request, response=plain)
    assert ai_assistant._describe_failure(exc2).startswith("HTTP 502 - <html>")

    assert ai_assistant._describe_failure(ValueError("x")) == "ValueError"
