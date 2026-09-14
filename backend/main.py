"""GenAI Legal Assistant - FastAPI backend.

Stateless service exposing POST /api/analyze-document, which sends contract
text to Claude Opus 5 and returns a strictly-typed JSON analysis.
"""

import json
import logging
import os
from typing import List

import anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

logger = logging.getLogger("legal-assistant")
logging.basicConfig(level=logging.INFO)

MODEL = "claude-opus-5"
MAX_DOCUMENT_CHARS = 200_000

SYSTEM_PROMPT = (
    "You are a legal parsing engine. You do not provide legal advice. "
    "Analyze the provided text and return ONLY a valid JSON object with these "
    "exact keys: `executive_summary` (3 sentences max), `risk_flags` (array of "
    "potential liabilities), `user_obligations` (array of mandatory actions), "
    "and `lawyer_questions` (array of 3 clarifying questions to ask an attorney)."
)

# JSON schema enforced server-side by the API (output_config.format) so the
# model cannot return anything other than this shape.
ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "executive_summary": {"type": "string"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "user_obligations": {"type": "array", "items": {"type": "string"}},
        "lawyer_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "executive_summary",
        "risk_flags",
        "user_obligations",
        "lawyer_questions",
    ],
    "additionalProperties": False,
}


# --------------------------------------------------------------------------- #
# Pydantic models
# --------------------------------------------------------------------------- #
class AnalyzeRequest(BaseModel):
    document_text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_DOCUMENT_CHARS,
        description="Raw legal/contract text to analyze.",
    )


class AnalyzeResponse(BaseModel):
    executive_summary: str
    risk_flags: List[str]
    user_obligations: List[str]
    lawyer_questions: List[str]


# --------------------------------------------------------------------------- #
# App setup
# --------------------------------------------------------------------------- #
app = FastAPI(
    title="GenAI Legal Assistant API",
    version="1.0.0",
    description="Parses legal text into a structured summary using Claude Opus 5.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=False,
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["Content-Type"],
)

# The SDK reads ANTHROPIC_API_KEY from the environment; fail fast if missing.
if not os.getenv("ANTHROPIC_API_KEY"):
    raise RuntimeError(
        "ANTHROPIC_API_KEY is not set. Create backend/.env with your key "
        "(see backend/.env.example)."
    )

client = anthropic.Anthropic()


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": MODEL}


@app.post("/api/analyze-document", response_model=AnalyzeResponse)
def analyze_document(payload: AnalyzeRequest) -> AnalyzeResponse:
    if not payload.document_text.strip():
        raise HTTPException(status_code=422, detail="document_text is empty.")

    try:
        # Streaming keeps long contracts clear of HTTP timeouts; we only need
        # the final assembled message.
        with client.messages.stream(
            model=MODEL,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            thinking={"type": "adaptive"},
            output_config={
                "format": {"type": "json_schema", "schema": ANALYSIS_SCHEMA}
            },
            messages=[
                {
                    "role": "user",
                    "content": (
                        "Analyze the following legal document:\n\n"
                        f"<document>\n{payload.document_text}\n</document>"
                    ),
                }
            ],
        ) as stream:
            message = stream.get_final_message()
    except anthropic.AuthenticationError:
        logger.exception("Anthropic authentication failed")
        raise HTTPException(status_code=500, detail="Invalid ANTHROPIC_API_KEY.")
    except anthropic.RateLimitError:
        raise HTTPException(
            status_code=429, detail="Rate limited by the model API. Retry shortly."
        )
    except anthropic.APIStatusError as exc:
        logger.exception("Anthropic API error")
        raise HTTPException(
            status_code=502, detail=f"Model API error ({exc.status_code})."
        )
    except anthropic.APIConnectionError:
        logger.exception("Could not reach Anthropic API")
        raise HTTPException(status_code=503, detail="Model API unreachable.")

    if message.stop_reason == "refusal":
        raise HTTPException(
            status_code=422, detail="The model declined to analyze this document."
        )
    if message.stop_reason == "max_tokens":
        raise HTTPException(
            status_code=502, detail="Analysis was truncated; try a shorter document."
        )

    raw_text = "".join(
        block.text for block in message.content if block.type == "text"
    ).strip()

    try:
        data = json.loads(raw_text)
        return AnalyzeResponse.model_validate(data)
    except (json.JSONDecodeError, ValidationError):
        logger.error("Model returned malformed JSON: %r", raw_text[:500])
        raise HTTPException(
            status_code=502, detail="Model returned malformed JSON. Please retry."
        )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
