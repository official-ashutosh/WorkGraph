"""
WorkGraph 1-Click Interactive Demo Launcher
Starts both:
1. LedgerOne Mock ERP on http://127.0.0.1:8000
2. WorkGraph Control Plane & Live UI on http://127.0.0.1:8080
Automatically opens the browser and displays interactive demo instructions.
"""

import sys
import os

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

import time
import webbrowser
import threading
import uvicorn

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from apps.ledgerone.database import seed_db
from apps.ledgerone.server import app as ledgerone_app
from api.server import app as workgraph_app


try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

def start_ledgerone():
    uvicorn.run(ledgerone_app, host="127.0.0.1", port=8000, log_level="warning")


def start_workgraph():
    uvicorn.run(workgraph_app, host="127.0.0.1", port=8080, log_level="warning")


def main():
    print("=" * 75)
    print(" [WORKGRAPH: COMPANY-AWARE AI EMPLOYEE RUNTIME]")
    print(" 'The LLM proposes. Deterministic code authorizes, executes & verifies.'")
    print("=" * 75)

    print("\n[1/3] Initializing LedgerOne ERP SQLite Database...")
    seed_db()
    print("      [OK] Database seeded with approved vendors and purchase orders.")

    print("\n[2/3] Launching background servers...")
    # Start LedgerOne server on port 8000
    t1 = threading.Thread(target=start_ledgerone, daemon=True)
    t1.start()
    print("      [OK] LedgerOne ERP active on http://127.0.0.1:8000")

    # Start WorkGraph server on port 8080
    t2 = threading.Thread(target=start_workgraph, daemon=True)
    t2.start()
    print("      [OK] WorkGraph UI active on http://127.0.0.1:8080")

    time.sleep(1.2)

    print("\n[3/3] Opening Interactive Control UI...")
    webbrowser.open("http://127.0.0.1:8080")
    print("      [OK] Browser opened to http://127.0.0.1:8080")

    print("\n" + "=" * 75)
    print(" DEMO SCENARIOS TO CLICK & TEST:")
    print(" 1. Click 'Clean Match (0% Var)': Demonstrates autonomous plan + verification.")
    print(" 2. Click 'Timeout After Commit': Simulates 504 gateway timeout -> reconciles 0 dups!")
    print(" 3. Click 'Amount Mismatch': Guard pauses for human approval modal with evidence.")
    print(" 4. Click 'Workflow B: Sales Report': Generalization proof with zero runtime edits.")
    print("=" * 75)
    print("\nServer running. Press Ctrl+C in this terminal to shut down.\n")

    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nShutting down WorkGraph demo servers...")
        sys.exit(0)


if __name__ == "__main__":
    main()
