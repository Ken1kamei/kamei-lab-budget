# Streamlit Budget App — Design Spec
**Date:** 2026-05-04
**Project:** Kamei Reverse Bioengineering Lab — Budget Management System

---

## Context

The current Google Apps Script (GAS) web app is being replaced with a Python Streamlit app. Key reasons:
- Eliminate Claude API token costs for invoice parsing (Python pdfplumber instead)
- Easier to maintain and extend in Python
- Add team-based sub-budget tracking (2+ project teams sharing the lab budget)

The existing Google Sheet (`KameiLab Budget FY2025-26`) stays as the data store. GAS Gmail auto-import triggers are kept running unchanged — they write directly to the sheet without needing a web UI.

---

## Architecture

```
Browser (any device)
    ↕ HTTPS + Streamlit password
Streamlit App  ←→  Google Sheet (existing)
    ↑
    └── utils/sheets.py (gspread service account)
    └── utils/parse_invoice.py (pdfplumber + openpyxl, no AI)
    └── utils/budget.py (calculations)

GAS Triggers (unchanged, kept running)
    └── Gmail → Transactions sheet (every 15 min)
```

**Hosting:** Streamlit Community Cloud (free tier)
**Auth:** Single shared password (Streamlit Community Cloud setting) + email-based role lookup inside the app

---

## Data Model Changes

### New: `Teams` sheet tab
| Column | Type | Notes |
|--------|------|-------|
| Team Name | string | Unique identifier, e.g. "Synbio", "Imaging" |
| Allocation (AED) | number | Total lab budget allocated to this team |
| Lead Emails | string | Comma-separated nyu.edu emails of team leads |
| Member Emails | string | Comma-separated nyu.edu emails of members (read-only) |
| Description | string | Optional project description |
| Active | Y/N | Whether team is active this fiscal year |

### Modified: `Transactions` sheet tab
Add one column at the end:
- **Team** (col U): dropdown of team names from the Teams sheet, or blank for lab-wide/unassigned transactions

Existing rows remain valid — blank Team = unassigned (visible to PI only, not attributed to any team budget).

---

## Roles

Determined by looking up the user's entered email in the Teams sheet:

| Role | Who | Determined by |
|------|-----|---------------|
| **PI** | `ken1kamei@nyu.edu` | Hardcoded PI email in `secrets.toml` |
| **Team Lead** | Any email in a team's Lead Emails field | Teams sheet lookup |
| **Member** | Any email in a team's Member Emails field | Teams sheet lookup |
| **Unknown** | Any other nyu.edu email | Shown "not registered" message |

---

## Login Flow

1. Streamlit Community Cloud password gate — blocks all outside access
2. Inside the app, first screen shows an email input field
3. User enters their `nyu.edu` email
4. App looks up the email in the Teams sheet to determine role and team(s)
5. Role + team stored in `st.session_state` for the session lifetime
6. No OAuth, no Google login required inside the app

---

## Pages

### 1. Dashboard (`pages/1_Dashboard.py`)
- **PI:** Summary cards (4 categories) + team allocation bar chart + recent transactions across all teams
- **Team Lead:** Own team's total spent vs allocated + lab-wide category totals (no team breakdown of others) + own team's recent transactions
- **Member:** Own team's total spent vs allocated + own team's recent transactions
- AED / USD toggle (client-side conversion using exchange rate from Config sheet)
- Plotly bar chart for monthly spending trend

### 2. Transactions (`pages/2_Transactions.py`)
- **PI:** Full table, filterable by team / category / status / date range. Edit any transaction's status, notes, PDF link.
- **Team Lead:** Own team's transactions only. Can edit status/notes. Can add new transactions for own team.
- **Member:** Own team's transactions, read-only. Export CSV.
- All roles: export filtered view as CSV.

### 3. Add Expense (`pages/3_Add_Expense.py`)
- Visible to PI and Team Leads only (hidden for Members)
- Form fields: Date, Category, Sub-category, Vendor, Description, PO#, Invoice#, Amount (AED), Amount (USD), Status, PDF link, Notes
- **Team field:** PI sees all teams dropdown + "Lab-wide (unassigned)". Team Lead sees only their own team (pre-filled, locked).
- AED equivalent calculated live as user types
- On submit: writes new row to Transactions sheet

