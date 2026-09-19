"""Generative-AI layer.

Sends a prompt *grounded* in the deterministic :class:`ClauseAnalysis` to
Google Gemini, constrained to a JSON schema so the answer is parsed directly
into the four cards the UI renders. The model explains facts the rules engine
already established; it is never the source of truth.

Without ``GEMINI_API_KEY`` - or if the model is slow, unreachable or returns
something that fails validation - the module degrades to a deterministic
"demo mode" built from the same analysis, so the service always answers.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from collections import OrderedDict

import httpx
from pydantic import BaseModel, ValidationError

from .clause_engine import analyze_document, score_risk
from .config import settings
from .models import AnalyzeRequest, AnalyzeResponse, ClauseAnalysis, RiskFlag

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTIONS = (
    "You are a legal parsing engine. You do not provide legal advice. "
    "Analyze the provided text and return ONLY a valid JSON object with these exact keys: "
    "`executive_summary` (3 sentences max), `risk_flags` (array of potential liabilities), "
    "`user_obligations` (array of mandatory actions), and `lawyer_questions` "
    "(array of 3 clarifying questions to ask an attorney). "
    "Ground every statement in the clause assessment you are given; do not invent clauses, "
    "amounts or dates that are not in the document."
)

# Forcing the model to fill exactly these fields in one pass is the efficient
# alternative to free-form generation: no wasted tokens, no re-prompting.
_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "risk_flags": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "severity": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH", "CRITICAL"]},
                    "title": {"type": "string"},
                    "explanation": {"type": "string"},
                },
                "required": ["category", "severity", "title", "explanation"],
            },
        },
        "user_obligations": {"type": "array", "items": {"type": "string"}},
        "lawyer_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["executive_summary", "risk_flags", "user_obligations", "lawyer_questions"],
}


class _ModelOutput(BaseModel):
    """Validates the model's JSON before it reaches the API response."""

    executive_summary: str
    risk_flags: list[RiskFlag]
    user_obligations: list[str]
    lawyer_questions: list[str]


def build_prompt(analysis: ClauseAnalysis, request: AnalyzeRequest) -> str:
    """Assemble the grounded prompt sent to the model."""
    role = request.user_role or "the party reading this document"
    lines = [
        SYSTEM_INSTRUCTIONS,
        "",
        f"The user is: {role}. Write from their perspective.",
        f"Document type: {analysis.document_type} ({analysis.word_count} words).",
        f"Overall risk: {analysis.risk_score}/100 ({analysis.risk_level}).",
    ]
    if analysis.parties:
        lines.append(f"Named parties: {', '.join(analysis.parties)}.")
    if analysis.one_sided_toward:
        lines.append(f"Obligations fall disproportionately on: {analysis.one_sided_toward}.")
    lines += ["", "Clauses detected by the rules engine (most serious first):"]
    for clause in analysis.clauses:
        lines.append(
            f"- [{clause.severity}] {clause.title} ({clause.category}): "
            f'"{clause.excerpt}" -> {clause.explanation}'
        )
    if not analysis.clauses:
        lines.append("- none of the tracked risk categories were found")
    lines += ["", "Obligation sentences extracted from the document:"]
    lines += [f"- {o}" for o in analysis.obligations] or ["- none found"]
    lines += [
        "",
        f"Write executive_summary, explanations and questions in {request.language}.",
        "risk_flags must include every detected clause above, using its category value. "
        "Then add any OTHER potential liabilities, penalties, deadlines, undertakings or adverse "
        "consequences for the user that are evident in the document text but not covered by the "
        "rules engine - use category `other` for those and quote the relevant wording. "
        "If the rules engine found nothing (e.g. a court filing, notice or letter), the document "
        "text is your primary source: list up to 5 such risks.",
        "Return exactly 3 lawyer_questions.",
        "",
        "<document>",
        request.document_text,
        "</document>",
    ]
    return "\n".join(lines)


def demo_response(analysis: ClauseAnalysis, request: AnalyzeRequest) -> AnalyzeResponse:
    """Build all four cards deterministically from the analysis (no model call)."""
    role = request.user_role or "the reader"
    top = analysis.clauses[:3]
    if top:
        headline = ", ".join(c.title.lower() for c in top)
        summary = (
            f"This appears to be a {analysis.document_type.lower()} of about "
            f"{analysis.word_count} words with an overall risk score of "
            f"{analysis.risk_score}/100 ({analysis.risk_level}). "
            f"The most significant clauses for {role} concern {headline}. "
        )
    else:
        summary = (
            f"This appears to be a {analysis.document_type.lower()} of about "
            f"{analysis.word_count} words. None of the tracked contract-risk clause "
            f"categories were detected, giving a rule-based risk score of "
            f"{analysis.risk_score}/100; risks specific to this kind of document may still "
            f"exist and should be reviewed with an attorney. "
        )
    if analysis.one_sided_toward:
        summary += f"Most obligations fall on {analysis.one_sided_toward}."
    else:
        summary += f"It contains {len(analysis.obligations)} explicit obligation statements."

    flags = [
        RiskFlag(category=c.category, severity=c.severity, title=c.title, explanation=c.explanation)
        for c in analysis.clauses
    ]
    questions = [c.suggested_question for c in analysis.clauses[:3]]
    generic = [
        "Which clauses in this document are negotiable, and which are standard?",
        "What happens - practically and financially - if I need to exit early?",
        "Are there any obligations here that conflict with agreements I already have?",
    ]
    for q in generic:
        if len(questions) == 3:
            break
        questions.append(q)

    return AnalyzeResponse(
        executive_summary=summary.strip(),
        risk_flags=flags,
        user_obligations=analysis.obligations,
        lawyer_questions=questions,
        analysis=analysis,
        mode="demo",
    )


