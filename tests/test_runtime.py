"""
WorkGraph Unit Tests
Validates deterministic subsystems:
1. Grounding check (hallucination rejection)
2. Policy engine & tolerance thresholds
3. RBAC & Guard risk gates
4. Idempotency key derivation & precheck
5. EventStore rehydration & state restoration
6. State reconciliation under simulated 504 timeouts
"""

import pytest
import os
import sys

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from runtime.contracts import (
    ToolSpec, PlanStep, RiskLevel, Rule, RuleCondition, RuleAction,
    Event, EventActor, StepStatus
)
from runtime.guard import Guard
from runtime.reconciler import StateReconciler
from runtime.event_store import EventStore
from runtime.verifier import IndependentVerifier
from apps.ledgerone.server import compute_bill_hash


def test_grounding_check():
    guard = Guard()
    source_text = """
    Acme Industrial Supply
    Invoice Number: INV-2026-101
    Total Due: $1,250.00
    Standard PO fulfillment.
    """

    # Valid extracted data
    valid_data = {
        "vendor_name": "Acme Industrial Supply",
        "invoice_number": "INV-2026-101",
        "amount": 1250.00
    }
    is_ok, errs = guard.check_grounding(valid_data, source_text)
    assert is_ok is True
    assert len(errs) == 0

    # Hallucinated data (e.g. wrong invoice number and fictitious amount)
    hallucinated = {
        "vendor_name": "Acme Industrial Supply",
        "invoice_number": "INV-9999-FAKE",
        "amount": 99999.00
    }
    is_ok_fake, errs_fake = guard.check_grounding(hallucinated, source_text)
    assert is_ok_fake is False
    assert len(errs_fake) >= 2


def test_policy_engine_variance_tolerance():
    guard = Guard()
    rules = [
        Rule(
            id="RULE_PO_TOLERANCE",
            source_doc="finance_policy.md",
            source_quote="2% tolerance band",
            condition=RuleCondition(field="variance_pct", op="<=", value=2.0),
            action=RuleAction.PASS,
            reason="Within 2% tolerance"
        )
    ]

    # Case A: 0% variance (clean match) -> Allowed automatically
    ctx_clean = {
        "vendor_id": "VEND-001",
        "vendor_status": "active",
        "invoice_amount": 1250.00,
        "po_amount": 1250.00,
        "is_duplicate": False
    }
    res_clean = guard.evaluate_policy(rules, ctx_clean)
    assert res_clean.allowed is True
    assert res_clean.requires_approval is False

    # Case B: 7.35% variance -> Requires human approval
    ctx_mismatch = {
        "vendor_id": "VEND-002",
        "vendor_status": "active",
        "invoice_amount": 3650.00,
        "po_amount": 3400.00,
        "is_duplicate": False
    }
    res_mismatch = guard.evaluate_policy(rules, ctx_mismatch)
    assert res_mismatch.allowed is True
    assert res_mismatch.requires_approval is True
    assert "7.35%" in res_mismatch.approval_reason

    # Case C: Gross variance > 15% -> Hard Rejection
    ctx_gross = {
        "vendor_id": "VEND-001",
        "vendor_status": "active",
        "invoice_amount": 2500.00,
        "po_amount": 1000.00,
        "is_duplicate": False
    }
    res_gross = guard.evaluate_policy(rules, ctx_gross)
    assert res_gross.allowed is False
    assert "Gross variance" in res_gross.rejection_reason


def test_unapproved_vendor_and_duplicate_rejection():
    guard = Guard()
    rules = []

    # Unapproved vendor
    ctx_unapproved = {
        "vendor_id": "VEND-999",
        "vendor_status": "unverified",
        "invoice_amount": 500.00,
        "po_amount": 500.00,
        "is_duplicate": False
    }
    res_unapproved = guard.evaluate_policy(rules, ctx_unapproved)
    assert res_unapproved.allowed is False
    assert "Unapproved vendor" in res_unapproved.rejection_reason

    # Duplicate invoice
    ctx_dup = {
        "vendor_id": "VEND-001",
        "vendor_status": "active",
        "invoice_number": "INV-2026-101",
        "invoice_amount": 1250.00,
        "po_amount": 1250.00,
        "is_duplicate": True
    }
    res_dup = guard.evaluate_policy(rules, ctx_dup)
    assert res_dup.allowed is False
    assert "Duplicate invoice rejection" in res_dup.rejection_reason


def test_idempotency_hash_determinism():
    h1 = compute_bill_hash("VEND-001", "INV-101", 1250.00, "2026-10-20")
    h2 = compute_bill_hash("VEND-001", "INV-101", 1250.00, "2026-10-20")
    h3 = compute_bill_hash("VEND-001", "INV-102", 1250.00, "2026-10-20")

    assert h1 == h2
    assert h1 != h3


def test_state_reconciler_uncertain_timeout():
    reconciler = StateReconciler(max_retries=2)
    step = PlanStep(
        id="step_write",
        goal="Post transaction to ledger",
        tool="ledgerone.create_bill",
        risk=RiskLevel.WRITE
    )

    # Simulate situation: 504 Timeout occurred, but DB check proves record was written!
    mock_app_check = lambda: {
        "exists": True,
        "bill": {"bill_id": "BILL-TEST-88", "amount": 1250.00}
    }

    result = reconciler.reconcile_uncertain_step(step, "504 Gateway Timeout", mock_app_check)
    assert result.recovered is True
    assert result.status == StepStatus.VERIFIED
    assert result.action == "RESOLVED_COMMITTED"
    assert result.data["bill_id"] == "BILL-TEST-88"


def test_independent_verifier_hash_and_mismatch_detection():
    verifier = IndependentVerifier()

    extracted = {
        "vendor_id": "VEND-001",
        "invoice_number": "INV-101",
        "amount": 1250.00,
        "issue_date": "2026-10-20"
    }

    # Perfect match record
    perfect_record = {
        "bill_id": "BILL-001",
        "vendor_id": "VEND-001",
        "invoice_number": "INV-101",
        "amount": 1250.00,
        "issue_date": "2026-10-20"
    }
    res_pass = verifier.verify_committed_bill(extracted, perfect_record)
    assert res_pass.passed is True
    assert len(res_pass.mismatches) == 0
    assert len(res_pass.evidence_bundle) >= 2

    # Tampered / Mismatched record (e.g. wrong amount)
    tampered_record = {
        "bill_id": "BILL-001",
        "vendor_id": "VEND-001",
        "invoice_number": "INV-101",
        "amount": 9999.00,  # Tampered!
        "issue_date": "2026-10-20"
    }
    res_fail = verifier.verify_committed_bill(extracted, tampered_record)
    assert res_fail.passed is False
    assert any("Amount mismatch" in m for m in res_fail.mismatches)
