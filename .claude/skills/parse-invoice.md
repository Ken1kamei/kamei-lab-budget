---
name: parse-invoice
description: Parse a PDF invoice or NYUAD ERB Excel file using Python (no Claude API tokens) and import it into the budget system
type: flexible
---

# Parse Invoice Skill

Use the Python script `scripts/parse_invoice.py` to parse a PDF invoice or NYUAD ERB Excel file
and import it into the budget — **no Claude API tokens consumed**.

## Steps

1. **Get the file path** from the user's argument or ask.

2. **Run the Python script** from the project root:
   ```bash
   cd "/Users/kkamei/Library/CloudStorage/Dropbox/Shared Folder NYUAD/Budget"
   .venv/bin/python3 scripts/parse_invoice.py path/to/invoice.pdf
   # or for Excel:
   .venv/bin/python3 scripts/parse_invoice.py path/to/ERB_report.xlsx
   ```
   Add `--dry-run` to preview without importing.

3. **The script will**:
   - Extract text with `pdfplumber` (PDF) or `openpyxl` (Excel)
   - Parse vendor, date, amount, invoice number using regex
   - Show a preview table for review
   - Let you edit any field before confirming
   - POST directly to the budget web app API

3. **Display parsed data** in a clear table:
   ```
   ┌─────────────────────────────────────────────┐
   │  Parsed Invoice                             │
   ├─────────────────────────────────────────────┤
   │  Vendor:         Fisher Scientific          │
   │  Invoice #:      INV-2025-00123             │
   │  Date:           2025-10-15                 │
   │  Total:          AED 3,450.00               │
   │  Category:       Equipment  (AI suggestion) │
   │  Confidence:     HIGH                       │
   ├─────────────────────────────────────────────┤
   │  Line Items:                                │
   │  • Pipette tips 1000uL x200   AED 120.00   │
   │  • Centrifuge tubes 50mL x500 AED 85.00    │
   │  ...                                        │
   └─────────────────────────────────────────────┘
   ```

4. **Ask the user to confirm or edit**:
   - Confirm the category (Equipment/Personnel/Travel/Other)
   - Confirm the amounts (AED or USD)
   - Optionally add a description or notes

5. **On confirmation**, call the GAS API:
   ```
   POST {webAppUrl}
   {
     "action": "addTransaction",
     "data": {
       "vendor": "...",
       "invoiceNumber": "...",
       "date": "YYYY-MM-DD",
       "category": "Equipment",
       "amountAed": 3450.00,
       "amountUsd": 0,
       "status": "Pending Review",
       "entryMethod": "Auto-PDF",
       "pdfLink": "https://drive.google.com/...",
       "notes": "Parsed by Claude. Confidence: high"
     }
   }
   ```

6. **Confirm** the transaction ID returned and show the updated budget status for the affected category.

## Notes

- If confidence is `low`, highlight fields that need manual verification in red.
- Always set `entryMethod: "Auto-PDF"` so auto-imports are distinguishable from manual entries.
- The `status` should be `"Pending Review"` — the PI reviews and updates to `"Ordered"` or `"Paid"` via the web app.
