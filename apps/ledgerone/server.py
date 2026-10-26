"""
LedgerOne - Self-hosted Mock Enterprise Finance ERP
Built for WorkGraph: Autonomous browser execution, fault injection, and verification.
"""

import os
import time
import uuid
import json
import hashlib
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import FastAPI, Request, Form, Response, Cookie, HTTPException, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from apps.ledgerone.database import get_db, init_db, seed_db, reset_db, get_faults, set_fault

app = FastAPI(title="LedgerOne ERP", version="1.0.0")

# Ensure DB initialized on module import
init_db()

# --- Helpers ---

def get_current_user(session_token: Optional[str] = Cookie(None)):
    if not session_token:
        return None
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT username FROM sessions WHERE token = ? AND expires_at > ?", 
                   (session_token, datetime.now().isoformat()))
    row = cursor.fetchone()
    conn.close()
    return row["username"] if row else None

def compute_bill_hash(vendor_id: str, invoice_number: str, amount: float, issue_date: str) -> str:
    raw = f"{vendor_id}|{invoice_number}|{amount:.2f}|{issue_date}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]

# --- HTML Templates (Single-file Styled with Modern Tailwind-style CSS) ---

def render_shell(title: str, content: str, user: Optional[str] = None, active_nav: str = "") -> HTMLResponse:
    nav_links = [
        ("/dashboard", "Dashboard", "dashboard"),
        ("/bills", "Bills & Payables", "bills"),
        ("/purchase_orders", "Purchase Orders", "pos"),
        ("/vendors", "Approved Vendors", "vendors"),
    ]
    
    links_html = "".join([
        f'<a href="{url}" class="px-3 py-2 rounded-md text-sm font-medium transition-colors { "bg-blue-700 text-white" if active_nav == key else "text-slate-300 hover:bg-slate-800 hover:text-white" }">{label}</a>'
        for url, label, key in nav_links
    ])
    
    user_section = ""
    if user:
        user_section = f'''
        <div class="flex items-center space-x-3">
            <span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-900/60 text-emerald-300 border border-emerald-500/30">
                ● Live: {user}
            </span>
            <a href="/logout" class="text-xs text-slate-400 hover:text-red-400">Logout</a>
        </div>
        '''
    else:
        user_section = '<a href="/login" class="text-sm text-blue-400 hover:underline">Login</a>'

    # Check active faults to show banner if any are active
    faults = get_faults()
    active_faults = [k for k, v in faults.items() if v.get("enabled")]
    fault_banner = ""
    if active_faults:
        fault_banner = f'''
        <div class="bg-amber-950/80 border-b border-amber-600/50 px-4 py-2 text-xs text-amber-200 flex items-center justify-between">
            <div>
                <span class="font-bold">⚠️ ACTIVE FAULT INJECTION:</span> {", ".join(active_faults)}
            </div>
            <button onclick="fetch('/__reset', {{method:'POST'}}).then(()=>location.reload())" class="underline text-amber-300 hover:text-white ml-4">
                Clear Faults
            </button>
        </div>
        '''

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - LedgerOne ERP</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ background-color: #0b1120; color: #f1f5f9; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
    </style>
</head>
<body class="min-h-screen flex flex-col">
    {fault_banner}
    <nav class="bg-slate-900/90 backdrop-blur border-b border-slate-800 sticky top-0 z-50">
        <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
            <div class="flex items-center justify-between h-16">
                <div class="flex items-center space-x-6">
                    <a href="/" class="flex items-center space-x-2">
                        <span class="text-2xl font-black bg-gradient-to-r from-blue-400 to-indigo-400 bg-clip-text text-transparent">LedgerOne</span>
                        <span class="text-xs uppercase tracking-widest text-slate-400 font-mono">ERP v2.6</span>
                    </a>
                    <div class="hidden md:flex space-x-2">
                        {links_html}
                    </div>
                </div>
                <div>{user_section}</div>
            </div>
        </div>
    </nav>

    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {content}
    </main>

    <footer class="bg-slate-950 border-t border-slate-800/80 py-4 text-center text-xs text-slate-500">
        LedgerOne Financial Operating System &bull; CentrAlign Evaluation System &bull; Strict Deterministic Audit
    </footer>
