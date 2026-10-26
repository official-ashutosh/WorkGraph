"""
WorkGraph Deterministic Guard Layer & Policy Engine
'The LLM proposes. Deterministic code authorizes, executes, recovers and verifies.'

Enforces:
1. Grounding: Extracted values must literally appear in source documents.
2. Role-Based Permissions (RBAC).
3. SOP Policy Rules: Evaluates compiled rules (match tolerance, threshold, vendor status, duplicates).
4. Risk Gates: write requires approval if flagged by policy; irreversible always requires approval.
Approval is decided strictly by code and rules, never by the LLM.
"""

from typing import Dict, Any, List, Optional, Tuple
from pydantic import BaseModel, Field

from runtime.contracts import (
    ToolSpec, PlanStep, RiskLevel, Rule, RuleAction, 
    ApprovalRequest, TerminalOutcome
)


class PolicyEvaluationResult(BaseModel):
    allowed: bool
    requires_approval: bool
    triggered_rules: List[Rule] = Field(default_factory=list)
    rejection_reason: Optional[str] = None
    approval_reason: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class Guard:
    def __init__(self, user_role: str = "ap_automation_bot"):
        self.user_role = user_role
        self.role_permissions = {
            "ap_automation_bot": [
                "pdf.read",
                "finance.po.read",
                "finance.vendor.read",
                "policy.read",
                "ledgerone.bill.check",
                "ledgerone.bill.create",
                "ledgerone.bill.verify",
                "crm.deals.read",
                "report.generate",
                "report.verify",
                "email.draft"
            ],
            "finance_manager": [
                "*"
            ]
        }

    def check_permission(self, tool: ToolSpec) -> Tuple[bool, Optional[str]]:
        """Checks caller role against tool required permission."""
        perms = self.role_permissions.get(self.user_role, [])
        if "*" in perms or tool.permission in perms:
            return True, None
        return False, f"Permission Denied: Role '{self.user_role}' lacks permission '{tool.permission}'"

    def check_grounding(self, extracted_data: Dict[str, Any], source_text: str) -> Tuple[bool, List[str]]:
        """
        Deterministic Grounding Check:
        Verifies that every extracted factual claim literally exists in the raw source text.
        Protects against model hallucination before data enters the write pipeline.
        """
        unsupported = []
        lower_source = source_text.lower()

        # Check invoice number
        inv_num = str(extracted_data.get("invoice_number", "")).strip()
        if inv_num and inv_num.lower() not in lower_source:
            unsupported.append(f"Invoice number '{inv_num}' not found in source text")

        # Check vendor name or vendor ID
        vendor_name = str(extracted_data.get("vendor_name", "")).strip()
        vendor_id = str(extracted_data.get("vendor_id", "")).strip()
        if vendor_name and vendor_name.lower() not in lower_source and vendor_id.lower() not in lower_source:
            unsupported.append(f"Vendor '{vendor_name}' not found in source text")

        # Check amount string (e.g. 1250 or 1,250 or 1250.00)
        amount = extracted_data.get("amount")
        if amount is not None:
            amt_val = float(amount)
            # Variations of currency representation
            variations = [
                f"{amt_val:.2f}",
                f"{amt_val:,.2f}",
                f"{int(amt_val)}"
            ]
            if not any(v in source_text for v in variations):
                unsupported.append(f"Amount '{amt_val}' not found in source text")

        if unsupported:
            return False, unsupported
        return True, []

    def evaluate_policy(self, rules: List[Rule], context: Dict[str, Any]) -> PolicyEvaluationResult:
        """
        Evaluates compiled SOP rules and active learned exception rules.
        """
        vendor_id = context.get("vendor_id", "")
        vendor_status = context.get("vendor_status", "unknown")
        invoice_amount = float(context.get("invoice_amount", 0.0))
        po_amount = float(context.get("po_amount", 0.0))
        is_duplicate = bool(context.get("is_duplicate", False))

        # Calculate variance if PO amount is present
        variance_pct = 0.0
        if po_amount > 0:
            variance_pct = ((invoice_amount - po_amount) / po_amount) * 100.0

        # Check for learned exception rule for this vendor
        learned_tolerance = 2.0  # standard default is 2%
        for r in rules:
            if r.condition.field == f"vendor_variance:{vendor_id}":
                learned_tolerance = max(learned_tolerance, float(r.condition.value))

        # Check 1: Duplicate Invoice (Immediate Reject)
        if is_duplicate:
            return PolicyEvaluationResult(
                allowed=False,
                requires_approval=False,
                rejection_reason=f"Duplicate invoice rejection: Invoice {context.get('invoice_number')} already exists in LedgerOne."
            )

        # Check 2: Approved Vendor List
        if vendor_status != "active":
            return PolicyEvaluationResult(
                allowed=False,
                requires_approval=False,
                rejection_reason=f"Unapproved vendor rejection: Vendor '{vendor_id}' is not on the corporate approved vendor list."
            )

        # Check 3: Gross Variance Exceeds Rejection Threshold (> 15%)
        if po_amount > 0 and variance_pct > 15.0:
            return PolicyEvaluationResult(
                allowed=False,
                requires_approval=False,
                rejection_reason=f"Gross variance rejection: Invoice amount variance (+{variance_pct:.2f}%) exceeds hard policy limit of 15%."
            )

        # Check 4: Variance Exceeds Tolerance Band (> learned_tolerance) -> Requires Approval
        if po_amount > 0 and variance_pct > learned_tolerance:
            reason = f"PO match variance (+{variance_pct:.2f}%) exceeds allowable tolerance band ({learned_tolerance:.1f}%). Requires human approval."
            return PolicyEvaluationResult(
                allowed=True,
                requires_approval=True,
                approval_reason=reason,
                details={"variance_pct": variance_pct, "po_amount": po_amount, "invoice_amount": invoice_amount}
            )

        # Check 5: Manager Spending Threshold (>= $5,000.00 USD)
        manager_threshold = float(context.get("manager_approval_threshold", 5000.00))
        if invoice_amount >= manager_threshold:
            reason = f"Invoice total (${invoice_amount:,.2f}) equals or exceeds authorization threshold (${manager_threshold:,.2f}). Requires Finance Director approval."
            return PolicyEvaluationResult(
                allowed=True,
                requires_approval=True,
                approval_reason=reason,
                details={"invoice_amount": invoice_amount, "threshold": manager_threshold}
            )

        # Passed all rules automatically
        return PolicyEvaluationResult(
            allowed=True,
            requires_approval=False,
            details={"variance_pct": variance_pct, "status": "AUTOMATICALLY_APPROVED"}
        )

    def evaluate_step_gate(self, step: PlanStep, tool: ToolSpec, policy_result: Optional[PolicyEvaluationResult] = None) -> Tuple[bool, Optional[ApprovalRequest]]:
        """
        Determines whether a step is allowed to proceed immediately or must pause for human approval.
        """
        # Irreversible actions ALWAYS require human approval
        if tool.risk == RiskLevel.IRREVERSIBLE or step.risk == RiskLevel.IRREVERSIBLE:
            req = ApprovalRequest(
                request_id=f"APPR-{step.id}",
                run_id="current_run",
                step_id=step.id,
                reason="Irreversible external mutation requested (e.g. dispatch email or payment). Mandatory dual-authorization.",
                risk_level=RiskLevel.IRREVERSIBLE,
                evidence_ids=[],
                proposed_action=step.args
            )
            return False, req

        # Write actions flagged by policy require approval
        if policy_result and policy_result.requires_approval and (tool.risk == RiskLevel.WRITE or step.risk == RiskLevel.WRITE):
            req = ApprovalRequest(
                request_id=f"APPR-{step.id}",
                run_id="current_run",
                step_id=step.id,
                reason=policy_result.approval_reason or "Policy variance requires human manager authorization.",
                risk_level=RiskLevel.WRITE,
                evidence_ids=[],
                proposed_action=step.args
            )
            return False, req

        # Policy hard rejection
        if policy_result and not policy_result.allowed:
            return False, None

        return True, None