### 4. Import Invoice / Receipt (`pages/4_Import_Invoice.py`)
- Visible to PI and Team Leads only
- **PDF upload:** drag-drop → pdfplumber extracts text → regex parses vendor, date, amount, invoice# → editable preview form → confirm imports
- **NYUAD ERB Excel upload:** openpyxl reads → maps ERB columns → preview table → confirm imports all rows
- No Claude API used — fully Python, zero token cost
- Team field shown in preview form (same dropdown rules as Add Expense)
- Saves PDF to Google Drive via Drive API (optional; can be disabled if Drive API scope is an issue)

### 5. Reports (`pages/5_Reports.py`)
- **PI:** Full breakdown — spending by category (pie), monthly trend (line), per-team comparison bar chart, transaction count table with TOTAL row and remaining
- **Team Lead:** Own team spending trend + lab-wide category summary (amounts, no team names of others). Download own team's transactions as CSV.
- **Member:** Own team summary card (allocated, spent, remaining %) + own team transaction list
- All charts use Plotly

### 6. Settings (`pages/6_Settings.py`)
- **PI only** (hidden for all other roles)
- Budget allocations per category (write to Summary sheet)
- Team management: add/edit/deactivate teams (write to Teams sheet)
- Exchange rate update (write to Config sheet)
- Test mode: load dummy data / clear all [TEST] tagged transactions
- Fiscal year initialisation

---

## File Structure

```
streamlit_app/
├── app.py                    # Entry point: email login + session state + sidebar nav
├── pages/
│   ├── 1_Dashboard.py
│   ├── 2_Transactions.py
│   ├── 3_Add_Expense.py
│   ├── 4_Import_Invoice.py
│   ├── 5_Reports.py
│   └── 6_Settings.py
├── utils/
│   ├── sheets.py             # All Google Sheets read/write (gspread)
│   ├── budget.py             # Summary calculations (totals, % used, remaining, team view)
│   └── parse_invoice.py      # Reuse existing PDF + Excel parser (moved/symlinked from scripts/)
├── .streamlit/
│   ├── config.toml           # Theme (NYUAD purple), layout wide
│   └── secrets.toml          # SPREADSHEET_ID, Google service account JSON (not committed)
└── requirements.txt          # streamlit, gspread, google-auth, pdfplumber, openpyxl, plotly
```

---

## Google Sheets Connection

Uses a **Google Service Account** (not the clasp OAuth credentials):
1. Create a service account in Google Cloud Console
2. Share the spreadsheet with the service account email (Editor)
3. Download the JSON key → store in `.streamlit/secrets.toml`
4. gspread authenticates automatically in both local and cloud environments

`secrets.toml` structure:
```toml
[gcp_service_account]
type = "service_account"
project_id = "..."
private_key_id = "..."
private_key = "..."
client_email = "..."
# ... full service account JSON fields

SPREADSHEET_ID = "1Ga6kOPohYxqQbt9ZoNXUma9Tf3cNmlxCJdvxp5edVWE"
PI_EMAIL = "ken1kamei@nyu.edu"
```

---

## Key Design Decisions

| Decision | Choice | Reason |
|----------|--------|--------|
| Framework | Streamlit | 100% Python, free hosting, fast to build |
| Auth | Password + email lookup | Simple; no OAuth app setup needed |
| Data store | Existing Google Sheet | No migration; GAS triggers keep working |
| PDF parsing | pdfplumber + regex | Zero Claude API cost |
| Charts | Plotly | Rich interactivity, works natively in Streamlit |
| Team budget | Total AED per team, no category split | Matches how PI allocates in practice |
| GAS kept | Gmail triggers only | Auto-import still needs GAS scheduler |

---

## Out of Scope (this version)

- Email notifications (still handled by GAS)
- Google Drive PDF storage (transactions store PDF URLs as text; Drive upload optional)
- Multi-fiscal-year view (one sheet per year; app defaults to current year)
- Mobile-optimised layout (Streamlit is responsive but not mobile-first)
