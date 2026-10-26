"""
WorkGraph Orchestrator (Event-Sourced State Machine)
Coordinates the execution pipeline:
INTAKE -> CONTEXT -> PLAN -> GUARD -> EXECUTE -> RECONCILE -> VERIFY -> REPORT

Enforces budgets, emits persistent events on every transition, pauses for human approval,
reconciles uncertain states to prevent duplicate mutations, and ensures independent verification.
"""

import uuid
import json
from typing import Dict, Any, Optional, List, Callable
from datetime import datetime

from runtime.contracts import (
    RunState, ExecutionPlan, PlanStep, StepStatus, TerminalOutcome,
    Event, EventActor, RiskLevel, RuleAction, ApprovalRequest, EvidenceItem, EvidenceKind
)
from runtime.event_store import EventStore
from runtime.memory import CompanyMemory
from runtime.guard import Guard, PolicyEvaluationResult
from runtime.llm_provider import LLMProvider
from runtime.reconciler import StateReconciler
from runtime.verifier import IndependentVerifier
from runtime.reporter import VerifiedReporter
from tools.registry import global_registry

# Preload tool modules
import tools.invoice_tools
import workflows.sales_report.tools


class WorkGraphOrchestrator:
    def __init__(self, event_store: Optional[EventStore] = None, memory: Optional[CompanyMemory] = None):
        self.event_store = event_store or EventStore()
        self.memory = memory or CompanyMemory()
        self.llm = LLMProvider()
        self.guard = Guard()
        self.reconciler = StateReconciler()
        self.verifier = IndependentVerifier()
        self.reporter = VerifiedReporter()

    def _emit(self, run_id: str, event_type: str, actor: EventActor, payload: Dict[str, Any], step_id: Optional[str] = None) -> Event:
        event = Event(
            run_id=run_id,
            seq=0,  # Will be calculated by EventStore
            event_type=event_type,
            step_id=step_id,
            actor=actor,
            payload=payload
        )
        return self.event_store.append(event)

    def start_run(self, objective: str, workflow_type: str = "invoice", initial_context: Optional[Dict[str, Any]] = None) -> RunState:
        """
        Initializes a new execution run from an open-ended natural language objective.
        """
        run_id = f"run_{uuid.uuid4().hex[:8]}"
        initial_context = initial_context or {}

        # 1. Emit RUN_STARTED
        self._emit(run_id, "RUN_STARTED", EventActor.CODE, {
            "objective": objective,
            "workflow_type": workflow_type,
            "initial_context": initial_context
        })

        # 2. CONTEXT: Retrieve SOPs, Rules, and Playbooks
        self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {"status": "CONTEXT"})
        cached_playbook = self.memory.get_playbook(workflow_type)

        # 3. PLAN: LLM generates structured DAG
        self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {"status": "PLAN"})
        plan = self.llm.generate_plan(objective, workflow_type, cached_playbook)

        self._emit(run_id, "PLAN_GENERATED", EventActor.LLM, {
            "plan_id": plan.plan_id,
            "workflow_name": plan.workflow_name,
            "steps": [s.dict() for s in plan.steps]
        })

        state = self.event_store.rehydrate_run_state(run_id)
        assert state is not None
        return state

    def execute_next_step(self, run_id: str) -> RunState:
        """
        Drives the state machine forward by one step.
        """
        state = self.event_store.rehydrate_run_state(run_id)
        if not state or not state.plan:
            raise ValueError(f"Run {run_id} not found or missing execution plan.")

        # If already paused for approval, do not execute
        if state.status == "WAITING_APPROVAL":
            return state

        # If already terminal, return
        if state.terminal_outcome:
            return state

        # Find next pending step whose dependencies are satisfied
        completed_step_ids = {s.id for s in state.plan.steps if s.status in (StepStatus.COMPLETED, StepStatus.VERIFIED)}
        next_step: Optional[PlanStep] = None

        for s in state.plan.steps:
            if s.status == StepStatus.PENDING:
                if all(dep in completed_step_ids for dep in s.depends_on):
                    next_step = s
                    break

        # If no more pending steps, run final verification & report!
        if not next_step:
            return self._finalize_run(run_id, state)

        # --- STEP_PROPOSE & ARGS RESOLUTION ---
        step_args = dict(next_step.args)
        self._resolve_dynamic_args(step_args, state)

        # Emit STEP_STARTED
        self._emit(run_id, "STEP_STARTED", EventActor.CODE, {
            "step_id": next_step.id,
            "args": step_args
        }, step_id=next_step.id)

        # --- STEP_GUARD: Permissions, Grounding & Policy Evaluation ---
        tool_spec = global_registry.get_spec(next_step.tool)
        if not tool_spec:
            self._emit(run_id, "STEP_FAILED", EventActor.CODE, {
                "error": f"Tool '{next_step.tool}' not found in registry."
            }, step_id=next_step.id)
            return self.event_store.rehydrate_run_state(run_id)

        # RBAC Check
        perm_ok, perm_err = self.guard.check_permission(tool_spec)
        if not perm_ok:
            self._emit(run_id, "STEP_FAILED", EventActor.CODE, {"error": perm_err}, step_id=next_step.id)
            self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {
                "status": "FAILED",
                "terminal_outcome": TerminalOutcome.FAILED.value
            })
            return self.event_store.rehydrate_run_state(run_id)

        # Policy & Risk Gate Check
        policy_res: Optional[PolicyEvaluationResult] = None
        if next_step.tool in ("ledgerone.create_bill", "policy.evaluate_rules"):
            rules = self.memory.get_all_rules()
            policy_res = self.guard.evaluate_policy(rules, state.context)

            # Store rule eval evidence
            self._emit(run_id, "EVIDENCE_ATTACHED", EventActor.CODE, {
                "id": f"EVID-POLICY-{uuid.uuid4().hex[:6].upper()}",
                "kind": EvidenceKind.RULE_EVAL.value,
                "title": "Deterministic Policy & Tolerance Evaluation",
                "data": policy_res.dict(),
                "hash": self.verifier.compute_sha256(policy_res.dict())
            })

            # Hard Policy Rejection
            if not policy_res.allowed:
                self._emit(run_id, "STEP_FAILED", EventActor.CODE, {
                    "error": policy_res.rejection_reason
                }, step_id=next_step.id)
                self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {
                    "status": "REJECTED_BY_POLICY",
                    "terminal_outcome": TerminalOutcome.REJECTED_BY_POLICY.value
                })
                return self.event_store.rehydrate_run_state(run_id)

        # Evaluate risk gate
        already_approved = (
            state.active_approval is not None
            and state.active_approval.step_id == next_step.id
            and state.active_approval.status == "APPROVED"
        )
        if not already_approved:
            can_proceed, approval_req = self.guard.evaluate_step_gate(next_step, tool_spec, policy_res)
            if not can_proceed and approval_req:
                # PAUSE execution for human approval!
                approval_req.run_id = run_id
                approval_req.evidence_ids = list(state.evidence.keys())
                self._emit(run_id, "APPROVAL_REQUESTED", EventActor.CODE, approval_req.dict(), step_id=next_step.id)
                return self.event_store.rehydrate_run_state(run_id)

        # --- STEP_EXECUTE ---
        try:
            handler = global_registry.get_handler(next_step.tool)
            result = handler(**step_args)

            # Update state context with results
            if isinstance(result, dict):
                state.context.update(result)
                if "vendor" in result and "purchase_order" in result:
                    v = result["vendor"]
                    p = result["purchase_order"]
                    state.context["vendor_status"] = v.get("status")
                    state.context["po_amount"] = p.get("total_amount", 0.0) if p else 0.0
                    state.context["manager_approval_threshold"] = v.get("manager_approval_threshold", 5000.0)

                if "amount" in result:
                    state.context["invoice_amount"] = result["amount"]
                if "invoice_number" in result:
                    state.context["invoice_number"] = result["invoice_number"]
                if "vendor_id" in result:
                    state.context["vendor_id"] = result["vendor_id"]
                if "exists" in result:
                    state.context["is_duplicate"] = result["exists"]
                if "bill_id" in result:
                    state.context["bill_id"] = result["bill_id"]

            self._emit(run_id, "STEP_COMPLETED", EventActor.CODE, {
                "result": result
            }, step_id=next_step.id)

        except Exception as e:
            # Handle potential uncertain state or timeout!
            error_str = str(e)
            if "504" in error_str or "timeout" in error_str.lower():
                self._emit(run_id, "STEP_UNCERTAIN", EventActor.CODE, {
                    "error": f"Save timed out or connection dropped: {error_str}"
                }, step_id=next_step.id)

                # TRIGGER RECONCILIATION
                rec_result = self.reconciler.reconcile_uncertain_step(
                    step=next_step,
                    error_msg=error_str,
                    app_check_fn=lambda: global_registry.execute("ledgerone.precheck_bill", {
                        "vendor_id": state.context.get("vendor_id", "VEND-001"),
                        "invoice_number": state.context.get("invoice_number", "")
                    })
                )

                if rec_result.recovered and rec_result.data:
                    state.context["bill_id"] = rec_result.data.get("bill_id")
                    self._emit(run_id, "STEP_RECONCILED", EventActor.CODE, {
                        "result": rec_result.data,
                        "message": rec_result.message
                    }, step_id=next_step.id)
                else:
                    self._emit(run_id, "STEP_FAILED", EventActor.CODE, {
                        "error": rec_result.message
                    }, step_id=next_step.id)
            elif "401" in error_str or "session expired" in error_str.lower():
                # Session expired: automatic re-auth and step retry
                next_step.retries += 1
                self._emit(run_id, "STEP_RETRY", EventActor.CODE, {
                    "retry_count": next_step.retries,
                    "reason": "Session expired mid-run. Re-authenticating and retrying.",
                    "error": error_str
                }, step_id=next_step.id)
            elif next_step.retries < tool_spec.max_retries:
                # Bounded retry with backoff (e.g. 500 deadlock before commit)
                next_step.retries += 1
                self._emit(run_id, "STEP_RETRY", EventActor.CODE, {
                    "retry_count": next_step.retries,
                    "max_retries": tool_spec.max_retries,
                    "reason": f"Retryable error encountered. Retrying step (Attempt {next_step.retries}/{tool_spec.max_retries}).",
                    "error": error_str
                }, step_id=next_step.id)
            else:
                self._emit(run_id, "STEP_FAILED", EventActor.CODE, {
                    "error": error_str
                }, step_id=next_step.id)
                self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {
                    "status": "FAILED",
                    "terminal_outcome": TerminalOutcome.FAILED.value
                })

        return self.event_store.rehydrate_run_state(run_id)

    def submit_approval(self, run_id: str, decision: str, learn_as_exception: bool = False,
                        exception_notes: Optional[str] = None, approver: str = "human_supervisor") -> RunState:
        """
        Resumes a paused run following a human supervisor approval decision.
        If learn_as_exception is selected, stores exception rule in CompanyMemory with provenance.
        """
        state = self.event_store.rehydrate_run_state(run_id)
        if not state or not state.active_approval:
            raise ValueError("No active approval request found for this run.")

        self._emit(run_id, "APPROVAL_DECIDED", EventActor.HUMAN, {
            "decision": decision,
            "learn_as_exception": learn_as_exception,
            "exception_notes": exception_notes,
            "decided_by": approver
        }, step_id=state.active_approval.step_id)

        # Attach approval evidence item
        self._emit(run_id, "EVIDENCE_ATTACHED", EventActor.HUMAN, {
            "id": f"EVID-APPR-{uuid.uuid4().hex[:6].upper()}",
            "kind": EvidenceKind.APPROVAL.value,
            "title": f"Human Authorization Record ({decision})",
            "data": {
                "decision": decision,
                "approver": approver,
                "notes": exception_notes,
                "learn_as_exception": learn_as_exception
            },
            "hash": self.verifier.compute_sha256({"decision": decision, "approver": approver})
        })

        if decision == "APPROVED":
            # Learn exception if checked
            if learn_as_exception:
                vendor_id = state.context.get("vendor_id", "VEND-004")
                po_amt = float(state.context.get("po_amount", 0.0))
                inv_amt = float(state.context.get("invoice_amount", 0.0))
                variance_pct = ((inv_amt - po_amt) / po_amt) * 100.0 if po_amt > 0 else 0.0
                
                self.memory.learn_exception_from_approval(
                    run_id=run_id,
                    vendor_id=vendor_id,
                    max_allowed_variance_pct=variance_pct,
                    approver=approver,
                    notes=exception_notes
                )

            # Mark step completed or clear waiting status so execute_next_step can run it
            self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {"status": "STEP_EXECUTE"})
        else:
            # Human rejected
            self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {
                "status": "ESCALATED",
                "terminal_outcome": TerminalOutcome.ESCALATED.value
            })

        return self.event_store.rehydrate_run_state(run_id)

    def _resolve_dynamic_args(self, args: Dict[str, Any], state: RunState):
        """Maps output of earlier steps to the inputs of downstream steps."""
        ctx = state.context
        for k in list(args.keys()):
            if args[k] == "" or args[k] is None:
                if k in ctx:
                    args[k] = ctx[k]

        # Specific mappings
        if "pdf_path" not in args and "pdf_path" in ctx:
            args["pdf_path"] = ctx["pdf_path"]
        if "vendor_id" not in args and "vendor_id" in ctx:
            args["vendor_id"] = ctx["vendor_id"]
        if "invoice_number" not in args and "invoice_number" in ctx:
            args["invoice_number"] = ctx["invoice_number"]
        if "amount" not in args and "invoice_amount" in ctx:
            args["amount"] = ctx["invoice_amount"]
        if "po_number" not in args and "po_number" in ctx:
            args["po_number"] = ctx["po_number"]
        if "issue_date" not in args and "issue_date" in ctx:
            args["issue_date"] = ctx["issue_date"]
        if "due_date" not in args and "due_date" in ctx:
            args["due_date"] = ctx["due_date"]
        if "bill_id" not in args and "bill_id" in ctx:
            args["bill_id"] = ctx["bill_id"]

    def _finalize_run(self, run_id: str, state: RunState) -> RunState:
        """
        Executes final out-of-band verification and evidence-backed audit report synthesis.
        """
        self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {"status": "FINAL_VERIFY"})

        # Independent Read-back Verification (if invoice workflow)
        if "bill_id" in state.context:
            actual_bill = global_registry.execute("ledgerone.verify_bill", {"bill_id": state.context["bill_id"]})
            extracted_data = {
                "vendor_id": state.context.get("vendor_id"),
                "invoice_number": state.context.get("invoice_number"),
                "amount": state.context.get("invoice_amount"),
                "issue_date": state.context.get("issue_date")
            }
            ver_res = self.verifier.verify_committed_bill(extracted_data, actual_bill)

            for item in ver_res.evidence_bundle:
                self._emit(run_id, "EVIDENCE_ATTACHED", EventActor.CODE, item.dict())

            if not ver_res.passed:
                self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {
                    "status": "FAILED",
                    "terminal_outcome": TerminalOutcome.FAILED.value
                })
                return self.event_store.rehydrate_run_state(run_id)

        # Assemble Report
        self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {"status": "REPORT"})
        state = self.event_store.rehydrate_run_state(run_id)
        evidence_list = list(state.evidence.values())

        outcome = TerminalOutcome.COMPLETED_AFTER_APPROVAL if state.active_approval and state.active_approval.status == "APPROVED" else TerminalOutcome.COMPLETED_VERIFIED

        report_data = self.reporter.build_report(
            objective=state.objective,
            terminal_outcome=outcome.value,
            evidence_bundle=evidence_list
        )

        self._emit(run_id, "EVIDENCE_ATTACHED", EventActor.LLM, {
            "id": f"EVID-REP-{uuid.uuid4().hex[:6].upper()}",
            "kind": EvidenceKind.LOG.value,
            "title": "Verified Audit Report Narrative",
            "data": report_data,
            "hash": self.verifier.compute_sha256(report_data)
        })

        self._emit(run_id, "STATUS_CHANGED", EventActor.CODE, {
            "status": "DONE",
            "terminal_outcome": outcome.value
        })

        return self.event_store.rehydrate_run_state(run_id)
