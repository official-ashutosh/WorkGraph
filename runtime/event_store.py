"""
WorkGraph Event Store (SQLite)
Append-only log of every state transition, plan update, tool action, and verification event.
Enables full run replay, state rehydration, auditability, and live SSE streaming.
"""

import sqlite3
import json
import os
from typing import List, Optional, Dict, Any
from runtime.contracts import Event, EventActor, RunState, ExecutionPlan, PlanStep, TerminalOutcome, StepStatus, ApprovalRequest, EvidenceItem

DB_PATH = os.getenv(
    "WORKGRAPH_EVENT_DB",
    os.path.join(os.path.dirname(__file__), "..", "data", "workgraph.db"),
)

def get_event_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_event_store():
    conn = get_event_db()
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        seq INTEGER NOT NULL,
        ts TEXT NOT NULL,
        event_type TEXT NOT NULL,
        step_id TEXT,
        actor TEXT NOT NULL,
        payload_json TEXT NOT NULL,
        UNIQUE(run_id, seq)
    )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_run_events ON events(run_id, seq)")
    conn.commit()
    conn.close()

init_event_store()


class EventStore:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or DB_PATH

    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def append(self, event: Event) -> Event:
        conn = self._conn()
        cursor = conn.cursor()
        
        # Calculate next seq if 0 or negative
        if event.seq <= 0:
            cursor.execute("SELECT COALESCE(MAX(seq), 0) + 1 as next_seq FROM events WHERE run_id = ?", (event.run_id,))
            event.seq = cursor.fetchone()["next_seq"]

        cursor.execute("""
        INSERT INTO events (run_id, seq, ts, event_type, step_id, actor, payload_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            event.run_id,
            event.seq,
            event.ts,
            event.event_type,
            event.step_id,
            event.actor.value if isinstance(event.actor, EventActor) else event.actor,
            json.dumps(event.payload)
        ))
        conn.commit()
        conn.close()
        return event

    def get_events(self, run_id: str, since_seq: int = 0) -> List[Event]:
        conn = self._conn()
        cursor = conn.cursor()
        cursor.execute("""
        SELECT run_id, seq, ts, event_type, step_id, actor, payload_json
        FROM events
        WHERE run_id = ? AND seq > ?
        ORDER BY seq ASC
        """, (run_id, since_seq))
        rows = cursor.fetchall()
        conn.close()

        events = []
        for r in rows:
            events.append(Event(
                run_id=r["run_id"],
                seq=r["seq"],
                ts=r["ts"],
                event_type=r["event_type"],
                step_id=r["step_id"],
                actor=EventActor(r["actor"]),
                payload=json.loads(r["payload_json"])
            ))
        return events

    def rehydrate_run_state(self, run_id: str) -> Optional[RunState]:
        """
        Reconstructs the RunState by replaying all historical events in sequence.
        Guarantees exact state restoration after crash, restart, or process pause.
        """
        events = self.get_events(run_id)
        if not events:
            return None

        state: Optional[RunState] = None

        for ev in events:
            p = ev.payload

            if ev.event_type == "RUN_STARTED":
                state = RunState(
                    run_id=ev.run_id,
                    objective=p.get("objective", ""),
                    status="INTAKE",
                    context=p.get("initial_context", {})
                )

            elif state is None:
                continue

            elif ev.event_type == "STATUS_CHANGED":
                state.status = p.get("status", state.status)
                if "terminal_outcome" in p and p["terminal_outcome"]:
                    state.terminal_outcome = TerminalOutcome(p["terminal_outcome"])

            elif ev.event_type == "PLAN_GENERATED":
                steps = [PlanStep(**s) for s in p.get("steps", [])]
                state.plan = ExecutionPlan(
                    plan_id=p.get("plan_id", "plan_01"),
                    objective=state.objective,
                    workflow_name=p.get("workflow_name", "generic"),
                    steps=steps
                )
                state.status = "STEP_PROPOSE"

            elif ev.event_type == "STEP_STARTED":
                state.current_step_id = ev.step_id
                if state.plan:
                    for s in state.plan.steps:
                        if s.id == ev.step_id:
                            s.status = StepStatus.RUNNING
                            s.args = p.get("args", s.args)
                            s.idempotency_key = p.get("idempotency_key")
                            break

            elif ev.event_type == "STEP_COMPLETED":
                if state.plan and ev.step_id:
                    for s in state.plan.steps:
                        if s.id == ev.step_id:
                            s.status = StepStatus.COMPLETED
                            s.result = p.get("result")
                            if isinstance(s.result, dict):
                                state.context.update(s.result)
                                if "amount" in s.result:
                                    state.context["invoice_amount"] = s.result["amount"]
                                if "bill_id" in s.result:
                                    state.context["bill_id"] = s.result["bill_id"]
                                if "exists" in s.result:
                                    state.context["is_duplicate"] = s.result["exists"]
                                if "vendor" in s.result:
                                    v = s.result["vendor"]
                                    state.context["vendor_status"] = v.get("status")
                                    state.context["manager_approval_threshold"] = v.get("manager_approval_threshold", 5000.0)
                                if "purchase_order" in s.result and s.result["purchase_order"]:
                                    state.context["po_amount"] = s.result["purchase_order"].get("total_amount", 0.0)
                            break

            elif ev.event_type == "STEP_UNCERTAIN":
                if state.plan and ev.step_id:
                    for s in state.plan.steps:
                        if s.id == ev.step_id:
                            s.status = StepStatus.UNCERTAIN
                            s.error = p.get("error")
                            break

            elif ev.event_type == "STEP_RECONCILED":
                if state.plan and ev.step_id:
                    for s in state.plan.steps:
                        if s.id == ev.step_id:
                            s.status = StepStatus.VERIFIED
                            s.result = p.get("result")
                            if isinstance(s.result, dict):
                                state.context.update(s.result)
                                if "bill_id" in s.result:
                                    state.context["bill_id"] = s.result["bill_id"]
                            break

            elif ev.event_type == "STEP_FAILED":
                if state.plan and ev.step_id:
                    for s in state.plan.steps:
                        if s.id == ev.step_id:
                            s.status = StepStatus.FAILED
                            s.error = p.get("error")
                            break

            elif ev.event_type == "STEP_RETRY":
                if state.plan and ev.step_id:
                    for s in state.plan.steps:
                        if s.id == ev.step_id:
                            s.status = StepStatus.PENDING
                            s.retries = p.get("retry_count", s.retries + 1)
                            s.error = p.get("error")
                            break

            elif ev.event_type == "APPROVAL_REQUESTED":
                state.active_approval = ApprovalRequest(**p)
                state.status = "WAITING_APPROVAL"
                if state.plan and ev.step_id:
                    for s in state.plan.steps:
                        if s.id == ev.step_id:
                            s.status = StepStatus.WAITING_APPROVAL
                            break

            elif ev.event_type == "APPROVAL_DECIDED":
                if state.active_approval:
                    state.active_approval.status = p.get("decision", "APPROVED")
                    state.active_approval.decided_by = p.get("decided_by", "human")
                    state.active_approval.decided_at = ev.ts
                    state.active_approval.learn_as_exception = p.get("learn_as_exception", False)
                    state.active_approval.exception_notes = p.get("exception_notes")
                    if p.get("decision") == "APPROVED" and ev.step_id and state.plan:
                        for s in state.plan.steps:
                            if s.id == ev.step_id:
                                s.status = StepStatus.PENDING
                                break

            elif ev.event_type == "EVIDENCE_ATTACHED":
                ev_item = EvidenceItem(**p)
                state.evidence[ev_item.id] = ev_item

            elif ev.event_type == "REPLAN_TRIGGERED":
                state.replan_count += 1

            state.updated_at = ev.ts

        return state
