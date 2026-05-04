# Streamlit Budget App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Google Apps Script web UI with a Python Streamlit app that connects to the same Google Sheet, adds team-based sub-budget tracking, and uses Python (no Claude API) for invoice parsing.

**Architecture:** Streamlit multi-page app hosted on Streamlit Community Cloud. All data lives in the existing Google Sheet (`KameiLab Budget FY2025-26`) accessed via gspread with a service account. Three roles (PI, Team Lead, Member) are determined by email lookup against a new `Teams` sheet tab. GAS Gmail auto-import triggers are kept unchanged.

**Tech Stack:** Python 3.11+, Streamlit 1.35+, gspread 6+, google-auth, pandas, plotly, pdfplumber, openpyxl

**Spec:** `docs/superpowers/specs/2026-05-04-streamlit-budget-app-design.md`

---

## File Map

| File | Responsibility |
|------|----------------|
| `streamlit_app/app.py` | Entry point, email login, session state, sidebar nav |
| `streamlit_app/pages/1_Dashboard.py` | Budget summary cards + monthly chart (role-filtered) |
| `streamlit_app/pages/2_Transactions.py` | Transaction table, filters, edit modal, CSV export |
| `streamlit_app/pages/3_Add_Expense.py` | Form to add a new transaction |
| `streamlit_app/pages/4_Import_Invoice.py` | PDF/Excel upload + parse preview + confirm import |
| `streamlit_app/pages/5_Reports.py` | Spending charts, category/team breakdown, CSV download |
| `streamlit_app/pages/6_Settings.py` | Budget allocations, team management, exchange rate, test mode |
| `streamlit_app/utils/sheets.py` | All gspread read/write; single source of truth for sheet access |
| `streamlit_app/utils/budget.py` | Pure calculation functions (summary, team totals, remaining) |
| `streamlit_app/utils/parse_invoice.py` | PDF + Excel parser (moved from `scripts/parse_invoice.py`) |
| `streamlit_app/utils/auth.py` | Role lookup, session helpers |
| `streamlit_app/.streamlit/config.toml` | Theme (NYUAD purple), wide layout |
| `streamlit_app/.streamlit/secrets.toml` | Service account JSON + SPREADSHEET_ID (not committed) |
| `streamlit_app/.streamlit/secrets.toml.example` | Template committed to repo |
| `streamlit_app/requirements.txt` | Python dependencies |
| `streamlit_app/tests/test_budget.py` | Unit tests for budget.py |
| `streamlit_app/tests/test_sheets.py` | Unit tests for sheets.py (mocked gspread) |
| `streamlit_app/tests/test_parse_invoice.py` | Unit tests for parse_invoice.py |
| `streamlit_app/tests/test_auth.py` | Unit tests for auth.py |

---

## Task 1: Project Scaffold

**Files:**
- Create: `streamlit_app/requirements.txt`
- Create: `streamlit_app/.streamlit/config.toml`
- Create: `streamlit_app/.streamlit/secrets.toml.example`
- Create: `streamlit_app/utils/__init__.py`
- Create: `streamlit_app/pages/__init__.py`
- Create: `streamlit_app/tests/__init__.py`

- [ ] **Step 1: Create directory structure**

```bash
cd "/Users/kkamei/Library/CloudStorage/Dropbox/Shared Folder NYUAD/Budget"
mkdir -p streamlit_app/{pages,utils,tests,.streamlit}
touch streamlit_app/utils/__init__.py
touch streamlit_app/pages/__init__.py
touch streamlit_app/tests/__init__.py
```

- [ ] **Step 2: Create requirements.txt**

Write `streamlit_app/requirements.txt`:
```
streamlit>=1.35.0
gspread>=6.0.0
google-auth>=2.28.0
pandas>=2.2.0
plotly>=5.22.0
pdfplumber>=0.11.0
openpyxl>=3.1.0
pytest>=8.0.0
```

- [ ] **Step 3: Create Streamlit config with NYUAD purple theme**

Write `streamlit_app/.streamlit/config.toml`:
```toml
[theme]
primaryColor = "#57068C"
backgroundColor = "#f8f9fa"
secondaryBackgroundColor = "#ffffff"
textColor = "#202124"
font = "sans serif"

[server]
headless = true

[browser]
gatherUsageStats = false
```

- [ ] **Step 4: Create secrets template**

Write `streamlit_app/.streamlit/secrets.toml.example`:
```toml
SPREADSHEET_ID = "1Ga6kOPohYxqQbt9ZoNXUma9Tf3cNmlxCJdvxp5edVWE"
PI_EMAIL = "ken1kamei@nyu.edu"

[gcp_service_account]
type = "service_account"
project_id = "YOUR_PROJECT_ID"
private_key_id = "YOUR_KEY_ID"
private_key = "-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----\n"
client_email = "budget-app@YOUR_PROJECT.iam.gserviceaccount.com"
client_id = "YOUR_CLIENT_ID"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "YOUR_CERT_URL"
```

- [ ] **Step 5: Add secrets.toml to .gitignore**

Append to `/Users/kkamei/Library/CloudStorage/Dropbox/Shared Folder NYUAD/Budget/.gitignore` (create if missing):
```
streamlit_app/.streamlit/secrets.toml
streamlit_app/.venv/
__pycache__/
*.pyc
.superpowers/
```

- [ ] **Step 6: Create virtual environment and install deps**

```bash
cd streamlit_app
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

Expected: packages install without errors.

- [ ] **Step 7: Commit scaffold**

```bash
cd "/Users/kkamei/Library/CloudStorage/Dropbox/Shared Folder NYUAD/Budget"
git add streamlit_app/
git commit -m "feat: scaffold streamlit app directory structure"
```

---

## Task 2: Google Service Account Setup (manual steps)

**Files:** None — this is a one-time manual setup. Output: `secrets.toml` on disk (never committed).

- [ ] **Step 1: Create a Google Cloud project (or reuse existing)**

1. Go to https://console.cloud.google.com
2. Click "New Project" → name it `kamei-lab-budget`
3. Note the **Project ID**

- [ ] **Step 2: Enable Google Sheets API**

In the project: APIs & Services → Enable APIs → search "Google Sheets API" → Enable.
Also enable "Google Drive API".

- [ ] **Step 3: Create a service account**

1. IAM & Admin → Service Accounts → Create Service Account
2. Name: `budget-app`
3. No need to grant project roles
4. Create and download a **JSON key** → save as `streamlit_app/.streamlit/secrets.toml` contents (see next step)

- [ ] **Step 4: Convert JSON key to secrets.toml**

The downloaded JSON looks like:
```json
{
  "type": "service_account",
  "project_id": "kamei-lab-budget",
  "private_key_id": "abc123",
  "private_key": "-----BEGIN RSA PRIVATE KEY-----\n...",
  ...
}
```

Copy each field into `streamlit_app/.streamlit/secrets.toml` following the example template. Also add:
```toml
SPREADSHEET_ID = "1Ga6kOPohYxqQbt9ZoNXUma9Tf3cNmlxCJdvxp5edVWE"
PI_EMAIL = "ken1kamei@nyu.edu"
```

- [ ] **Step 5: Share the Google Sheet with the service account**

1. Open https://docs.google.com/spreadsheets/d/1Ga6kOPohYxqQbt9ZoNXUma9Tf3cNmlxCJdvxp5edVWE
2. Click Share → add the service account email (format: `budget-app@kamei-lab-budget.iam.gserviceaccount.com`) as **Editor**

---

## Task 3: Add Teams Sheet + Team Column to Transactions

**Files:**
- Create: `streamlit_app/scripts/setup_teams_sheet.py`

- [ ] **Step 1: Write setup script**

Write `streamlit_app/scripts/setup_teams_sheet.py`:
```python
"""One-time script: adds Teams tab and Team column to the existing spreadsheet."""
import json, sys
from pathlib import Path
import gspread
from google.oauth2.service_account import Credentials

SCOPES = ["https://spreadsheets.google.com/feeds",
          "https://www.googleapis.com/auth/drive"]

def load_secrets():
    secrets_path = Path(__file__).parent.parent / ".streamlit" / "secrets.toml"
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib
    with open(secrets_path, "rb") as f:
        return tomllib.load(f)

def main():
    secrets = load_secrets()
    creds = Credentials.from_service_account_info(
        secrets["gcp_service_account"], scopes=SCOPES)
    gc = gspread.authorize(creds)
    ss = gc.open_by_key(secrets["SPREADSHEET_ID"])

    # 1. Add Teams sheet if not present
    sheet_names = [s.title for s in ss.worksheets()]
    if "Teams" not in sheet_names:
        teams_sheet = ss.add_worksheet("Teams", rows=50, cols=6)
        headers = ["Team Name", "Allocation (AED)", "Lead Emails",
                   "Member Emails", "Description", "Active"]
        teams_sheet.append_row(headers)
        # Format header row purple
        teams_sheet.format("A1:F1", {
            "backgroundColor": {"red": 0.341, "green": 0.024, "blue": 0.549},
            "textFormat": {"foregroundColor": {"red":1,"green":1,"blue":1},
                           "bold": True}
        })
        print("✓ Created Teams sheet")
    else:
        print("  Teams sheet already exists, skipping")

    # 2. Add Team column to Transactions if not present
    txn_sheet = ss.worksheet("Transactions")
    headers = txn_sheet.row_values(1)
    if "Team" not in headers:
        next_col = len(headers) + 1
        txn_sheet.update_cell(1, next_col, "Team")
        # Format new header cell
        col_letter = chr(64 + next_col)
        txn_sheet.format(f"{col_letter}1", {
            "backgroundColor": {"red": 0.341, "green": 0.024, "blue": 0.549},
            "textFormat": {"foregroundColor": {"red":1,"green":1,"blue":1},
                           "bold": True}
        })
        print(f"✓ Added 'Team' column at column {next_col} of Transactions sheet")
    else:
        print("  Team column already exists, skipping")

    print("\nSetup complete.")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Install tomli if needed (Python < 3.11)**

