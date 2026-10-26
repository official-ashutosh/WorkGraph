"""
Automated Video Demo Recorder for WorkGraph
Uses Playwright's native record_video_dir to record an end-to-end interactive demo video in the new Light Theme.
Saves the video directly to data/demo_video/workgraph_demo.webm.
"""

import os
import sys
import time
import socket
import threading
import uvicorn

os.environ["OPENBLAS_NUM_THREADS"] = "1"
os.environ["OMP_NUM_THREADS"] = "1"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from playwright.sync_api import sync_playwright
from apps.ledgerone.database import seed_db
from apps.ledgerone.server import app as ledgerone_app
from api.server import app as workgraph_app

VIDEO_DIR = os.path.abspath(os.path.join(BASE_DIR, "data", "demo_video"))
os.makedirs(VIDEO_DIR, exist_ok=True)


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def ensure_servers():
    """Ensure LedgerOne (8000) and WorkGraph (8080) are running."""
    seed_db()

    if not is_port_in_use(8000):
        print("  Starting LedgerOne ERP on http://127.0.0.1:8000...")
        t1 = threading.Thread(
            target=lambda: uvicorn.run(ledgerone_app, host="127.0.0.1", port=8000, log_level="error"),
            daemon=True
        )
        t1.start()

    if not is_port_in_use(8080):
        print("  Starting WorkGraph Control Plane on http://127.0.0.1:8080...")
        t2 = threading.Thread(
            target=lambda: uvicorn.run(workgraph_app, host="127.0.0.1", port=8080, log_level="error"),
            daemon=True
        )
        t2.start()

    # Wait for ports to become active
    retries = 20
    while retries > 0:
        if is_port_in_use(8000) and is_port_in_use(8080):
            break
        time.sleep(0.3)
        retries -= 1


def cleanup_temp_videos():
    """Removes temporary page@*.webm files."""
    if not os.path.exists(VIDEO_DIR):
        return
    for f in os.listdir(VIDEO_DIR):
        if f.startswith("page@") and f.endswith(".webm"):
            try:
                os.remove(os.path.join(VIDEO_DIR, f))
            except Exception:
                pass


def record_demo():
    print(f"Recording WorkGraph interactive demo to: {VIDEO_DIR}...")
    cleanup_temp_videos()
    ensure_servers()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            record_video_dir=VIDEO_DIR,
            record_video_size={"width": 1280, "height": 720},
            viewport={"width": 1280, "height": 720}
        )
        page = context.new_page()

        # Step 1: Open WorkGraph UI
        print("[1/6] Navigating to http://127.0.0.1:8080...")
        page.goto("http://127.0.0.1:8080")
        page.wait_for_timeout(3000)

        # Step 2: Clean Match Scenario
        print("[2/6] Running Clean Match (0% Var)...")
        page.locator("button:has-text('Clean Match')").click()
        page.wait_for_timeout(5000)

        # Step 3: Timeout After Commit Fault
        print("[3/6] Running Timeout After Commit (Uncertain State Recovery)...")
        page.locator("button:has-text('Timeout After Commit')").click()
        page.wait_for_timeout(6000)

        # Step 4: Amount Mismatch & Human Approval Modal
        print("[4/6] Running Amount Mismatch (+7.35% Variance)...")
        page.locator("button:has-text('Amount Mismatch')").click()
        
        # Wait for approval modal to pop up
        print("      Waiting for Human Authorization Modal to open...")
        page.wait_for_selector("#approval-modal.flex", timeout=15000)
        page.wait_for_timeout(1500)  # Pause to display modal clearly on video

        # Confirm Human Authorization
        print("      Authorizing transaction from Approval Modal...")
        page.locator("button:has-text('Authorize & Continue')").click()
        page.wait_for_timeout(4000)

        # Step 5: Generalization - Sales Report
        print("[5/6] Running Workflow B: Weekly Sales Report...")
        page.locator("button:has-text('Sales Report')").click()
        
        # Wait for email approval modal to open
        print("      Waiting for email authorization gate...")
        try:
            page.wait_for_selector("#approval-modal.flex", timeout=12000)
            page.wait_for_timeout(1500)
            print("      Authorizing Sales Report email dispatch...")
            page.locator("button:has-text('Authorize & Continue')").click()
            page.wait_for_timeout(3000)
        except Exception:
            pass

        # Step 6: Eval Report Modal
        print("[6/6] Opening Eval Scorecard (12/12 Passed)...")
        page.locator("button:has-text('Eval Report')").click()
        page.wait_for_timeout(5000)

        # Close eval modal
        page.locator("#evals-modal button").click()
        page.wait_for_timeout(2000)

        # Final pause before closing
        page.wait_for_timeout(2000)

        # Close context to flush video
        context.close()
        browser.close()

    # Find the recorded video file and rename to workgraph_demo.webm
    files = [f for f in os.listdir(VIDEO_DIR) if f.endswith(".webm")]
    if files:
        latest = max([os.path.join(VIDEO_DIR, f) for f in files], key=os.path.getctime)
        final_dest = os.path.join(VIDEO_DIR, "workgraph_demo.webm")
        if latest != final_dest:
            if os.path.exists(final_dest):
                os.remove(final_dest)
            os.rename(latest, final_dest)
        
        cleanup_temp_videos()

        print(f"\nDemo video recorded successfully!")
        print(f"File: {final_dest} ({os.path.getsize(final_dest) // 1024} KB)")
        return final_dest

    return None


if __name__ == "__main__":
    record_demo()
