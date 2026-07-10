# Fiscal Year Procedures — Kamei Lab Budget

## Fiscal Year Calendar

| Event | Date |
|-------|------|
| New fiscal year begins | September 1 |
| Budget allocation entry | September 1–15 |
| Fiscal year ends | August 31 |
| Year-end report | August 15–31 |

## Start of Year Checklist

**By September 15:**

- [ ] Confirm total budget amount from NYUAD grants/finance office
- [ ] Confirm that **Settings → Fiscal Year** shows that the PI My Drive
      fiscal-year creator is configured.
- [ ] Open web app → **Settings** → **Fiscal Year** → enter `FY20XX-YY` and select **Queue Dedicated Google Sheet**. Refresh after about one minute.
      The first use creates `KameiLab Budget Template`; every later fiscal-year
      workbook is copied from this template so its worksheet format remains
      consistent.
- [ ] Use **Open FY20XX-YY workbook** in Settings and confirm it has standard
      `Transactions`, `Summary`, `Teams`, and `Config` tabs.
- [ ] Open web app → **Settings** → **Budget Allocations** → select the new
      academic year and enter budget allocations for each category.
- [ ] Verify AED/USD exchange rate in Settings (default: 3.6725)
- [ ] Check that Gmail auto-import triggers are active (Settings → Setup Triggers)
- [ ] Confirm that the new spreadsheet is owned by the PI in **My Drive** and
      that the Budget service account has Editor access.
- [ ] Share the new spreadsheet URL with finance if direct Sheet access is
      needed. The app service account continues to manage app writes.
- [ ] Archive the previous year's spreadsheet in Google Drive when appropriate.

### Moving a Year Created Under the Old Shared-Tab Layout

If Settings shows a year as stored in the FY2025-26 master workbook, use
**Move FY20XX-YY** in **Settings → Fiscal Year**. This copies the four active
app tabs into a dedicated workbook and changes the app routing only after the
copy succeeds. The original FY-suffixed tabs remain in the master workbook as
an archival backup.

## End of Year Checklist

**By August 25:**

- [ ] Run `/generate-report` or go to web app **Reports** → **Export to Google Doc**
- [ ] Review all transactions with `Status = "Pending Review"` — resolve or cancel
- [ ] Confirm all equipment orders have receipt confirmations (run `/reconcile-receipts`)
- [ ] Download a CSV export from Transactions page for institutional records
- [ ] Send the final budget narrative to the grants office if required
- [ ] Note any unspent budget — check with grants office about carryover rules

## Monthly Tasks

**First week of each month:**

- [ ] Review the monthly digest email sent automatically on the 1st
- [ ] Process any `Pending Review` transactions in the web app
- [ ] Check for equipment orders outstanding > 30 days (`/reconcile-receipts`)

## Handling Common Situations

### New invoice received by email
1. Apply `Budget/Invoices` label in Gmail
2. Auto-import runs within 15 minutes
3. Review the new `Pending Review` entry in the web app
4. Update Status to `Ordered`, `Delivered`, or `Paid` as appropriate

### Invoice received as PDF attachment
1. Open web app → **Import PDF**
2. Upload the PDF → review parsed fields → confirm
3. Or use `/parse-invoice` in Claude Code terminal

### Personnel payment (salary/stipend)
1. Add as manual transaction via **Add Expense** or `/add-expense`
2. Category: `Personnel`, Sub-category: position type
3. Set Status to `Paid` immediately

### Conference/travel reimbursement
1. Add transaction with Category: `Travel` before travel (estimate) and Status: `Ordered`
2. After travel, update Status to `Paid` and add actual receipt PDF

### Budget category exceeds 80%
- An automatic alert email is sent to the PI
- Review the category in the web app dashboard
- Contact grants office to discuss reallocation if needed
