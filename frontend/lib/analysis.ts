/**
 * Types and pure helpers for the analysis API. Kept free of React so they can
 * be unit-tested in isolation.
 */

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type RiskLevel = "LOW" | "MODERATE" | "HIGH" | "CRITICAL";

export interface RiskFlag {
  category: string;
  severity: Severity;
  title: string;
  explanation: string;
}

export interface DetectedClause {
  category: string;
  title: string;
  severity: Severity;
  explanation: string;
  excerpt: string;
  suggested_question: string;
}

export interface ClauseAnalysis {
  document_type: string;
  word_count: number;
  reading_time_minutes: number;
  risk_score: number;
  risk_level: RiskLevel;
  parties: string[];
  obligations_by_party: Record<string, number>;
  one_sided_toward: string | null;
  clauses: DetectedClause[];
  obligations: string[];
}

export interface Analysis {
  executive_summary: string;
  risk_flags: RiskFlag[];
  user_obligations: string[];
  lawyer_questions: string[];
  analysis: ClauseAnalysis;
  mode: "live" | "demo";
  disclaimer: string;
}

export interface AnalyzeRequest {
  document_text: string;
  user_role: string;
  language: string;
}

export const SEVERITIES: readonly Severity[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

const isStringArray = (x: unknown): x is string[] =>
  Array.isArray(x) && x.every((item) => typeof item === "string");

const isRecord = (x: unknown): x is Record<string, unknown> =>
  typeof x === "object" && x !== null;

function isRiskFlag(x: unknown): x is RiskFlag {
  return (
    isRecord(x) &&
    typeof x.category === "string" &&
    typeof x.title === "string" &&
    typeof x.explanation === "string" &&
    SEVERITIES.includes(x.severity as Severity)
  );
}

/** Runtime guard so a malformed server payload can never crash the UI. */
export function isAnalysis(value: unknown): value is Analysis {
  if (!isRecord(value) || !isRecord(value.analysis)) return false;
  const a = value.analysis;
  return (
    typeof value.executive_summary === "string" &&
    Array.isArray(value.risk_flags) &&
    value.risk_flags.every(isRiskFlag) &&
    isStringArray(value.user_obligations) &&
    isStringArray(value.lawyer_questions) &&
    (value.mode === "live" || value.mode === "demo") &&
    typeof value.disclaimer === "string" &&
    typeof a.risk_score === "number" &&
    typeof a.risk_level === "string" &&
    typeof a.document_type === "string" &&
    Array.isArray(a.clauses) &&
    isStringArray(a.obligations)
  );
}

/** Extract a human-readable message from a FastAPI error body. */
export function errorMessage(body: unknown, status: number): string {
  if (isRecord(body) && "detail" in body) {
    const detail = body.detail;
    if (typeof detail === "string") return detail;
    // Pydantic validation errors arrive as an array of {msg, loc}.
    if (Array.isArray(detail) && detail.length > 0 && isRecord(detail[0])) {
      const first = detail[0];
      if (typeof first.msg === "string") return first.msg;
    }
  }
  return `Request failed with HTTP ${status}.`;
}

/** Tailwind classes for a severity badge; every pair meets WCAG AA contrast. */
export function severityClasses(severity: Severity): string {
  switch (severity) {
    case "CRITICAL":
      return "bg-red-100 text-red-900 ring-red-300";
    case "HIGH":
      return "bg-orange-100 text-orange-900 ring-orange-300";
    case "MEDIUM":
      return "bg-amber-100 text-amber-900 ring-amber-300";
    case "LOW":
    default:
      return "bg-slate-100 text-slate-800 ring-slate-300";
  }
}

export function riskLevelClasses(level: RiskLevel): string {
  switch (level) {
    case "CRITICAL":
      return "text-red-800";
    case "HIGH":
      return "text-orange-800";
    case "MODERATE":
      return "text-amber-800";
    case "LOW":
    default:
      return "text-emerald-800";
  }
}
