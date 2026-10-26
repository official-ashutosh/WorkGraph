"""
Generates realistic seed invoice PDFs for WorkGraph testing and evaluation.
Uses ReportLab to produce standard vector PDF documents with selectable text.
"""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

INVOICES_DIR = os.path.join(os.path.dirname(__file__), "invoices")
os.makedirs(INVOICES_DIR, exist_ok=True)

INVOICE_SPECS = [
    {
        "filename": "inv_01_clean_match.pdf",
        "vendor_id": "VEND-001",
        "vendor_name": "Acme Industrial Supply",
        "vendor_address": "100 Industrial Parkway, Detroit, MI 48201",
        "tax_id": "US-84920192",
        "invoice_number": "INV-2026-101",
        "po_number": "PO-2026-001",
        "issue_date": "2026-10-20",
        "payment_terms": "Net 30",
        "due_date": "2026-11-19",
        "currency": "USD",
        "items": [
            ("Industrial Fasteners Grade 8 (Box of 500)", "500", "$2.50", "$1,250.00")
        ],
        "subtotal": "$1,250.00",
        "tax": "$0.00",
        "total": "$1,250.00",
        "notes": "Standard PO fulfillment. Clean match to PO-2026-001."
    },
    {
        "filename": "inv_02_amount_mismatch.pdf",
        "vendor_id": "VEND-002",
        "vendor_name": "Global Cloud Technologies",
        "vendor_address": "400 Cloud Vista Way, Austin, TX 78701",
        "tax_id": "US-73910482",
        "invoice_number": "INV-2026-102",
        "po_number": "PO-2026-002",
        "issue_date": "2026-10-21",
        "payment_terms": "Net 15",
        "due_date": "2026-11-05",
        "currency": "USD",
        "items": [
            ("Enterprise Cloud Hosting Q1 Base", "1", "$3,400.00", "$3,400.00"),
            ("Unscheduled Over-Quota Bandwidth", "1", "$250.00", "$250.00")
        ],
        "subtotal": "$3,650.00",
        "tax": "$0.00",
        "total": "$3,650.00",
        "notes": "PO was $3,400.00. Total is $3,650.00 (+7.35% variance). Exceeds 2% policy tolerance."
    },
    {
        "filename": "inv_03_vendor_x_surcharge.pdf",
        "vendor_id": "VEND-004",
        "vendor_name": "Vendor X Logistics",
        "vendor_address": "77 Route 66 Freight Way, Tulsa, OK 74103",
        "tax_id": "US-99182301",
        "invoice_number": "INV-2026-103",
        "po_number": "PO-2026-004",
        "issue_date": "2026-10-22",
        "payment_terms": "Net 30",
        "due_date": "2026-11-21",
        "currency": "USD",
        "items": [
            ("Dedicated Linehaul Route 14 Base Rate", "1", "$2,000.00", "$2,000.00"),
            ("Standard Diesel Fuel Surcharge (3.0%)", "1", "$60.00", "$60.00")
        ],
        "subtotal": "$2,060.00",
        "tax": "$0.00",
        "total": "$2,060.00",
        "notes": "PO is $2,000.00. Fuel surcharge adds $60.00 (+3.0%). Approver can remember as learned exception."
    },
    {
        "filename": "inv_03b_vendor_x_over_limit.pdf",
        "vendor_id": "VEND-004",
        "vendor_name": "Vendor X Logistics",
        "vendor_address": "77 Route 66 Freight Way, Tulsa, OK 74103",
        "tax_id": "US-99182301",
        "invoice_number": "INV-2026-103B",
        "po_number": "PO-2026-004",
        "issue_date": "2026-10-23",
        "payment_terms": "Net 30",
        "due_date": "2026-11-22",
        "currency": "USD",
        "items": [
            ("Dedicated Linehaul Route 14 Base Rate", "1", "$2,000.00", "$2,000.00"),
            ("Emergency Fuel Index Surcharge (4.0%)", "1", "$80.00", "$80.00")
        ],
        "subtotal": "$2,080.00",
        "tax": "$0.00",
        "total": "$2,080.00",
        "notes": "PO is $2,000.00. Surcharge is 4.0%. Even with 3% learned exception, this still requires human approval."
    },
    {
        "filename": "inv_04_duplicate.pdf",
        "vendor_id": "VEND-001",
        "vendor_name": "Acme Industrial Supply",
        "vendor_address": "100 Industrial Parkway, Detroit, MI 48201",
        "tax_id": "US-84920192",
        "invoice_number": "INV-2026-101",
        "po_number": "PO-2026-001",
        "issue_date": "2026-10-20",
        "payment_terms": "Net 30",
        "due_date": "2026-11-19",
        "currency": "USD",
        "items": [
            ("Industrial Fasteners Grade 8 (Box of 500)", "500", "$2.50", "$1,250.00")
        ],
        "subtotal": "$1,250.00",
        "tax": "$0.00",
        "total": "$1,250.00",
        "notes": "Duplicate invoice copy. Same invoice number INV-2026-101 and vendor as inv_01."
    },
    {
        "filename": "inv_05_unknown_vendor.pdf",
        "vendor_id": "VEND-999",
        "vendor_name": "Phantom Unverified Services",
        "vendor_address": "Unknown PO Box, Tortola, BVI",
        "tax_id": "XX-00000000",
        "invoice_number": "INV-2026-999",
        "po_number": "PO-NONE",
        "issue_date": "2026-10-24",
        "payment_terms": "Due Upon Receipt",
        "due_date": "2026-10-24",
        "currency": "USD",
        "items": [
            ("Anonymous Consulting Retainer", "1", "$980.00", "$980.00")
        ],
        "subtotal": "$980.00",
        "tax": "$0.00",
        "total": "$980.00",
        "notes": "Unapproved vendor. Must trigger immediate guard escalation without write."
    },
    {
        "filename": "inv_06_over_threshold.pdf",
        "vendor_id": "VEND-001",
        "vendor_name": "Acme Industrial Supply",
        "vendor_address": "100 Industrial Parkway, Detroit, MI 48201",
        "tax_id": "US-84920192",
        "invoice_number": "INV-2026-106",
        "po_number": "PO-2026-006",
        "issue_date": "2026-10-25",
        "payment_terms": "Net 30",
        "due_date": "2026-11-24",
        "currency": "USD",
        "items": [
            ("Heavy CNC Milling Replacement Motor Unit", "1", "$7,500.00", "$7,500.00")
        ],
        "subtotal": "$7,500.00",
        "tax": "$0.00",
        "total": "$7,500.00",
        "notes": "Total is $7,500.00. Matches PO but exceeds $5,000.00 manager threshold. Requires Director approval."
    },
    {
        "filename": "inv_07_older_starlight.pdf",
        "vendor_id": "VEND-003",
        "vendor_name": "Starlight Logistics Corp",
        "vendor_address": "88 Orbital Way, Denver, CO 80202",
        "tax_id": "US-19283019",
        "invoice_number": "INV-2026-080",
        "po_number": "PO-2026-003",
        "issue_date": "2026-09-01",
        "payment_terms": "Net 30",
        "due_date": "2026-10-01",
        "currency": "USD",
        "items": [
            ("August Warehousing & Handling", "1", "$1,800.00", "$1,800.00")
        ],
        "subtotal": "$1,800.00",
        "tax": "$0.00",
        "total": "$1,800.00",
        "notes": "Older Starlight invoice from September."
    },
    {
        "filename": "inv_08_latest_starlight.pdf",
        "vendor_id": "VEND-003",
        "vendor_name": "Starlight Logistics Corp",
        "vendor_address": "88 Orbital Way, Denver, CO 80202",
        "tax_id": "US-19283019",
        "invoice_number": "INV-2026-108",
        "po_number": "PO-2026-003",
        "issue_date": "2026-10-26",
        "payment_terms": "Net 30",
        "due_date": "2026-11-25",
        "currency": "USD",
        "items": [
            ("October Freight & Warehousing Services", "1", "$1,800.00", "$1,800.00")
        ],
        "subtotal": "$1,800.00",
        "tax": "$0.00",
        "total": "$1,800.00",
        "notes": "Latest Starlight invoice. Clean match to PO-2026-003."
    }
]

