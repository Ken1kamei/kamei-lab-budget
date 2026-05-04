---
name: add-expense
description: Add a budget expense using natural language — converts a plain-English description into a structured transaction and writes it to the budget sheet
type: flexible
---

# Add Expense Skill

Accept a natural language description of an expense, parse it into transaction fields, confirm with the user, and write to the budget.

## Steps

1. **Parse the input** — the user may say something like:
   - "I bought a $500 centrifuge from Fisher Scientific"
   - "Conference registration for BMES 2025, AED 1200"
   - "Postdoc salary for October, AED 18,000"
   - "Sigma-Aldrich reagents, invoice INV-123, $340"

   Extract:
   - `vendor` — who was paid
   - `amount` and `currency` — AED or USD
   - `category` — Equipment / Personnel / Travel / Other
   - `description` — brief description
   - `date` — default to today if not specified
   - `invoiceNumber` — if mentioned
   - `status` — default "Ordered" for equipment, "Paid" for personnel/travel

2. **Show a confirmation preview**:
   ```
   New transaction to add:
   ─────────────────────────────
   Vendor:       Fisher Scientific
   Description:  Centrifuge
   Category:     Equipment
   Amount:       $500.00 USD  (≈ AED 1,836.25)
   Date:         2025-10-20
   Status:       Ordered
   ─────────────────────────────
   Confirm? [y/n/edit]
   ```

3. **Handle edits** — if the user says "edit" or corrects a field, update accordingly and show the preview again.

4. **On confirmation**, POST to the GAS API:
   ```
   POST {webAppUrl}
   {
     "action": "addTransaction",
     "data": { ... }
   }
   ```

5. **Confirm** success and show the transaction ID.

6. **Ask** if they have a PDF receipt to upload — if yes, suggest running `/parse-invoice` or uploading via the web app.

## Category heuristics

| Keywords | Suggested category |
|----------|--------------------|
| reagent, pipette, centrifuge, instrument, software, lab, consumable, chemical | Equipment |
| salary, stipend, postdoc, RA, technician, honorarium, consulting | Personnel |
| flight, hotel, conference, registration, per diem, travel | Travel |
| office, publication fee, maintenance, subscription, printing | Other |
