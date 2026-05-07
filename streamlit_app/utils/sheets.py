import streamlit as st
import gspread
from google.oauth2.service_account import Credentials
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from utils.budget import fiscal_year_for_date, LIFECYCLE_STATUSES
from utils.categories import CATEGORIES

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
    "Entry Method", "Notes", "Last Modified", "Team", "Approved By",
    "Approved At",
]

SUMMARY_COLS = [
    "Category",
    "Budgeted (AED)", "Budgeted (USD)", "Budgeted (AED equiv)",
    "Spent (AED)", "Spent (USD)", "Spent (AED equiv)",
    "Remaining (AED equiv)", "% Used", "Visual",
]

_SUMMARY_CATEGORIES = set(CATEGORIES) | {"TOTAL"}
CACHE_TTL_SECONDS = 300

@st.cache_resource
def _get_client():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return gspread.authorize(creds, http_client=gspread.BackOffHTTPClient)

@st.cache_resource(show_spinner=False)
def _open_spreadsheet(spreadsheet_id: str):
    return _get_client().open_by_key(spreadsheet_id)

def get_spreadsheet():
    try:
        return _open_spreadsheet(st.secrets["SPREADSHEET_ID"])
    except gspread.exceptions.APIError as e:
        st.error(
            f"Cannot open spreadsheet. Check that SPREADSHEET_ID is correct and "
            f"the service account has been shared on the sheet. API error: {e}"
        )
        st.stop()

def _ws(name: str):
    return get_spreadsheet().worksheet(name)

def _normalize_key(value) -> str:
    return " ".join(str(value or "").strip().casefold().split())

def _stop_on_sheet_api_error(action: str, error: gspread.exceptions.APIError):
    st.error(
        "Google Sheets read quota was reached while "
        f"{action}. Please wait about a minute and refresh. "
        "The app now caches Sheet reads to reduce repeat requests."
    )
    st.caption(f"Google Sheets API error: {error}")
    st.stop()

def ensure_transaction_columns():
    """Add lifecycle columns to Transactions header if the sheet is still on v1."""
    ws = _ws("Transactions")
    headers = ws.row_values(1)
    for col in TXN_COLUMNS:
        if col not in headers:
            ws.update_cell(1, len(headers) + 1, col)
            headers.append(col)
    return headers

# ── Read ──────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_transactions() -> pd.DataFrame:
    try:
        records = _ws("Transactions").get_all_records()
    except gspread.exceptions.APIError as e:
        _stop_on_sheet_api_error("reading Transactions", e)
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=TXN_COLUMNS)
    # Only rows with a Transaction ID
    if "Transaction ID" in df.columns:
        df = df[df["Transaction ID"].astype(str).str.strip() != ""]
    for col in TXN_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    return df

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
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
    except gspread.exceptions.APIError as e:
        _stop_on_sheet_api_error("reading Teams", e)

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_summary() -> pd.DataFrame:
    try:
        values = _ws("Summary").get_all_values()
    except gspread.exceptions.APIError as e:
        _stop_on_sheet_api_error("reading Summary", e)
    # Match rows by category name in col A — works regardless of title/header layout
    data_rows = [r for r in values if r and r[0] in _SUMMARY_CATEGORIES]
    if not data_rows:
        return pd.DataFrame(columns=SUMMARY_COLS)
    n = len(SUMMARY_COLS)
    padded = [r[:n] + [""] * (n - len(r)) for r in data_rows]
    return pd.DataFrame(padded, columns=SUMMARY_COLS)

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def get_config_values() -> list[list[str]]:
    try:
        return _ws("Config").get_all_values()
    except gspread.exceptions.APIError as e:
        _stop_on_sheet_api_error("reading Config", e)

def get_config(key: str):
    for row in get_config_values():
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
    return fiscal_year_for_date(datetime.now(DUBAI_TZ))

