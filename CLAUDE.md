# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Budget management system for the Kamei Reverse Bioengineering Lab at NYUAD (New York University Abu Dhabi). Tracks equipment orders, personnel costs, travel, and other expenses across academic fiscal years (Sep 1 – Aug 31). Currencies: AED and USD.

## Architecture

```
Gmail / Google Drive
       │
       ▼
Google Apps Script (gas/)   ←→   Claude API (invoice/email parsing)
       │
       ▼
Google Sheets (one spreadsheet per fiscal year)
       │
       ▼
GAS Web App (HTML Service) — nyu.edu domain-restricted
```

All backend logic lives in `gas/*.gs` files. The web app UI is in `gas/html/*.html`. Authentication is handled automatically by Google Workspace — only nyu.edu accounts can access. The Claude API is called from GAS via `UrlFetchApp`.

## Development Commands

```bash
# Install clasp (once)
npm install -g @google/clasp
clasp login

# Push code to Apps Script
cd gas && clasp push

# Deploy web app
cd gas && clasp deploy --description "vX"

# List deployments (to get web app URL)
cd gas && clasp deployments

# Open Apps Script editor
cd gas && clasp open
```

## Key Files

| File | Purpose |
|------|---------|
| `gas/Code.gs` | Web app entry point — `doGet()`, `doPost()`, routing, auth check |
| `gas/Transactions.gs` | Core ledger: `addTransaction()`, `updateTransaction()`, `getTransactions()` |
| `gas/Budget.gs` | Budget summary: `getBudgetSummary()`, `updateBudgetAllocation()`, `initializeFiscalYear()` |
| `gas/ClaudeAPI.gs` | Claude API integration — `parseInvoicePDF()`, `parseEmailBody()`, `generateBudgetNarrative()` |
| `gas/Auth.gs` | User registration/approval — `isRegisteredUser()`, `registerUser()`, `approveUser()` |
| `gas/GmailIntegration.gs` | Gmail auto-import — `checkBudgetEmails()` (runs on 15-min trigger) |
| `gas/Triggers.gs` | Time-based trigger setup — run `setupTriggers()` once after deployment |
| `gas/Utils.gs` | Shared utilities — `getConfig()`, `setConfig()`, `getCurrentFiscalYear()`, `toAedEquiv()` |
| `gas/html/index.html` | Dashboard — budget vs. actuals with Google Charts |
| `gas/html/import.html` | PDF upload → Claude parse → confirm → add transaction |

## Script Properties (set in Apps Script editor, never in code)

| Property | Description |
|----------|-------------|
| `SPREADSHEET_ID` | Google Sheets spreadsheet ID |
| `CLAUDE_API_KEY` | Anthropic API key |
| `TOKEN_SECRET` | Random string for user approval tokens |

## Google Sheets Structure

One spreadsheet per fiscal year named `KameiLab Budget FY{YYYY}-{YY}`.

**8 tabs:** `Summary` · `Transactions` · `Equipment` · `Personnel` · `Travel` · `Receipts` · `Other` · `Config`

`Summary` tab has the budget allocations and sparkline progress bars. All actuals are computed from `Transactions` in `getBudgetSummary()` — the sheet formulas are for display only.

`Config` tab stores runtime settings: exchange rate, registered users list, Drive folder ID, notification threshold %. Scripts read/write Config via `getConfig(key)` / `setConfig(key, value)`.

## Claude Code Skills

8 skills in `.claude/skills/` — use them from the Claude Code terminal in this directory:

| Skill | Command |
|-------|---------|
| Live budget overview | `/budget-status` |
| Parse PDF invoice | `/parse-invoice [file.pdf]` |
| Natural language expense entry | `/add-expense` |
| Generate fiscal year report | `/generate-report [FY20XX-XX]` |
| Find unconfirmed orders | `/reconcile-receipts` |
| Trigger Gmail scan | `/import-from-email` |
| Initialize new fiscal year | `/fiscal-year-init` |
| Update AED/USD rate | `/update-exchange-rate` |

Each skill calls the GAS web app JSON API at the deployed URL. Update `{webAppUrl}` in each skill file after first deployment.

## Access Control

- GAS Web App deployed with `Execute as: Me`, `Who has access: Anyone in NYUAD domain`
- `doGet()` additionally verifies `email.endsWith('@nyu.edu')`
- New users see a registration form → PI receives approval email → user added to `Config` registered users list
- PI email: `ken1kamei@nyu.edu`

## PDF Parsing Pipeline

1. PDF uploaded via web app (`import.html`) or Gmail attachment trigger
2. Saved to Google Drive under `Kamei Lab Budget / FY#### / Invoices/`
3. `parseInvoicePDF(fileId)` in `ClaudeAPI.gs` encodes to base64, POSTs to `claude-sonnet-4-6`
4. Claude returns JSON per `prompts/parse-invoice.txt` schema
5. Auto-imports create transactions with `Status = "Pending Review"` and `Entry Method = "Auto-PDF"` or `"Auto-Email"`

## Setup

See [docs/setup-guide.md](docs/setup-guide.md) for full first-time setup instructions.
See [docs/fiscal-year-procedures.md](docs/fiscal-year-procedures.md) for annual rollover checklist.
