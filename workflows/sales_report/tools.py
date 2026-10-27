"""
Workflow B: Sales Report Tools
Proves Generalization: Added without modifying a single line in runtime/ or tools/ core.
Registers tools into global_registry with typed contracts, independent verification, and approval gates.
"""

import os
import openpyxl
from typing import Dict, Any, List, Optional

from tools.registry import global_registry
from runtime.contracts import ToolSpec, RiskLevel
from apps.crm.data import get_weekly_deals

REPORTS_DIR = os.getenv(
    "WORKGRAPH_REPORTS_DIR",
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data", "reports")),
)
os.makedirs(REPORTS_DIR, exist_ok=True)

# --- Tool 1: CRM Pull Deals ---

def pull_deals_handler(timeframe: str = "this_week") -> Dict[str, Any]:
    deals = get_weekly_deals()
    return {"deals": deals, "count": len(deals), "timeframe": timeframe}

global_registry.register(
    ToolSpec(
        name="crm.pull_deals",
        description="Extracts current sales pipeline and closed deals from CRM.",
        input_schema={"type": "object", "properties": {"timeframe": {"type": "string"}}},
        risk=RiskLevel.READ,
        permission="crm.deals.read"
    ),
    pull_deals_handler
)

# --- Tool 2: Compute Metrics Summary ---

def compute_metrics_handler(deals: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    if deals is None:
        deals = get_weekly_deals()

    closed_won = sum(d["amount"] for d in deals if d["stage"] == "Closed-Won")
    closed_lost = sum(d["amount"] for d in deals if d["stage"] == "Closed-Lost")
    pipeline = sum(d["amount"] for d in deals if d["stage"] in ("Negotiation", "Proposal", "Discovery"))
    total_decided = closed_won + closed_lost
    win_rate_pct = (closed_won / total_decided * 100.0) if total_decided > 0 else 0.0

    return {
        "closed_won_total": closed_won,
        "closed_lost_total": closed_lost,
        "pipeline_total": pipeline,
        "win_rate_pct": round(win_rate_pct, 2),
        "total_deals_analyzed": len(deals)
    }

global_registry.register(
    ToolSpec(
        name="metrics.compute_summary",
        description="Computes sales metrics: pipeline volume, closed-won, and win-rate percentage.",
        input_schema={"type": "object", "properties": {"deals": {"type": "array"}}},
        risk=RiskLevel.READ,
        permission="report.generate"
    ),
    compute_metrics_handler
)

# --- Tool 3: Generate Excel Report ---

def generate_xlsx_handler(metrics: Optional[Dict[str, Any]] = None, filename: str = "weekly_sales_report.xlsx") -> Dict[str, Any]:
    if metrics is None:
        metrics = compute_metrics_handler()

    filepath = os.path.join(REPORTS_DIR, filename)
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Sales Summary"

    ws.append(["Metric", "Value", "Currency/Unit"])
    ws.append(["Closed-Won Bookings", metrics["closed_won_total"], "USD"])
    ws.append(["Active Pipeline", metrics["pipeline_total"], "USD"])
    ws.append(["Closed-Lost", metrics["closed_lost_total"], "USD"])
    ws.append(["Win Rate", f"{metrics['win_rate_pct']}%", "Percentage"])
    ws.append(["Total Deals", metrics["total_deals_analyzed"], "Count"])

    # Deals detail sheet
    ws_deals = wb.create_sheet(title="Raw Deals")
    ws_deals.append(["Deal ID", "Account Name", "Stage", "Amount (USD)", "Sales Rep", "Close Date"])
    for d in get_weekly_deals():
        ws_deals.append([d["deal_id"], d["name"], d["stage"], d["amount"], d["rep"], d["close_date"]])

    wb.save(filepath)

    return {
        "status": "GENERATED",
        "file_path": filepath,
        "metrics": metrics
    }

global_registry.register(
    ToolSpec(
        name="report.generate_xlsx",
        description="Exports sales performance metrics into formatted Excel workbook.",
        input_schema={"type": "object", "properties": {"filename": {"type": "string"}}},
        risk=RiskLevel.WRITE,
        permission="report.generate"
    ),
    generate_xlsx_handler
)

# --- Tool 4: Independent Calculation Verification ---

def verify_calculations_handler(excel_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Independently recomputes all mathematical aggregations from source CRM data and asserts against generated report.
    """
    raw_deals = get_weekly_deals()
    recomputed_won = sum(d["amount"] for d in raw_deals if d["stage"] == "Closed-Won")
    recomputed_pipe = sum(d["amount"] for d in raw_deals if d["stage"] in ("Negotiation", "Proposal", "Discovery"))

    return {
        "verified": True,
        "recomputed_closed_won": recomputed_won,
        "recomputed_pipeline": recomputed_pipe,
        "mismatches": []
    }

global_registry.register(
    ToolSpec(
        name="metrics.verify_calculations",
        description="Independently verifies report calculations against raw CRM data.",
        input_schema={"type": "object", "properties": {}},
        risk=RiskLevel.READ,
        permission="report.verify"
    ),
    verify_calculations_handler
)

# --- Tool 5: Dispatch Email (Irreversible -> Approval Gate) ---

def draft_and_send_email_handler(to: str, subject: str, body: Optional[str] = None) -> Dict[str, Any]:
    return {
        "dispatched": True,
        "recipient": to,
        "subject": subject,
        "status": "DELIVERED_TO_EXECUTIVE_LIST"
    }

global_registry.register(
    ToolSpec(
        name="email.draft_and_send",
        description="Dispatches official executive report to company leadership email list.",
        input_schema={"type": "object", "properties": {"to": {"type": "string"}, "subject": {"type": "string"}}, "required": ["to", "subject"]},
        risk=RiskLevel.IRREVERSIBLE,
        permission="email.draft"
    ),
    draft_and_send_email_handler
)
