"use client";

import { useEffect, useRef, useState, type FormEvent } from "react";

import {
  errorMessage,
  isAnalysis,
  riskLevelClasses,
  severityClasses,
  type Analysis,
  type AnalyzeRequest,
  type Severity,
} from "@/lib/analysis";

// Same-origin in production (FastAPI serves the static export); the dev server
// points at the local API via .env.development.
const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "";

const LANGUAGES = ["English", "Hindi", "Spanish", "French", "German", "Portuguese", "Arabic"];

const ROLE_SUGGESTIONS = ["tenant", "landlord", "employee", "freelancer", "customer", "small business owner"];

export default function Home() {
  const [documentText, setDocumentText] = useState("");
  const [userRole, setUserRole] = useState("");
  const [language, setLanguage] = useState(LANGUAGES[0]);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [loading, setLoading] = useState(false);
  const [loadingSample, setLoadingSample] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const resultsHeading = useRef<HTMLHeadingElement>(null);

  // Move keyboard/screen-reader focus to the results once they arrive.
  useEffect(() => {
    if (analysis) resultsHeading.current?.focus();
  }, [analysis]);

  async function loadSample() {
    setLoadingSample(true);
    setError(null);
    try {
      const res = await fetch(`${API_URL}/api/sample`);
      if (!res.ok) throw new Error(`Could not load the sample (HTTP ${res.status}).`);
      const body = (await res.json()) as Partial<AnalyzeRequest>;
      setDocumentText(body.document_text ?? "");
      setUserRole(body.user_role ?? "");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the sample.");
    } finally {
      setLoadingSample(false);
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!documentText.trim() || loading) return;

    setLoading(true);
    setError(null);
    setAnalysis(null);

    const payload: AnalyzeRequest = {
      document_text: documentText,
      user_role: userRole.trim(),
      language,
    };

    try {
      const res = await fetch(`${API_URL}/api/analyze-document`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      let body: unknown;
      try {
        body = await res.json();
      } catch {
        throw new Error(`Server returned a non-JSON response (HTTP ${res.status}).`);
      }

      if (!res.ok) throw new Error(errorMessage(body, res.status));
      if (!isAnalysis(body)) {
        throw new Error("The analysis response was malformed. Please try again.");
      }
      setAnalysis(body);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <a
        href="#results"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-indigo-700 focus:px-4 focus:py-2 focus:text-white"
      >
        Skip to results
      </a>

      <main className="mx-auto flex min-h-screen max-w-7xl flex-col px-4 py-8 sm:px-6 lg:px-8">
        <header className="mb-8">
          <h1 className="text-3xl font-bold tracking-tight text-slate-900">ClauseWise</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-700">
            Paste a contract, lease, NDA or terms of service. ClauseWise finds risky clauses with a
            transparent rules engine, then uses generative AI to explain them from{" "}
            <em>your</em> side of the table — in your language.
          </p>
          <p className="mt-1 text-xs text-slate-600">
            This is a reading aid, not legal advice. Always consult a licensed attorney.
          </p>
        </header>

        <div className="grid flex-1 gap-6 lg:grid-cols-2">
          {/* Left pane: input */}
          <form
            onSubmit={handleSubmit}
            aria-labelledby="input-heading"
            className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 shadow-sm"
          >
            <div className="mb-3 flex items-center justify-between gap-3">
              <h2 id="input-heading" className="text-base font-semibold text-slate-900">
                Your document
              </h2>
              <button
                type="button"
                onClick={loadSample}
                disabled={loading || loadingSample}
                className="rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold text-slate-800 hover:bg-slate-50 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600 focus-visible:ring-offset-2 disabled:opacity-50"
              >
                {loadingSample ? "Loading…" : "Load sample contract"}
              </button>
            </div>

            <div className="mb-4 grid gap-4 sm:grid-cols-2">
              <div>
                <label htmlFor="role" className="mb-1 block text-sm font-medium text-slate-800">
                  I am the… <span className="font-normal text-slate-600">(optional)</span>
                </label>
                <input
                  id="role"
                  name="role"
                  list="role-suggestions"
                  value={userRole}
                  onChange={(e) => setUserRole(e.target.value)}
                  maxLength={60}
                  placeholder="e.g. tenant, freelancer"
                  aria-describedby="role-help"
                  className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900 placeholder:text-slate-500 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                />
                <datalist id="role-suggestions">
                  {ROLE_SUGGESTIONS.map((r) => (
                    <option key={r} value={r} />
                  ))}
                </datalist>
                <p id="role-help" className="mt-1 text-xs text-slate-600">
                  Tailors the summary and questions to your position in the document.
                </p>
              </div>
              <div>
                <label htmlFor="language" className="mb-1 block text-sm font-medium text-slate-800">
                  Explain in
                </label>
                <select
                  id="language"
                  name="language"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                  className="w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-200"
                >
                  {LANGUAGES.map((l) => (
                    <option key={l} value={l}>
                      {l}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <label htmlFor="document" className="mb-1 block text-sm font-medium text-slate-800">
              Legal document text <span aria-hidden="true">*</span>
            </label>
            <textarea
              id="document"
              name="document"
              required
              value={documentText}
              onChange={(e) => setDocumentText(e.target.value)}
              placeholder="Paste the full text of your contract, lease, terms of service, NDA…"
              disabled={loading}
              aria-describedby="document-help"
              className="min-h-[20rem] flex-1 resize-y rounded-lg border border-slate-300 p-4 font-mono text-sm leading-relaxed text-slate-900 placeholder:text-slate-500 focus:border-indigo-600 focus:outline-none focus:ring-2 focus:ring-indigo-200 disabled:bg-slate-50"
            />
            <div className="mt-4 flex items-center justify-between gap-4">
              <span id="document-help" className="text-xs text-slate-600">
                {documentText.length.toLocaleString()} characters · nothing is stored
              </span>
              <button
                type="submit"
                disabled={loading || !documentText.trim()}
                className="inline-flex items-center gap-2 rounded-lg bg-indigo-700 px-5 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:bg-indigo-800 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600 focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {loading && <Spinner />}
                {loading ? "Analyzing…" : "Analyze Document"}
              </button>
            </div>
          </form>

          {/* Right pane: results */}
          <section id="results" aria-labelledby="results-heading" className="flex flex-col gap-4">
            <h2
              id="results-heading"
              ref={resultsHeading}
              tabIndex={-1}
              className="text-base font-semibold text-slate-900 focus:outline-none"
            >
              Analysis
            </h2>

            <div role="status" aria-live="polite" className="sr-only">
              {loading && "Analyzing your document."}
              {analysis && `Analysis complete. Risk level ${analysis.analysis.risk_level}.`}
            </div>

            {error && (
              <div role="alert" className="rounded-xl border border-red-300 bg-red-50 p-4 text-sm text-red-900">
                <p className="font-semibold">Analysis failed</p>
                <p className="mt-1">{error}</p>
              </div>
            )}

            {loading && <ResultsSkeleton />}

            {!loading && !error && !analysis && (
              <div className="flex min-h-[20rem] flex-1 items-center justify-center rounded-xl border border-dashed border-slate-300 bg-white/60 p-8 text-center text-sm text-slate-600">
                Your analysis will appear here.
              </div>
            )}

            {analysis && <Results analysis={analysis} />}
          </section>
        </div>
      </main>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Results
// --------------------------------------------------------------------------- //

function Results({ analysis }: { analysis: Analysis }) {
  const a = analysis.analysis;
  return (
    <>
      <div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <p className="text-sm text-slate-700">
            <span className="font-semibold text-slate-900">{a.document_type}</span> ·{" "}
            {a.word_count.toLocaleString()} words · ~{a.reading_time_minutes} min read
          </p>
          <p className="text-sm">
            <span className="text-slate-700">Risk score </span>
            <span className={`text-lg font-bold ${riskLevelClasses(a.risk_level)}`}>
              {a.risk_score}
            </span>
            <span className="text-slate-700">/100 · </span>
            <span className={`font-semibold ${riskLevelClasses(a.risk_level)}`}>{a.risk_level}</span>
          </p>
        </div>
        <div
          role="meter"
          aria-label="Overall risk score"
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={a.risk_score}
          aria-valuetext={`${a.risk_score} out of 100, ${a.risk_level}`}
          className="mt-3 h-2 w-full overflow-hidden rounded-full bg-slate-200"
        >
          <div
            className="h-full rounded-full bg-gradient-to-r from-emerald-500 via-amber-500 to-red-600"
            style={{ width: `${a.risk_score}%` }}
          />
        </div>
        {a.clauses.length === 0 && (
          <p className="mt-3 text-sm text-slate-700">
            The score reflects the rule-based contract-clause scan, which matched nothing here
            {a.document_type === "Court petition / application" || a.document_type === "Legal notice"
              ? " — this is not a contract, so the AI-identified risks below are the ones to read."
              : ". Any risks below were identified by the AI directly from the text."}
          </p>
        )}
        {a.one_sided_toward && (
          <p className="mt-3 text-sm text-slate-700">
            Most obligations fall on <strong className="text-slate-900">{a.one_sided_toward}</strong>.
          </p>
        )}
        {analysis.mode === "demo" && (
          <p className="mt-3 rounded-lg bg-slate-100 px-3 py-2 text-xs text-slate-800">
            Demo mode: no AI key is configured on the server, so this explanation was generated by the
            rules engine alone. Add a Gemini key for tailored, natural-language output.
          </p>
        )}
      </div>

      <Card title="Executive Summary" accent="indigo">
        <p className="text-sm leading-relaxed text-slate-800">{analysis.executive_summary}</p>
      </Card>

      <Card title="Critical Risk Flags" accent="red">
        {analysis.risk_flags.length === 0 ? (
          <p className="text-sm italic text-slate-600">No risk flags identified.</p>
        ) : (
          <ul className="space-y-3">
            {analysis.risk_flags.map((flag, i) => (
              <li key={`${flag.category}-${i}`} className="text-sm leading-relaxed text-slate-800">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={flag.severity} />
                  <span className="font-semibold text-slate-900">{flag.title}</span>
                </div>
                <p>{flag.explanation}</p>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="User Obligations" accent="amber">
        <BulletList items={analysis.user_obligations} empty="No explicit obligations found." />
      </Card>

      <Card title="Questions for a Lawyer" accent="emerald">
        <BulletList items={analysis.lawyer_questions} ordered empty="No questions generated." />
      </Card>

      {a.clauses.length > 0 && (
        <details className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
          <summary className="cursor-pointer text-sm font-semibold text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-indigo-600">
            Show the evidence ({a.clauses.length} clauses matched)
          </summary>
          <ul className="mt-3 space-y-3">
            {a.clauses.map((c) => (
              <li key={c.category} className="text-sm text-slate-800">
                <div className="mb-1 flex flex-wrap items-center gap-2">
                  <SeverityBadge severity={c.severity} />
                  <span className="font-semibold text-slate-900">{c.title}</span>
                </div>
                <blockquote className="border-l-2 border-slate-300 pl-3 italic text-slate-700">
                  “{c.excerpt}”
                </blockquote>
              </li>
            ))}
          </ul>
        </details>
      )}

      <p className="text-xs text-slate-600">{analysis.disclaimer}</p>
    </>
  );
}

// --------------------------------------------------------------------------- //
// Presentational helpers
// --------------------------------------------------------------------------- //

type Accent = "indigo" | "red" | "amber" | "emerald";

const accentClasses: Record<Accent, string> = {
  indigo: "border-l-indigo-600",
  red: "border-l-red-600",
  amber: "border-l-amber-600",
  emerald: "border-l-emerald-600",
};

function Card({ title, accent, children }: { title: string; accent: Accent; children: React.ReactNode }) {
  return (
    <article
      aria-label={title}
      className={`rounded-xl border border-slate-200 border-l-4 bg-white p-5 shadow-sm ${accentClasses[accent]}`}
    >
      <h3 className="mb-3 text-base font-semibold text-slate-900">{title}</h3>
      {children}
    </article>
  );
}

function SeverityBadge({ severity }: { severity: Severity }) {
  return (
    <span
      className={`inline-block rounded-full px-2 py-0.5 text-xs font-semibold ring-1 ${severityClasses(severity)}`}
    >
      {severity}
    </span>
  );
}

function BulletList({ items, ordered = false, empty }: { items: string[]; ordered?: boolean; empty: string }) {
  if (items.length === 0) {
    return <p className="text-sm italic text-slate-600">{empty}</p>;
  }
  const List = ordered ? "ol" : "ul";
  return (
    <List
      className={`space-y-2 pl-5 text-sm leading-relaxed text-slate-800 ${ordered ? "list-decimal" : "list-disc"}`}
    >
      {items.map((item, i) => (
        <li key={i}>{item}</li>
      ))}
    </List>
  );
}

function Spinner() {
  return (
    <svg className="h-4 w-4 animate-spin motion-reduce:animate-none" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
    </svg>
  );
}

const SKELETON_TITLES = ["Executive Summary", "Critical Risk Flags", "User Obligations", "Questions for a Lawyer"];

function ResultsSkeleton() {
  return (
    <div aria-hidden="true">
      {SKELETON_TITLES.map((title) => (
        <div
          key={title}
          className="mb-4 animate-pulse rounded-xl border border-slate-200 bg-white p-5 shadow-sm motion-reduce:animate-none"
        >
          <div className="mb-4 h-4 w-40 rounded bg-slate-200" />
          <div className="space-y-2">
            <div className="h-3 w-full rounded bg-slate-100" />
            <div className="h-3 w-11/12 rounded bg-slate-100" />
            <div className="h-3 w-3/4 rounded bg-slate-100" />
          </div>
        </div>
      ))}
    </div>
  );
}
