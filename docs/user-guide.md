# User Guide — Kamei Lab Budget System

## Accessing the System

Navigate to the integrated Cloud Run web URL shared by the PI. You must sign in
with your verified `nyu.edu` Google account. The Portal opens Budget Manager,
Project Tracker, and Notebooks/Protocols inside the same web application; it
does not redirect to a legacy app.

Access is based on the `Teams` sheet. If you see "Email not registered", ask the PI to add your email as a team lead or member.

---

## Dashboard

The dashboard shows the current fiscal year budget at a glance:

- **Summary cards** — one per category (Equipment, Consumables, Personnel, Travel, Publications, Memberships, Other), showing amount spent, total budget, and a progress bar
- **Team cards** — allocated, committed, paid, and remaining budget for your team
- **Color coding** — green (<70%), yellow (70–90%), red (>90%)
- **Currency toggle** — switch between AED and USD display
- **Recent transactions** — the 10 most recent entries
- **Pending review alert** — if any auto-imported transactions need your attention

---

## Adding an Expense

Go to **Add Request** in the navigation.

Required fields:
- **Category** — Equipment / Consumables / Personnel / Travel / Publications / Memberships / Other
- **Vendor / Payee** — who was paid
- **Description** — what it was for
- **Amount** — enter in AED, USD, or both (AED equivalent is calculated automatically)

Members create requests with `Status = Requested`. Team leads and the PI can approve or update the request through **Requests / Transactions**.

Optional:
- PO Number and Invoice Number for cross-referencing
- PDF Link — paste a Google Drive URL for the receipt
- Notes

---

## Importing a PDF Invoice

Go to **Import PDF** and drag-and-drop (or click to select) a PDF invoice or receipt.

The Python parser will extract:
- Vendor name
- Invoice date and number
- Total amount and currency
- Suggested category

Review the parsed fields, assign the team, then import. PDF and ERB imports are saved as `Pending Review`. If the PO number, invoice number, or vendor matches an existing request in the same team, the existing row is updated.

---

## Transaction Statuses

| Status | Meaning |
|--------|---------|
| Requested | A member or lead has submitted a purchase request |
| Approved | Team lead or PI approved the request |
| Ordered | Purchase order placed, not yet received |
| Pending Review | Auto-imported — needs human verification |
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
