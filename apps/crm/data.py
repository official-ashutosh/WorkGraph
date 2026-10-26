"""
Mock CRM Data for Workflow B (Generalization Proof)
Weekly sales pipeline and closed deals data.
"""

from typing import List, Dict, Any

SEED_DEALS: List[Dict[str, Any]] = [
    {"deal_id": "DEAL-501", "name": "Acme Industrial IoT Expansion", "stage": "Closed-Won", "amount": 85000.0, "rep": "Sarah Chen", "close_date": "2026-10-22"},
    {"deal_id": "DEAL-502", "name": "BlueSky Retail Analytics", "stage": "Closed-Won", "amount": 42000.0, "rep": "Marcus Vance", "close_date": "2026-10-23"},
    {"deal_id": "DEAL-503", "name": "Pinnacle Financial Security Suite", "stage": "Negotiation", "amount": 120000.0, "rep": "Sarah Chen", "close_date": "2026-10-28"},
    {"deal_id": "DEAL-504", "name": "Horizon Health Telehealth Stack", "stage": "Proposal", "amount": 65000.0, "rep": "Elena Rostova", "close_date": "2026-10-30"},
    {"deal_id": "DEAL-505", "name": "Vertex Logistics Route AI", "stage": "Closed-Lost", "amount": 35000.0, "rep": "Marcus Vance", "close_date": "2026-10-21"},
    {"deal_id": "DEAL-506", "name": "Nexus Energy Smart Grid", "stage": "Closed-Won", "amount": 95000.0, "rep": "Elena Rostova", "close_date": "2026-10-24"}
]

def get_weekly_deals() -> List[Dict[str, Any]]:
    return list(SEED_DEALS)