def generate_pdf(spec):
    pdf_path = os.path.join(INVOICES_DIR, spec["filename"])
    doc = SimpleDocTemplate(
        pdf_path,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'InvoiceTitle',
        parent=styles['Heading1'],
        fontSize=20,
        textColor=colors.HexColor('#1E293B'),
        spaceAfter=12
    )
    bold_style = ParagraphStyle(
        'BoldText',
        parent=styles['Normal'],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor('#0F172A')
    )
    gray_style = ParagraphStyle(
        'GrayText',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#64748B')
    )

    story = []
    # Header: Vendor Name & Title
    header_data = [
        [
            Paragraph(f"<b>{spec['vendor_name']}</b><br/>{spec['vendor_address']}<br/>Tax ID: {spec['tax_id']}", bold_style),
            Paragraph("<b>COMMERCIAL INVOICE</b>", title_style)
        ]
    ]
    header_table = Table(header_data, colWidths=[320, 220])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (1, 0), (1, 0), 'RIGHT')
    ]))
    story.append(header_table)
    story.append(Spacer(1, 15))

    # Meta Table: Invoice #, Date, PO, Terms
    meta_data = [
        [
            Paragraph(f"<b>Invoice Number:</b> {spec['invoice_number']}", bold_style),
            Paragraph(f"<b>Issue Date:</b> {spec['issue_date']}", bold_style)
        ],
        [
            Paragraph(f"<b>PO Number:</b> {spec['po_number']}", bold_style),
            Paragraph(f"<b>Payment Terms:</b> {spec['payment_terms']}", bold_style)
        ],
        [
            Paragraph(f"<b>Vendor ID:</b> {spec['vendor_id']}", bold_style),
            Paragraph(f"<b>Due Date:</b> {spec['due_date']}", bold_style)
        ]
    ]
    meta_table = Table(meta_data, colWidths=[270, 270])
    meta_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#CBD5E1')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    story.append(meta_table)
    story.append(Spacer(1, 15))

    # Line items
    items_data = [
        [
            Paragraph("<b>Description</b>", bold_style),
            Paragraph("<b>Qty</b>", bold_style),
            Paragraph("<b>Unit Price</b>", bold_style),
            Paragraph("<b>Amount</b>", bold_style)
        ]
    ]
    for desc, qty, unit, amt in spec['items']:
        items_data.append([
            Paragraph(desc, bold_style),
            Paragraph(qty, bold_style),
            Paragraph(unit, bold_style),
            Paragraph(amt, bold_style)
        ])
    
    # Subtotal and Total rows
    items_data.append(["", "", Paragraph("<b>Subtotal:</b>", bold_style), Paragraph(spec['subtotal'], bold_style)])
    items_data.append(["", "", Paragraph("<b>Tax (0%):</b>", bold_style), Paragraph(spec['tax'], bold_style)])
    items_data.append(["", "", Paragraph("<b>TOTAL DUE:</b>", bold_style), Paragraph(f"<b>{spec['total']}</b>", bold_style)])

    items_table = Table(items_data, colWidths=[280, 50, 90, 120])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0F172A')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('GRID', (0, 0), (-1, len(spec['items'])), 0.5, colors.HexColor('#E2E8F0')),
        ('LINEBELOW', (2, -1), (3, -1), 1.5, colors.HexColor('#0F172A')),
    ]))
    story.append(items_table)
    story.append(Spacer(1, 15))

    # Notes / Grounding quote section
    notes_p = Paragraph(f"<b>Billing Notes & Certification:</b><br/>{spec['notes']}<br/>Certified genuine invoice issued to Apex Global Corp.", gray_style)
    story.append(notes_p)

    doc.build(story)
    return pdf_path

if __name__ == "__main__":
    print(f"Generating {len(INVOICE_SPECS)} seed invoice PDFs...")
    for spec in INVOICE_SPECS:
        path = generate_pdf(spec)
        print(f"  [Created] {spec['filename']} -> {os.path.basename(path)}")
    print("All invoice PDFs successfully generated in data/invoices/")
