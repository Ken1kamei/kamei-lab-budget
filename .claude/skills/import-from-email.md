---
name: import-from-email
description: Search Gmail for recent unprocessed budget-related emails and import them as transactions
type: flexible
---

# Import from Email Skill

Surface candidate budget emails from Gmail, let the user select which to import, and trigger the GAS auto-import pipeline.

## Steps

1. **Trigger Gmail scan** via the GAS API:
   ```
   POST {webAppUrl}
   {"action": "checkBudgetEmails"}
   ```
   This scans emails labeled `Budget/Invoices` and returns a list of imported transactions.

2. **If results returned**, display them:
   ```
   Auto-imported 3 transaction(s):
   ────────────────────────────────────────────
   1. TXN-20251020-0015 | Fisher Scientific | AED 3,450 | Status: Pending Review
   2. TXN-20251021-0016 | Emirates Airlines | AED 2,100 | Status: Pending Review
   3. TXN-20251021-0017 | Sigma-Aldrich     | USD 340   | Status: Pending Review
   ```

3. **If no labeled emails found**, instruct the user:
   ```
   No emails found with the "Budget/Invoices" Gmail label.

   To import an invoice email:
   1. Open Gmail in your browser
   2. Find the invoice/receipt email
   3. Apply the label "Budget/Invoices" to it
   4. Run /import-from-email again

   Or use /parse-invoice to upload a PDF directly.
   ```

4. **For each imported transaction**, offer quick review:
   - Confirm the category is correct
   - Flag any with `confidence: low` for manual review

5. **Remind** the user that all auto-imports have `Status = "Pending Review"` and should be reviewed at the web app: `?page=transactions`

## Tips

- Forward invoice emails to your Gmail and apply the `Budget/Invoices` label before running this command.
- PDF attachments in labeled emails are automatically saved to Google Drive under `Kamei Lab Budget / FY#### / Invoices/`.
- The GAS trigger also runs this automatically every 15 minutes once set up via `/fiscal-year-init` or the Settings page.