```bash
cd streamlit_app
.venv/bin/pip install tomli
```

- [ ] **Step 3: Run the setup script**

```bash
cd streamlit_app
.venv/bin/python scripts/setup_teams_sheet.py
```

Expected output:
```
✓ Created Teams sheet
✓ Added 'Team' column at column 21 of Transactions sheet
Setup complete.
```

- [ ] **Step 4: Commit script**

```bash
git add streamlit_app/scripts/
git commit -m "feat: add Teams sheet and Team column setup script"
```

---

## Task 4: sheets.py — Google Sheets Data Layer

**Files:**
- Create: `streamlit_app/utils/sheets.py`
- Create: `streamlit_app/tests/test_sheets.py`

- [ ] **Step 1: Write failing tests**

Write `streamlit_app/tests/test_sheets.py`:
```python
from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

# We patch gspread and st.secrets before importing sheets
@pytest.fixture(autouse=True)
def mock_secrets(monkeypatch):
    import streamlit as st
    monkeypatch.setattr(st, "secrets", {
        "SPREADSHEET_ID": "TEST_ID",
        "PI_EMAIL": "pi@nyu.edu",
        "gcp_service_account": {"type": "service_account"}
    })

@patch("utils.sheets.get_spreadsheet")
def test_get_transactions_returns_dataframe(mock_ss):
    from utils.sheets import get_transactions
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = [
        {"Transaction ID": "TXN-001", "Category": "Equipment",
         "Amount (AED)": 100, "Team": "Synbio", "Status": "Paid"}
    ]
    mock_ss.return_value.worksheet.return_value = mock_ws
    df = get_transactions()
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 1
    assert df.iloc[0]["Transaction ID"] == "TXN-001"

@patch("utils.sheets.get_spreadsheet")
def test_get_teams_returns_dataframe(mock_ss):
    from utils.sheets import get_teams
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = [
        {"Team Name": "Synbio", "Allocation (AED)": 400000,
         "Lead Emails": "lead@nyu.edu", "Member Emails": "ra@nyu.edu",
         "Description": "Synthetic Biology", "Active": "Y"}
    ]
    mock_ss.return_value.worksheet.return_value = mock_ws
    df = get_teams()
    assert df.iloc[0]["Team Name"] == "Synbio"
    assert df.iloc[0]["Allocation (AED)"] == 400000

@patch("utils.sheets.get_spreadsheet")
def test_append_transaction_calls_append_row(mock_ss):
    from utils.sheets import append_transaction
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = []
    mock_ws.get_all_values.return_value = [["Transaction ID"]]
    mock_ss.return_value.worksheet.return_value = mock_ws
    row_data = {"Transaction ID": "TXN-002", "Category": "Equipment",
                "Amount (AED)": 200, "Team": "Synbio"}
    append_transaction(row_data)
    mock_ws.append_row.assert_called_once()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd streamlit_app
.venv/bin/pytest tests/test_sheets.py -v 2>&1 | head -20
```

