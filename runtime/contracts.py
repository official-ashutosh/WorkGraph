"""
WorkGraph Core Data Contracts (Pydantic v2)
Strict data schemas for tools, plans, policies, events, evidence, and run state.
"""

from enum import Enum
from typing import List, Dict, Any, Optional, Callable, Union
from pydantic import BaseModel, Field
from datetime import datetime


class RiskLevel(str, Enum):
    READ = "read"
    WRITE = "write"
    IRREVERSIBLE = "irreversible"


class StepStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    UNCERTAIN = "UNCERTAIN"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class TerminalOutcome(str, Enum):
    COMPLETED_VERIFIED = "COMPLETED_VERIFIED"
    COMPLETED_AFTER_APPROVAL = "COMPLETED_AFTER_APPROVAL"
    ESCALATED = "ESCALATED"
    REJECTED_BY_POLICY = "REJECTED_BY_POLICY"
    FAILED = "FAILED"


class ProvenanceKind(str, Enum):
    USER_PROVIDED = "user_provided"
    DOCUMENT_EXTRACTED = "document_extracted"
    EXECUTION_VERIFIED = "execution_verified"


class EvidenceKind(str, Enum):
    RECORD_JSON = "record_json"
    SCREENSHOT = "screenshot"
    RULE_EVAL = "rule_eval"
    APPROVAL = "approval"
    EXTRACTION = "extraction"
    LOG = "log"


# --- Tool Specifications ---

class ToolSpec(BaseModel):
    name: str
    description: str
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    risk: RiskLevel = RiskLevel.READ
    permission: str  # e.g., "finance.bill.create", "finance.po.read"
    idempotent: bool = True
    max_retries: int = 2
    timeout_s: float = 15.0

    model_config = {"arbitrary_types_allowed": True}


# --- Policy & Rules (Compiled from SOP) ---

class RuleAction(str, Enum):
    PASS = "pass"
    REQUIRE_APPROVAL = "require_approval"
    REJECT = "reject"


class RuleCondition(BaseModel):
    field: str
    op: str  # "==", "!=", ">", "<", ">=", "<=", "in", "not_in", "variance_gt"
    value: Any


class Rule(BaseModel):
    id: str
    source_doc: str
    source_quote: str
    condition: RuleCondition
    action: RuleAction
    reason: str
    approved_by: Optional[str] = "SYSTEM_ADMIN"
    version: int = 1


# --- Plan and Step Definitions ---

class PlanStep(BaseModel):
    id: str
    goal: str
    tool: str
    args: Dict[str, Any] = Field(default_factory=dict)
    depends_on: List[str] = Field(default_factory=list)
    risk: RiskLevel = RiskLevel.READ
    requires_approval_if: Optional[str] = None
    status: StepStatus = StepStatus.PENDING
    result: Optional[Any] = None
    error: Optional[str] = None
    retries: int = 0
    idempotency_key: Optional[str] = None


class ExecutionPlan(BaseModel):
    plan_id: str
    objective: str
    workflow_name: str
    steps: List[PlanStep]
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# --- Events (Event Sourced Architecture) ---

class EventActor(str, Enum):
    LLM = "llm"
    CODE = "code"
    HUMAN = "human"


class Event(BaseModel):
    run_id: str
    seq: int
    ts: str = Field(default_factory=lambda: datetime.now().isoformat())
    event_type: str  # e.g. "RUN_STARTED", "PLAN_GENERATED", "STEP_STARTED", "STEP_COMPLETED", "APPROVAL_REQUESTED", "APPROVAL_DECIDED", "STEP_RECONCILED", "VERIFIED"
    step_id: Optional[str] = None
    actor: EventActor
    payload: Dict[str, Any] = Field(default_factory=dict)


# --- Evidence Items ---

class EvidenceItem(BaseModel):
    id: str
    kind: EvidenceKind
    title: str
    data: Any
    hash: str
    uri: Optional[str] = None
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())


# --- Human Approval Request / Decision ---

class ApprovalRequest(BaseModel):
    request_id: str
    run_id: str
    step_id: str
    rule_id: Optional[str] = None
    reason: str
    risk_level: RiskLevel
    evidence_ids: List[str]
    proposed_action: Dict[str, Any]
    status: str = "PENDING"  # "PENDING", "APPROVED", "REJECTED"
    learn_as_exception: bool = False
    exception_notes: Optional[str] = None
    decided_by: Optional[str] = None
    decided_at: Optional[str] = None


# --- Run State ---

class RunState(BaseModel):
    run_id: str
    objective: str
    status: str = "INTAKE"
    terminal_outcome: Optional[TerminalOutcome] = None
    current_step_id: Optional[str] = None
    plan: Optional[ExecutionPlan] = None
    evidence: Dict[str, EvidenceItem] = Field(default_factory=dict)
    active_approval: Optional[ApprovalRequest] = None
    context: Dict[str, Any] = Field(default_factory=dict)
    replan_count: int = 0
    total_retries: int = 0
    max_steps: int = 25
    max_replans: int = 1
    max_total_retries: int = 5
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())
