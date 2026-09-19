"""Deterministic clause engine.

Rules-based intelligence with **no AI dependency**. Given raw legal text it:

1. guesses the document type,
2. recognises risky clause categories with weighted regex rules,
3. extracts the mandatory obligations ("shall", "must", "agrees to", ...),
4. measures which named party carries most of those obligations,
5. rolls everything into an explainable 0-100 risk score.

Every output is traceable to a rule and a quoted excerpt, so the result is
auditable and unit-testable. The generative layer in :mod:`app.ai_assistant`
only *explains* these facts - it never invents them.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

from .models import ClauseAnalysis, DetectedClause, RiskLevel, Severity

WORDS_PER_MINUTE = 200
MAX_OBLIGATIONS = 12
MAX_EXCERPT_CHARS = 260

# Weight each severity contributes to the overall score.
SEVERITY_WEIGHT: dict[Severity, int] = {"LOW": 4, "MEDIUM": 9, "HIGH": 16, "CRITICAL": 25}

# Rank used for sorting clauses, most serious first.
SEVERITY_RANK: dict[Severity, int] = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}


@dataclass(frozen=True)
class ClauseRule:
    category: str
    title: str
    severity: Severity
    patterns: tuple[str, ...]
    explanation: str
    question: str


# Patterns are matched case-insensitively against individual sentences.
CLAUSE_RULES: tuple[ClauseRule, ...] = (
    ClauseRule(
        "indemnification",
        "Indemnification / hold harmless",
        "CRITICAL",
        (r"\bindemnif(y|ies|ied|ication)\b", r"\bhold\s+harmless\b"),
        "You may have to cover the other party's losses, legal fees or third-party "
        "claims - potentially far beyond the value of the contract.",
        "What is the scope and cap of the indemnity, and does it cover the other party's own negligence?",
    ),
    ClauseRule(
        "personal_guarantee",
        "Personal guarantee",
        "CRITICAL",
        (r"\bpersonal(ly)?\s+guarant(ee|y|or)\b", r"\bjointly\s+and\s+severally\b"),
        "Your personal assets - not just the business - could be on the line.",
        "Can the personal guarantee be removed, capped, or limited in time?",
    ),
    ClauseRule(
        "unlimited_liability",
        "Uncapped or one-sided liability",
        "HIGH",
        (
            r"\bunlimited\s+liability\b",
            r"\bliab(le|ility)\s+for\s+(all|any\s+and\s+all)\b",
            r"\bconsequential\s+damages\b",
        ),
        "Liability may not be capped, or the cap may only protect the other side.",
        "Is liability capped for both parties, and what is excluded from the cap?",
    ),
    ClauseRule(
        "auto_renewal",
        "Automatic renewal",
        "HIGH",
        (
            r"\bauto(matic(ally)?|-)?\s*renew(s|al|ed)?\b",
            r"\brenew(s|ed)?\s+automatically\b",
            r"\bevergreen\b",
        ),
        "The agreement renews on its own unless you cancel inside a notice window; "
        "missing it can lock you in for another full term.",
        "What is the exact cancellation notice window, and how must notice be delivered?",
    ),
    ClauseRule(
        "non_compete",
        "Non-compete / non-solicit",
        "HIGH",
        (
            r"\bnon-?compet(e|ition)\b",
            r"\bnon-?solicit(ation)?\b",
            r"\bshall\s+not\s+(compete|solicit)\b",
            r"\bshall\s+not\s+(provide|perform|render)\s+(similar|competing)\b",
        ),
        "Restricts who you can work for or with after the agreement ends.",
        "How long and how broad is the restriction, and is it enforceable in my jurisdiction?",
    ),
    ClauseRule(
        "arbitration",
        "Mandatory arbitration / class-action waiver",
        "HIGH",
        (r"\bbinding\s+arbitration\b", r"\barbitrat(e|ion|or)\b", r"\bclass[-\s]action\s+waiver\b"),
        "You may be giving up the right to sue in court or join a class action.",
        "Who pays arbitration fees, where is it held, and can I opt out?",
    ),
    ClauseRule(
        "unilateral_change",
        "Unilateral changes to terms",
        "HIGH",
        (
            r"\b(reserves?|reserved)\s+the\s+right\s+to\s+(modify|change|amend|alter)\b",
            r"\bmay\s+(modify|change|amend|alter)\s+(these|this|the)\s+(terms|agreement)\b",
            r"\bat\s+(its|our)\s+sole\s+discretion\b",
        ),
        "The other party can change the deal - or exercise key rights - without your consent.",
        "Will I be notified of changes and can I terminate without penalty if I disagree?",
    ),
    ClauseRule(
        "liquidated_damages",
        "Liquidated damages / penalties",
        "HIGH",
        (r"\bliquidated\s+damages\b", r"\bpenalt(y|ies)\b", r"\bearly\s+termination\s+fee\b"),
        "A fixed sum becomes payable on breach or early exit, regardless of actual loss.",
        "Is the amount a genuine pre-estimate of loss, or could it be challenged as a penalty?",
    ),
    ClauseRule(
        "ip_assignment",
        "Intellectual property assignment",
        "HIGH",
        (
            r"\b(assigns?|assignment\s+of|transfers?)\s+(all\s+)?(right,?\s+title|intellectual\s+property)\b",
            r"\bwork\s+(made\s+)?for\s+hire\b",
            r"\bhereby\s+assigns?\b",
        ),
        "Ownership of what you create - possibly including pre-existing work - moves to the other party.",
        "Does the assignment cover my pre-existing IP or work done outside this engagement?",
    ),
    ClauseRule(
        "termination_convenience",
        "Termination for convenience",
        "MEDIUM",
        (
            r"\bterminat(e|ion)\s+(this\s+agreement\s+)?(at\s+any\s+time|for\s+(any|no)\s+reason|for\s+convenience|without\s+cause)\b",
            r"\bwithout\s+(prior\s+)?notice\b",
        ),
        "One side may be able to walk away at will, possibly without notice.",
        "Is the termination right mutual, and what notice period and payouts apply?",
    ),
    ClauseRule(
        "late_fees",
        "Late fees and interest",
        "MEDIUM",
        (r"\blate\s+(fee|charge|payment\s+penalty)\b", r"\binterest\s+(at|of)\s+\d", r"\bper\s+annum\b"),
        "Missed payments accrue extra charges that can compound quickly.",
        "What is the effective annual rate, and is there a grace period?",
    ),
    ClauseRule(
        "confidentiality",
        "Confidentiality",
        "MEDIUM",
        (r"\bconfidential(ity)?\b", r"\bnon-?disclosure\b", r"\btrade\s+secrets?\b"),
        "You have ongoing duties not to disclose information - sometimes indefinitely.",
        "How long do confidentiality duties last, and what are the carve-outs?",
    ),
    ClauseRule(
        "governing_law",
        "Governing law / venue",
        "MEDIUM",
        (r"\bgoverned\s+by\s+the\s+laws?\s+of\b", r"\bexclusive\s+jurisdiction\b", r"\bvenue\b"),
        "Disputes may have to be resolved under another state's or country's law, far from you.",
        "Is the chosen jurisdiction practical and affordable for me if a dispute arises?",
    ),
    ClauseRule(
        "as_is",
        "'As is' / warranty disclaimer",
        "MEDIUM",
        (r"\bas\s+is\b", r"\bdisclaims?\s+(all\s+)?warrant(y|ies)\b", r"\bwithout\s+warranty\b"),
        "The other party promises nothing about quality or fitness for purpose.",
        "What recourse do I have if the product or service fails?",
    ),
    ClauseRule(
        "exclusivity",
        "Exclusivity",
        "MEDIUM",
        (r"\bexclusiv(e|ity)\b", r"\bsole\s+(provider|supplier|source)\b"),
        "You may be barred from working with alternatives for the term.",
        "How narrowly is the exclusive field defined, and can it be released early?",
    ),
    ClauseRule(
        "assignment",
        "Assignment / change of control",
        "LOW",
        (r"\bmay\s+not\s+assign\b", r"\bshall\s+not\s+assign\b", r"\bchange\s+of\s+control\b"),
        "You may be unable to transfer the contract if your situation changes.",
        "Can I assign the agreement if my business is sold or restructured?",
    ),
    ClauseRule(
        "data_privacy",
        "Data collection and sharing",
        "LOW",
        (
            r"\bpersonal\s+(data|information)\b",
            r"\bshare\s+(your\s+)?(data|information)\s+with\b",
            r"\bthird[-\s]part(y|ies)\b",
        ),
        "Your data may be collected, retained or shared with third parties.",
        "What data is collected, how long is it kept, and who is it shared with?",
    ),
)

DOCUMENT_TYPE_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Lease agreement", (r"\blease\b", r"\blandlord\b", r"\btenant\b", r"\bpremises\b")),
    ("Employment agreement", (r"\bemploy(ee|er|ment)\b", r"\bsalary\b", r"\bat-will\b")),
    (
        "Non-disclosure agreement",
        (r"\bnon-?disclosure\b", r"\breceiving\s+party\b", r"\bdisclosing\s+party\b"),
    ),
    (
        "Services / freelance agreement",
        (r"\bcontractor\b", r"\bservices\b", r"\bdeliverables\b", r"\bstatement\s+of\s+work\b"),
    ),
    (
        "Terms of service",
        (r"\bterms\s+of\s+(service|use)\b", r"\byour\s+account\b", r"\bwebsite\b", r"\bplatform\b"),
    ),
    ("Loan agreement", (r"\bloan\b", r"\bborrower\b", r"\blender\b", r"\bprincipal\b")),
    ("Purchase / sales agreement", (r"\bpurchase\b", r"\bbuyer\b", r"\bseller\b")),
    (
        "Court petition / application",
        (r"\bpetition(er)?\b", r"\bapplicant\b", r"\bhon'?ble\b", r"\bprayed\b", r"\bbail\b", r"\bFIR\b"),
    ),
    ("Legal notice", (r"\blegal\s+notice\b", r"\bcease\s+and\s+desist\b", r"\bdemand\s+notice\b")),
)

OBLIGATION_PATTERN = re.compile(
    r"\b(shall|must|agrees?\s+to|is\s+(required|obligated)\s+to|will\s+be\s+responsible\s+for|"
    r"is\s+responsible\s+for|undertakes\s+to)\b",
    re.IGNORECASE,
)
NEGATED_OBLIGATION = re.compile(r"\b(shall|must)\s+not\b", re.IGNORECASE)
# Defined terms such as ("Tenant") or (the "Company").
PARTY_DEFINITION = re.compile(r"\((?:the\s+)?[\"“']([A-Z][A-Za-z ]{1,30})[\"”']\)")
SENTENCE_SPLIT = re.compile(r"(?<=[.;:!?])\s+(?=[A-Z(\"“])|\n{2,}")
WHITESPACE = re.compile(r"\s+")


def _sentences(text: str) -> list[str]:
    """Split text into trimmed sentences, dropping fragments too short to matter."""
    parts = (WHITESPACE.sub(" ", s).strip() for s in SENTENCE_SPLIT.split(text))
    return [s for s in parts if len(s) >= 20]


def _excerpt(sentence: str) -> str:
    if len(sentence) <= MAX_EXCERPT_CHARS:
        return sentence
    return sentence[: MAX_EXCERPT_CHARS - 1].rstrip() + "…"


def guess_document_type(text: str) -> str:
    """Return the best-matching document type label, or a generic fallback."""
    lowered = text.lower()
    best_label, best_hits = "Legal agreement", 0
    for label, patterns in DOCUMENT_TYPE_HINTS:
        hits = sum(len(re.findall(p, lowered)) for p in patterns)
        if hits > best_hits:
            best_label, best_hits = label, hits
    return best_label


def detect_clauses(sentences: list[str]) -> list[DetectedClause]:
    """Apply every rule to every sentence; keep the first hit per category."""
    found: dict[str, DetectedClause] = {}
    for rule in CLAUSE_RULES:
        regexes = [re.compile(p, re.IGNORECASE) for p in rule.patterns]
        for sentence in sentences:
            if any(r.search(sentence) for r in regexes):
                found[rule.category] = DetectedClause(
                    category=rule.category,
                    title=rule.title,
                    severity=rule.severity,
                    explanation=rule.explanation,
                    excerpt=_excerpt(sentence),
                    suggested_question=rule.question,
                )
                break
    return sorted(found.values(), key=lambda c: (SEVERITY_RANK[c.severity], c.title))


def extract_parties(text: str) -> list[str]:
    """Pull defined party names like ("Tenant") in order of first appearance."""
    seen: list[str] = []
    for match in PARTY_DEFINITION.finditer(text):
        name = match.group(1).strip()
        if name not in seen:
            seen.append(name)
        if len(seen) == 4:
            break
    return seen


def extract_obligations(sentences: list[str]) -> list[str]:
    """Return sentences that impose a positive duty (not prohibitions)."""
    obligations: list[str] = []
    seen: set[str] = set()
    for sentence in sentences:
        if not OBLIGATION_PATTERN.search(sentence) or NEGATED_OBLIGATION.search(sentence):
            continue
        key = sentence.lower()
        if key in seen:
            continue
        seen.add(key)
        obligations.append(_excerpt(sentence))
        if len(obligations) == MAX_OBLIGATIONS:
            break
    return obligations


def obligations_by_party(obligations: list[str], parties: list[str]) -> dict[str, int]:
    """Count how many obligation sentences name each party as the subject."""
    counts: Counter[str] = Counter()
    for party in parties:
        pattern = re.compile(
            rf"\b{re.escape(party)}\b\s+(shall|must|agrees?|is|will|undertakes)", re.IGNORECASE
        )
        counts[party] = sum(1 for o in obligations if pattern.search(o))
    return dict(counts)


def one_sided_toward(counts: dict[str, int]) -> str | None:
    """Name the party carrying a clear majority of duties, if any."""
    if len(counts) < 2:
        return None
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    top, runner_up = ranked[0], ranked[1]
    if top[1] >= 3 and top[1] >= 2 * max(runner_up[1], 1):
        return top[0]
    return None


def score_risk(clauses: list[DetectedClause], lopsided: bool) -> tuple[int, RiskLevel]:
    """Combine clause weights (and a lopsidedness penalty) into a 0-100 score."""
    score = sum(SEVERITY_WEIGHT[c.severity] for c in clauses)
    if lopsided:
        score += 10
    score = min(100, score)
    if score >= 70:
        level: RiskLevel = "CRITICAL"
    elif score >= 45:
        level = "HIGH"
    elif score >= 20:
        level = "MODERATE"
    else:
        level = "LOW"
    return score, level


def analyze_document(text: str) -> ClauseAnalysis:
    """Run the full deterministic pipeline over raw text."""
    sentences = _sentences(text)
    clauses = detect_clauses(sentences)
    parties = extract_parties(text)
    obligations = extract_obligations(sentences)
    counts = obligations_by_party(obligations, parties)
    lopsided_party = one_sided_toward(counts)
    score, level = score_risk(clauses, lopsided_party is not None)
    words = len(text.split())
    return ClauseAnalysis(
        document_type=guess_document_type(text),
        word_count=words,
        reading_time_minutes=max(1, round(words / WORDS_PER_MINUTE)),
        risk_score=score,
        risk_level=level,
        parties=parties,
        obligations_by_party=counts,
        one_sided_toward=lopsided_party,
        clauses=clauses,
        obligations=obligations,
    )