Expected: ImportError or ModuleNotFoundError (sheets.py doesn't exist yet).

- [ ] **Step 3: Write sheets.py**

Write `streamlit_app/utils/sheets.py`:
```python
import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
DUBAI_TZ = ZoneInfo("Asia/Dubai")

TXN_COLUMNS = [
    "Transaction ID", "Date", "Fiscal Year", "Category", "Sub-category",
    "Vendor / Payee", "Description", "PO Number", "Invoice Number",
    "Amount (AED)", "Amount (USD)", "Amount (AED equiv)", "Status",
    "Receipt Confirmed", "PDF Link", "Email Thread ID", "Entered By",
    "Entry Method", "Notes", "Last Modified", "Team",
]

@st.cache_resource
def _get_client():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return gspread.authorize(creds)

def get_spreadsheet():
    return _get_client().open_by_key(st.secrets["SPREADSHEET_ID"])

def _ws(name: str):
    return get_spreadsheet().worksheet(name)

# ── Read ──────────────────────────────────────────────────────────────────────

def get_transactions() -> pd.DataFrame:
    records = _ws("Transactions").get_all_records()
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=TXN_COLUMNS)
    # Only rows with a Transaction ID
    if "Transaction ID" in df.columns:
        df = df[df["Transaction ID"].astype(str).str.strip() != ""]
    return df

def get_teams() -> pd.DataFrame:
    try:
        records = _ws("Teams").get_all_records()
        return pd.DataFrame(records) if records else pd.DataFrame(
            columns=["Team Name","Allocation (AED)","Lead Emails",
                     "Member Emails","Description","Active"])
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=["Team Name","Allocation (AED)",
                                      "Lead Emails","Member Emails",
                                      "Description","Active"])

def get_summary() -> pd.DataFrame:
    records = _ws("Summary").get_all_records(head=2)  # skip title row
    return pd.DataFrame(records) if records else pd.DataFrame()

def get_config(key: str):
    ws = _ws("Config")
    records = ws.get_all_values()
    for row in records:
        if row and row[0] == key:
            return row[1] if len(row) > 1 else None
    return None

def get_exchange_rate() -> float:
    val = get_config("AED/USD Exchange Rate")
    try:
        return float(val)
    except (TypeError, ValueError):
        return 3.6725

# ── Write ─────────────────────────────────────────────────────────────────────

def _next_txn_id() -> str:
    df = get_transactions()
    date_str = datetime.now(DUBAI_TZ).strftime("%Y%m%d")
    seq = str(len(df) + 1).zfill(4)
    return f"TXN-{date_str}-{seq}"

def _current_fy() -> str:
    now = datetime.now(DUBAI_TZ)
    y, m = now.year, now.month
    return f"FY{y}-{str(y+1)[2:]}" if m >= 9 else f"FY{y-1}-{str(y)[2:]}"

def append_transaction(data: dict) -> str:
    """Write one transaction row. Returns the Transaction ID."""
    ws = _ws("Transactions")
    txn_id = data.get("Transaction ID") or _next_txn_id()
    now_str = datetime.now(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S")

    # Build row in TXN_COLUMNS order
    rate = get_exchange_rate()
    aed = float(data.get("Amount (AED)") or 0)
    usd = float(data.get("Amount (USD)") or 0)
    equiv = aed + usd * rate

    row = {col: "" for col in TXN_COLUMNS}
    row.update({
        "Transaction ID": txn_id,
        "Date": data.get("Date") or datetime.now(DUBAI_TZ).strftime("%Y-%m-%d"),
        "Fiscal Year": _current_fy(),
        "Category": data.get("Category", ""),
        "Sub-category": data.get("Sub-category", ""),
        "Vendor / Payee": data.get("Vendor / Payee", ""),
        "Description": data.get("Description", ""),
        "PO Number": data.get("PO Number", ""),
        "Invoice Number": data.get("Invoice Number", ""),
        "Amount (AED)": aed,
        "Amount (USD)": usd,
        "Amount (AED equiv)": round(equiv, 2),
        "Status": data.get("Status", "Pending Review"),
        "Receipt Confirmed": False,
        "PDF Link": data.get("PDF Link", ""),
        "Entered By": data.get("Entered By", ""),
        "Entry Method": data.get("Entry Method", "Manual"),
        "Notes": data.get("Notes", ""),
        "Last Modified": now_str,
        "Team": data.get("Team", ""),
    })
    ws.append_row([row[col] for col in TXN_COLUMNS])
    # Invalidate cache
    st.cache_data.clear()
    return txn_id

def update_transaction(txn_id: str, updates: dict):
    """Update specific fields of a transaction row."""
    ws = _ws("Transactions")
    all_values = ws.get_all_values()
    if not all_values:
        return
    headers = all_values[0]
    for i, row in enumerate(all_values[1:], start=2):
        if row and row[0] == txn_id:
            for field, value in updates.items():
                if field in headers:
                    col = headers.index(field) + 1
                    ws.update_cell(i, col, value)
            # Update Last Modified
            if "Last Modified" in headers:
                col = headers.index("Last Modified") + 1
                ws.update_cell(i, col,
                    datetime.now(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S"))
            st.cache_data.clear()
            return

def set_budget_allocation(category: str, aed: float, usd: float):
    ws = _ws("Summary")
    all_values = ws.get_all_values()
    rate = get_exchange_rate()
    for i, row in enumerate(all_values, start=1):
        if row and row[0] == category:
            equiv = aed + usd * rate
            ws.update_cell(i, 2, aed)
            ws.update_cell(i, 3, usd)
            ws.update_cell(i, 4, round(equiv, 2))
            st.cache_data.clear()
            return

def upsert_team(team_data: dict):
    """Insert or update a team row."""
    ws = _ws("Teams")
    records = ws.get_all_values()
    headers = records[0] if records else []
    team_names = [r[0] for r in records[1:]] if len(records) > 1 else []
    row = [
        team_data.get("Team Name", ""),
        team_data.get("Allocation (AED)", 0),
        team_data.get("Lead Emails", ""),
        team_data.get("Member Emails", ""),
        team_data.get("Description", ""),
        team_data.get("Active", "Y"),
    ]
    if team_data["Team Name"] in team_names:
        row_idx = team_names.index(team_data["Team Name"]) + 2
        ws.update(f"A{row_idx}:F{row_idx}", [row])
    else:
        ws.append_row(row)
    st.cache_data.clear()

def set_config(key: str, value):
    ws = _ws("Config")
    records = ws.get_all_values()
    for i, row in enumerate(records, start=1):
        if row and row[0] == key:
            ws.update_cell(i, 2, value)
            st.cache_data.clear()
            return
    ws.append_row([key, value])
    st.cache_data.clear()
```

- [ ] **Step 4: Run tests**

```bash
cd streamlit_app
.venv/bin/pytest tests/test_sheets.py -v
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add streamlit_app/utils/sheets.py streamlit_app/tests/test_sheets.py
git commit -m "feat: add sheets.py data layer with gspread"
```

---

## Task 5: budget.py — Calculations

**Files:**
- Create: `streamlit_app/utils/budget.py`
- Create: `streamlit_app/tests/test_budget.py`

- [ ] **Step 1: Write failing tests**

Write `streamlit_app/tests/test_budget.py`:
```python
import pandas as pd
import pytest
from utils.budget import (
    get_category_summary,
    get_team_summary,
    get_lab_totals,
)

CATEGORIES = ["Equipment", "Personnel", "Travel", "Other"]

def make_txns(**kwargs):
    """Build a minimal transactions DataFrame."""
    defaults = {
        "Transaction ID": ["TXN-001", "TXN-002", "TXN-003"],
        "Category":       ["Equipment", "Travel", "Equipment"],
        "Amount (AED)":   [1000.0, 500.0, 200.0],
        "Amount (USD)":   [0.0, 0.0, 0.0],
        "Amount (AED equiv)": [1000.0, 500.0, 200.0],
        "Status":         ["Paid", "Paid", "Cancelled"],
        "Team":           ["Synbio", "Imaging", "Synbio"],
        "Fiscal Year":    ["FY2025-26", "FY2025-26", "FY2025-26"],
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)

def make_summary_df():
    return pd.DataFrame({
        "Category":            ["Equipment", "Personnel", "Travel", "Other"],
        "Budgeted (AED)":      [500000.0, 300000.0, 50000.0, 30000.0],
        "Budgeted (USD)":      [0.0, 0.0, 10000.0, 5000.0],
        "Budgeted (AED equiv)":[500000.0, 300000.0, 86725.0, 48362.5],
    })

def test_category_summary_excludes_cancelled():
    txns = make_txns()
    summary_df = make_summary_df()
    result = get_category_summary(txns, summary_df, 3.6725)
    # Equipment: TXN-001 paid (1000), TXN-003 cancelled (excluded)
    assert result["Equipment"]["spent_equiv"] == 1000.0
    assert result["Equipment"]["budget_equiv"] == 500000.0

def test_category_summary_pct_used():
    txns = make_txns()
    summary_df = make_summary_df()
    result = get_category_summary(txns, summary_df, 3.6725)
    pct = result["Equipment"]["pct_used"]
    assert 0.001 < pct < 0.01  # 1000/500000 = 0.2%

def test_get_team_summary():
    txns = make_txns()
    teams_df = pd.DataFrame({
        "Team Name": ["Synbio", "Imaging"],
        "Allocation (AED)": [400000.0, 280000.0],
        "Active": ["Y", "Y"],
    })
    result = get_team_summary(txns, teams_df)
    # Synbio: TXN-001 (1000), TXN-003 cancelled → spent = 1000
    assert result["Synbio"]["spent"] == 1000.0
    assert result["Synbio"]["allocated"] == 400000.0
    assert result["Imaging"]["spent"] == 500.0

def test_get_lab_totals():
    txns = make_txns()
    summary_df = make_summary_df()
    result = get_lab_totals(txns, summary_df, 3.6725)
    assert result["total_budget"] == pytest.approx(935087.5, abs=1)
    assert result["total_spent"] == 1500.0  # 1000 + 500 (cancelled excluded)
    assert result["remaining"] == pytest.approx(935087.5 - 1500.0, abs=1)
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd streamlit_app
.venv/bin/pytest tests/test_budget.py -v 2>&1 | head -10
```

Expected: ImportError (budget.py doesn't exist).

- [ ] **Step 3: Write budget.py**

Write `streamlit_app/utils/budget.py`:
```python
import pandas as pd
from typing import Any

CATEGORIES = ["Equipment", "Personnel", "Travel", "Other"]


def get_category_summary(
    txns: pd.DataFrame,
    summary_df: pd.DataFrame,
    exchange_rate: float,
) -> dict[str, dict[str, Any]]:
    """
    Returns per-category dict with keys:
      budget_aed, budget_usd, budget_equiv,
      spent_aed, spent_usd, spent_equiv,
      remaining, pct_used
    """
    active = txns[txns["Status"] != "Cancelled"] if "Status" in txns.columns else txns
    result = {}
    for cat in CATEGORIES:
        # Budget from Summary sheet
        cat_row = summary_df[summary_df["Category"] == cat] if "Category" in summary_df.columns else pd.DataFrame()
        budget_aed   = float(cat_row["Budgeted (AED)"].iloc[0])   if not cat_row.empty else 0.0
        budget_usd   = float(cat_row["Budgeted (USD)"].iloc[0])   if not cat_row.empty else 0.0
        budget_equiv = float(cat_row["Budgeted (AED equiv)"].iloc[0]) if not cat_row.empty else budget_aed + budget_usd * exchange_rate

        # Actuals from transactions
        cat_txns    = active[active["Category"] == cat] if "Category" in active.columns else pd.DataFrame()
        spent_aed   = float(cat_txns["Amount (AED)"].sum())        if not cat_txns.empty else 0.0
        spent_usd   = float(cat_txns["Amount (USD)"].sum())        if not cat_txns.empty else 0.0
        spent_equiv = float(cat_txns["Amount (AED equiv)"].sum())  if not cat_txns.empty else 0.0

        remaining = budget_equiv - spent_equiv
        pct_used  = (spent_equiv / budget_equiv) if budget_equiv > 0 else 0.0

        result[cat] = {
            "budget_aed":   budget_aed,
            "budget_usd":   budget_usd,
            "budget_equiv": budget_equiv,
            "spent_aed":    spent_aed,
            "spent_usd":    spent_usd,
            "spent_equiv":  spent_equiv,
            "remaining":    remaining,
            "pct_used":     pct_used,
        }
    return result


def get_team_summary(
    txns: pd.DataFrame,
    teams_df: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """
    Returns per-team dict with keys: allocated, spent, remaining, pct_used
    """
    active = txns[txns["Status"] != "Cancelled"] if "Status" in txns.columns else txns
    result = {}
    active_teams = teams_df[teams_df.get("Active", pd.Series(["Y"] * len(teams_df))) == "Y"] \
        if "Active" in teams_df.columns else teams_df

    for _, team_row in active_teams.iterrows():
        name      = team_row["Team Name"]
        allocated = float(team_row.get("Allocation (AED)", 0))
        team_txns = active[active["Team"] == name] if "Team" in active.columns else pd.DataFrame()
        spent     = float(team_txns["Amount (AED equiv)"].sum()) if not team_txns.empty else 0.0
        remaining = allocated - spent
        pct_used  = (spent / allocated) if allocated > 0 else 0.0
        result[name] = {
            "allocated": allocated,
            "spent":     spent,
            "remaining": remaining,
            "pct_used":  pct_used,
        }
    return result


def get_lab_totals(
    txns: pd.DataFrame,
    summary_df: pd.DataFrame,
    exchange_rate: float,
) -> dict[str, float]:
    """Overall lab totals across all categories."""
    cat_summary = get_category_summary(txns, summary_df, exchange_rate)
    total_budget = sum(v["budget_equiv"] for v in cat_summary.values())
    total_spent  = sum(v["spent_equiv"]  for v in cat_summary.values())
    return {
        "total_budget": total_budget,
        "total_spent":  total_spent,
        "remaining":    total_budget - total_spent,
        "pct_used":     (total_spent / total_budget) if total_budget > 0 else 0.0,
    }


def monthly_spending(txns: pd.DataFrame) -> pd.DataFrame:
    """Returns DataFrame with columns: month, category, amount_equiv."""
    active = txns[txns["Status"] != "Cancelled"] if "Status" in txns.columns else txns
    if active.empty or "Date" not in active.columns:
        return pd.DataFrame(columns=["month", "category", "amount_equiv"])
    df = active.copy()
    df["month"] = pd.to_datetime(df["Date"], errors="coerce").dt.to_period("M").astype(str)
    return (
        df.groupby(["month", "Category"])["Amount (AED equiv)"]
        .sum()
        .reset_index()
        .rename(columns={"Category": "category", "Amount (AED equiv)": "amount_equiv"})
    )
```

- [ ] **Step 4: Run tests**

```bash
cd streamlit_app
.venv/bin/pytest tests/test_budget.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add streamlit_app/utils/budget.py streamlit_app/tests/test_budget.py
git commit -m "feat: add budget.py calculation utilities"
```

---

## Task 6: auth.py — Role Lookup

**Files:**
- Create: `streamlit_app/utils/auth.py`
- Create: `streamlit_app/tests/test_auth.py`

- [ ] **Step 1: Write failing tests**

Write `streamlit_app/tests/test_auth.py`:
```python
import pandas as pd
import pytest
from unittest.mock import patch

@pytest.fixture
def teams_df():
    return pd.DataFrame({
        "Team Name":    ["Synbio", "Imaging"],
        "Lead Emails":  ["lead1@nyu.edu, lead2@nyu.edu", "lead3@nyu.edu"],
        "Member Emails":["ra1@nyu.edu", "ra2@nyu.edu, ra3@nyu.edu"],
        "Active":       ["Y", "Y"],
    })

@patch("utils.auth.get_teams")
@patch("utils.auth.st")
def test_pi_role(mock_st, mock_get_teams, teams_df):
    mock_st.secrets = {"PI_EMAIL": "pi@nyu.edu"}
    mock_get_teams.return_value = teams_df
    from utils.auth import get_user_role
    role, team = get_user_role("pi@nyu.edu")
    assert role == "pi"
    assert team is None

@patch("utils.auth.get_teams")
@patch("utils.auth.st")
def test_lead_role(mock_st, mock_get_teams, teams_df):
    mock_st.secrets = {"PI_EMAIL": "pi@nyu.edu"}
    mock_get_teams.return_value = teams_df
    from utils.auth import get_user_role
    role, team = get_user_role("lead1@nyu.edu")
    assert role == "lead"
    assert team == "Synbio"

@patch("utils.auth.get_teams")
@patch("utils.auth.st")
def test_member_role(mock_st, mock_get_teams, teams_df):
    mock_st.secrets = {"PI_EMAIL": "pi@nyu.edu"}
    mock_get_teams.return_value = teams_df
    from utils.auth import get_user_role
    role, team = get_user_role("ra2@nyu.edu")
    assert role == "member"
    assert team == "Imaging"

@patch("utils.auth.get_teams")
@patch("utils.auth.st")
def test_unknown_role(mock_st, mock_get_teams, teams_df):
    mock_st.secrets = {"PI_EMAIL": "pi@nyu.edu"}
    mock_get_teams.return_value = teams_df
    from utils.auth import get_user_role
    role, team = get_user_role("stranger@nyu.edu")
    assert role == "unknown"
    assert team is None
```

- [ ] **Step 2: Run tests to confirm failure**

```bash
cd streamlit_app
.venv/bin/pytest tests/test_auth.py -v 2>&1 | head -10
```

Expected: ImportError.

- [ ] **Step 3: Write auth.py**

Write `streamlit_app/utils/auth.py`:
```python
import streamlit as st
from utils.sheets import get_teams


def get_user_role(email: str) -> tuple[str, str | None]:
    """
    Determine role from email.
    Returns (role, team_name) where role is 'pi' | 'lead' | 'member' | 'unknown'
    and team_name is None for pi/unknown.
    """
    pi_email = st.secrets.get("PI_EMAIL", "ken1kamei@nyu.edu")
    if email.strip().lower() == pi_email.strip().lower():
        return "pi", None

    teams_df = get_teams()
    if teams_df.empty:
        return "unknown", None

    for _, row in teams_df.iterrows():
        if str(row.get("Active", "Y")).strip().upper() != "Y":
            continue
        leads   = [e.strip().lower() for e in str(row.get("Lead Emails", "")).split(",") if e.strip()]
        members = [e.strip().lower() for e in str(row.get("Member Emails", "")).split(",") if e.strip()]
        if email.strip().lower() in leads:
            return "lead", str(row["Team Name"])
        if email.strip().lower() in members:
            return "member", str(row["Team Name"])

    return "unknown", None


def require_role(*allowed_roles: str):
    """Call at top of page to block access. Shows error and stops if role not allowed."""
    role = st.session_state.get("role")
    if role not in allowed_roles:
        st.error("You don't have permission to view this page.")
        st.stop()


def is_pi() -> bool:
    return st.session_state.get("role") == "pi"

def is_lead() -> bool:
    return st.session_state.get("role") == "lead"

def can_edit() -> bool:
    return st.session_state.get("role") in ("pi", "lead")

def current_team() -> str | None:
    return st.session_state.get("team")
```

- [ ] **Step 4: Run tests**

```bash
cd streamlit_app
.venv/bin/pytest tests/test_auth.py -v
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add streamlit_app/utils/auth.py streamlit_app/tests/test_auth.py
git commit -m "feat: add auth.py role lookup"
```

---

## Task 7: app.py — Entry Point + Login

**Files:**
- Create: `streamlit_app/app.py`

- [ ] **Step 1: Write app.py**

Write `streamlit_app/app.py`:
```python
import streamlit as st
from utils.auth import get_user_role

st.set_page_config(
    page_title="Kamei Lab Budget",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state initialisation ──────────────────────────────────────────────
if "email" not in st.session_state:
    st.session_state.email = None
    st.session_state.role  = None
    st.session_state.team  = None

# ── Login screen ──────────────────────────────────────────────────────────────
if not st.session_state.email:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🔬 Kamei Lab Budget")
        st.markdown("*Kamei Reverse Bioengineering Lab · NYUAD*")
        st.divider()
        email = st.text_input("Enter your nyu.edu email", placeholder="yourname@nyu.edu")
        if st.button("Sign in", type="primary", use_container_width=True):
            if not email.strip().endswith("@nyu.edu"):
                st.error("Please use your nyu.edu email address.")
            else:
                role, team = get_user_role(email.strip().lower())
                if role == "unknown":
                    st.error("Email not registered. Ask the PI to add you to the lab roster (Settings → Team Management).")
                else:
                    st.session_state.email = email.strip().lower()
                    st.session_state.role  = role
                    st.session_state.team  = team
                    st.rerun()
    st.stop()

# ── Sidebar (shown after login) ───────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"**🔬 Kamei Lab Budget**")
    st.caption(f"Logged in as: `{st.session_state.email}`")
    st.caption(f"Role: **{st.session_state.role.upper()}**"
               + (f" · {st.session_state.team}" if st.session_state.team else ""))
    st.divider()
    if st.button("Sign out", use_container_width=True):
        for key in ("email", "role", "team"):
            st.session_state[key] = None
        st.rerun()

# ── Default landing page ───────────────────────────────────────────────────────
st.markdown("## Budget Dashboard")
st.info("Select a page from the sidebar to get started.")
```

- [ ] **Step 2: Run the app locally to verify login works**

```bash
cd streamlit_app
.venv/bin/streamlit run app.py
```

Open http://localhost:8501. You should see the login screen. Enter `ken1kamei@nyu.edu` — it should load the sidebar. Enter an unknown email — should show error.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/app.py
git commit -m "feat: add app.py entry point with email login"
```

---

## Task 8: Dashboard Page

**Files:**
- Create: `streamlit_app/pages/1_Dashboard.py`

- [ ] **Step 1: Write 1_Dashboard.py**

Write `streamlit_app/pages/1_Dashboard.py`:
```python
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from utils.sheets import get_transactions, get_summary, get_exchange_rate, get_teams
from utils.budget import get_category_summary, get_team_summary, get_lab_totals, monthly_spending
from utils.auth import require_role, is_pi, current_team

require_role("pi", "lead", "member")

st.title("📊 Budget Dashboard")

# Load data
txns      = get_transactions()
summary   = get_summary()
teams_df  = get_teams()
rate      = get_exchange_rate()

# Filter to current FY
current_fy = [r for r in summary.to_dict("records") if True]  # all rows

# ── Currency toggle ───────────────────────────────────────────────────────────
currency = st.radio("Display in", ["AED", "USD"], horizontal=True)
divisor  = rate if currency == "USD" else 1.0
sym      = "$" if currency == "USD" else "AED "

# ── Role-specific view ────────────────────────────────────────────────────────
if is_pi():
    # PI: lab-wide category summary + team comparison
    cat_summary = get_category_summary(txns, summary, rate)
    totals      = get_lab_totals(txns, summary, rate)

    # Summary cards
    cols = st.columns(4)
    for i, (cat, data) in enumerate(cat_summary.items()):
        with cols[i]:
            spent  = data["spent_equiv"]  / divisor
            budget = data["budget_equiv"] / divisor
            pct    = data["pct_used"]
            color  = "🔴" if pct > 0.9 else "🟡" if pct > 0.7 else "🟢"
            st.metric(
                label=f"{color} {cat}",
                value=f"{sym}{spent:,.0f}",
                delta=f"{sym}{budget - spent / divisor:,.0f} remaining",
                delta_color="normal",
            )
            st.progress(min(pct, 1.0))

    st.divider()

    # Team comparison bar chart
    team_summary = get_team_summary(txns, teams_df)
    if team_summary:
        team_names  = list(team_summary.keys())
        spent_vals  = [v["spent"] / divisor for v in team_summary.values()]
        alloc_vals  = [v["allocated"] / divisor for v in team_summary.values()]
        fig = go.Figure(data=[
            go.Bar(name="Spent",     x=team_names, y=spent_vals,  marker_color="#57068C"),
            go.Bar(name="Allocated", x=team_names, y=alloc_vals,  marker_color="#e1bee7"),
        ])
        fig.update_layout(barmode="overlay", title="Team Spending vs Allocation",
                          yaxis_title=f"Amount ({currency})", height=300,
                          margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

else:
    # Team Lead / Member: own team card + lab totals
    team_name    = current_team()
    team_summary = get_team_summary(txns, teams_df)
    team_data    = team_summary.get(team_name, {})
    totals       = get_lab_totals(txns, summary, rate)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(f"🏷️ {team_name} — Allocated",
                  f"{sym}{team_data.get('allocated', 0) / divisor:,.0f}")
    with col2:
        st.metric(f"💸 {team_name} — Spent",
                  f"{sym}{team_data.get('spent', 0) / divisor:,.0f}")
    with col3:
        rem = team_data.get("remaining", 0)
        st.metric(f"✅ {team_name} — Remaining",
                  f"{sym}{rem / divisor:,.0f}",
                  delta_color="normal")

    st.divider()
    st.subheader("🔬 Lab-Wide Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Budget",  f"AED {totals['total_budget']:,.0f}")
    c2.metric("Total Spent",   f"AED {totals['total_spent']:,.0f}")
    c3.metric("Total Remaining", f"AED {totals['remaining']:,.0f}")

# ── Monthly spending chart (all roles) ───────────────────────────────────────
st.subheader("📈 Monthly Spending Trend")
team_filter = None if is_pi() else current_team()
filtered    = txns if is_pi() else txns[txns["Team"] == team_filter]
monthly_df  = monthly_spending(filtered)

if not monthly_df.empty:
    fig2 = px.bar(monthly_df, x="month", y="amount_equiv", color="category",
                  color_discrete_sequence=["#57068C","#9c27b0","#ce93d8","#e1bee7"],
                  labels={"amount_equiv": f"Amount (AED)", "month": "Month"},
                  title="")
    fig2.update_layout(height=280, margin=dict(t=10, b=20))
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No transaction data yet for the current fiscal year.")

# ── Recent transactions ───────────────────────────────────────────────────────
st.subheader("🕐 Recent Transactions")
display_txns = txns if is_pi() else txns[txns["Team"] == current_team()]
recent = display_txns.tail(10).iloc[::-1]  # newest first
if not recent.empty:
    show_cols = ["Date", "Vendor / Payee", "Description",
                 "Category", "Team", "Amount (AED)", "Amount (USD)", "Status"]
    show_cols = [c for c in show_cols if c in recent.columns]
    st.dataframe(recent[show_cols], use_container_width=True, hide_index=True)
else:
    st.info("No transactions yet.")
```

- [ ] **Step 2: Verify page loads**

```bash
cd streamlit_app
.venv/bin/streamlit run app.py
```

Sign in as PI email → click "1 Dashboard" in sidebar → verify cards, charts, recent table render without errors.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/1_Dashboard.py
git commit -m "feat: add Dashboard page with role-filtered views"
```

---

## Task 9: Transactions Page

**Files:**
- Create: `streamlit_app/pages/2_Transactions.py`

- [ ] **Step 1: Write 2_Transactions.py**

Write `streamlit_app/pages/2_Transactions.py`:
```python
import streamlit as st
import pandas as pd
from utils.sheets import get_transactions, get_teams, update_transaction
from utils.auth import require_role, is_pi, can_edit, current_team

require_role("pi", "lead", "member")

st.title("📋 Transactions")

txns     = get_transactions()
teams_df = get_teams()
team     = current_team()

# ── Filter to own team for non-PI ─────────────────────────────────────────────
if not is_pi() and "Team" in txns.columns:
    txns = txns[txns["Team"] == team]

# ── Filters ───────────────────────────────────────────────────────────────────
col1, col2, col3, col4 = st.columns(4)
with col1:
    cats = ["All"] + sorted(txns["Category"].dropna().unique().tolist()) if "Category" in txns.columns else ["All"]
    cat_filter = st.selectbox("Category", cats)
with col2:
    statuses = ["All"] + sorted(txns["Status"].dropna().unique().tolist()) if "Status" in txns.columns else ["All"]
    status_filter = st.selectbox("Status", statuses)
with col3:
    if is_pi() and "Team" in txns.columns:
        team_opts = ["All"] + sorted(txns["Team"].dropna().unique().tolist())
        team_filter = st.selectbox("Team", team_opts)
    else:
        team_filter = "All"
with col4:
    search = st.text_input("Search vendor / description", "")

# Apply filters
filtered = txns.copy()
if cat_filter    != "All": filtered = filtered[filtered["Category"] == cat_filter]
if status_filter != "All": filtered = filtered[filtered["Status"]   == status_filter]
if team_filter   != "All": filtered = filtered[filtered["Team"]     == team_filter]
if search:
    mask = (
        filtered.get("Vendor / Payee", pd.Series(dtype=str)).str.contains(search, case=False, na=False) |
        filtered.get("Description",    pd.Series(dtype=str)).str.contains(search, case=False, na=False)
    )
    filtered = filtered[mask]

# Sort newest first
if "Date" in filtered.columns:
    filtered = filtered.sort_values("Date", ascending=False)

st.caption(f"Showing {len(filtered)} of {len(txns)} transactions")

# ── Table ─────────────────────────────────────────────────────────────────────
SHOW_COLS = ["Transaction ID", "Date", "Category", "Team",
             "Vendor / Payee", "Description",
             "Amount (AED)", "Amount (USD)", "Status", "Entry Method"]
show_cols = [c for c in SHOW_COLS if c in filtered.columns]
st.dataframe(filtered[show_cols], use_container_width=True, hide_index=True)

# ── CSV Export ────────────────────────────────────────────────────────────────
csv = filtered[show_cols].to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Export CSV", csv, "transactions.csv", "text/csv")

# ── Edit transaction (PI + Lead only) ─────────────────────────────────────────
if can_edit():
    st.divider()
    st.subheader("✏️ Edit Transaction")
    txn_ids = filtered["Transaction ID"].tolist() if "Transaction ID" in filtered.columns else []
    if txn_ids:
        selected_id = st.selectbox("Select Transaction ID to edit", txn_ids)
        row = filtered[filtered["Transaction ID"] == selected_id].iloc[0]

        with st.form("edit_form"):
            new_status = st.selectbox("Status",
                ["Pending Review", "Ordered", "Delivered", "Paid", "Cancelled"],
                index=["Pending Review","Ordered","Delivered","Paid","Cancelled"]
                    .index(str(row.get("Status", "Pending Review"))))
            new_notes  = st.text_area("Notes", value=str(row.get("Notes", "")))
            new_pdf    = st.text_input("PDF Link", value=str(row.get("PDF Link", "")))
            submitted  = st.form_submit_button("Save Changes", type="primary")

        if submitted:
            update_transaction(selected_id, {
                "Status":   new_status,
                "Notes":    new_notes,
                "PDF Link": new_pdf,
            })
            st.success(f"✓ Updated {selected_id}")
            st.rerun()
    else:
        st.info("No transactions match the current filters.")
```

- [ ] **Step 2: Verify page loads with data**

Run app → sign in → click "2 Transactions". Verify filter dropdowns populate, table shows rows, CSV download works.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/2_Transactions.py
git commit -m "feat: add Transactions page with filters and edit"
```

---

## Task 10: Add Expense Page

**Files:**
- Create: `streamlit_app/pages/3_Add_Expense.py`

- [ ] **Step 1: Write 3_Add_Expense.py**

Write `streamlit_app/pages/3_Add_Expense.py`:
```python
import streamlit as st
from datetime import date
from utils.sheets import get_teams, get_exchange_rate, append_transaction
from utils.auth import require_role, is_pi, current_team

require_role("pi", "lead")

st.title("➕ Add Expense")

teams_df  = get_teams()
rate      = get_exchange_rate()
my_team   = current_team()

SUBCATS = {
    "Equipment":  ["Consumables","Capital Equipment","Software","Lab Supplies","Other"],
    "Personnel":  ["Research Assistant","Postdoc","Technician","Visiting Researcher","Other"],
    "Travel":     ["Conference","Field Work","Collaboration Visit","Other"],
    "Other":      ["Office Supplies","Publication Fees","Maintenance","Other"],
}

with st.form("add_expense_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        exp_date = st.date_input("Date *", value=date.today())
        category = st.selectbox("Category *", ["Equipment","Personnel","Travel","Other"])
    with col2:
        subcat   = st.selectbox("Sub-category", SUBCATS.get(category, ["Other"]))
        status   = st.selectbox("Status", ["Ordered","Delivered","Paid","Pending Review"])

    vendor      = st.text_input("Vendor / Payee *")
    description = st.text_input("Description *")

    col3, col4 = st.columns(2)
    with col3:
        po_num  = st.text_input("PO Number (optional)")
        inv_num = st.text_input("Invoice Number (optional)")
    with col4:
        aed_amt = st.number_input("Amount (AED) — 0 if paid in USD", min_value=0.0, step=0.01)
        usd_amt = st.number_input("Amount (USD) — 0 if paid in AED", min_value=0.0, step=0.01)

    if aed_amt + usd_amt > 0:
        equiv = aed_amt + usd_amt * rate
        st.caption(f"AED equivalent: **AED {equiv:,.2f}** (rate: {rate})")

    pdf_link = st.text_input("PDF Link (Google Drive URL, optional)")
    notes    = st.text_area("Notes", height=80)

    # Team field
    if is_pi():
        team_names = ["(Lab-wide / unassigned)"] + teams_df["Team Name"].tolist()
        team_sel   = st.selectbox("Team", team_names)
        team_value = "" if team_sel == "(Lab-wide / unassigned)" else team_sel
    else:
        st.info(f"Team: **{my_team}** (pre-assigned)")
        team_value = my_team

    submitted = st.form_submit_button("Add Transaction", type="primary", use_container_width=True)

if submitted:
    if not vendor.strip() or not description.strip():
        st.error("Vendor and Description are required.")
    else:
        txn_id = append_transaction({
            "Date":          exp_date.isoformat(),
            "Category":      category,
            "Sub-category":  subcat,
            "Vendor / Payee": vendor.strip(),
            "Description":   description.strip(),
            "PO Number":     po_num.strip(),
            "Invoice Number": inv_num.strip(),
            "Amount (AED)":  aed_amt,
            "Amount (USD)":  usd_amt,
            "Status":        status,
            "PDF Link":      pdf_link.strip(),
            "Notes":         notes.strip(),
            "Entered By":    st.session_state.email,
            "Entry Method":  "Manual",
            "Team":          team_value,
        })
        st.success(f"✓ Transaction added: **{txn_id}**")
        st.balloons()
```

- [ ] **Step 2: Verify form works**

Run app → Add Expense → fill in vendor + description → Submit. Check the Google Sheet Transactions tab for the new row.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/3_Add_Expense.py
git commit -m "feat: add Add Expense page with team-aware form"
```

---

## Task 11: Import Invoice Page

**Files:**
- Create: `streamlit_app/pages/4_Import_Invoice.py`
- Create: `streamlit_app/utils/parse_invoice.py` (adapted from `scripts/parse_invoice.py`)

- [ ] **Step 1: Copy and adapt parse_invoice.py to be importable**

Write `streamlit_app/utils/parse_invoice.py` (same logic as `scripts/parse_invoice.py` but without the CLI `main()` — just the parsing functions):

```python
"""
Parse invoice PDFs and NYUAD ERB Excel files.
No AI / no Claude API — uses pdfplumber + openpyxl + regex.
"""
import re
from datetime import datetime
from pathlib import Path


# ── PDF parsing ────────────────────────────────────────────────────────────────

def parse_pdf_bytes(pdf_bytes: bytes, filename: str = "") -> dict:
    """Parse PDF from bytes (for Streamlit file_uploader). Returns field dict."""
    try:
        import pdfplumber, io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text   = "\n".join(page.extract_text() or "" for page in pdf.pages)
            tables = [tbl for page in pdf.pages for tbl in page.extract_tables()]
    except Exception as e:
        return {"_error": str(e)}
    return _extract_invoice_fields(text, tables, filename)


def _extract_invoice_fields(text: str, tables: list, filename: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return {
        "vendor":         _find_vendor(lines),
        "invoice_number": _find_pattern(text, [
            r'(?:Invoice\s*(?:#|No\.?|Number)[:\s]+)([A-Z0-9\-/]+)',
            r'(?:INV|Invoice)[- ]([A-Z0-9\-/]+)',
        ]),
        "invoice_date":   _find_date(text),
        "total_amount":   _find_total(text, tables),
        "currency":       _detect_currency(text),
        "po_number":      _find_pattern(text, [
            r'(?:P\.?O\.?\s*(?:#|No\.?|Number|Order)[:\s]+)([A-Z0-9\-/]+)',
        ]),
        "suggested_category": _guess_category(text),
        "line_items":     _extract_line_items(tables),
    }

def _find_vendor(lines):
    skip = {"invoice","receipt","tax invoice","bill","statement","page",
            "date:","to:","from:","ship","bill to","sold to"}
    for line in lines[:10]:
        if line.lower() not in skip and len(line) > 3 and not line[0].isdigit():
            return line
    return ""

def _find_pattern(text, patterns):
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m: return m.group(1).strip()
    return ""

def _find_date(text):
    patterns = [
        r'(?:Invoice|Date)[:\s]+(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
        r'(\d{4}-\d{2}-\d{2})', r'(\d{1,2}/\d{1,2}/\d{4})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m: return _normalise_date(m.group(1))
    return datetime.today().strftime("%Y-%m-%d")

def _normalise_date(s):
    for fmt in ("%Y-%m-%d","%d/%m/%Y","%m/%d/%Y","%d-%m-%Y","%d.%m.%Y"):
        try: return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError: pass
    return datetime.today().strftime("%Y-%m-%d")

def _find_total(text, tables):
    for pat in [r'(?:Grand\s+)?Total[:\s]+(?:AED|USD|\$)?\s*([\d,]+\.?\d*)',
                r'Amount\s+(?:Due|Payable)[:\s]+(?:AED|USD|\$)?\s*([\d,]+\.?\d*)']:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try: return float(m.group(1).replace(",",""))
            except ValueError: pass
    for table in tables:
        for row in (table or []):
            cells = [str(c or "").strip() for c in row]
            if any(re.search(r'total', c, re.IGNORECASE) for c in cells):
                for cell in reversed(cells):
                    try:
                        v = float(re.sub(r"[^\d.]","",cell))
                        if v > 0: return v
                    except ValueError: pass
    return 0.0

def _detect_currency(text):
    if re.search(r'AED|د\.إ|Dhs\.?|Dirham', text, re.IGNORECASE): return "AED"
    if re.search(r'\$|USD|US Dollar', text): return "USD"
    return "AED"

def _guess_category(text):
    t = text.lower()
    if re.search(r'reagent|chemical|pipette|centrifug|assay|antibod|enzyme|kit|consumable|instrument|software|license', t):
        return "Equipment"
    if re.search(r'salary|stipend|postdoc|research assistant|technician', t):
        return "Personnel"
    if re.search(r'flight|hotel|conference|registration|airfare|per diem|travel', t):
        return "Travel"
    return "Other"

def _find_col(headers, keywords):
    for kw in keywords:
        for i, h in enumerate(headers):
            if kw in h.lower(): return i
    return None

def _to_float(val):
    try: return float(re.sub(r"[^\d.]","",str(val or "")))
    except ValueError: return 0.0

def _extract_line_items(tables):
    items = []
    for table in tables:
        if not table or len(table) < 2: continue
        header = [str(c or "").strip().lower() for c in table[0]]
        desc_col  = _find_col(header, ["description","item","product"])
        total_col = _find_col(header, ["total","amount"])
        qty_col   = _find_col(header, ["qty","quantity"])
        price_col = _find_col(header, ["unit price","unit cost","price"])
        if desc_col is None: continue
        for row in table[1:]:
            try:
                desc  = str(row[desc_col] or "").strip()
                total = _to_float(row[total_col]) if total_col is not None and len(row) > total_col else 0
                qty   = _to_float(row[qty_col])   if qty_col   is not None and len(row) > qty_col   else 1
                price = _to_float(row[price_col]) if price_col is not None and len(row) > price_col else 0
                if desc and total > 0:
                    items.append({"description":desc,"quantity":qty,"unit_price":price,"total":total})
            except (IndexError, TypeError): pass
    return items


# ── Excel (NYUAD ERB) parsing ──────────────────────────────────────────────────

def parse_erb_excel_bytes(excel_bytes: bytes) -> list[dict]:
    """Parse NYUAD ERB cross-charge Excel from bytes. Returns list of transaction dicts."""
    import openpyxl, io
    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
    ws = wb.active
    rows = list(ws.values)

    header_row = None
    for i, row in enumerate(rows):
        strs = [str(c or "").strip() for c in row]
        if "Long Descr" in strs or "Business Unit" in strs:
            header_row = i
            break
    if header_row is None:
        return []

    headers = [str(c or "").strip() for c in rows[header_row]]
    col     = {h: i for i, h in enumerate(headers)}
    result  = []

    for row in rows[header_row + 1:]:
        if not any(row): continue
        descr = str(row[col.get("Long Descr", -1)] or "").strip()
        if not descr: continue
        acctg = row[col.get("Acctg Date", -1)]
        date_str = acctg.strftime("%Y-%m-%d") if hasattr(acctg, "strftime") else str(acctg or "")[:10]
        aed     = float(row[col.get("Total Amount (AED)", -1)] or 0)
        order   = str(row[col.get("Order No.", -1)] or "").split(".")[0]
        sku     = str(row[col.get("Item (SKU #)", -1)] or "").strip()
        proj    = str(row[col.get("Project", -1)] or "").strip()
        dept    = str(row[col.get("Department", -1)] or "").split(".")[0]
        fund    = str(row[col.get("Fund Code", -1)] or "").split(".")[0]
        req     = str(row[col.get("Requestor Name", -1)] or "").strip()
        result.append({
            "Date":          date_str,
            "Category":      "Equipment",
            "Sub-category":  "Consumables",
            "Vendor / Payee":"NYUAD ERB (Stores)",
            "Description":   descr,
            "Amount (AED)":  aed,
            "Amount (USD)":  0,
            "Status":        "Paid",
            "Invoice Number":order,
            "PO Number":     order,
            "Entry Method":  "Excel Import",
            "Notes":         f"SKU: {sku} | Project: {proj} | Dept: {dept} | Fund: {fund} | Req: {req}",
        })
    return result
```

- [ ] **Step 2: Write 4_Import_Invoice.py**

Write `streamlit_app/pages/4_Import_Invoice.py`:
```python
import streamlit as st
from utils.sheets import get_teams, get_exchange_rate, append_transaction
from utils.parse_invoice import parse_pdf_bytes, parse_erb_excel_bytes
from utils.auth import require_role, is_pi, current_team

require_role("pi", "lead")

st.title("📥 Import Invoice / Receipt")

teams_df = get_teams()
rate     = get_exchange_rate()
my_team  = current_team()

tab1, tab2 = st.tabs(["📄 PDF Invoice", "📊 NYUAD ERB Excel"])

# ── Tab 1: PDF ────────────────────────────────────────────────────────────────
with tab1:
    st.markdown("Upload a PDF invoice or receipt. Fields are extracted automatically using Python (no AI).")
    pdf_file = st.file_uploader("Drop PDF here", type=["pdf"], key="pdf_upload")

    if pdf_file:
        with st.spinner("Parsing invoice..."):
            parsed = parse_pdf_bytes(pdf_file.read(), pdf_file.name)

        if "_error" in parsed:
            st.error(f"Parse error: {parsed['_error']}")
        else:
            conf_color = {"high":"🟢","medium":"🟡","low":"🔴"}.get("medium","🟡")
            st.success(f"Parsed successfully. Review fields below before importing.")

            with st.form("pdf_import_form"):
                col1, col2 = st.columns(2)
                with col1:
                    vendor   = st.text_input("Vendor *",     value=parsed.get("vendor",""))
                    inv_num  = st.text_input("Invoice #",    value=parsed.get("invoice_number",""))
                    inv_date = st.text_input("Date",         value=parsed.get("invoice_date",""))
                with col2:
                    category = st.selectbox("Category",
                        ["Equipment","Personnel","Travel","Other"],
                        index=["Equipment","Personnel","Travel","Other"]
                              .index(parsed.get("suggested_category","Equipment")))
                    po_num   = st.text_input("PO Number",    value=parsed.get("po_number",""))

                currency = parsed.get("currency","AED")
                total    = parsed.get("total_amount", 0.0)
                col3, col4 = st.columns(2)
                with col3:
                    aed = st.number_input("Amount (AED)", value=total if currency=="AED" else 0.0, min_value=0.0)
                with col4:
                    usd = st.number_input("Amount (USD)", value=total if currency=="USD" else 0.0, min_value=0.0)

                description = st.text_input("Description", value=pdf_file.name)
                notes       = st.text_area("Notes", value=f"Parsed by Python from {pdf_file.name}")

                if is_pi():
                    team_names = ["(Lab-wide)"] + teams_df["Team Name"].tolist()
                    team_sel   = st.selectbox("Team", team_names)
                    team_value = "" if team_sel == "(Lab-wide)" else team_sel
                else:
                    team_value = my_team
                    st.info(f"Team: **{my_team}**")

                status    = st.selectbox("Status", ["Pending Review","Ordered","Delivered","Paid"])
                submitted = st.form_submit_button("Import Transaction", type="primary")

            if submitted:
                if not vendor.strip():
                    st.error("Vendor is required.")
                else:
                    txn_id = append_transaction({
                        "Date":          inv_date,
                        "Category":      category,
                        "Vendor / Payee":vendor.strip(),
                        "Description":   description,
                        "Invoice Number":inv_num,
                        "PO Number":     po_num,
                        "Amount (AED)":  aed,
                        "Amount (USD)":  usd,
                        "Status":        status,
                        "Notes":         notes,
                        "Entry Method":  "Auto-PDF",
                        "Entered By":    st.session_state.email,
                        "Team":          team_value,
                    })
                    st.success(f"✓ Imported as **{txn_id}**")

# ── Tab 2: ERB Excel ──────────────────────────────────────────────────────────
with tab2:
    st.markdown("Upload a `ADH_COST_ACCT_CRS_CHRG_ERB_DTL_*.xlsx` file from the NYUAD cost accounting system.")
    excel_file = st.file_uploader("Drop Excel here", type=["xlsx","xls"], key="excel_upload")

    if excel_file:
        with st.spinner("Parsing Excel..."):
            rows = parse_erb_excel_bytes(excel_file.read())

        if not rows:
            st.error("No transactions found. Is this a valid ERB report?")
        else:
            st.success(f"Found **{len(rows)} row(s)**. Review below.")
            import pandas as pd
            preview_df = pd.DataFrame(rows)[["Date","Description","Amount (AED)","Notes"]]
            st.dataframe(preview_df, use_container_width=True, hide_index=True)
            total = sum(r["Amount (AED)"] for r in rows)
            st.metric("Total", f"AED {total:,.2f}")

            if is_pi():
                team_names  = ["(Lab-wide)"] + teams_df["Team Name"].tolist()
                team_sel    = st.selectbox("Assign all rows to team", team_names, key="excel_team")
                team_value  = "" if team_sel == "(Lab-wide)" else team_sel
            else:
                team_value  = my_team
                st.info(f"Team: **{my_team}**")

            if st.button(f"Import all {len(rows)} transactions", type="primary"):
                count = 0
                prog  = st.progress(0)
                for i, row in enumerate(rows):
                    row["Team"]       = team_value
                    row["Entered By"] = st.session_state.email
                    append_transaction(row)
                    count += 1
                    prog.progress((i + 1) / len(rows))
                st.success(f"✓ Imported {count} transactions.")
                st.balloons()
```

- [ ] **Step 3: Verify import works**

Run app → Import Invoice / Receipt → upload one of the sample PDFs from Drive (generated by test mode) → verify parsed fields appear → click Import.

- [ ] **Step 4: Commit**

```bash
git add streamlit_app/utils/parse_invoice.py streamlit_app/pages/4_Import_Invoice.py
git commit -m "feat: add Import Invoice page with PDF and ERB Excel parsing"
```

---

## Task 12: Reports Page

**Files:**
- Create: `streamlit_app/pages/5_Reports.py`

- [ ] **Step 1: Write 5_Reports.py**

Write `streamlit_app/pages/5_Reports.py`:
```python
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from utils.sheets import get_transactions, get_summary, get_exchange_rate, get_teams
from utils.budget import get_category_summary, get_team_summary, get_lab_totals, monthly_spending
from utils.auth import require_role, is_pi, current_team

require_role("pi", "lead", "member")

st.title("📈 Reports")

txns     = get_transactions()
summary  = get_summary()
teams_df = get_teams()
rate     = get_exchange_rate()
team     = current_team()

# Filter for non-PI
team_txns = txns if is_pi() else txns[txns["Team"] == team] if "Team" in txns.columns else txns

# ── Summary table ─────────────────────────────────────────────────────────────
st.subheader("Budget Summary")
cat_summary = get_category_summary(txns, summary, rate)
totals      = get_lab_totals(txns, summary, rate)

summary_rows = []
for cat, data in cat_summary.items():
    summary_rows.append({
        "Category":           cat,
        "Budget (AED equiv)": f"AED {data['budget_equiv']:,.0f}",
        "Spent (AED equiv)":  f"AED {data['spent_equiv']:,.0f}",
        "Remaining":          f"AED {data['remaining']:,.0f}",
        "% Used":             f"{data['pct_used']*100:.1f}%",
    })
summary_rows.append({
    "Category":           "**TOTAL**",
    "Budget (AED equiv)": f"**AED {totals['total_budget']:,.0f}**",
    "Spent (AED equiv)":  f"**AED {totals['total_spent']:,.0f}**",
    "Remaining":          f"**AED {totals['remaining']:,.0f}**",
    "% Used":             f"**{totals['pct_used']*100:.1f}%**",
})
st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

# ── Charts ────────────────────────────────────────────────────────────────────
col1, col2 = st.columns(2)

with col1:
    st.subheader("Spending by Category")
    pie_data = {cat: data["spent_equiv"] for cat, data in cat_summary.items() if data["spent_equiv"] > 0}
    if pie_data:
        fig = px.pie(values=list(pie_data.values()), names=list(pie_data.keys()),
                     color_discrete_sequence=["#57068C","#9c27b0","#ce93d8","#e1bee7"],
                     hole=0.35)
        fig.update_layout(height=300, margin=dict(t=10,b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No spending data yet.")

with col2:
    if is_pi():
        st.subheader("Team Spending vs Allocation")
        team_summary = get_team_summary(txns, teams_df)
        if team_summary:
            names  = list(team_summary.keys())
            spent  = [v["spent"]     for v in team_summary.values()]
            alloc  = [v["allocated"] for v in team_summary.values()]
            fig2 = go.Figure(data=[
                go.Bar(name="Spent",     x=names, y=spent, marker_color="#57068C"),
                go.Bar(name="Allocated", x=names, y=alloc, marker_color="#e1bee7"),
            ])
            fig2.update_layout(barmode="overlay", height=300, margin=dict(t=10,b=10))
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.subheader(f"{team} — Spending Trend")
        monthly_df = monthly_spending(team_txns)
        if not monthly_df.empty:
            fig3 = px.line(monthly_df, x="month", y="amount_equiv", color="category",
                           color_discrete_sequence=["#57068C","#9c27b0","#ce93d8","#e1bee7"])
            fig3.update_layout(height=300, margin=dict(t=10,b=10))
            st.plotly_chart(fig3, use_container_width=True)

# ── Monthly trend (all) ───────────────────────────────────────────────────────
st.subheader("Monthly Spending Trend")
monthly_df = monthly_spending(team_txns)
if not monthly_df.empty:
    fig4 = px.bar(monthly_df, x="month", y="amount_equiv", color="category",
                  color_discrete_sequence=["#57068C","#9c27b0","#ce93d8","#e1bee7"],
                  labels={"amount_equiv":"Amount (AED)","month":"Month"})
    fig4.update_layout(height=320, margin=dict(t=10,b=20))
    st.plotly_chart(fig4, use_container_width=True)

# ── Download ──────────────────────────────────────────────────────────────────
st.divider()
csv = team_txns.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download all transactions (CSV)", csv, "report.csv", "text/csv")
```

- [ ] **Step 2: Verify**

Run app → Reports → verify charts render, table shows TOTAL row, CSV downloads.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/5_Reports.py
git commit -m "feat: add Reports page with charts and CSV download"
```

---

## Task 13: Settings Page

**Files:**
- Create: `streamlit_app/pages/6_Settings.py`

- [ ] **Step 1: Write 6_Settings.py**

Write `streamlit_app/pages/6_Settings.py`:
```python
import streamlit as st
import pandas as pd
from utils.sheets import (get_teams, get_exchange_rate, get_summary,
                           set_budget_allocation, upsert_team, set_config,
                           get_transactions, append_transaction, update_transaction)
from utils.auth import require_role

require_role("pi")

st.title("⚙️ Settings")

tab1, tab2, tab3, tab4 = st.tabs([
    "💰 Budget Allocations", "👥 Teams", "🔧 Exchange Rate", "🧪 Test Mode"
])

# ── Tab 1: Budget Allocations ─────────────────────────────────────────────────
with tab1:
    st.markdown("Set the lab budget per category for the current fiscal year.")
    summary_df = get_summary()
    CATEGORIES = ["Equipment", "Personnel", "Travel", "Other"]

    with st.form("budget_alloc_form"):
        st.markdown("**Enter amounts in AED, USD, or both:**")
        alloc_data = {}
        for cat in CATEGORIES:
            row = summary_df[summary_df["Category"] == cat] if "Category" in summary_df.columns else pd.DataFrame()
            curr_aed = float(row["Budgeted (AED)"].iloc[0]) if not row.empty else 0.0
            curr_usd = float(row["Budgeted (USD)"].iloc[0]) if not row.empty else 0.0
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.markdown(f"**{cat}**")
            aed = c2.number_input(f"AED##{cat}", value=curr_aed, min_value=0.0, step=1000.0, label_visibility="collapsed")
            usd = c3.number_input(f"USD##{cat}", value=curr_usd, min_value=0.0, step=1000.0, label_visibility="collapsed")
            alloc_data[cat] = (aed, usd)
        if st.form_submit_button("Save Allocations", type="primary"):
            for cat, (aed, usd) in alloc_data.items():
                set_budget_allocation(cat, aed, usd)
            st.success("✓ Budget allocations saved.")

# ── Tab 2: Team Management ────────────────────────────────────────────────────
with tab2:
    st.markdown("Manage lab teams. Team leads can add/edit transactions for their team.")
    teams_df = get_teams()

    if not teams_df.empty:
        st.dataframe(teams_df, use_container_width=True, hide_index=True)
    else:
        st.info("No teams defined yet.")

    st.divider()
    st.markdown("**Add / Update Team:**")
    with st.form("team_form"):
        team_names_existing = teams_df["Team Name"].tolist() if not teams_df.empty else []
        team_name  = st.text_input("Team Name *")
        allocation = st.number_input("Total Allocation (AED)", min_value=0.0, step=1000.0)
        lead_emails   = st.text_input("Lead Emails (comma-separated nyu.edu)", placeholder="lead@nyu.edu, lead2@nyu.edu")
        member_emails = st.text_input("Member Emails (comma-separated nyu.edu)", placeholder="ra@nyu.edu")
        description   = st.text_input("Description (optional)")
        active        = st.selectbox("Active", ["Y", "N"])
        if st.form_submit_button("Save Team", type="primary"):
            if not team_name.strip():
                st.error("Team Name is required.")
            else:
                upsert_team({
                    "Team Name":       team_name.strip(),
                    "Allocation (AED)":allocation,
                    "Lead Emails":     lead_emails.strip(),
                    "Member Emails":   member_emails.strip(),
                    "Description":     description.strip(),
                    "Active":          active,
                })
                st.success(f"✓ Team '{team_name}' saved.")
                st.rerun()

# ── Tab 3: Exchange Rate ──────────────────────────────────────────────────────
with tab3:
    current_rate = get_exchange_rate()
    st.metric("Current AED/USD Rate", f"1 USD = {current_rate} AED")
    with st.form("rate_form"):
        new_rate = st.number_input("New Rate (1 USD = ? AED)",
                                   value=current_rate, min_value=0.001, step=0.0001, format="%.4f")
        if st.form_submit_button("Update Rate", type="primary"):
            set_config("AED/USD Exchange Rate", new_rate)
            st.success(f"✓ Rate updated to {new_rate}")

# ── Tab 4: Test Mode ──────────────────────────────────────────────────────────
with tab4:
    st.warning("⚠️ Test mode loads sample data tagged with `[TEST]`. Remove it cleanly when done.")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🧪 Load Dummy Data", use_container_width=True):
            from datetime import date, timedelta
            samples = [
                {"Date": (date.today() - timedelta(days=80)).isoformat(), "Category":"Equipment",
                 "Vendor / Payee":"Fisher Scientific","Description":"Pipette tips 1000uL",
                 "Amount (AED)":3450,"Amount (USD)":0,"Status":"Delivered","Team":"","Entry Method":"Manual",
                 "Notes":"[TEST] Auto-generated"},
                {"Date": (date.today() - timedelta(days=60)).isoformat(), "Category":"Travel",
                 "Vendor / Payee":"Emirates Airlines","Description":"AUH-BOS-AUH conference",
                 "Amount (AED)":0,"Amount (USD)":1850,"Status":"Paid","Team":"","Entry Method":"Manual",
                 "Notes":"[TEST] Auto-generated"},
                {"Date": (date.today() - timedelta(days=30)).isoformat(), "Category":"Personnel",
                 "Vendor / Payee":"Postdoc — October","Description":"Monthly stipend",
                 "Amount (AED)":18000,"Amount (USD)":0,"Status":"Paid","Team":"","Entry Method":"Manual",
                 "Notes":"[TEST] Auto-generated"},
            ]
            set_budget_allocation("Equipment", 500000, 0)
            set_budget_allocation("Personnel", 300000, 0)
            set_budget_allocation("Travel",     50000, 10000)
            set_budget_allocation("Other",      30000,  5000)
            for s in samples:
                s["Entered By"] = st.session_state.email
                append_transaction(s)
            st.success(f"✓ Loaded {len(samples)} test transactions and budget allocations.")

    with col2:
        if st.button("🗑️ Clear All Test Data", type="secondary", use_container_width=True):
            txns = get_transactions()
            if "Notes" in txns.columns:
                test_ids = txns[txns["Notes"].str.contains(r"\[TEST\]", na=False)]["Transaction ID"].tolist()
                for txn_id in test_ids:
                    update_transaction(txn_id, {"Status": "Cancelled"})
                for cat in ["Equipment","Personnel","Travel","Other"]:
                    set_budget_allocation(cat, 0, 0)
                st.success(f"✓ Cancelled {len(test_ids)} test transactions and reset allocations.")
            else:
                st.info("No transactions found.")
```

- [ ] **Step 2: Verify settings work**

Run app → Settings → add a team (e.g., "Synbio", AED 400000, lead email = your nyu.edu email). Reload → verify Teams tab shows the new row.

- [ ] **Step 3: Commit**

```bash
git add streamlit_app/pages/6_Settings.py
git commit -m "feat: add Settings page with team management and test mode"
```

---

## Task 14: Run All Tests

- [ ] **Step 1: Run full test suite**

```bash
cd streamlit_app
.venv/bin/pytest tests/ -v
```

Expected: all tests in `test_budget.py`, `test_sheets.py`, `test_auth.py` PASS.

- [ ] **Step 2: Fix any failures**

If a test fails, fix the implementation (not the test). Re-run until all PASS.

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "test: all unit tests passing"
```

---

## Task 15: Deploy to Streamlit Community Cloud

- [ ] **Step 1: Push to GitHub**

The Streamlit Community Cloud deploys from a GitHub repo.

```bash
# If no remote yet:
gh repo create kamei-lab-budget --private
git remote add origin https://github.com/YOUR_USERNAME/kamei-lab-budget.git
git push -u origin main
```

- [ ] **Step 2: Create the app on Streamlit Community Cloud**

1. Go to https://share.streamlit.io → "New app"
2. Connect your GitHub account
3. Select repo: `kamei-lab-budget`
4. Branch: `main`
5. Main file path: `streamlit_app/app.py`
6. Click "Advanced settings" → paste the full contents of your local `secrets.toml` into the Secrets field
7. Click "Deploy"

- [ ] **Step 3: Set the password**

1. In the Streamlit Cloud dashboard → Settings → Sharing
2. Enable "Password protection"
3. Set a strong shared password
4. Share the URL + password with lab members

- [ ] **Step 4: Verify live deployment**

Open the deployed URL → sign in with the password → enter your nyu.edu email → verify Dashboard loads with real data from the Google Sheet.

- [ ] **Step 5: Update CLAUDE.md with new commands**

Edit `CLAUDE.md` — add a section:

```markdown
## Python Streamlit App

Location: `streamlit_app/`

### Run locally
```bash
cd streamlit_app
.venv/bin/streamlit run app.py
```

### Run tests
```bash
cd streamlit_app
.venv/bin/pytest tests/ -v
```

### Deploy
Deployed on Streamlit Community Cloud. Push to `main` branch on GitHub to trigger redeploy.
Secrets stored in Streamlit Cloud dashboard (not in repo).
```

- [ ] **Step 6: Final commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with Streamlit app commands"
git push
```

---

## Self-Review

**Spec coverage check:**
- ✅ Streamlit + gspread + service account auth → Tasks 1, 2, 4
- ✅ Teams sheet + Team column in Transactions → Task 3
- ✅ Role system (pi / lead / member) → Task 6
- ✅ Email login flow → Task 7
- ✅ Dashboard with role-filtered views → Task 8
- ✅ Transactions with filters + edit → Task 9
- ✅ Add Expense with team field → Task 10
- ✅ PDF + ERB Excel import (no Claude API) → Task 11
- ✅ Reports with charts + CSV → Task 12
- ✅ Settings with team management + test mode → Task 13
- ✅ Deploy to Streamlit Community Cloud with password → Task 15
- ✅ GAS triggers kept (not touched in this plan — intentional)

**Placeholder scan:** No TBDs, no "implement later", no vague steps — all code blocks present.

**Type consistency:** `get_user_role` returns `(str, str | None)` — used consistently in `auth.py` and `app.py`. `append_transaction` takes a `dict` and returns `str` (txn_id) — consistent in Tasks 10, 11, 13. `get_category_summary` returns `dict[str, dict[str, Any]]` — consistent in Tasks 8, 12.
