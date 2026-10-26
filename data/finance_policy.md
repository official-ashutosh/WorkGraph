# Apex Global Corporate Finance Policy: Accounts Payable & Bill Registration

**Standard Operating Procedure (SOP) - AP-042**  
*Effective Date: Q1 2026*  
*Classification: Internal Finance Standard*

---

## 1. Approved Vendor Verification
1. Every invoice submitted for payment must originate from an authorized vendor on the Corporate Approved Vendor List (`data/vendors.csv`).
2. Invoices originating from unknown, unverified, or flagged vendors **must be rejected immediately** and escalated to Finance Operations for vendor onboarding. No bill may be created for an unapproved vendor under any circumstances.

## 2. Purchase Order (PO) Matching & Tolerance Thresholds
1. All invoices exceeding $100.00 require a valid Purchase Order number matching an open, approved PO in the ERP system (`LedgerOne`).
2. **Tolerance Band**:
   - If the total invoice amount matches the PO amount exactly, or differs by **no more than 2.00%**, the invoice is approved for automated bill creation.
   - If the variance between the invoice amount and PO amount exceeds **2.00%**, automated bill creation is **strictly prohibited**. The transaction must be paused, and explicit **Human Manager Approval** is required before the bill can be registered.
   - If the invoice variance exceeds **15.00%**, the invoice must be escalated and rejected as an unauthorized charge.

## 3. Manager Approval Thresholds
1. Any invoice where the total bill amount equals or exceeds **$5,000.00 USD** requires mandatory **Finance Director Approval**, regardless of PO match status.
2. Irreversible payment execution or disbursement actions always require dual-authorization human sign-off.

## 4. Duplicate Invoice Prevention
1. Under no circumstances may an invoice with an identical `Invoice Number` and `Vendor ID` be registered more than once.
2. Prior to creating any bill, the system must perform an idempotency and existence precheck against existing records.
3. If an invoice number already exists in `LedgerOne`, automated registration must refuse the transaction with a documented reason.

## 5. Payment Terms & Due Date Derivation
1. Due dates must be calculated strictly from the vendor's agreed master terms (e.g., `Net 30`, `Net 15`, `Due Upon Receipt`) starting from the invoice issue date.
2. Line items, tax codes, and currency (`USD`) must match the designated PO currency.
