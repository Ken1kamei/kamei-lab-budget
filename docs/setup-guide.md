# Setup Guide — Kamei Lab Budget System

One-time setup for the PI or lab manager. Estimated time: 30–45 minutes.

## Prerequisites

- Google account with `nyu.edu` domain (NYUAD Google Workspace)
- Node.js installed (for `clasp`)
- Python 3.11+ for the Streamlit app
- A Google Cloud service account with Sheets/Drive API access
- A Google OAuth client for Streamlit OIDC login

---

## Step 1 — Install clasp

```bash
npm install -g @google/clasp
clasp login   # opens browser to authenticate with your nyu.edu Google account
```

---

## Step 2 — Create the Google Spreadsheet

1. Go to [sheets.google.com](https://sheets.google.com) and create a new spreadsheet.
2. Name it: `KameiLab Budget FY2025-26`
3. Copy the spreadsheet ID from the URL:
   `https://docs.google.com/spreadsheets/d/**SPREADSHEET_ID**/edit`

---

## Step 3 — Create the Apps Script Project

1. In the spreadsheet, go to **Extensions → Apps Script**.
2. Note the **Script ID** from the URL: `https://script.google.com/home/projects/**SCRIPT_ID**/edit`
3. Back in your terminal, navigate to the `gas/` directory:
   ```bash
   cd gas/
   ```
4. Edit `.clasp.json` and replace `REPLACE_WITH_YOUR_SCRIPT_ID` with the Script ID.
5. Push the code:
   ```bash
   clasp push
   ```

---

## Step 4 — Configure Script Properties

In the Apps Script editor (**Project Settings → Script Properties**), add:

| Property | Value |
|----------|-------|
| `SPREADSHEET_ID` | Your spreadsheet ID from Step 2 |
| `TOKEN_SECRET` | Any random string (used for approval tokens) |

---

## Step 5 — Initialize the Spreadsheet

In the Apps Script editor, run the `initializeFiscalYear` function:

1. Open the editor, select `Budget.gs`
2. Select the function `initializeFiscalYear` from the dropdown
3. Click **Run** — this creates all tabs with correct headers, formulas, and validation

Then enter your budget allocations:
1. Open the spreadsheet → `Kamei Budget` menu → **Open Web App** (or run `setupTriggers` first)
2. Go to **Settings** in the web app
3. Enter budget amounts for each category

---

## Step 6 — Deploy GAS Automation Web App

In the Apps Script editor:

1. Click **Deploy → New deployment**
2. Type: **Web app**
3. Description: `Kamei Lab Budget v1`
4. Execute as: `Me`
5. Who has access: `Anyone in NYUAD domain` (or `Anyone` if needed)
6. Click **Deploy** and copy the **Web App URL**

Save the URL for internal automation and optional PI maintenance. Lab members should normally use the Streamlit app URL.

---

## Step 7 — Set Up Gmail Auto-Import

1. In the web app, go to **Settings → Gmail Auto-Import**
2. Click **Create Gmail Label** — this creates the `Budget/Invoices` label in your Gmail
3. Click **Setup Auto-Import Triggers** — installs 15-minute Gmail scan + monthly reports

To import an invoice email manually: open Gmail → find the email → apply the `Budget/Invoices` label → triggers will pick it up within 15 minutes.

---

## Step 8 — Configure Streamlit Cloud

1. Share the spreadsheet with the Google service account email as **Editor**.
2. In Streamlit Cloud secrets, add the contents shown in `streamlit_app/.streamlit/secrets.toml.example`.
3. Configure the Google OAuth client redirect URI and Streamlit Cloud `[auth].redirect_uri` as:
   `https://YOUR-STREAMLIT-APP.streamlit.app/~/+/oauth2callback`
4. Install dependencies from `streamlit_app/requirements.txt`.
5. Run the Teams setup script once:
   ```bash
   cd streamlit_app
   .venv/bin/python scripts/setup_teams_sheet.py
   ```
6. Add teams, leads, members, and allocations in **Settings → Teams**.
7. Keep Streamlit Cloud password protection off. The app already uses NYU Google/OIDC login through `st.login()`, and Cloud password protection prevents automated keep-awake requests from reaching the app.

The app uses `st.login()` / `st.user`; users cannot choose their email manually.

---

## Step 8A — Configure PI My Drive Fiscal-Year Creation

The Streamlit service account can edit a shared ledger, but it has no personal
Drive quota and cannot create annual files itself. A small standalone Apps
Script runs as the PI once per minute, creates new annual Google Sheets in the
PI's **My Drive**, then shares each new workbook with the service account.

1. Ensure `clasp show-authorized-user` reports the PI's NYU account.
2. From the repository root, create and upload the dedicated script:
   ```bash
   clasp create --type standalone --title "Kamei Lab Budget Fiscal Year Creator" --rootDir gas_fiscal_year_creator
   clasp push
   ```
3. In the Apps Script editor, run `setupFiscalYearCreatorTrigger` once and
   approve the requested Drive and Sheets permissions. It installs the
   PI-owned one-minute trigger.
4. Confirm that **Settings → Fiscal Year** says the PI My Drive creator is
   ready.

The next use of **Queue Dedicated Google Sheet** writes a request to the master
ledger. The trigger creates a clean `KameiLab Budget Template` in the PI's My
Drive, then copies it for each fiscal year. The app records each resulting
Spreadsheet ID in the FY2025-26 master `Config` tab, so fiscal-year switching
always opens the correct workbook.

---

## Step 9 — Configure Claude Code Skills (optional, for power users)

The 8 skills in `.claude/skills/` are usable from the terminal via Claude Code:

```bash
cd "/Users/kkamei/Library/CloudStorage/Dropbox/Shared Folder NYUAD/Budget"
claude
```

Then use:
- `/budget-status` — live budget overview
- `/parse-invoice path/to/invoice.pdf` — parse and import a PDF
- `/add-expense` — natural language expense entry
- `/generate-report` — fiscal year report with narrative

Each skill makes API calls to the GAS web app URL. Update the `webAppUrl` variable in each skill file with your deployment URL.

---

## Annual Renewal (Fiscal Year Rollover)

See [fiscal-year-procedures.md](fiscal-year-procedures.md) for the full checklist.
See [maintenance-verification.md](maintenance-verification.md) for the required verification protocol before reporting app maintenance work as complete.

Quick version:
1. Go to **Settings → Fiscal Year** and queue `FY2026-27`.
2. Wait about one minute, then confirm the new workbook opens from Settings.
3. Go to **Budget Allocations**, select `FY2026-27`, and enter the new budget allocations.