</body>
</html>"""
    return HTMLResponse(html)

# --- Routes ---

@app.get("/")
def index(request: Request, user: Optional[str] = Cookie(None, alias="session_token")):
    if not get_current_user(user):
        return RedirectResponse("/login")
    return RedirectResponse("/dashboard")

@app.get("/login")
def login_page(expired: Optional[int] = 0, error: Optional[str] = None):
    expired_alert = ""
    if expired:
        expired_alert = """
        <div class="mb-4 p-3 bg-red-950/70 border border-red-500/40 rounded-lg text-red-200 text-sm">
            Session expired or terminated by system policy. Please log in again.
        </div>
        """
    err_alert = ""
    if error:
        err_alert = f"""
        <div class="mb-4 p-3 bg-red-950/70 border border-red-500/40 rounded-lg text-red-200 text-sm">
            {error}
        </div>
        """
        
    content = f"""
    <div class="max-w-md mx-auto mt-12 bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-2xl">
        <div class="text-center mb-6">
            <h1 class="text-2xl font-bold text-white">Sign in to LedgerOne</h1>
            <p class="text-sm text-slate-400 mt-1">Enterprise Finance & Accounts Payable</p>
        </div>
        {expired_alert}
        {err_alert}
        <form action="/login" method="POST" class="space-y-4">
            <div>
                <label class="block text-xs font-semibold uppercase text-slate-400 mb-1" for="username">Username</label>
                <input id="username" name="username" type="text" value="admin" required
                       class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500">
            </div>
            <div>
                <label class="block text-xs font-semibold uppercase text-slate-400 mb-1" for="password">Password</label>
                <input id="password" name="password" type="password" value="ledger2026" required
                       class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500">
            </div>
            <button id="login-submit-btn" type="submit" 
                    class="w-full py-2.5 px-4 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-lg shadow-lg transition-all">
                Authenticate & Enter
            </button>
        </form>
        <div class="mt-6 text-center text-xs text-slate-500">
            Default credentials: <code class="text-slate-300 font-mono">admin</code> / <code class="text-slate-300 font-mono">ledger2026</code>
        </div>
    </div>
    """
    return render_shell("Login", content)

@app.post("/login")
def do_login(response: Response, username: str = Form(...), password: str = Form(...)):
    if username == "admin" and password == "ledger2026":
        token = str(uuid.uuid4())
        expires = (datetime.now() + timedelta(hours=8)).isoformat()
        
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO sessions (token, username, expires_at) VALUES (?, ?, ?)", (token, username, expires))
        conn.commit()
        conn.close()

        resp = RedirectResponse("/dashboard", status_code=303)
        resp.set_cookie("session_token", token, httponly=True, max_age=28800)
        return resp
    else:
        return RedirectResponse("/login?error=Invalid+credentials", status_code=303)

@app.get("/logout")
def logout(response: Response, session_token: Optional[str] = Cookie(None)):
    if session_token:
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE token = ?", (session_token,))
        conn.commit()
        conn.close()
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie("session_token")
    return resp

@app.get("/dashboard")
def dashboard(session_token: Optional[str] = Cookie(None)):
    user = get_current_user(session_token)
    if not user:
        return RedirectResponse("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) as count FROM bills")
    bills_count = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM purchase_orders")
    pos_count = cursor.fetchone()["count"]
    cursor.execute("SELECT COUNT(*) as count FROM vendors")
    vendors_count = cursor.fetchone()["count"]
    cursor.execute("SELECT SUM(amount) as total FROM bills")
    total_val = cursor.fetchone()["total"] or 0.0
    conn.close()

    content = f"""
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <div>
                <h1 class="text-3xl font-extrabold text-white">Executive AP Dashboard</h1>
                <p class="text-sm text-slate-400 mt-1">Autonomous Accounts Payable & Financial Controls</p>
            </div>
            <a href="/bills/create" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg shadow transition">
                + Register New Bill
            </a>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-4 gap-4">
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-xl">
                <span class="text-xs uppercase font-semibold text-slate-400">Total Bills Recorded</span>
                <div class="text-3xl font-bold text-white mt-2">{bills_count}</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-xl">
                <span class="text-xs uppercase font-semibold text-slate-400">Total Value Registered</span>
                <div class="text-3xl font-bold text-emerald-400 mt-2">${total_val:,.2f}</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-xl">
                <span class="text-xs uppercase font-semibold text-slate-400">Open Purchase Orders</span>
                <div class="text-3xl font-bold text-indigo-400 mt-2">{pos_count}</div>
            </div>
            <div class="bg-slate-900 border border-slate-800 p-5 rounded-xl">
                <span class="text-xs uppercase font-semibold text-slate-400">Approved Vendors</span>
                <div class="text-3xl font-bold text-purple-400 mt-2">{vendors_count}</div>
            </div>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-xl p-6">
            <h2 class="text-lg font-bold text-white mb-4">Quick Operations & Live Diagnostics</h2>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-4">
                <a href="/bills" class="p-4 bg-slate-950 hover:bg-slate-800/80 border border-slate-800 rounded-lg block transition">
                    <div class="font-semibold text-white">Browse Bills</div>
                    <div class="text-xs text-slate-400 mt-1">View registered payables, proof hashes, and invoice details.</div>
                </a>
                <a href="/purchase_orders" class="p-4 bg-slate-950 hover:bg-slate-800/80 border border-slate-800 rounded-lg block transition">
                    <div class="font-semibold text-white">Inspect Purchase Orders</div>
                    <div class="text-xs text-slate-400 mt-1">Check approved amounts and line items for 2% variance checks.</div>
                </a>
                <a href="/vendors" class="p-4 bg-slate-950 hover:bg-slate-800/80 border border-slate-800 rounded-lg block transition">
                    <div class="font-semibold text-white">Vendor Directory</div>
                    <div class="text-xs text-slate-400 mt-1">Approved vendor IDs, payment terms, and manager thresholds.</div>
                </a>
            </div>
        </div>
    </div>
    """
    return render_shell("Dashboard", content, user=user, active_nav="dashboard")

@app.get("/bills")
def bills_list(session_token: Optional[str] = Cookie(None)):
    user = get_current_user(session_token)
    if not user:
        return RedirectResponse("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bills ORDER BY id DESC")
    bills = cursor.fetchall()
    conn.close()

    rows_html = ""
    for b in bills:
        rows_html += f"""
        <tr class="border-b border-slate-800/80 hover:bg-slate-800/40">
            <td class="px-4 py-3 font-mono text-xs text-blue-400"><a href="/bills/{b['bill_id']}" class="hover:underline">{b['bill_id']}</a></td>
            <td class="px-4 py-3 font-medium text-white">{b['vendor_name']} <span class="text-xs text-slate-500">({b['vendor_id']})</span></td>
            <td class="px-4 py-3 font-mono text-sm">{b['invoice_number']}</td>
            <td class="px-4 py-3 font-mono text-xs text-slate-400">{b['po_number'] or 'N/A'}</td>
            <td class="px-4 py-3 text-right font-semibold text-emerald-400">${b['amount']:,.2f}</td>
            <td class="px-4 py-3 text-xs text-slate-400">{b['issue_date']}</td>
            <td class="px-4 py-3 text-xs text-slate-400">{b['due_date']}</td>
            <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded text-xs font-semibold bg-emerald-950 border border-emerald-600/40 text-emerald-300">
                    {b['status']}
                </span>
            </td>
        </tr>
        """
        
    if not bills:
        rows_html = '<tr><td colspan="8" class="text-center py-8 text-slate-500">No bills currently registered.</td></tr>'

    content = f"""
    <div class="space-y-6">
        <div class="flex items-center justify-between">
            <div>
                <h1 class="text-2xl font-bold text-white">Registered Bills & Payables</h1>
                <p class="text-sm text-slate-400">All posted liabilities committed to the system of record</p>
            </div>
            <a href="/bills/create" class="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white font-medium rounded-lg shadow transition">
                + Register New Bill
            </a>
        </div>

        <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow">
            <table class="w-full text-left text-sm text-slate-300">
                <thead class="bg-slate-950 text-xs uppercase text-slate-400 border-b border-slate-800">
                    <tr>
                        <th class="px-4 py-3">Bill ID</th>
                        <th class="px-4 py-3">Vendor</th>
                        <th class="px-4 py-3">Invoice #</th>
                        <th class="px-4 py-3">PO #</th>
                        <th class="px-4 py-3 text-right">Amount (USD)</th>
                        <th class="px-4 py-3">Issue Date</th>
                        <th class="px-4 py-3">Due Date</th>
                        <th class="px-4 py-3">Status</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </div>
    </div>
    """
    return render_shell("Bills", content, user=user, active_nav="bills")

@app.get("/bills/create")
def create_bill_page(session_token: Optional[str] = Cookie(None)):
    user = get_current_user(session_token)
    if not user:
        return RedirectResponse("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT vendor_id, name FROM vendors WHERE status = 'active' ORDER BY name")
    vendors = cursor.fetchall()
    cursor.execute("SELECT po_number, vendor_id, total_amount FROM purchase_orders ORDER BY po_number")
    pos = cursor.fetchall()
    conn.close()

    # Check for selector drift fault!
    faults = get_faults()
    has_selector_drift = faults.get("selector_drift", {}).get("enabled", False)

    if has_selector_drift:
        # Selector drift! Changed button ID and label to test fallback reasoning
        btn_id = "btn-execute-record-posting-v2"
        btn_label = "Commit & Post Transaction"
        drift_notice = """
        <div class="p-3 bg-amber-950/60 border border-amber-500/40 rounded-lg text-amber-300 text-xs mb-4">
            <b>Note:</b> UI Selector Drift active: Form submit button has altered ID and label.
        </div>
        """
    else:
        btn_id = "submit-bill-btn"
        btn_label = "Register Bill"
        drift_notice = ""

    vendor_options = "".join([f'<option value="{v["vendor_id"]}">{v["name"]} ({v["vendor_id"]})</option>' for v in vendors])
    po_options = '<option value="">-- No PO (Direct Expense) --</option>' + "".join([
        f'<option value="{p["po_number"]}">{p["po_number"]} - ${p["total_amount"]:,.2f} ({p["vendor_id"]})</option>' for p in pos
    ])

    content = f"""
    <div class="max-w-2xl mx-auto bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-xl">
        <div class="mb-6">
            <h1 class="text-2xl font-bold text-white">Create & Register Bill</h1>
            <p class="text-sm text-slate-400">Post an approved vendor invoice into the general ledger</p>
        </div>
        {drift_notice}
        <form action="/bills/create" method="POST" class="space-y-4">
            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-xs font-semibold uppercase text-slate-400 mb-1" for="vendor_id">Vendor *</label>
                    <select id="vendor_id" name="vendor_id" required
                            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500">
                        {vendor_options}
                    </select>
                </div>
                <div>
                    <label class="block text-xs font-semibold uppercase text-slate-400 mb-1" for="invoice_number">Invoice Number *</label>
                    <input id="invoice_number" name="invoice_number" type="text" required placeholder="e.g. INV-2026-101"
                           class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500">
                </div>
            </div>

            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-xs font-semibold uppercase text-slate-400 mb-1" for="po_number">Purchase Order</label>
                    <select id="po_number" name="po_number"
                            class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500">
                        {po_options}
                    </select>
                </div>
                <div>
                    <label class="block text-xs font-semibold uppercase text-slate-400 mb-1" for="amount">Total Amount (USD) *</label>
                    <input id="amount" name="amount" type="number" step="0.01" min="0.01" required placeholder="1250.00"
                           class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500 font-mono">
                </div>
            </div>

            <div class="grid grid-cols-2 gap-4">
                <div>
                    <label class="block text-xs font-semibold uppercase text-slate-400 mb-1" for="issue_date">Issue Date *</label>
                    <input id="issue_date" name="issue_date" type="date" required
                           class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500">
                </div>
                <div>
                    <label class="block text-xs font-semibold uppercase text-slate-400 mb-1" for="due_date">Due Date *</label>
                    <input id="due_date" name="due_date" type="date" required
                           class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500">
                </div>
            </div>

            <div>
                <label class="block text-xs font-semibold uppercase text-slate-400 mb-1" for="line_items_desc">Line Item Description / Notes</label>
                <textarea id="line_items_desc" name="line_items_desc" rows="2" placeholder="Itemized goods or services description..."
                          class="w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-lg text-white focus:outline-none focus:border-blue-500 text-sm"></textarea>
            </div>

            <div class="pt-4 flex items-center justify-end space-x-3">
                <a href="/bills" class="px-4 py-2 border border-slate-700 text-slate-300 rounded-lg hover:bg-slate-800 transition">Cancel</a>
                <button id="{btn_id}" type="submit"
                        class="px-5 py-2.5 bg-blue-600 hover:bg-blue-500 text-white font-semibold rounded-lg shadow-lg transition">
                    {btn_label}
                </button>
            </div>
        </form>
    </div>
    """
    return render_shell("Create Bill", content, user=user, active_nav="bills")

@app.post("/bills/create")
def do_create_bill(
    vendor_id: str = Form(...),
    invoice_number: str = Form(...),
    po_number: Optional[str] = Form(None),
    amount: float = Form(...),
    issue_date: str = Form(...),
    due_date: str = Form(...),
    line_items_desc: Optional[str] = Form(""),
    session_token: Optional[str] = Cookie(None)
):
    # Check session auth
    user = get_current_user(session_token)
    faults = get_faults()

    # Fault: session_expire
    if faults.get("session_expire", {}).get("enabled"):
        # Expire session mid-request and clear fault
        set_fault("session_expire", False)
        if session_token:
            conn = get_db()
            conn.cursor().execute("DELETE FROM sessions WHERE token = ?", (session_token,))
            conn.commit()
            conn.close()
        raise HTTPException(status_code=401, detail="Session expired during transaction")

    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")

    # Fault: slow_load
    if faults.get("slow_load", {}).get("enabled"):
        time.sleep(3.0)

    # Fault: fail_before_commit
    if faults.get("fail_before_commit", {}).get("enabled"):
        set_fault("fail_before_commit", False)  # Single-shot fault
        raise HTTPException(status_code=500, detail="Database deadlocked before transaction commit. Nothing was written.")

    conn = get_db()
    cursor = conn.cursor()

    # Lookup vendor
    cursor.execute("SELECT name FROM vendors WHERE vendor_id = ?", (vendor_id,))
    v_row = cursor.fetchone()
    vendor_name = v_row["name"] if v_row else "Unknown Vendor"

    # Precheck Duplicate: invoice_number + vendor_id must be unique
    idempotency_key = f"{vendor_id}:{invoice_number}:{amount:.2f}"
    cursor.execute("SELECT bill_id FROM bills WHERE vendor_id = ? AND invoice_number = ?", (vendor_id, invoice_number))
    existing = cursor.fetchone()
    if existing:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Duplicate invoice rejection: Bill {existing['bill_id']} already exists for vendor {vendor_id} and invoice {invoice_number}")

    # Generate bill ID
    bill_id = f"BILL-{uuid.uuid4().hex[:8].upper()}"
    created_at = datetime.now().isoformat()

    # Commit to DB
    cursor.execute("""
    INSERT INTO bills (bill_id, vendor_id, vendor_name, invoice_number, po_number, issue_date, due_date, amount, currency, line_items_json, status, idempotency_key, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'USD', ?, 'REGISTERED', ?, ?)
    """, (
        bill_id,
        vendor_id,
        vendor_name,
        invoice_number,
        po_number or None,
        issue_date,
        due_date,
        amount,
        json.dumps([{"desc": line_items_desc, "amount": amount}]),
        idempotency_key,
        created_at
    ))
    conn.commit()
    conn.close()

    # Fault: timeout_after_commit
    # THE WRITE COMMITTED, but the response hangs or drops!
    if faults.get("timeout_after_commit", {}).get("enabled"):
        set_fault("timeout_after_commit", False)  # Single-shot
        # Simulating gateway timeout 504
        raise HTTPException(status_code=504, detail="Gateway 504 Timeout: Upstream response timed out after database commit.")

    return RedirectResponse(f"/bills/{bill_id}?created=1", status_code=303)

@app.get("/bills/{bill_id}")
def view_bill(bill_id: str, created: Optional[int] = 0, session_token: Optional[str] = Cookie(None)):
    user = get_current_user(session_token)
    if not user:
        return RedirectResponse("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bills WHERE bill_id = ?", (bill_id,))
    bill = cursor.fetchone()
    conn.close()

    if not bill:
        raise HTTPException(status_code=404, detail="Bill not found")

    created_banner = ""
    if created:
        created_banner = """
        <div class="mb-4 p-4 bg-emerald-950/80 border border-emerald-500/40 rounded-xl text-emerald-200 text-sm flex items-center justify-between">
            <div><b>Success:</b> Bill successfully committed to ledger and verified.</div>
            <span class="text-xs font-mono bg-emerald-900/90 px-2 py-0.5 rounded">STATUS: COMMITTED</span>
        </div>
        """

    proof_hash = compute_bill_hash(bill["vendor_id"], bill["invoice_number"], bill["amount"], bill["issue_date"])

    content = f"""
    <div class="max-w-3xl mx-auto space-y-6">
        {created_banner}
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-8 shadow-xl">
            <div class="flex items-center justify-between border-b border-slate-800 pb-5 mb-5">
                <div>
                    <span class="text-xs font-mono text-slate-400">LEDGER RECORD ID</span>
                    <h1 class="text-3xl font-black text-white font-mono mt-0.5" id="record-bill-id">{bill['bill_id']}</h1>
                </div>
                <div class="text-right">
                    <span class="px-3 py-1 bg-emerald-950 border border-emerald-500/40 text-emerald-300 font-semibold rounded-full text-xs">
                        {bill['status']}
                    </span>
                    <div class="text-xs text-slate-500 mt-1 font-mono">{bill['created_at']}</div>
                </div>
            </div>

            <div class="grid grid-cols-2 gap-6 text-sm mb-6">
                <div>
                    <span class="text-xs uppercase text-slate-400 font-semibold">Vendor</span>
                    <div class="font-bold text-white text-base mt-0.5" id="record-vendor-name">{bill['vendor_name']}</div>
                    <div class="text-xs font-mono text-slate-400" id="record-vendor-id">{bill['vendor_id']}</div>
                </div>
                <div>
                    <span class="text-xs uppercase text-slate-400 font-semibold">Total Amount</span>
                    <div class="font-black text-emerald-400 text-2xl font-mono mt-0.5" id="record-amount">${bill['amount']:,.2f} USD</div>
                </div>
            </div>

            <div class="grid grid-cols-3 gap-4 p-4 bg-slate-950 border border-slate-800 rounded-lg text-xs font-mono mb-6">
                <div>
                    <span class="text-slate-500 block uppercase">Invoice Number</span>
                    <span class="text-slate-200 font-bold" id="record-invoice-num">{bill['invoice_number']}</span>
                </div>
                <div>
                    <span class="text-slate-500 block uppercase">PO Number</span>
                    <span class="text-slate-200 font-bold" id="record-po-num">{bill['po_number'] or 'N/A'}</span>
                </div>
                <div>
                    <span class="text-slate-500 block uppercase">Due Date</span>
                    <span class="text-slate-200 font-bold" id="record-due-date">{bill['due_date']}</span>
                </div>
            </div>

            <div class="p-4 bg-slate-950/60 border border-slate-800/80 rounded-lg text-xs font-mono text-slate-400">
                <div class="flex items-center justify-between">
                    <span class="text-slate-500">Cryptographic State Hash:</span>
                    <span class="text-indigo-400 font-mono" id="record-proof-hash">{proof_hash}</span>
                </div>
                <div class="flex items-center justify-between mt-1">
                    <span class="text-slate-500">Idempotency Key:</span>
                    <span class="text-slate-300 font-mono">{bill['idempotency_key']}</span>
                </div>
            </div>

            <div class="mt-6 flex justify-between items-center pt-4 border-t border-slate-800">
                <a href="/bills" class="text-sm text-slate-400 hover:text-white">&larr; Back to Bills List</a>
                <a href="/api/bills/{bill['bill_id']}" target="_blank" class="text-xs text-blue-400 hover:underline font-mono">
                    View Verification JSON &rarr;
                </a>
            </div>
        </div>
    </div>
    """
    return render_shell(f"Bill {bill['bill_id']}", content, user=user, active_nav="bills")

@app.get("/vendors")
def vendors_list(session_token: Optional[str] = Cookie(None)):
    user = get_current_user(session_token)
    if not user:
        return RedirectResponse("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vendors ORDER BY name")
    vendors = cursor.fetchall()
    conn.close()

    rows = ""
    for v in vendors:
        rows += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-800/40">
            <td class="px-4 py-3 font-mono text-xs text-blue-400">{v['vendor_id']}</td>
            <td class="px-4 py-3 font-bold text-white">{v['name']}</td>
            <td class="px-4 py-3 text-xs text-slate-300">{v['contact_email']}</td>
            <td class="px-4 py-3 text-xs font-mono text-slate-300">{v['payment_terms']}</td>
            <td class="px-4 py-3 text-xs font-mono text-slate-400">{v['tax_id']}</td>
            <td class="px-4 py-3 text-xs text-right font-mono">${v['manager_approval_threshold']:,.2f}</td>
            <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded text-xs bg-emerald-950 border border-emerald-600/40 text-emerald-300 uppercase">
                    {v['status']}
                </span>
            </td>
        </tr>
        """

    content = f"""
    <div class="space-y-6">
        <div>
            <h1 class="text-2xl font-bold text-white">Corporate Approved Vendors</h1>
            <p class="text-sm text-slate-400">Master vendor directory, terms, and approval authorization thresholds</p>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow">
            <table class="w-full text-left text-sm text-slate-300">
                <thead class="bg-slate-950 text-xs uppercase text-slate-400 border-b border-slate-800">
                    <tr>
                        <th class="px-4 py-3">Vendor ID</th>
                        <th class="px-4 py-3">Name</th>
                        <th class="px-4 py-3">Email</th>
                        <th class="px-4 py-3">Payment Terms</th>
                        <th class="px-4 py-3">Tax ID</th>
                        <th class="px-4 py-3 text-right">Approval Threshold</th>
                        <th class="px-4 py-3">Status</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return render_shell("Vendors", content, user=user, active_nav="vendors")

@app.get("/purchase_orders")
def pos_list(session_token: Optional[str] = Cookie(None)):
    user = get_current_user(session_token)
    if not user:
        return RedirectResponse("/login")
        
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM purchase_orders ORDER BY po_number")
    pos = cursor.fetchall()
    conn.close()

    rows = ""
    for p in pos:
        items = json.loads(p["items_json"] or "[]")
        items_summary = ", ".join([f"{it.get('description')} (x{it.get('quantity')})" for it in items])
        rows += f"""
        <tr class="border-b border-slate-800 hover:bg-slate-800/40">
            <td class="px-4 py-3 font-mono text-xs text-blue-400 font-bold">{p['po_number']}</td>
            <td class="px-4 py-3 text-white font-medium">{p['vendor_name']} <span class="text-xs text-slate-500">({p['vendor_id']})</span></td>
            <td class="px-4 py-3 text-right font-mono font-bold text-emerald-400">${p['total_amount']:,.2f}</td>
            <td class="px-4 py-3 text-xs text-slate-400">{items_summary}</td>
            <td class="px-4 py-3">
                <span class="px-2 py-0.5 rounded text-xs bg-indigo-950 border border-indigo-600/40 text-indigo-300 uppercase">
                    {p['status']}
                </span>
            </td>
        </tr>
        """

    content = f"""
    <div class="space-y-6">
        <div>
            <h1 class="text-2xl font-bold text-white">Purchase Orders (Open & Approved)</h1>
            <p class="text-sm text-slate-400">Baseline authorization POs for invoice matching and 2% variance checks</p>
        </div>
        <div class="bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow">
            <table class="w-full text-left text-sm text-slate-300">
                <thead class="bg-slate-950 text-xs uppercase text-slate-400 border-b border-slate-800">
                    <tr>
                        <th class="px-4 py-3">PO Number</th>
                        <th class="px-4 py-3">Vendor</th>
                        <th class="px-4 py-3 text-right">Approved Amount</th>
                        <th class="px-4 py-3">Line Items</th>
                        <th class="px-4 py-3">Status</th>
                    </tr>
                </thead>
                <tbody>{rows}</tbody>
            </table>
        </div>
    </div>
    """
    return render_shell("Purchase Orders", content, user=user, active_nav="pos")

# --- JSON REST APIs for Independent Verifier & Runtime Prechecks ---

@app.get("/api/bills/check")
def api_check_bill(vendor_id: str, invoice_number: str):
    """
    Precheck API: Checks if a bill already exists in LedgerOne.
    Used by the Guard and Uncertain-State Reconciler.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT bill_id, vendor_id, invoice_number, amount, created_at, status FROM bills WHERE vendor_id = ? AND invoice_number = ?", 
                   (vendor_id, invoice_number))
    row = cursor.fetchone()
    conn.close()
    if row:
        return {
            "exists": True,
            "bill": dict(row)
        }
    return {"exists": False, "bill": None}

@app.get("/api/bills/{bill_id}")
def api_get_bill(bill_id: str):
    """
    Independent Verification API: Read-back record directly from database.
    """
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bills WHERE bill_id = ?", (bill_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        raise HTTPException(status_code=404, detail="Bill not found")
    data = dict(row)
    data["proof_hash"] = compute_bill_hash(data["vendor_id"], data["invoice_number"], data["amount"], data["issue_date"])
    return data

@app.get("/api/bills")
def api_list_bills():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM bills ORDER BY id DESC")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/vendors")
def api_list_vendors():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM vendors")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

@app.get("/api/purchase_orders")
def api_list_pos():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM purchase_orders")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

# --- Fault Injection & Admin Control Endpoints ---

@app.get("/__faults")
def get_fault_config():
    return get_faults()

@app.post("/__faults")
async def configure_faults(request: Request):
    data = await request.json()
    for fault_name, conf in data.items():
        if isinstance(conf, bool):
            set_fault(fault_name, conf)
        elif isinstance(conf, dict):
            set_fault(fault_name, conf.get("enabled", True), conf.get("params"))
    return {"status": "ok", "faults": get_faults()}

@app.post("/__reset")
def reset_environment():
    reset_db()
    return {"status": "reset_successful", "bills_count": 0}