# One pooled async client for the whole process: no per-request handshakes,
# and the outbound call never blocks the event loop.
_client = httpx.AsyncClient(timeout=settings.request_timeout)


async def close_client() -> None:
    await _client.aclose()


async def _call_gemini(prompt: str) -> dict:
    """Single constrained, low-temperature call; returns the parsed JSON body."""
    url = f"{settings.gemini_base_url}/models/{settings.gemini_model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 2048,
            "responseMimeType": "application/json",
            "responseSchema": _RESPONSE_SCHEMA,
            "thinkingConfig": {"thinkingBudget": 0},
        },
    }
    # The key travels in a header, never in the URL, so it can't leak into logs.
    response = await _client.post(url, json=payload, headers={"x-goog-api-key": settings.gemini_api_key})
    response.raise_for_status()
    data = response.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(text)


def _describe_failure(exc: Exception) -> str:
    """Short, secret-free description of why a model call failed."""
    if isinstance(exc, httpx.HTTPStatusError):
        try:
            message = exc.response.json()["error"]["message"]
        except (ValueError, KeyError, TypeError):
            message = exc.response.text[:200]
        return f"HTTP {exc.response.status_code} - {message}"
    return type(exc).__name__


class _LRUCache:
    """Tiny in-memory LRU so repeated analyses of the same text cost nothing."""

    def __init__(self, capacity: int) -> None:
        self._capacity = max(0, capacity)
        self._items: OrderedDict[str, AnalyzeResponse] = OrderedDict()
        self._lock = asyncio.Lock()

    @staticmethod
    def key(request: AnalyzeRequest) -> str:
        raw = f"{request.language}\x1f{request.user_role}\x1f{request.document_text}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    async def get(self, key: str) -> AnalyzeResponse | None:
        async with self._lock:
            value = self._items.get(key)
            if value is not None:
                self._items.move_to_end(key)
            return value

    async def put(self, key: str, value: AnalyzeResponse) -> None:
        if self._capacity == 0:
            return
        async with self._lock:
            self._items[key] = value
            self._items.move_to_end(key)
            while len(self._items) > self._capacity:
                self._items.popitem(last=False)

    def clear(self) -> None:
        self._items.clear()


cache = _LRUCache(settings.cache_size)


async def run_analysis(request: AnalyzeRequest) -> AnalyzeResponse:
    """Full pipeline: deterministic assessment, then grounded generation.

    Live mode is only used when a key is configured *and* the model returns a
    schema-valid answer; every other path yields the deterministic demo response.
    """
    cache_key = cache.key(request)
    cached = await cache.get(cache_key)
    if cached is not None:
        return cached

    analysis = analyze_document(request.document_text)

    if not settings.ai_enabled:
        return demo_response(analysis, request)

    try:
        raw = await _call_gemini(build_prompt(analysis, request))
        parsed = _ModelOutput.model_validate(raw)
        if not analysis.clauses and parsed.risk_flags:
            # The rules engine found no contract clauses (e.g. a court filing),
            # so derive the headline score from the model's flags with the same
            # severity weights - otherwise the UI would show 0/100 beside HIGH risks.
            score, level = score_risk(parsed.risk_flags, lopsided=False)  # type: ignore[arg-type]
            analysis = analysis.model_copy(update={"risk_score": score, "risk_level": level})
        result = AnalyzeResponse(
            executive_summary=parsed.executive_summary.strip(),
            risk_flags=parsed.risk_flags,
            user_obligations=parsed.user_obligations or analysis.obligations,
            lawyer_questions=parsed.lawyer_questions[:3],
            analysis=analysis,
            mode="live",
        )
    except (httpx.HTTPError, ValidationError, KeyError, IndexError, ValueError) as exc:
        # Never fail the request because the model misbehaved. Log enough to
        # diagnose (exception class, HTTP status, the API's own error message)
        # but never the document text or key material.
        logger.warning("Gemini call failed: %s; using demo response", _describe_failure(exc))
        result = demo_response(analysis, request)

    if result.mode == "live":
        # Only successful model answers are cached; a transient outage should
        # not pin a demo answer to this document.
        await cache.put(cache_key, result)
    return result
