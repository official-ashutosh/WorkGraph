"""
WorkGraph Main Application Server (FastAPI + SSE + Live Web UI)
Coordinates execution runs, live Server-Sent Events (SSE), human approvals, and interactive UI.
"""

import os
import sys

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import json
import asyncio
import uuid
import time
from typing import Dict, Any, Optional, List

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import FastAPI, Request, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from runtime.orchestrator import WorkGraphOrchestrator
from runtime.event_store import EventStore
from runtime.memory import CompanyMemory
from runtime.contracts import StepStatus, TerminalOutcome
from apps.ledgerone.database import reset_db, set_fault, get_faults

app = FastAPI(title="WorkGraph Control Plane", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

orchestrator = WorkGraphOrchestrator()
event_store = EventStore()
memory = CompanyMemory()

# Active run registry for background execution
RUN_LOCKS: Dict[str, bool] = {}


# --- Background Runner Loop ---

async def auto_run_worker(run_id: str):
    """
    Drives a run forward step-by-step asynchronously until it reaches a terminal outcome
    or halts at a human approval gate.
    """
    RUN_LOCKS[run_id] = True
    try:
        for _ in range(25):
            state = event_store.rehydrate_run_state(run_id)
            if not state or state.terminal_outcome or state.status in ("WAITING_APPROVAL", "DONE", "ESCALATED", "REJECTED_BY_POLICY", "FAILED"):
                break

            await asyncio.sleep(0.4)  # Visual pacing for demo
            state = orchestrator.execute_next_step(run_id)

            if state.terminal_outcome or state.status in ("WAITING_APPROVAL", "DONE", "ESCALATED", "REJECTED_BY_POLICY", "FAILED"):
                break
    finally:
        RUN_LOCKS[run_id] = False


# --- API Routes ---

@app.post("/api/runs")
async def create_run(request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    objective = data.get("objective", "Process latest vendor invoice")
    workflow_type = data.get("workflow_type", "invoice")
    invoice_file = data.get("invoice_file", "inv_01_clean_match.pdf")
    fault = data.get("fault")

    # Reset ledger environment for clean demo run if requested
    if data.get("reset_env", True):
        reset_db()
        if fault:
            set_fault(fault, True)

    initial_context = {}
    if workflow_type == "invoice":
        initial_context["pdf_path"] = os.path.join(BASE_DIR, "data", "invoices", invoice_file)

    state = orchestrator.start_run(objective=objective, workflow_type=workflow_type, initial_context=initial_context)

    # Start execution loop in background if auto_run requested
    if data.get("auto_run", True):
        background_tasks.add_task(auto_run_worker, state.run_id)

    return {"run_id": state.run_id, "status": state.status, "plan": state.plan.dict() if state.plan else None}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str):
    state = event_store.rehydrate_run_state(run_id)
    if not state:
        raise HTTPException(status_code=404, detail="Run not found")
    events = event_store.get_events(run_id)
    return {
        "run_id": state.run_id,
        "objective": state.objective,
        "status": state.status,
        "terminal_outcome": state.terminal_outcome.value if state.terminal_outcome else None,
        "current_step_id": state.current_step_id,
        "plan": state.plan.dict() if state.plan else None,
        "evidence": {k: v.dict() for k, v in state.evidence.items()},
        "active_approval": state.active_approval.dict() if state.active_approval else None,
        "events": [e.dict() for e in events]
    }


@app.post("/api/runs/{run_id}/step")
def step_run(run_id: str):
    state = orchestrator.execute_next_step(run_id)
    return {"status": state.status, "current_step": state.current_step_id, "terminal_outcome": state.terminal_outcome.value if state.terminal_outcome else None}


@app.post("/api/runs/{run_id}/approve")
async def submit_approval(run_id: str, request: Request, background_tasks: BackgroundTasks):
    data = await request.json()
    decision = data.get("decision", "APPROVED")  # "APPROVED" or "REJECTED"
    learn_as_exception = bool(data.get("learn_as_exception", False))
    exception_notes = data.get("exception_notes")
    approver = data.get("approver", "human_finance_director")

    state = orchestrator.submit_approval(
        run_id=run_id,
        decision=decision,
        learn_as_exception=learn_as_exception,
        exception_notes=exception_notes,
        approver=approver
    )

    if decision == "APPROVED" and data.get("auto_resume", True):
        background_tasks.add_task(auto_run_worker, run_id)

    return {"status": state.status, "active_approval": state.active_approval.dict() if state.active_approval else None}


@app.get("/api/runs/{run_id}/stream")
async def stream_events(run_id: str):
    """Server-Sent Events (SSE) live event push to the UI."""
    async def event_generator():
        last_seq = 0
        while True:
            events = event_store.get_events(run_id, since_seq=last_seq)
            for ev in events:
                last_seq = max(last_seq, ev.seq)
                yield f"data: {json.dumps(ev.dict())}\n\n"

            state = event_store.rehydrate_run_state(run_id)
            if state and (state.terminal_outcome or state.status in ("DONE", "ESCALATED", "REJECTED_BY_POLICY", "FAILED")):
                yield f"data: {json.dumps({'event_type': 'STREAM_CLOSED', 'terminal_outcome': state.terminal_outcome.value if state.terminal_outcome else state.status})}\n\n"
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.get("/api/memory")
def get_memory_state():
    rules = memory.get_all_rules()
    return {
        "rules": [r.dict() for r in rules],
        "active_faults": get_faults()
    }


@app.get("/api/evals/report")
def get_evals_report():
    report_path = os.path.join(BASE_DIR, "evals", "report.md")
    if os.path.exists(report_path):
        with open(report_path, "r", encoding="utf-8") as f:
            return {"content": f.read()}
    return {"content": "Evaluation report not found."}


# --- Frontend Single-Page App (SPA) ---

@app.get("/", response_class=HTMLResponse)
def index_ui():
    with open(os.path.join(BASE_DIR, "ui", "index.html"), "r", encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.server:app", host="0.0.0.0", port=8080, reload=True)