def append_transaction(data: dict) -> str:
    """Write one transaction row. Returns the Transaction ID."""
    ws = _ws("Transactions")
    ensure_transaction_columns()
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
        "Status": data.get("Status", "Requested"),
        "Receipt Confirmed": False,
        "PDF Link": data.get("PDF Link", ""),
        "Entered By": data.get("Entered By", ""),
        "Entry Method": data.get("Entry Method", "Manual"),
        "Notes": data.get("Notes", ""),
        "Last Modified": now_str,
        "Team": data.get("Team", ""),
        "Approved By": data.get("Approved By", ""),
        "Approved At": data.get("Approved At", ""),
    })
    if row["Status"] not in LIFECYCLE_STATUSES:
        row["Status"] = "Requested"
    ws.append_row([row[col] for col in TXN_COLUMNS])
    # Invalidate cache
    st.cache_data.clear()
    return txn_id

def update_transaction(txn_id: str, updates: dict):
    """Update specific fields of a transaction row."""
    ws = _ws("Transactions")
    ensure_transaction_columns()
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

def approve_transaction(txn_id: str, approver_email: str, status: str = "Approved"):
    """Mark a request approved by a lead or PI."""
    if status not in {"Approved", "Ordered", "Pending Review", "Delivered", "Paid", "Cancelled"}:
        status = "Approved"
    update_transaction(txn_id, {
        "Status": status,
        "Approved By": approver_email,
        "Approved At": datetime.now(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    })

def find_matching_transaction_id(txns: pd.DataFrame, candidate: dict) -> str | None:
    """Find an existing request/import row by team plus PO, invoice, or vendor."""
    if txns.empty or "Transaction ID" not in txns.columns:
        return None
    team = _normalize_key(candidate.get("Team", ""))
    scoped = txns.copy()
    if "Team" in scoped.columns:
        scoped = scoped[scoped["Team"].map(_normalize_key) == team]
    if scoped.empty:
        return None

    checks = [
        ("PO Number", candidate.get("PO Number")),
        ("Invoice Number", candidate.get("Invoice Number")),
        ("Vendor / Payee", candidate.get("Vendor / Payee")),
    ]
    for col, raw_value in checks:
        value = _normalize_key(raw_value)
        if not value or col not in scoped.columns:
            continue
        matches = scoped[scoped[col].map(_normalize_key) == value]
        if not matches.empty:
            return str(matches.iloc[0]["Transaction ID"])
    return None

def upsert_imported_transaction(data: dict) -> dict:
    """Update a matching request from an import, or append a new Pending Review row."""
    row = dict(data)
    row["Status"] = "Pending Review"
    txns = get_transactions()
    match_id = find_matching_transaction_id(txns, row)
    if match_id:
        updates = dict(row)
        updates.pop("Transaction ID", None)
        update_transaction(match_id, updates)
        return {"transaction_id": match_id, "matched": True}
    txn_id = append_transaction(row)
    return {"transaction_id": txn_id, "matched": False}

def set_budget_allocation(category: str, aed: float, usd: float):
    ws = _ws("Summary")
    all_values = ws.get_all_values()
    rate = get_exchange_rate()
    equiv = round(aed + usd * rate, 2)
    for i, row in enumerate(all_values, start=1):
        if row and row[0] == category:
            ws.update_cell(i, 2, aed)
            ws.update_cell(i, 3, usd)
            ws.update_cell(i, 4, equiv)
            st.cache_data.clear()
            return
    new_row = [category, aed, usd, equiv, 0, 0, 0, equiv, 0, ""]
    if category in CATEGORIES:
        following_categories = set(CATEGORIES[CATEGORIES.index(category) + 1 :]) | {"TOTAL"}
    else:
        following_categories = {"TOTAL"}
    insert_idx = next(
        (i for i, row in enumerate(all_values, start=1) if row and row[0] in following_categories),
        None,
    )
    if insert_idx:
        ws.insert_row(new_row, insert_idx, value_input_option="USER_ENTERED")
    else:
        ws.append_row(new_row, value_input_option="USER_ENTERED")
    st.cache_data.clear()

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
