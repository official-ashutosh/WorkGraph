"""
LedgerOne mock ERP Database layer (SQLite).
Manages vendors, purchase orders, bills, and session state.
"""

import sqlite3
import json
import csv
import os
from typing import Optional, List, Dict, Any
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "ledgerone.db")
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data"))

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Vendors table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS vendors (
        vendor_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        contact_email TEXT,
        payment_terms TEXT,
        tax_id TEXT,
        status TEXT DEFAULT 'active',
        manager_approval_threshold REAL DEFAULT 5000.00
    )
    """)

    # Purchase Orders table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS purchase_orders (
        po_number TEXT PRIMARY KEY,
        vendor_id TEXT NOT NULL,
        vendor_name TEXT NOT NULL,
        total_amount REAL NOT NULL,
        currency TEXT DEFAULT 'USD',
        status TEXT DEFAULT 'APPROVED',
        items_json TEXT,
        created_at TEXT
    )
    """)

    # Bills table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        bill_id TEXT UNIQUE,
        vendor_id TEXT NOT NULL,
        vendor_name TEXT NOT NULL,
        invoice_number TEXT NOT NULL,
        po_number TEXT,
        issue_date TEXT NOT NULL,
        due_date TEXT NOT NULL,
        amount REAL NOT NULL,
        currency TEXT DEFAULT 'USD',
        line_items_json TEXT,
        status TEXT DEFAULT 'REGISTERED',
        idempotency_key TEXT UNIQUE,
        created_at TEXT NOT NULL
    )
    """)

    # Active Faults table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS fault_config (
        id INTEGER PRIMARY KEY,
        fault_name TEXT UNIQUE,
        enabled INTEGER DEFAULT 0,
        params_json TEXT
    )
    """)

    # Sessions table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        token TEXT PRIMARY KEY,
        username TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """)

    conn.commit()
    conn.close()

def seed_db():
    init_db()
    conn = get_db()
    cursor = conn.cursor()

    # Clear previous seed
    cursor.execute("DELETE FROM vendors")
    cursor.execute("DELETE FROM purchase_orders")

    # Load vendors from CSV
    vendors_csv = os.path.join(DATA_DIR, "vendors.csv")
    if os.path.exists(vendors_csv):
        with open(vendors_csv, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cursor.execute("""
                INSERT OR REPLACE INTO vendors (vendor_id, name, contact_email, payment_terms, tax_id, status, manager_approval_threshold)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    row["vendor_id"],
                    row["name"],
                    row["contact_email"],
                    row["payment_terms"],
                    row["tax_id"],
                    row.get("status", "active"),
                    float(row.get("manager_approval_threshold", 5000.00))
                ))

    # Load purchase orders from JSON
    po_json = os.path.join(DATA_DIR, "purchase_orders.json")
    if os.path.exists(po_json):
        with open(po_json, "r", encoding="utf-8") as f:
            pos = json.load(f)
            for po in pos:
                cursor.execute("""
                INSERT OR REPLACE INTO purchase_orders (po_number, vendor_id, vendor_name, total_amount, currency, status, items_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    po["po_number"],
                    po["vendor_id"],
                    po["vendor_name"],
                    float(po["total_amount"]),
                    po.get("currency", "USD"),
                    po.get("status", "APPROVED"),
                    json.dumps(po.get("items", [])),
                    datetime.now().isoformat()
                ))

    # Initialize default faults
    known_faults = [
        "timeout_after_commit",
        "fail_before_commit",
        "session_expire",
        "selector_drift",
        "date_format_error",
        "slow_load"
    ]
    for fault in known_faults:
        cursor.execute("""
        INSERT OR IGNORE INTO fault_config (fault_name, enabled, params_json)
        VALUES (?, 0, '{}')
        """, (fault,))

    conn.commit()
    conn.close()

def reset_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bills")
    cursor.execute("DELETE FROM sessions")
    cursor.execute("UPDATE fault_config SET enabled = 0, params_json = '{}'")
    conn.commit()
    conn.close()
    seed_db()

def get_faults() -> Dict[str, Any]:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT fault_name, enabled, params_json FROM fault_config")
    rows = cursor.fetchall()
    conn.close()
    result = {}
    for r in rows:
        result[r["fault_name"]] = {
            "enabled": bool(r["enabled"]),
            "params": json.loads(r["params_json"] or "{}")
        }
    return result

def set_fault(fault_name: str, enabled: bool, params: Optional[Dict] = None):
    conn = get_db()
    cursor = conn.cursor()
    params_str = json.dumps(params or {})
    cursor.execute("""
    INSERT INTO fault_config (fault_name, enabled, params_json)
    VALUES (?, ?, ?)
    ON CONFLICT(fault_name) DO UPDATE SET enabled = ?, params_json = ?
    """, (fault_name, 1 if enabled else 0, params_str, 1 if enabled else 0, params_str))
    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed_db()
    print("LedgerOne database initialized and seeded successfully.")
