# WorkGraph Formal Evaluation & Ablation Report

*CentrAlign AI Founding Engineer / Intern Submission Evaluation*  
*Timestamp: 2026-10-27 01:10:37*

---

## 1. Comparative Headline Results: WorkGraph vs. No-Guard Baseline

| Evaluation Metric | WorkGraph (Guarded + Reconciler) | Baseline (No Guards / Plain Tool Loop) | Target / Spec |
| :--- | :---: | :---: | :---: |
| **Verified Task Success Rate** | **100.0% (12/12)** | 50.0% (6/12) | > 90% |
| **Duplicate Writes to Ledger** | **0** | 3 (Severe Data Corruption) | **0** |
| **False Completion Rate** | **0 (0.0%)** | 4 (33.3%) | **0%** |
| **Correct Escalation / Approval Rate** | **100%** | 0% (Blind Execution) | 100% |
| **Mean Execution Steps** | **7.4** | 5.2 | < 15 |
| **Mean Wall-Clock Latency** | **0.50s** | 1.84s | < 5.0s |

---

## 2. Detailed Scenario Breakdown

| # | Scenario Name | Expected Outcome | Actual Outcome | Duplicates | Time | Result |
| :-: | :--- | :--- | :--- | :-: | :-: | :-: |
| 1 | Clean Invoice Match | `COMPLETED_VERIFIED` | `COMPLETED_VERIFIED` | 0 | 0.389s | PASS |
| 2 | Timeout After Commit (Uncertain State) | `COMPLETED_VERIFIED` | `COMPLETED_VERIFIED` | 0 | 0.322s | PASS |
| 3 | Fail Before Commit (Deadlock) | `COMPLETED_VERIFIED` | `COMPLETED_VERIFIED` | 0 | 0.332s | PASS |
| 4 | Amount Mismatch - Approver Approves | `COMPLETED_AFTER_APPROVAL` | `COMPLETED_AFTER_APPROVAL` | 0 | 0.358s | PASS |
| 5 | Amount Mismatch - Approver Rejects | `ESCALATED` | `ESCALATED` | 0 | 0.209s | PASS |
| 6 | Duplicate Invoice Submission | `REJECTED_BY_POLICY` | `REJECTED_BY_POLICY` | 0 | 0.419s | PASS |
| 7 | Unknown / Unapproved Vendor | `REJECTED_BY_POLICY` | `REJECTED_BY_POLICY` | 0 | 0.249s | PASS |
| 8 | UI Selector Drift | `COMPLETED_VERIFIED` | `COMPLETED_VERIFIED` | 0 | 0.701s | PASS |
| 9 | Session Expiry Mid-Run | `COMPLETED_VERIFIED` | `COMPLETED_VERIFIED` | 0 | 0.781s | PASS |
| 10 | Learned Exception - Within Authorized 3% Band | `COMPLETED_VERIFIED` | `COMPLETED_VERIFIED` | 0 | 0.866s | PASS |
| 11 | Learned Exception - Exceeds Band at 4% | `COMPLETED_AFTER_APPROVAL` | `COMPLETED_AFTER_APPROVAL` | 0 | 0.818s | PASS |
| 12 | Generalization - Weekly Sales Report | `COMPLETED_AFTER_APPROVAL` | `COMPLETED_AFTER_APPROVAL` | 0 | 0.541s | PASS |

---

## 3. Key Findings & Reliability Proof

1. **Uncertain-State Recovery (Scenario 2):**
   When the LedgerOne HTTP response times out after commit (HTTP 504), WorkGraph's active state reconciliation checks ground truth via `api/bills/check` before retrying, achieving **0 duplicate writes**.
2. **Generalization without Runtime Edits (Scenario 12):**
   Workflow B (Weekly Sales Report) executed end-to-end on the exact same runtime without touching `runtime/` or `tools/registry.py`.
3. **Learned Exceptions (Scenarios 10 & 11):**
   Authorized 3.0% fuel surcharge passed autonomously from memory; at 4.0% the runtime correctly paused and requested human manager authorization.
