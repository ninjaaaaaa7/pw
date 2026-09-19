"""ClauseWise API - FastAPI application.

Stateless JSON API plus (optionally) the statically exported Next.js UI.
Security posture: strict CORS, security headers on every response, a
per-client rate limit on the expensive endpoint, bounded input sizes, and no
secrets or document text in logs.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict, deque
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import ai_assistant
from .clause_engine import analyze_document
from .config import settings
from .models import AnalyzeRequest, AnalyzeResponse, ClauseAnalysis, HealthResponse
from .sample_data import SAMPLE_DOCUMENT, SAMPLE_USER_ROLE

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class RateLimiter:
    """Sliding-window limiter keyed by client IP. In-memory: fine for one replica."""

    SWEEP_EVERY = 256  # calls between evictions of idle clients

    def __init__(self, limit: int, window_seconds: float = 60.0) -> None:
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._calls = 0

    def allow(self, key: str, now: float | None = None) -> bool:
        now = time.monotonic() if now is None else now
        self._calls += 1
        if self._calls % self.SWEEP_EVERY == 0:
            self._sweep(now)
        hits = self._hits[key]
        while hits and now - hits[0] > self.window:
            hits.popleft()
        if len(hits) >= self.limit:
            return False
        hits.append(now)
        return True

    def _sweep(self, now: float) -> None:
        """Drop clients with no hits inside the window so memory stays bounded."""
        stale = [k for k, h in self._hits.items() if not h or now - h[-1] > self.window]
        for key in stale:
            del self._hits[key]

    def reset(self) -> None:
        self._hits.clear()


rate_limiter = RateLimiter(settings.rate_limit_per_minute)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logger.info("ClauseWise starting (ai_enabled=%s)", settings.ai_enabled)
    yield
    await ai_assistant.close_client()


app = FastAPI(
    title="ClauseWise API",
    version="1.0.0",
    description="Explainable legal-document analysis: deterministic clause engine + grounded GenAI.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    response: Response = await call_next(request)
    for header, value in SECURITY_HEADERS.items():
        response.headers.setdefault(header, value)
    if request.url.path.startswith("/api/"):
        # Analyses contain user documents: never let a shared cache keep them.
        response.headers["Cache-Control"] = "no-store"
    return response


def _client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "anonymous"


# --------------------------------------------------------------------------- #
# API routes
# --------------------------------------------------------------------------- #
@app.get("/api/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    return HealthResponse(status="ok", ai_enabled=settings.ai_enabled, model=settings.gemini_model)


@app.get("/api/sample", tags=["meta"])
async def sample() -> dict[str, str]:
    """A realistic contract so reviewers can try the app without pasting anything."""
    return {"document_text": SAMPLE_DOCUMENT, "user_role": SAMPLE_USER_ROLE}


@app.post("/api/assess", response_model=ClauseAnalysis, tags=["analysis"])
async def assess(payload: AnalyzeRequest) -> ClauseAnalysis:
    """Deterministic assessment only - no model call, instant and fully explainable."""
    return await asyncio.to_thread(analyze_document, payload.document_text)


@app.post("/api/analyze-document", response_model=AnalyzeResponse, tags=["analysis"])
async def analyze(payload: AnalyzeRequest, request: Request) -> AnalyzeResponse:
    """Full pipeline: assessment plus grounded generative explanation."""
    if not rate_limiter.allow(_client_key(request)):
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait a minute and try again.",
            headers={"Retry-After": "60"},
        )
    return await ai_assistant.run_analysis(payload)


# --------------------------------------------------------------------------- #
# Static UI (present in the Docker image; absent during API-only development)
# --------------------------------------------------------------------------- #
_static_root = Path(settings.static_dir)
if (_static_root / "index.html").is_file():
    app.mount("/_next", StaticFiles(directory=_static_root / "_next"), name="next-assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        candidate = (_static_root / path).resolve()
        # Never serve anything outside the export directory.
        if candidate.is_file() and _static_root.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(_static_root / "index.html")
