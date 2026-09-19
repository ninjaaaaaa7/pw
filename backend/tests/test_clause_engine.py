"""Unit tests for the deterministic clause engine."""

import pytest

from app.clause_engine import (
    CLAUSE_RULES,
    analyze_document,
    detect_clauses,
    extract_obligations,
    extract_parties,
    guess_document_type,
    obligations_by_party,
    one_sided_toward,
    score_risk,
)
from app.models import DetectedClause
from app.sample_data import SAMPLE_DOCUMENT


def _clause(severity: str) -> DetectedClause:
    return DetectedClause(
        category="x",
        title="x",
        severity=severity,  # type: ignore[arg-type]
        explanation="",
        excerpt="",
        suggested_question="",
    )


def test_rule_categories_are_unique():
    categories = [rule.category for rule in CLAUSE_RULES]
    assert len(categories) == len(set(categories))


@pytest.mark.parametrize(
    ("sentence", "category"),
    [
        ("Contractor shall indemnify and hold harmless the Company.", "indemnification"),
        ("This Agreement shall automatically renew for successive terms.", "auto_renewal"),
        ("Any dispute shall be settled by binding arbitration in Delaware.", "arbitration"),
        ("Contractor shall not compete with the Company for two years.", "non_compete"),
        ("The Company reserves the right to modify these terms at any time.", "unilateral_change"),
        ("Contractor hereby assigns all right, title and interest in the work.", "ip_assignment"),
        ("The Company may terminate this Agreement at any time without cause.", "termination_convenience"),
        ("The service is provided as is without warranty of any kind.", "as_is"),
    ],
)
def test_detects_each_major_category(sentence, category):
    detected = detect_clauses([sentence])
    assert [c.category for c in detected] == [category]
    assert detected[0].excerpt == sentence


def test_detection_is_sorted_by_severity():
    sentences = [
        "Tenant may not assign this lease.",  # LOW
        "Tenant shall indemnify Landlord against all claims.",  # CRITICAL
        "Rent is subject to a late fee of 5 percent.",  # MEDIUM
    ]
    severities = [c.severity for c in detect_clauses(sentences)]
    assert severities == ["CRITICAL", "MEDIUM", "LOW"]


def test_one_hit_per_category():
    sentences = ["Contractor shall indemnify the Company.", "Contractor shall hold harmless the Company."]
    assert len(detect_clauses(sentences)) == 1


def test_no_clauses_in_benign_text():
    benign = ["The parties will meet monthly to review progress together.", "Coffee is provided."]
    assert detect_clauses(benign) == []


def test_extract_obligations_skips_prohibitions_and_duplicates():
    sentences = [
        "Tenant shall pay rent on the first day of each month.",
        "Tenant shall not sublet the premises.",
        "Tenant shall pay rent on the first day of each month.",
        "The parties may meet to discuss the project informally.",
    ]
    assert extract_obligations(sentences) == ["Tenant shall pay rent on the first day of each month."]


def test_extract_parties_in_order_of_appearance():
    text = 'Between Acme Corp (the "Landlord") and Jane Doe ("Tenant") and Acme Corp (the "Landlord").'
    assert extract_parties(text) == ["Landlord", "Tenant"]


def test_obligations_by_party_and_lopsidedness():
    obligations = [
        "Tenant shall pay rent monthly.",
        "Tenant shall maintain insurance.",
        "Tenant must keep the premises clean.",
        "Landlord shall provide heat.",
    ]
    counts = obligations_by_party(obligations, ["Landlord", "Tenant"])
    assert counts == {"Landlord": 1, "Tenant": 3}
    assert one_sided_toward(counts) == "Tenant"
    assert one_sided_toward({"A": 2, "B": 2}) is None
    assert one_sided_toward({"A": 5}) is None


def test_score_risk_bands_and_cap():
    assert score_risk([], lopsided=False) == (0, "LOW")
    assert score_risk([_clause("MEDIUM"), _clause("MEDIUM"), _clause("LOW")], lopsided=False) == (
        22,
        "MODERATE",
    )
    assert score_risk([_clause("CRITICAL"), _clause("HIGH"), _clause("MEDIUM")], lopsided=False) == (
        50,
        "HIGH",
    )
    score, level = score_risk([_clause("CRITICAL")] * 10, lopsided=True)
    assert score == 100 and level == "CRITICAL"


def test_lopsidedness_adds_penalty():
    base, _ = score_risk([_clause("HIGH")], lopsided=False)
    penalised, _ = score_risk([_clause("HIGH")], lopsided=True)
    assert penalised == base + 10


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("The Landlord leases the premises to the Tenant.", "Lease agreement"),
        ("Your use of the platform and website is subject to these Terms of Service.", "Terms of service"),
        ("The Borrower shall repay the loan principal to the Lender.", "Loan agreement"),
        (
            "It is therefore prayed that the Hon'ble Court may direct the release of the applicant on bail.",
            "Court petition / application",
        ),
        (
            "Questionnaire for directors and executive officers for the registration statement.",
            "Corporate / securities document",
        ),
        ("Hello world.", "Legal agreement"),
    ],
)
def test_guess_document_type(text, expected):
    assert guess_document_type(text) == expected


def test_sample_document_end_to_end():
    analysis = analyze_document(SAMPLE_DOCUMENT)
    categories = {c.category for c in analysis.clauses}
    assert {"indemnification", "auto_renewal", "non_compete", "arbitration", "ip_assignment"} <= categories
    assert analysis.document_type == "Services / freelance agreement"
    assert analysis.risk_level == "CRITICAL"
    assert analysis.parties == ["Agreement", "Company", "Contractor"] or "Contractor" in analysis.parties
    assert analysis.one_sided_toward == "Contractor"
    assert analysis.obligations and all(len(o) <= 261 for o in analysis.obligations)
    assert analysis.reading_time_minutes >= 1
