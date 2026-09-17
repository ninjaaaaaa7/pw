import { describe, expect, it } from "vitest";

import {
  errorMessage,
  isAnalysis,
  riskLevelClasses,
  severityClasses,
  type Analysis,
} from "@/lib/analysis";

const valid: Analysis = {
  executive_summary: "A short summary.",
  risk_flags: [
    { category: "indemnification", severity: "CRITICAL", title: "Indemnity", explanation: "Uncapped." },
  ],
  user_obligations: ["Pay on time."],
  lawyer_questions: ["Q1?", "Q2?", "Q3?"],
  analysis: {
    document_type: "Lease agreement",
    word_count: 120,
    reading_time_minutes: 1,
    risk_score: 42,
    risk_level: "MODERATE",
    parties: ["Landlord", "Tenant"],
    obligations_by_party: { Landlord: 1, Tenant: 3 },
    one_sided_toward: "Tenant",
    clauses: [],
    obligations: ["Pay on time."],
  },
  mode: "demo",
  disclaimer: "Not legal advice.",
};

describe("isAnalysis", () => {
  it("accepts a well-formed payload", () => {
    expect(isAnalysis(valid)).toBe(true);
  });

  it("rejects non-objects", () => {
    expect(isAnalysis(null)).toBe(false);
    expect(isAnalysis("text")).toBe(false);
    expect(isAnalysis([])).toBe(false);
  });

  it("rejects missing or mistyped top-level keys", () => {
    const { executive_summary: _dropped, ...withoutSummary } = valid;
    expect(isAnalysis(withoutSummary)).toBe(false);
    expect(isAnalysis({ ...valid, lawyer_questions: "not an array" })).toBe(false);
    expect(isAnalysis({ ...valid, mode: "offline" })).toBe(false);
  });

  it("rejects a risk flag with an unknown severity", () => {
    const bad = { ...valid, risk_flags: [{ ...valid.risk_flags[0], severity: "EXTREME" }] };
    expect(isAnalysis(bad)).toBe(false);
  });

  it("rejects a malformed nested analysis", () => {
    expect(isAnalysis({ ...valid, analysis: { risk_score: "high" } })).toBe(false);
  });
});

describe("errorMessage", () => {
  it("uses a string detail from FastAPI", () => {
    expect(errorMessage({ detail: "Too many requests." }, 429)).toBe("Too many requests.");
  });

  it("uses the first pydantic validation message", () => {
    const body = { detail: [{ loc: ["body", "document_text"], msg: "document_text must not be blank" }] };
    expect(errorMessage(body, 422)).toBe("document_text must not be blank");
  });

  it("falls back to the status code", () => {
    expect(errorMessage(undefined, 502)).toBe("Request failed with HTTP 502.");
    expect(errorMessage({ detail: [] }, 500)).toBe("Request failed with HTTP 500.");
  });
});

describe("style helpers", () => {
  it("returns a distinct class set for every severity", () => {
    const classes = (["LOW", "MEDIUM", "HIGH", "CRITICAL"] as const).map(severityClasses);
    expect(new Set(classes).size).toBe(4);
  });

  it("maps every risk level to a colour", () => {
    for (const level of ["LOW", "MODERATE", "HIGH", "CRITICAL"] as const) {
      expect(riskLevelClasses(level)).toMatch(/^text-/);
    }
  });
});
