"""Pydantic models shared by the API, the clause engine and the AI layer."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from .config import settings

Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
RiskLevel = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
Mode = Literal["live", "demo"]


class AnalyzeRequest(BaseModel):
    """Incoming document plus the user context that shapes the analysis."""

    document_text: str = Field(
        ...,
        min_length=1,
        max_length=settings.max_document_chars,
        description="Raw legal text to analyze (contract, lease, ToS, NDA, ...).",
    )
    user_role: str = Field(
        default="",
        max_length=60,
        description="Who the user is in this document, e.g. 'tenant' or 'freelancer'.",
    )
    language: str = Field(
        default="English",
        max_length=40,
        description="Language for the generated summary and questions.",
    )

    @field_validator("document_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("document_text must not be blank")
        return value

    @field_validator("user_role", "language")
    @classmethod
    def _strip(cls, value: str) -> str:
        return value.strip()


class DetectedClause(BaseModel):
    """One clause the rules engine recognised in the text."""

    category: str
    title: str
    severity: Severity
    explanation: str
    excerpt: str
    suggested_question: str


class ClauseAnalysis(BaseModel):
    """Deterministic, explainable assessment of a document (no AI involved)."""

    document_type: str
    word_count: int
    reading_time_minutes: int
    risk_score: int = Field(ge=0, le=100)
    risk_level: RiskLevel
    parties: list[str]
    obligations_by_party: dict[str, int]
    one_sided_toward: str | None
    clauses: list[DetectedClause]
    obligations: list[str]


class RiskFlag(BaseModel):
    category: str
    severity: Severity
    title: str
    explanation: str


class AnalyzeResponse(BaseModel):
    """The four cards the UI renders, plus the assessment they were grounded in."""

    executive_summary: str
    risk_flags: list[RiskFlag]
    user_obligations: list[str]
    lawyer_questions: list[str]
    analysis: ClauseAnalysis
    mode: Mode
    disclaimer: str = (
        "This is an automated reading aid, not legal advice. "
        "Consult a licensed attorney before acting on any document."
    )


class HealthResponse(BaseModel):
    status: Literal["ok"]
    ai_enabled: bool
    model: str
