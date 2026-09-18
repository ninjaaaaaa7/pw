---
title: ClauseWise
emoji: ⚖️
colorFrom: indigo
colorTo: blue
sdk: docker
app_port: 7860
pinned: false
license: mit
---

# ClauseWise — explainable GenAI legal document assistant

**Paste a contract, lease, NDA or terms of service. ClauseWise finds the risky clauses with a
transparent rules engine, then uses generative AI to explain them from *your* side of the
table — in your language.**

[![CI](https://github.com/ninjaaaaaa7/pw/actions/workflows/ci.yml/badge.svg)](https://github.com/ninjaaaaaa7/pw/actions/workflows/ci.yml)

> **🔗 Live demo:** _add your Render URL here after deploying (see §6)_

---

## 1. Chosen vertical

**Vertical:** Legal & consumer protection — contract intelligence
**Persona:** Individuals and small-business owners who must sign legal documents without a
lawyer on hand: tenants, freelancers, employees, customers accepting terms of service.
**Problem:** Legal text is long, one-sided and full of clauses whose consequences aren't obvious
until it's too late (auto-renewals, uncapped indemnities, IP assignment, arbitration…).

ClauseWise turns a wall of legalese into four things a person can act on:

| Card | What it answers |
|------|-----------------|
| **Executive Summary** | What is this document and how risky is it for *me*? |
| **Critical Risk Flags** | Which clauses could cost me money or rights, and why? |
| **User Obligations** | What am I actually committing to do? |
| **Questions for a Lawyer** | What should I ask before I sign? |

It is a reading aid, not legal advice — the UI, the API and the model prompt all say so.

## 2. Approach and logic

The system is built in **two deliberately separated layers**:

### a) Deterministic clause engine — the "logic" (`backend/app/clause_engine.py`)

Rules-based intelligence with **no AI dependency**. For every document it:

1. **Guesses the document type** (lease, employment, NDA, services, ToS, loan, sale) from keyword density.
2. **Detects 17 risk categories** with weighted regex rules matched sentence-by-sentence —
   indemnification, personal guarantee, uncapped liability, auto-renewal, non-compete,
   arbitration / class-action waiver, unilateral changes, liquidated damages, IP assignment,
   termination for convenience, late fees, confidentiality, governing law, "as is" disclaimers,
   exclusivity, assignment restrictions, data sharing. Each hit carries a **severity**, a
   plain-English **explanation**, the **quoted excerpt** it matched, and a **suggested question**.
3. **Extracts obligations** — sentences that impose a positive duty (*shall*, *must*, *agrees to*…),
   skipping prohibitions and duplicates.
4. **Measures one-sidedness** — pulls the defined parties (`("Tenant")`, `(the "Company")`),
   counts which party carries the obligations, and flags a lopsided document.
5. **Scores risk 0–100** from severity weights plus a lopsidedness penalty, banded into
   `LOW / MODERATE / HIGH / CRITICAL`.

Every output is traceable to a rule and an excerpt, so it is auditable and fully unit-tested.

### b) Generative-AI layer — the "assistant" (`backend/app/ai_assistant.py`)

Builds a prompt **grounded in the engine's assessment** — document type, score, named parties,
every detected clause with its excerpt, every obligation — plus the **user's role** and
**preferred language**, and sends it to **Google Gemini** with a **constrained JSON response
schema**. The model returns exactly the four cards in one deterministic, low-temperature pass;
the result is validated with Pydantic before it reaches the client.

**Why this split matters:** the decision logic is deterministic and tested; the AI is a
natural-language layer *on top of* verified facts — not the source of truth. Changing the user
role from *tenant* to *landlord* changes the perspective of the summary and the questions while
the underlying evidence stays identical. That is the "logical decision making based on user
context" the challenge asks for.

**Graceful demo mode:** without `GEMINI_API_KEY` — or if the model is slow, unreachable or
returns something that fails schema validation — the service builds all four cards from the
deterministic analysis instead. The app **always answers**, which makes it usable offline, in
CI, and for automated grading.

## 3. How the solution works

```
Browser (Next.js static export)
   │  POST /api/analyze-document {document_text, user_role, language}
   ▼
FastAPI  ──►  clause_engine.analyze_document()   deterministic assessment
         └─►  ai_assistant.run_analysis()        grounded Gemini call (or demo fallback)
   │
   ▼
{executive_summary, risk_flags[], user_obligations[], lawyer_questions[], analysis{…}, mode}
```

### API

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Status, whether live AI is enabled, model name |
| GET | `/api/sample` | A realistic sample contract + role so reviewers can try it in one click |
| POST | `/api/assess` | Deterministic assessment only — instant, no model call |
| POST | `/api/analyze-document` | Full pipeline: assessment + grounded generative explanation |
| GET | `/docs` | Interactive OpenAPI documentation |

### Repository layout

```
backend/
  app/
    main.py            FastAPI app, CORS, security headers, rate limit, static serving
    clause_engine.py   deterministic rules engine (no AI)
    ai_assistant.py    grounded Gemini call, JSON schema, LRU cache, demo fallback
    models.py          Pydantic request/response models
    config.py          environment-driven settings
    sample_data.py     sample contract
  tests/               pytest suites: engine, AI layer, API
frontend/
  app/page.tsx         dual-pane UI (input | four result cards + evidence)
  lib/analysis.ts      types, runtime response guard, helpers (unit-tested)
  __tests__/           vitest suite
Dockerfile             multi-stage image: build UI, serve UI + API from one container
.github/workflows/     CI: ruff, pytest, tsc, vitest, next build, docker build
```

## 4. Assumptions

- **Input is plain text.** Users paste text; PDF/DOCX parsing is out of scope for this build.
- **English legal drafting conventions.** The rules target English-language contracts (US/UK/IN
  drafting style). Output can be in any language, but detection runs on the English source.
- **Documents ≤ 60 000 characters** (~15 000 words) — covers the vast majority of consumer and
  SMB contracts. The limit is configurable via `MAX_DOCUMENT_CHARS`.
- **Rules are heuristics.** They are tuned for high recall on common consumer-facing clauses;
  a matched sentence is always shown as evidence so the user can judge it.
- **Single-replica deployment.** The rate limiter and response cache are in-process; a
  multi-replica deployment would move them to Redis.
- **No persistence by design.** Documents are processed in memory and never written to disk or
  logs.

## 5. Running locally

### Backend (FastAPI, port 8000)

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   |   macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # optional: add GEMINI_API_KEY for live AI
uvicorn app.main:app --reload --port 8000
```

### Frontend (Next.js, port 3000)

```bash
cd frontend
npm install
npm run dev
```

Open <http://localhost:3000>, click **Load sample contract**, then **Analyze Document**.

### Single container (what the demo runs)

```bash
docker build -t clausewise .
docker run -p 7860:7860 -e GEMINI_API_KEY=your_key clausewise
```

## 6. Deploying for free (Render)

The repo ships a [`render.yaml`](render.yaml) blueprint, so deployment is a few clicks:

1. Sign in at <https://render.com> with GitHub and click **New → Blueprint**.
2. Pick this repository; Render reads `render.yaml` and proposes the `clausewise` web service
   on the **free** plan.
3. When prompted, set `GEMINI_API_KEY` (stored as a secret). Leave it blank to run in demo mode.
4. Click **Apply**. The first build takes ~3 minutes; the health check is `/api/health`.

Free instances sleep after 15 minutes of inactivity, so the first request after a pause takes
~30-50 seconds to wake. The container honours the host's `PORT` variable, so the same image
also runs on Hugging Face Spaces (Docker SDK, port 7860), Cloud Run, Railway or Fly.

## 7. Testing

| Suite | Command | Covers |
|-------|---------|--------|
| Backend unit + integration (47 tests) | `cd backend && pytest` | every clause rule, scoring bands, obligation extraction, party/lopsidedness logic, prompt grounding, demo fallback on each failure class, cache behaviour, key-in-header, all endpoints, validation, rate limiting, security headers, CORS |
| Frontend unit (10 tests) | `cd frontend && npm test` | runtime response guard, error-message extraction, style helpers |
| Type safety | `cd frontend && npm run typecheck` | strict TypeScript |
| Lint / format | `cd backend && ruff check . && ruff format --check .` | includes the `S` (bandit) security rules |

All of the above plus a Docker build run on every push via GitHub Actions.

## 8. Security

- **Secrets only in the environment**; `.env` is git-ignored, `.env.example` is blank.
- The Gemini key is sent in a **request header, never the URL**, so it cannot leak into logs.
- **No document text or key material is logged** — failures log the exception class only.
- **Strict CORS** (configurable allow-list, no credentials), **security headers** on every response
  (`nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`), and
  `Cache-Control: no-store` on all API responses so shared caches never retain a document.
- **Input bounds** enforced by Pydantic (blank / oversized / over-long fields → 422).
- **Per-client rate limiting** on the expensive endpoint (429 + `Retry-After`).
- **Model output is untrusted**: validated against a schema before use, and the deterministic
  analysis is never overwritten by the model.
- Static serving **refuses paths outside the export directory**.
- Container runs as a **non-root user**; `ruff` runs bandit-style security checks in CI.

## 9. Efficiency

- The deterministic engine runs in milliseconds; only one bounded model call per document.
- **Constrained JSON output** with low temperature and no thinking budget — no wasted tokens,
  no re-prompting.
- **In-memory LRU cache** keyed on (text, role, language) — identical re-analyses are free.
- A **single pooled async HTTP client**; the outbound call never blocks the event loop.
- Static UI (~107 kB first load) served from the same container — no second service.

## 10. Accessibility

- Semantic landmarks (`main`, `header`, `form`, `section`, `article`) with labelled headings.
- Every control has a visible `<label>`; helper text is linked via `aria-describedby`.
- **Skip link**, visible focus rings, and focus moved to the results heading when analysis lands.
- Live regions announce loading and completion to screen readers; errors use `role="alert"`.
- The risk gauge is an ARIA `meter` with a textual value; severity is conveyed by **text badges,
  not colour alone**, and all colour pairs meet WCAG AA contrast.
- Layout is fully responsive; animations respect `prefers-reduced-motion`.
- Language of the explanation is user-selectable (multilingual assistance).

## License

MIT — see [LICENSE](LICENSE).
