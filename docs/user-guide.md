# User Guide — Kamei Lab Budget System

## Accessing the System

Navigate to the web app URL shared by the PI. You must be signed in to your `nyu.edu` Google account.

**First time?** You will be asked to register — fill in your name, role, and reason for access. The PI will approve your request by email.

---

## Dashboard

The dashboard shows the current fiscal year budget at a glance:

- **Summary cards** — one per category (Equipment, Personnel, Travel, Other), showing amount spent, total budget, and a progress bar
- **Color coding** — green (<70%), yellow (70–90%), red (>90%)
- **Currency toggle** — switch between AED and USD display
- **Recent transactions** — the 10 most recent entries
- **Pending review alert** — if any auto-imported transactions need your attention

---

## Adding an Expense

Go to **Add Expense** in the navigation.

Required fields:
- **Category** — Equipment / Personnel / Travel / Other
- **Vendor / Payee** — who was paid
- **Description** — what it was for
- **Amount** — enter in AED, USD, or both (AED equivalent is calculated automatically)

Optional:
- PO Number and Invoice Number for cross-referencing
- PDF Link — paste a Google Drive URL for the receipt
- Notes

---

## Importing a PDF Invoice

Go to **Import PDF** and drag-and-drop (or click to select) a PDF invoice or receipt.

Claude AI will extract:
- Vendor name
- Invoice date and number
- Total amount and currency
- Suggested category

Review the parsed fields (highlighted if confidence is low), make any corrections, then click **Confirm & Add Transaction**.

---

## Transaction Statuses

| Status | Meaning |
|--------|---------|
| Pending Review | Auto-imported — needs human verification |
| Ordered | Purchase order placed, not yet received |
| Delivered | Item received, not yet paid |
| Paid | Payment processed |
| Cancelled | Order cancelled — excluded from budget totals |

---

## Reports

Go to **Reports** to see:
- Category breakdown (pie chart)
- Monthly spending trend (line chart)
- AI-generated budget narrative (suitable for grant reports)
- Export to Google Doc button

---

## Gmail Auto-Import

To import an invoice that arrived by email:
1. Open Gmail
2. Find the invoice email
3. Apply the label **Budget/Invoices** (create it if not present)
4. The system will automatically import it within 15 minutes

All auto-imports appear with `Status = Pending Review`. Check the Transactions page to verify them.

---

## Claude Code Terminal Skills (PI / Power Users)

From the terminal in the project directory:

| Command | What it does |
|---------|-------------|
| `/budget-status` | Live budget overview in terminal |
| `/parse-invoice file.pdf` | Parse PDF and optionally add transaction |
| `/add-expense` | Natural language expense entry |
| `/generate-report` | Full report with narrative |
| `/reconcile-receipts` | Find unconfirmed orders |
| `/import-from-email` | Trigger Gmail scan |
| `/fiscal-year-init` | Initialize new fiscal year |
| `/update-exchange-rate` | Update AED/USD rate |
