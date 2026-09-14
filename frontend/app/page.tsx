"use client";

import { useState, type FormEvent } from "react";

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

interface Analysis {
  executive_summary: string;
  risk_flags: string[];
  user_obligations: string[];
  lawyer_questions: string[];
}

function isAnalysis(value: unknown): value is Analysis {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  const isStringArray = (x: unknown) =>
    Array.isArray(x) && x.every((item) => typeof item === "string");
  return (
    typeof v.executive_summary === "string" &&
    isStringArray(v.risk_flags) &&
    isStringArray(v.user_obligations) &&
    isStringArray(v.lawyer_questions)
  );
}

export default function Home() {
  const [documentText, setDocumentText] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!documentText.trim() || loading) return;

    setLoading(true);
    setError(null);
    setAnalysis(null);

    try {
      const res = await fetch(`${API_URL}/api/analyze-document`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_text: documentText }),
      });

      let body: unknown;
      try {
        body = await res.json();
      } catch {
        throw new Error(
          `Server returned a non-JSON response (HTTP ${res.status}).`,
        );
      }

      if (!res.ok) {
        const detail =
          typeof body === "object" && body !== null && "detail" in body
            ? String((body as { detail: unknown }).detail)
            : `Request failed with HTTP ${res.status}.`;
        throw new Error(detail);
      }

      if (!isAnalysis(body)) {
        throw new Error(
          "The analysis response was malformed. Please try again.",
        );
      }

      setAnalysis(body);
    } catch (err) {
      setError(
        err instanceof Error
          ? err.message
          : "Something went wrong. Please try again.",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="mx-auto flex min-h-screen max-w-7xl flex-col px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          GenAI Legal Assistant
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-slate-600">
          Paste a contract or legal document to get a plain-language summary,
          risk flags, your obligations, and questions to bring to an attorney.
          This tool does not provide legal advice.
        </p>
      </header>

      <div className="grid flex-1 gap-6 lg:grid-cols-2">
        {/* Left pane: input */}
        <form
          onSubmit={handleSubmit}
          className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <label
            htmlFor="document"
            className="mb-2 text-sm font-semibold text-slate-800"
          >
            Legal document text
          </label>
          <textarea
            id="document"
            name="document"
            value={documentText}
            onChange={(e) => setDocumentText(e.target.value)}
            placeholder="Paste the full text of your contract, lease, terms of service, NDA, etc."
            disabled={loading}
            className="min-h-[24rem] flex-1 resize-y rounded-lg border border-slate-300 p-4 font-mono text-sm leading-relaxed text-slate-900 placeholder:text-slate-400 focus:border-indigo-500 focus:outline-none focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-50"
          />
          <div className="mt-4 flex items-center justify-between gap-4">
            <span className="text-xs text-slate-500">
              {documentText.length.toLocaleString()} characters
            </span>
            <button
              type="submit"
              disabled={loading || !documentText.trim()}
              className="inline-flex items-center gap-2 rounded-lg bg-indigo-600 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading && <Spinner />}
              {loading ? "Analyzing…" : "Analyze Document"}
            </button>
          </div>
        </form>

        {/* Right pane: results */}
        <section aria-live="polite" className="flex flex-col gap-4">
          {error && (
            <div
              role="alert"
              className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800"
            >
              <p className="font-semibold">Analysis failed</p>
              <p className="mt-1">{error}</p>
            </div>
          )}

          {loading && <ResultsSkeleton />}

          {!loading && !error && !analysis && (
            <div className="flex h-full min-h-[24rem] items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white/60 p-8 text-center text-sm text-slate-500">
              Your analysis will appear here.
            </div>
          )}

          {analysis && (
            <>
              <Card title="Executive Summary" accent="indigo">
                <p className="text-sm leading-relaxed text-slate-700">
                  {analysis.executive_summary}
                </p>
              </Card>
              <Card title="Critical Risk Flags" accent="red">
                <BulletList
                  items={analysis.risk_flags}
                  empty="No risk flags identified."
                />
              </Card>
              <Card title="User Obligations" accent="amber">
                <BulletList
                  items={analysis.user_obligations}
                  empty="No obligations identified."
                />
              </Card>
              <Card title="Questions for a Lawyer" accent="emerald">
                <BulletList
                  items={analysis.lawyer_questions}
                  ordered
                  empty="No questions generated."
                />
              </Card>
            </>
          )}
        </section>
      </div>
    </main>
  );
}

// --------------------------------------------------------------------------- //
// Presentational helpers
// --------------------------------------------------------------------------- //

type Accent = "indigo" | "red" | "amber" | "emerald";

const accentClasses: Record<Accent, string> = {
  indigo: "border-l-indigo-500",
  red: "border-l-red-500",
  amber: "border-l-amber-500",
  emerald: "border-l-emerald-500",
};

function Card({
  title,
  accent,
  children,
}: {
  title: string;
  accent: Accent;
  children: React.ReactNode;
}) {
  return (
    <article
      className={`rounded-xl border border-slate-200 border-l-4 bg-white p-5 shadow-sm ${accentClasses[accent]}`}
    >
      <h2 className="mb-3 text-base font-semibold text-slate-900">{title}</h2>
      {children}
    </article>
  );
}

function BulletList({
  items,
  ordered = false,
  empty,
}: {
  items: string[];
  ordered?: boolean;
  empty: string;
}) {
  if (items.length === 0) {
    return <p className="text-sm italic text-slate-500">{empty}</p>;
  }
  const List = ordered ? "ol" : "ul";
  return (
    <List
      className={`space-y-2 pl-5 text-sm leading-relaxed text-slate-700 ${
        ordered ? "list-decimal" : "list-disc"
      }`}
    >
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </List>
  );
}

function Spinner() {
  return (
    <svg
      className="h-4 w-4 animate-spin"
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
    >
      <circle
        className="opacity-25"
        cx="12"
        cy="12"
        r="10"
        stroke="currentColor"
        strokeWidth="4"
      />
      <path
        className="opacity-75"
        fill="currentColor"
        d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z"
      />
    </svg>
  );
}

const SKELETON_TITLES = [
  "Executive Summary",
  "Critical Risk Flags",
  "User Obligations",
  "Questions for a Lawyer",
];

function ResultsSkeleton() {
  return (
    <>
      {SKELETON_TITLES.map((title) => (
        <div
          key={title}
          className="animate-pulse rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
        >
          <div className="mb-4 h-4 w-40 rounded bg-slate-200" />
          <div className="space-y-2">
            <div className="h-3 w-full rounded bg-slate-100" />
            <div className="h-3 w-11/12 rounded bg-slate-100" />
            <div className="h-3 w-3/4 rounded bg-slate-100" />
          </div>
        </div>
      ))}
    </>
  );
}
