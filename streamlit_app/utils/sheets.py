import streamlit as st
import base64
import gspread
import hashlib
import json
import os
import re
import secrets
from pathlib import Path
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import AuthorizedSession
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from utils.budget import (
    fiscal_year_for_date,
    DEFAULT_AED_USD_EXCHANGE_RATE,
    DEFAULT_RATES_TO_USD,
    LIFECYCLE_STATUSES,
    canonical_budget_status,
    normalize_aed_equivalent,
    normalize_usd_equivalent,
    round_currency,
    SUPPORTED_CURRENCIES,
    to_aed_equivalent,
    to_usd_equivalent,
)
from utils.categories import CATEGORIES

SCOPES = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/drive",
]
DUBAI_TZ = ZoneInfo("Asia/Dubai")

TXN_COLUMNS = [
    "Transaction ID", "Date", "Fiscal Year", "Category", "Sub-category",
    "Vendor / Payee", "Description", "PO Number", "Invoice Number",
    "Currency", "Amount", "Amount (USD equiv)",
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
BASE_SPREADSHEET_SECRET = "SPREADSHEET_ID"
DEFAULT_REGISTRY_SPREADSHEET_ID = "1gZU_0tG10O2JuliAq6Hdy3GONVCSBAAuiQAKXNug2Lk"
STREAMLIT_CLOUD_HOME = "/home/adminuser"
STREAMLIT_CLOUD_SOURCE_ROOT = "/mount/src"
FY_SPREADSHEET_CONFIG_PREFIX = "Spreadsheet ID "
FISCAL_YEAR_TEMPLATE_CONFIG_KEY = "Fiscal Year Template Spreadsheet ID"
FISCAL_YEAR_TEMPLATE_TITLE = "KameiLab Budget Template"
FISCAL_YEAR_WORKSHEET_NAMES = ("Transactions", "Summary", "Teams", "Config")
FISCAL_YEAR_SHARED_DRIVE_FOLDER_CONFIG_KEY = "Fiscal Year Shared Drive Folder ID"
GOOGLE_SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
TEAM_COLUMNS = [
    "Team Name",
    "Allocation (AED)",
    "Allocation (USD)",
    "Budget Manager Emails",
    "Budget Manager Names",
    "Lead Emails",
    "Lead Names",
    "Member Emails",
    "Member Names",
    "Description",
    "Active",
]

@st.cache_resource
def _get_credentials():
    return Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )

@st.cache_resource
def _get_client():
    return gspread.authorize(_get_credentials(), http_client=gspread.BackOffHTTPClient)

@st.cache_resource
def _drive_session():
    return AuthorizedSession(_get_credentials())

@st.cache_resource(show_spinner=False)
def _open_spreadsheet(spreadsheet_id: str):
    return _get_client().open_by_key(spreadsheet_id)

def _base_spreadsheet_id() -> str:
    return st.secrets[BASE_SPREADSHEET_SECRET]

def _base_spreadsheet():
    return _open_spreadsheet(_base_spreadsheet_id())

def _base_ws(name: str):
    return _base_spreadsheet().worksheet(name)

@st.cache_data(ttl=60, show_spinner=False)
def _base_config_values() -> list[list[str]]:
    return _base_ws("Config").get_all_values()

def _base_config_map() -> dict[str, str]:
    return {
        str(row[0]): (row[1] if len(row) > 1 else "")
        for row in _base_config_values()
        if row
    }

def _read_config_from_base(key: str):
    try:
        return _base_config_map().get(key)
    except Exception:
        return None

def get_base_config(key: str):
    return _read_config_from_base(key)

def _set_config_in_base(key: str, value) -> None:
    ws = _base_ws("Config")
    records = ws.get_all_values()
    for i, row in enumerate(records, start=1):
        if row and row[0] == key:
            ws.update_cell(i, 2, value)
            st.cache_data.clear()
            return
    ws.append_row([key, value], value_input_option="USER_ENTERED")
    st.cache_data.clear()

def set_base_config(key: str, value) -> None:
    _set_config_in_base(key, value)

def _default_fiscal_year() -> str:
    return fiscal_year_for_date(datetime.now(DUBAI_TZ))

def get_active_fiscal_year() -> str:
    return st.session_state.get("selected_fiscal_year") or _default_fiscal_year()

def fiscal_year_options() -> list[str]:
    options = {_default_fiscal_year(), get_active_fiscal_year()}
    try:
        for key, value in _base_config_map().items():
            if key.startswith(FY_SPREADSHEET_CONFIG_PREFIX):
                options.add(key.removeprefix(FY_SPREADSHEET_CONFIG_PREFIX))
            elif key in {"Current Fiscal Year", "Fiscal Year"} and str(value).startswith("FY"):
                options.add(str(value))
    except Exception:
        pass
    current = _default_fiscal_year()
    try:
        start_year = int(current[2:6])
        options.add(f"FY{start_year - 1}-{str(start_year)[2:]}")
        options.add(f"FY{start_year + 1}-{str(start_year + 2)[2:]}")
    except (ValueError, IndexError):
        pass
    return sorted(options, reverse=True)

def _spreadsheet_id_for_fiscal_year(fiscal_year: str) -> str | None:
    return _read_config_from_base(f"{FY_SPREADSHEET_CONFIG_PREFIX}{fiscal_year}")

def fiscal_year_template_id() -> str | None:
    return _read_config_from_base(FISCAL_YEAR_TEMPLATE_CONFIG_KEY)

def fiscal_year_shared_drive_folder_id() -> str | None:
    value = str(_read_config_from_base(FISCAL_YEAR_SHARED_DRIVE_FOLDER_CONFIG_KEY) or "").strip()
    match = re.search(r"/folders/([^/?#]+)", value)
    return match.group(1) if match else value or None

def _require_fiscal_year_shared_drive_folder() -> str:
    folder_id = fiscal_year_shared_drive_folder_id()
    if not folder_id:
        raise RuntimeError(
            "Set a Shared Drive folder in Settings > Fiscal Year before creating a new fiscal-year workbook."
        )
    try:
        response = _drive_session().get(
            f"https://www.googleapis.com/drive/v3/files/{folder_id}",
            params={"supportsAllDrives": "true", "fields": "id,driveId,capabilities(canAddChildren)"},
            timeout=30,
        )
    except Exception as error:
        raise RuntimeError(f"Could not validate the Shared Drive folder: {error}") from error
    if not 200 <= response.status_code < 300:
        raise _drive_copy_error(response)
    metadata = response.json()
    if not metadata.get("driveId"):
        raise RuntimeError(
            "The configured folder is not in a Google Shared Drive. Use a research-group Shared Drive folder."
        )
    if not metadata.get("capabilities", {}).get("canAddChildren", False):
        raise RuntimeError(
            "The service account cannot create files in the configured Shared Drive folder. "
            "Grant it Content Manager access."
        )
    return folder_id

@st.cache_data(ttl=60, show_spinner=False)
def fiscal_year_shared_drive_status() -> tuple[bool, str]:
    try:
        folder_id = _require_fiscal_year_shared_drive_folder()
        return True, f"Shared Drive folder verified: {folder_id}"
    except RuntimeError as error:
        return False, str(error)

def _existing_spreadsheet_id_for_fiscal_year(fiscal_year: str | None) -> str | None:
    fy = fiscal_year or get_active_fiscal_year()
    registered_id = _spreadsheet_id_for_fiscal_year(fy)
    if registered_id:
        return registered_id
    base_id = _base_spreadsheet_id()
    base_fy = _read_config_from_base("Current Fiscal Year") or _read_config_from_base("Fiscal Year")
    if not base_fy or fy == base_fy:
        return base_id
    return None

def fiscal_year_spreadsheet_ready(fiscal_year: str | None = None) -> bool:
    return bool(_existing_spreadsheet_id_for_fiscal_year(fiscal_year))

def _register_fiscal_year_spreadsheet(fiscal_year: str, spreadsheet_id: str) -> None:
    _set_config_in_base(f"{FY_SPREADSHEET_CONFIG_PREFIX}{fiscal_year}", spreadsheet_id)

def _base_fiscal_year() -> str | None:
    return _read_config_from_base("Current Fiscal Year") or _read_config_from_base("Fiscal Year")

def fiscal_year_uses_legacy_tabs(fiscal_year: str | None = None) -> bool:
    fy = fiscal_year or get_active_fiscal_year()
    return bool(
        fy
        and _spreadsheet_id_for_fiscal_year(fy) == _base_spreadsheet_id()
        and fy != _base_fiscal_year()
    )

def _uses_fiscal_year_tabs(fiscal_year: str | None = None) -> bool:
    return fiscal_year_uses_legacy_tabs(fiscal_year)

def _worksheet_name(name: str, fiscal_year: str | None = None) -> str:
    return f"{name} {fiscal_year}" if fiscal_year and _uses_fiscal_year_tabs(fiscal_year) else name

def _clear_new_fiscal_year_transactions(ss, fiscal_year: str) -> None:
    try:
        ws = ss.worksheet("Transactions")
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet("Transactions", rows=1000, cols=len(TXN_COLUMNS))
    _ensure_sheet_columns(ws, len(TXN_COLUMNS))
    end_col = _column_label(len(TXN_COLUMNS))
    ws.update(f"A1:{end_col}1", [TXN_COLUMNS])
    if getattr(ws, "row_count", 0) and ws.row_count > 1:
        ws.batch_clear([f"A2:{end_col}{ws.row_count}"])
    try:
        summary_ws = ss.worksheet("Summary")
        values = summary_ws.get_all_values()
        updates = []
        for i, row in enumerate(values, start=1):
            if row and row[0] in _SUMMARY_CATEGORIES:
                budget_equiv = row[3] if len(row) > 3 else ""
                updates.append(
                    {
                        "range": f"E{i}:I{i}",
                        "values": [[0, 0, 0, budget_equiv, 0]],
                    }
                )
        if updates:
            summary_ws.batch_update(updates, value_input_option="USER_ENTERED")
    except gspread.exceptions.WorksheetNotFound:
        pass
    try:
        config_ws = ss.worksheet("Config")
        records = config_ws.get_all_values()
        found = False
        for i, row in enumerate(records, start=1):
            if row and row[0] in {"Current Fiscal Year", "Fiscal Year"}:
                config_ws.update_cell(i, 2, fiscal_year)
                found = True
        if not found:
            config_ws.append_row(["Current Fiscal Year", fiscal_year], value_input_option="USER_ENTERED")
    except gspread.exceptions.WorksheetNotFound:
        pass

def _replace_worksheet_values(ws, columns: list[str], rows: list[list] | None = None) -> None:
    rows = rows or []
    _ensure_sheet_columns(ws, len(columns))
    ws.clear()
    ws.update([columns] + rows, value_input_option="USER_ENTERED")

def _worksheet_for_new_ledger(ss, name: str, rows: int, cols: int, *, use_default: bool = False):
    if use_default:
        ws = ss.sheet1
        if ws.title != name:
            ws.update_title(name)
        return ws
    try:
        return ss.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        return ss.add_worksheet(name, rows=rows, cols=cols)

def _ensure_worksheet_values(ss, name: str, columns: list[str], rows: list[list] | None = None):
    rows = rows or []
    try:
        return ss.worksheet(name)
    except gspread.exceptions.WorksheetNotFound:
        ws = ss.add_worksheet(name, rows=max(len(rows) + 10, 100), cols=max(len(columns), 1))
        _replace_worksheet_values(ws, columns, rows)
        return ws

def _config_rows_for_fiscal_year(fiscal_year: str) -> list[list[str]]:
    rows = []
    try:
        rows = _base_ws("Config").get_all_values()
    except Exception:
        rows = []
    output = []
    seen = set()
    for row in rows:
        if not row:
            continue
        key = str(row[0])
        value = row[1] if len(row) > 1 else ""
        if key.startswith(FY_SPREADSHEET_CONFIG_PREFIX) or key == FISCAL_YEAR_TEMPLATE_CONFIG_KEY:
            continue
        if key in {"Current Fiscal Year", "Fiscal Year"}:
            value = fiscal_year
        output.append([key, value])
        seen.add(key)
    for key, value in (
        ("Current Fiscal Year", fiscal_year),
        ("Fiscal Year", fiscal_year),
        ("AED/USD Exchange Rate", DEFAULT_AED_USD_EXCHANGE_RATE),
        ("EUR/USD Exchange Rate", DEFAULT_RATES_TO_USD["EUR"]),
        ("JPY/USD Exchange Rate", DEFAULT_RATES_TO_USD["JPY"]),
        ("GBP/USD Exchange Rate", DEFAULT_RATES_TO_USD["GBP"]),
        ("Notification Threshold %", 80),
        ("Gmail Label", "Budget/Invoices"),
    ):
        if key not in seen:
            output.append([key, value])
    return output

def _blank_summary_rows() -> list[list]:
    summary_rows = [[category, 0, 0, 0, 0, 0, 0, 0, 0, ""] for category in CATEGORIES]
    summary_rows.append(["TOTAL", 0, 0, 0, 0, 0, 0, 0, 0, ""])
    return summary_rows

def _remove_legacy_fiscal_year_tabs(ss) -> None:
    for ws in ss.worksheets():
        if re.fullmatch(r"(?:Transactions|Summary|Teams|Config) FY\d{4}-\d{2}", ws.title):
            ss.del_worksheet(ws)

def _blank_team_rows(ws) -> list[list]:
    try:
        records = ws.get_all_records()
    except Exception:
        records = []
    rows = []
    for record in records:
        if not str(record.get("Team Name", "")).strip():
            continue
        row = [record.get(column, "") for column in TEAM_COLUMNS]
        row[TEAM_COLUMNS.index("Allocation (AED)")] = 0
        row[TEAM_COLUMNS.index("Allocation (USD)")] = 0
        rows.append(row)
    return rows

def _initialize_new_fiscal_year_workbook(ss, fiscal_year: str) -> None:
    """Reset a copied template while retaining worksheet formatting and team roster."""
    _remove_legacy_fiscal_year_tabs(ss)
    txn_ws = _worksheet_for_new_ledger(ss, "Transactions", 1000, len(TXN_COLUMNS))
    _replace_worksheet_values(txn_ws, TXN_COLUMNS)

    summary_ws = _worksheet_for_new_ledger(ss, "Summary", max(len(CATEGORIES) + 10, 100), len(SUMMARY_COLS))
    _replace_worksheet_values(summary_ws, SUMMARY_COLS, _blank_summary_rows())

    teams_ws = _worksheet_for_new_ledger(ss, "Teams", 1000, len(TEAM_COLUMNS))
    _replace_worksheet_values(teams_ws, TEAM_COLUMNS, _blank_team_rows(teams_ws))

    config_ws = _worksheet_for_new_ledger(ss, "Config", 100, 2)
    _replace_worksheet_values(config_ws, ["Key", "Value"], _config_rows_for_fiscal_year(fiscal_year))
    st.cache_data.clear()

def _share_with_pi(ss) -> None:
    email = str(st.secrets.get("PI_EMAIL", "") or "").strip()
    if not email:
        return
    try:
        ss.share(email, perm_type="user", role="writer", notify=False)
    except Exception:
        # The copy remains usable by the app service account even if the PI is
        # already an owner/editor or the domain blocks duplicate invitations.
        pass

def _drive_copy_error(response) -> RuntimeError:
    try:
        payload = response.json().get("error", {})
        message = str(payload.get("message", "") or "")
        reasons = ", ".join(
            str(item.get("reason", "")) for item in payload.get("errors", []) if item.get("reason")
        )
    except Exception:
        message = ""
        reasons = ""
    status = int(getattr(response, "status_code", 0) or 0)
    if status == 403 and ("storageQuota" in reasons or "quota" in message.lower()):
        return RuntimeError(
            "Google Drive cannot create the workbook in the service account's My Drive. "
            "Set a Shared Drive folder in Settings > Fiscal Year and add the service account as a Content Manager."
        )
    if status in {403, 404} and fiscal_year_shared_drive_folder_id():
        return RuntimeError(
            "The configured Shared Drive folder is not accessible to the service account. "
            "Confirm the folder is in a Shared Drive and grant the service account Content Manager access."
        )
    detail = message or reasons or "Unknown Google Drive error"
    return RuntimeError(f"Google Drive could not copy the fiscal-year workbook (HTTP {status}): {detail}")

def _copy_fiscal_year_workbook(source_id: str, title: str):
    folder_id = _require_fiscal_year_shared_drive_folder()
    body = {
        "name": title,
        "mimeType": GOOGLE_SHEETS_MIME_TYPE,
        "parents": [folder_id],
    }
    response = _drive_session().post(
        f"https://www.googleapis.com/drive/v3/files/{source_id}/copy",
        params={"supportsAllDrives": "true", "fields": "id,name"},
        json=body,
        timeout=45,
    )
    if not 200 <= response.status_code < 300:
        raise _drive_copy_error(response)
    workbook_id = str(response.json().get("id", "") or "")
    if not workbook_id:
        raise RuntimeError("Google Drive copied the fiscal-year workbook but did not return a file ID.")
    return _open_spreadsheet(workbook_id)

def _delete_fiscal_year_workbook(workbook_id: str) -> None:
    response = _drive_session().delete(
        f"https://www.googleapis.com/drive/v3/files/{workbook_id}",
        params={"supportsAllDrives": "true"},
        timeout=45,
    )
    if not 200 <= response.status_code < 300:
        raise _drive_copy_error(response)

def ensure_fiscal_year_template():
    template_id = fiscal_year_template_id()
    if template_id:
        return _open_spreadsheet(template_id)

    template = _copy_fiscal_year_workbook(_base_spreadsheet_id(), FISCAL_YEAR_TEMPLATE_TITLE)
    _share_with_pi(template)
    _initialize_new_fiscal_year_workbook(template, _base_fiscal_year() or _default_fiscal_year())
    _set_config_in_base(FISCAL_YEAR_TEMPLATE_CONFIG_KEY, template.id)
    return template

def _create_fiscal_year_spreadsheet(fiscal_year: str):
    template = ensure_fiscal_year_template()
    workbook = _copy_fiscal_year_workbook(template.id, f"KameiLab Budget {fiscal_year}")
    _share_with_pi(workbook)
    _initialize_new_fiscal_year_workbook(workbook, fiscal_year)
    return workbook

def _prepare_fiscal_year_tabs(ss, fiscal_year: str) -> None:
    suffix = fiscal_year
    summary_rows = [[category, 0, 0, 0, 0, 0, 0, 0, 0, ""] for category in CATEGORIES]
    summary_rows.append(["TOTAL", 0, 0, 0, 0, 0, 0, 0, 0, ""])
    _ensure_worksheet_values(ss, f"Transactions {suffix}", TXN_COLUMNS)
    _ensure_worksheet_values(ss, f"Summary {suffix}", SUMMARY_COLS, summary_rows)
    _ensure_worksheet_values(ss, f"Teams {suffix}", TEAM_COLUMNS)
    _ensure_worksheet_values(ss, f"Config {suffix}", ["Key", "Value"], _config_rows_for_fiscal_year(fiscal_year))

def ensure_fiscal_year_spreadsheet(fiscal_year: str | None = None):
    fy = fiscal_year or get_active_fiscal_year()
    registered_id = _spreadsheet_id_for_fiscal_year(fy)
    if registered_id:
        return _open_spreadsheet(registered_id)
    base_id = _base_spreadsheet_id()
    base_fy = _read_config_from_base("Current Fiscal Year") or _read_config_from_base("Fiscal Year")
    if not base_fy or fy == base_fy:
        _register_fiscal_year_spreadsheet(fy, base_id)
        return _open_spreadsheet(base_id)
    workbook = _create_fiscal_year_spreadsheet(fy)
    _register_fiscal_year_spreadsheet(fy, workbook.id)
    st.cache_data.clear()
    return workbook

def create_fiscal_year_workbook(fiscal_year: str):
    fy = str(fiscal_year or "").strip()
    if not re.fullmatch(r"FY\d{4}-\d{2}", fy):
        raise ValueError("Fiscal year must look like FY2026-27.")
    if _spreadsheet_id_for_fiscal_year(fy):
        raise ValueError(f"{fy} already has a registered workbook.")
    return ensure_fiscal_year_spreadsheet(fy)

def migrate_fiscal_year_to_dedicated_workbook(fiscal_year: str):
    """Copy legacy FY tabs into a dedicated workbook without changing the source tabs."""
    fy = str(fiscal_year or "").strip()
    if not fiscal_year_uses_legacy_tabs(fy):
        raise ValueError(f"{fy} is already stored in a dedicated workbook.")

    source = _base_spreadsheet()
    workbook = _create_fiscal_year_spreadsheet(fy)
    try:
        copied_sheet_ids = {}
        for name in FISCAL_YEAR_WORKSHEET_NAMES:
            source_ws = source.worksheet(f"{name} {fy}")
            copied_sheet_ids[name] = source_ws.copy_to(workbook.id)["sheetId"]
        for name in FISCAL_YEAR_WORKSHEET_NAMES:
            workbook.del_worksheet(workbook.worksheet(name))
        for name, sheet_id in copied_sheet_ids.items():
            workbook.get_worksheet_by_id(sheet_id).update_title(name)
    except Exception:
        try:
            _delete_fiscal_year_workbook(workbook.id)
        finally:
            raise

    _register_fiscal_year_spreadsheet(fy, workbook.id)
    st.cache_data.clear()
    return workbook

def fiscal_year_workbook_url(fiscal_year: str | None = None) -> str | None:
    spreadsheet_id = _existing_spreadsheet_id_for_fiscal_year(fiscal_year)
    if not spreadsheet_id:
        return None
    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

def get_spreadsheet(fiscal_year: str | None = None, create_if_missing: bool = True):
    try:
        if create_if_missing:
            return ensure_fiscal_year_spreadsheet(fiscal_year)
        spreadsheet_id = _existing_spreadsheet_id_for_fiscal_year(fiscal_year)
        return _open_spreadsheet(spreadsheet_id) if spreadsheet_id else None
    except gspread.exceptions.APIError as e:
        st.error(
            f"Cannot open spreadsheet. Check that SPREADSHEET_ID is correct and "
            f"the service account has been shared on the sheet. API error: {e}"
        )
        st.stop()

def _ws(name: str, fiscal_year: str | None = None):
    fy = fiscal_year or get_active_fiscal_year()
    spreadsheet = get_spreadsheet(fy, create_if_missing=False)
    if spreadsheet is None:
        raise ValueError(
            f"{fy} has not been prepared. Ask a PI to create its dedicated Google Sheet in Settings > Fiscal Year."
        )
    return spreadsheet.worksheet(_worksheet_name(name, fy))

def _read_ws(name: str, fiscal_year: str | None = None):
    spreadsheet = get_spreadsheet(fiscal_year, create_if_missing=False)
    if spreadsheet is None:
        return None
    return spreadsheet.worksheet(_worksheet_name(name, fiscal_year))

def _normalize_key(value) -> str:
    return " ".join(str(value or "").strip().casefold().split())

def _sheet_number(value) -> float:
    text = str(value or "").strip().replace(",", "")
    if not text:
        return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0

def _column_label(index: int) -> str:
    label = ""
    while index:
        index, rem = divmod(index - 1, 26)
        label = chr(65 + rem) + label
    return label

def _ensure_sheet_columns(ws, needed: int) -> None:
    current = int(getattr(ws, "col_count", 0) or 0)
    if current and needed > current:
        ws.add_cols(needed - current)

def _stop_on_sheet_api_error(action: str, error: gspread.exceptions.APIError):
    st.error(
        "Google Sheets read quota was reached while "
        f"{action}. Please wait about a minute and refresh. "
        "The app now caches Sheet reads to reduce repeat requests."
    )
    st.caption(f"Google Sheets API error: {error}")
    st.stop()

def ensure_transaction_columns(fiscal_year: str | None = None):
    """Add lifecycle columns to Transactions header if the sheet is still on v1."""
    ws = _ws("Transactions", fiscal_year)
    headers = ws.row_values(1)
    for col in TXN_COLUMNS:
        if col not in headers:
            headers.append(col)
    _ensure_sheet_columns(ws, len(headers))
    end_col = _column_label(len(headers))
    ws.update(f"A1:{end_col}1", [headers])
    return headers

# ── Read ──────────────────────────────────────────────────────────────────────

def get_transactions(fiscal_year: str | None = None) -> pd.DataFrame:
    return _get_transactions_for_fiscal_year(fiscal_year or get_active_fiscal_year())

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _get_transactions_for_fiscal_year(fiscal_year: str) -> pd.DataFrame:
    try:
        ws = _read_ws("Transactions", fiscal_year)
        if ws is None:
            return pd.DataFrame(columns=TXN_COLUMNS)
        records = ws.get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=TXN_COLUMNS)
    except gspread.exceptions.APIError as e:
        _stop_on_sheet_api_error("reading Transactions", e)
    df = pd.DataFrame(records) if records else pd.DataFrame(columns=TXN_COLUMNS)
    # Only rows with a Transaction ID
    if "Transaction ID" in df.columns:
        df = df[df["Transaction ID"].astype(str).str.strip() != ""]
    for col in TXN_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    df = normalize_aed_equivalent(df, DEFAULT_AED_USD_EXCHANGE_RATE)
    df = normalize_usd_equivalent(df, DEFAULT_RATES_TO_USD)
    if "Status" in df.columns:
        df["Status"] = df["Status"].map(canonical_budget_status)
    return df

def get_teams(fiscal_year: str | None = None, include_registry: bool = True) -> pd.DataFrame:
    return _get_teams_for_fiscal_year(fiscal_year or get_active_fiscal_year(), include_registry)

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _get_teams_for_fiscal_year(fiscal_year: str, include_registry: bool = True) -> pd.DataFrame:
    try:
        ws = _read_ws("Teams", fiscal_year)
        if ws is None:
            if not include_registry:
                return pd.DataFrame(columns=TEAM_COLUMNS)
            registry_df = _get_budget_teams_from_portal_registry(fiscal_year, pd.DataFrame(columns=TEAM_COLUMNS))
            return registry_df if registry_df is not None else pd.DataFrame(columns=TEAM_COLUMNS)
        records = ws.get_all_records()
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=TEAM_COLUMNS)
        for col in TEAM_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        if not include_registry:
            return df
        registry_df = _get_budget_teams_from_portal_registry(fiscal_year, df)
        return registry_df if registry_df is not None else df
    except gspread.exceptions.WorksheetNotFound:
        if not include_registry:
            return pd.DataFrame(columns=TEAM_COLUMNS)
        registry_df = _get_budget_teams_from_portal_registry(fiscal_year, pd.DataFrame(columns=TEAM_COLUMNS))
        return registry_df if registry_df is not None else pd.DataFrame(columns=TEAM_COLUMNS)
    except gspread.exceptions.APIError as e:
        _stop_on_sheet_api_error("reading Teams", e)


def _registry_spreadsheet_id() -> str:
    try:
        configured_id = str(st.secrets.get("REGISTRY_SPREADSHEET_ID", "") or "").strip()
    except Exception:
        configured_id = ""
    if configured_id:
        return configured_id
    return DEFAULT_REGISTRY_SPREADSHEET_ID


def _render_registry_load_error(error: Exception) -> None:
    st.error("The shared Kamei Lab registry could not be loaded.")
    if isinstance(error, PermissionError) or type(error).__name__ in {"PermissionError", "APIError"}:
        st.info(
            "Check this app's Streamlit Cloud secrets and Google Sheet sharing. "
            "The central registry Sheet must be shared with the service account configured in "
            "`gcp_service_account`, and `REGISTRY_SPREADSHEET_ID` must point to that same central registry Sheet."
        )
    else:
        st.info("Refresh the app after updating Streamlit Cloud secrets or Google Sheet sharing.")
    with st.expander("Technical detail"):
        st.code(f"{type(error).__name__}: {error}")
    st.stop()


def _registry_client_email() -> str:
    try:
        return str(dict(st.secrets.get("gcp_service_account", {})).get("client_email", "")).strip()
    except Exception:
        return ""


def registry_setup_hint() -> str:
    email_hint = "the service account configured in `gcp_service_account`"
    client_email = _registry_client_email()
    if client_email:
        email_hint = f"`{client_email}`"
    return (
        "Set `REGISTRY_SPREADSHEET_ID` in this app's Streamlit Cloud secrets and share the central "
        f"Registry Google Sheet with {email_hint} as an editor."
    )


def registry_connected() -> bool:
    try:
        return bool(_registry_spreadsheet_id() and st.secrets.get("gcp_service_account", {}))
    except Exception:
        return False


def running_on_streamlit_cloud() -> bool:
    return os.environ.get("HOME") == STREAMLIT_CLOUD_HOME or str(Path.cwd()).startswith(STREAMLIT_CLOUD_SOURCE_ROOT)


def require_shared_registry_on_cloud() -> None:
    if not running_on_streamlit_cloud() or registry_connected():
        return
    st.error(
        "The shared Kamei Lab registry is required on Streamlit Cloud. "
    )
    st.info(registry_setup_hint())
    st.stop()


def _next_registry_id(frame: pd.DataFrame, column: str, prefix: str) -> str:
    values = frame[column].astype(str).tolist() if column in frame else []
    numbers = []
    for value in values:
        if value.startswith(prefix) and value.removeprefix(prefix).isdigit():
            numbers.append(int(value.removeprefix(prefix)))
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def _registry_password_hash(password: str) -> str:
    if len(str(password)) < 8:
        raise ValueError("Password must be at least 8 characters.")
    iterations = 200_000
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", str(password).encode("utf-8"), salt, iterations)
    return "pbkdf2_sha256${}${}${}".format(
        iterations,
        base64.urlsafe_b64encode(salt).decode("ascii").rstrip("="),
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    )


def _registry_frame(registry, table_name: str, columns: list[str]) -> pd.DataFrame:
    try:
        records = registry.worksheet(table_name).get_all_records()
    except gspread.exceptions.WorksheetNotFound:
        registry.add_worksheet(table_name, rows=1000, cols=max(len(columns), 1))
        records = []
    frame = pd.DataFrame(records)
    return frame.reindex(columns=columns, fill_value="").fillna("").astype(str)


def _write_registry_frame(registry, table_name: str, frame: pd.DataFrame, columns: list[str]) -> None:
    try:
        worksheet = registry.worksheet(table_name)
    except gspread.exceptions.WorksheetNotFound:
        worksheet = registry.add_worksheet(table_name, rows=1000, cols=max(len(columns), 1))
    output = frame.reindex(columns=columns, fill_value="").fillna("").astype(str)
    worksheet.clear()
    worksheet.update([columns] + output.values.tolist())


def _append_registry_audit(audit: pd.DataFrame, *, actor_email: str, action: str, target_type: str, target_id: str, before, after) -> pd.DataFrame:
    def redacted(record):
        data = dict(record or {})
        if "password_hash" in data:
            data["password_hash"] = "<redacted>"
        return data

    row = {
        "audit_id": _next_registry_id(audit, "audit_id", "AU"),
        "timestamp": datetime.now(DUBAI_TZ).replace(microsecond=0).isoformat(),
        "actor_email": actor_email,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "before": json.dumps(redacted(before), sort_keys=True),
        "after": json.dumps(redacted(after), sort_keys=True),
    }
    return pd.concat([audit, pd.DataFrame([row])], ignore_index=True)


def save_budget_member_access_to_registry(
    *,
    actor_email: str,
    email: str,
    name: str,
    team_name: str,
    access: str,
    password: str = "",
) -> None:
    registry = _open_spreadsheet(_registry_spreadsheet_id())
    member_columns = [
        "member_id",
        "email",
        "name",
        "display_name",
        "global_role",
        "active",
        "start_date",
        "end_date",
        "password_hash",
        "password_set_at",
        "password_must_change",
        "notes",
    ]
    team_columns = ["team_id", "team_name", "description", "active"]
    member_team_columns = ["member_team_id", "member_id", "team_id", "team_role", "active", "start_date", "end_date"]
    app_role_columns = ["app_role_id", "member_id", "app_id", "app_role", "scope_team_id", "active", "start_date", "end_date"]
    audit_columns = ["audit_id", "timestamp", "actor_email", "action", "target_type", "target_id", "before", "after"]

    members = _registry_frame(registry, "Members", member_columns)
    teams = _registry_frame(registry, "Teams", team_columns)
    member_teams = _registry_frame(registry, "Member_Teams", member_team_columns)
    app_roles = _registry_frame(registry, "App_Roles", app_role_columns)
    audit = _registry_frame(registry, "Audit_Log", audit_columns)

    normalized_email = email.strip().lower()
    display_name = name.strip() or normalized_email
    if not normalized_email:
        raise ValueError("NYU email is required.")
    if not normalized_email.endswith("@nyu.edu"):
        raise ValueError("Email must end with @nyu.edu.")
    if not team_name.strip():
        raise ValueError("Team is required.")

    today = datetime.now(DUBAI_TZ).date().isoformat()
    member_matches = members[members["email"].astype(str).str.strip().str.lower() == normalized_email]
    if member_matches.empty:
        password_hash = _registry_password_hash(password)
        member_row = {
            "member_id": _next_registry_id(members, "member_id", "M"),
            "email": normalized_email,
            "name": display_name,
            "display_name": display_name,
            "global_role": "member",
            "active": "TRUE",
            "start_date": today,
            "end_date": "",
            "password_hash": password_hash,
            "password_set_at": datetime.now(DUBAI_TZ).replace(microsecond=0).isoformat(),
            "password_must_change": "TRUE",
            "notes": "Added from Budget app",
        }
        members = pd.concat([members, pd.DataFrame([member_row])], ignore_index=True)
        audit = _append_registry_audit(
            audit,
            actor_email=actor_email,
            action="member.add",
            target_type="Members",
            target_id=member_row["member_id"],
            before=None,
            after=member_row,
        )
    else:
        member_index = member_matches.index[0]
        before = members.loc[member_index].to_dict()
        members.loc[member_index, "email"] = normalized_email
        members.loc[member_index, "name"] = display_name
        members.loc[member_index, "display_name"] = display_name
        members.loc[member_index, "active"] = "TRUE"
        if password:
            members.loc[member_index, "password_hash"] = _registry_password_hash(password)
            members.loc[member_index, "password_set_at"] = datetime.now(DUBAI_TZ).replace(microsecond=0).isoformat()
            members.loc[member_index, "password_must_change"] = "TRUE"
        after = members.loc[member_index].to_dict()
        audit = _append_registry_audit(
            audit,
            actor_email=actor_email,
            action="member.update",
            target_type="Members",
            target_id=str(after["member_id"]),
            before=before,
            after=after,
        )
        member_row = after

    team_matches = teams[teams["team_name"].astype(str).str.strip().str.lower() == team_name.strip().lower()]
    if team_matches.empty:
        team_row = {
            "team_id": _next_registry_id(teams, "team_id", "T"),
            "team_name": team_name.strip(),
            "description": "Added from Budget app",
            "active": "TRUE",
        }
        teams = pd.concat([teams, pd.DataFrame([team_row])], ignore_index=True)
        audit = _append_registry_audit(
            audit,
            actor_email=actor_email,
            action="team.add",
            target_type="Teams",
            target_id=team_row["team_id"],
            before=None,
            after=team_row,
        )
    else:
        team_row = team_matches.iloc[0].to_dict()

    member_id = str(member_row["member_id"])
    team_id = str(team_row["team_id"])
    final_access = "No access" if access.startswith("No access") else access
    role_lookup = {"Budget Manager": "manager", "Team Lead": "lead", "Member": "viewer"}
    member_team_mask = (member_teams["member_id"] == member_id) & (member_teams["team_id"] == team_id)
    if final_access == "No access":
        member_teams.loc[member_team_mask, "active"] = "FALSE"
    elif member_team_mask.any():
        member_teams.loc[member_team_mask, "active"] = "TRUE"
        member_teams.loc[member_team_mask, "team_role"] = "lead" if final_access in {"Budget Manager", "Team Lead"} else "member"
    else:
        member_teams = pd.concat(
            [
                member_teams,
                pd.DataFrame(
                    [
                        {
                            "member_team_id": _next_registry_id(member_teams, "member_team_id", "MT"),
                            "member_id": member_id,
                            "team_id": team_id,
                            "team_role": "lead" if final_access in {"Budget Manager", "Team Lead"} else "member",
                            "active": "TRUE",
                            "start_date": today,
                            "end_date": "",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    active_budget_role_mask = (app_roles["member_id"] == member_id) & (app_roles["app_id"] == "budget") & app_roles["active"].map(_sheet_truthy)
    app_roles.loc[active_budget_role_mask, "active"] = "FALSE"
    if final_access != "No access":
        app_roles = pd.concat(
            [
                app_roles,
                pd.DataFrame(
                    [
                        {
                            "app_role_id": _next_registry_id(app_roles, "app_role_id", "AR"),
                            "member_id": member_id,
                            "app_id": "budget",
                            "app_role": role_lookup[final_access],
                            "scope_team_id": team_id,
                            "active": "TRUE",
                            "start_date": today,
                            "end_date": "",
                        }
                    ]
                ),
            ],
            ignore_index=True,
        )

    _write_registry_frame(registry, "Members", members, member_columns)
    _write_registry_frame(registry, "Teams", teams, team_columns)
    _write_registry_frame(registry, "Member_Teams", member_teams, member_team_columns)
    _write_registry_frame(registry, "App_Roles", app_roles, app_role_columns)
    _write_registry_frame(registry, "Audit_Log", audit, audit_columns)
    st.cache_data.clear()


@st.cache_data(ttl=60, show_spinner=False)
def _get_budget_teams_from_portal_registry(fiscal_year: str, existing_team_rows: pd.DataFrame) -> pd.DataFrame | None:
    del fiscal_year
    require_shared_registry_on_cloud()
    registry_id = _registry_spreadsheet_id()
    if not registry_id:
        return None
    try:
        registry = _open_spreadsheet(registry_id)
        members = pd.DataFrame(registry.worksheet("Members").get_all_records())
        teams = pd.DataFrame(registry.worksheet("Teams").get_all_records())
        member_teams = pd.DataFrame(registry.worksheet("Member_Teams").get_all_records())
        app_roles = pd.DataFrame(registry.worksheet("App_Roles").get_all_records())
    except Exception as error:
        if running_on_streamlit_cloud():
            _render_registry_load_error(error)
        return None
    for frame, columns in (
        (members, ["member_id", "email", "display_name", "name", "global_role", "active"]),
        (teams, ["team_id", "team_name", "description", "active"]),
        (member_teams, ["member_id", "team_id", "active"]),
        (app_roles, ["member_id", "app_id", "app_role", "scope_team_id", "active"]),
    ):
        for column in columns:
            if column not in frame.columns:
                frame[column] = ""
    active_members = members[members["active"].map(_sheet_truthy)].copy()
    active_teams = teams[teams["active"].map(_sheet_truthy)].copy()
    active_member_teams = member_teams[member_teams["active"].map(_sheet_truthy)].copy()
    active_budget_roles = app_roles[
        (app_roles["active"].map(_sheet_truthy)) & (app_roles["app_id"].astype(str) == "budget")
    ].copy()
    global_budget_roles = active_members[
        active_members["global_role"].astype(str).str.strip().str.lower().isin({"pi", "admin"})
    ].copy()
    if not global_budget_roles.empty:
        global_budget_roles = pd.DataFrame(
            [
                {
                    "member_id": str(row["member_id"]),
                    "app_id": "budget",
                    "app_role": "owner",
                    "scope_team_id": "",
                    "active": "TRUE",
                }
                for _, row in global_budget_roles.iterrows()
            ]
        )
        active_budget_roles = pd.concat([active_budget_roles, global_budget_roles], ignore_index=True)
    if active_members.empty or active_teams.empty or active_budget_roles.empty:
        return pd.DataFrame(columns=TEAM_COLUMNS)
    active_member_ids = set(active_members["member_id"].astype(str))
    role_by_member = active_budget_roles[active_budget_roles["member_id"].astype(str).isin(active_member_ids)].copy()
    if role_by_member.empty:
        return pd.DataFrame(columns=TEAM_COLUMNS)
    member_lookup = active_members.set_index("member_id").to_dict("index")
    global_budget_manager_ids = set(
        active_members.loc[
            active_members["global_role"].astype(str).str.strip().str.lower().isin({"pi", "admin"}),
            "member_id",
        ].astype(str)
    )
    allocations = _budget_team_allocation_lookup(existing_team_rows)
    rows = []
    for _, team in active_teams.iterrows():
        team_id = str(team["team_id"])
        team_name = str(team["team_name"]).strip()
        if not team_name:
            continue
        team_member_ids = set(
            active_member_teams.loc[active_member_teams["team_id"].astype(str) == team_id, "member_id"].astype(str)
        )
        scoped_roles = role_by_member[
            (
                role_by_member["member_id"].astype(str).isin(team_member_ids)
                | role_by_member["member_id"].astype(str).isin(global_budget_manager_ids)
            )
            & role_by_member["scope_team_id"].astype(str).isin({"", team_id})
        ]
        managers = _role_people(scoped_roles, member_lookup, {"owner", "manager"})
        leads = _role_people(scoped_roles, member_lookup, {"lead"})
        members_for_team = _role_people(scoped_roles, member_lookup, {"editor", "viewer"})
        if not (managers[0] or leads[0] or members_for_team[0]):
            continue
        existing = allocations.get(team_name, {})
        rows.append(
            {
                "Team Name": team_name,
                "Allocation (AED)": existing.get("Allocation (AED)", ""),
                "Allocation (USD)": existing.get("Allocation (USD)", ""),
                "Budget Manager Emails": managers[0],
                "Budget Manager Names": managers[1],
                "Lead Emails": leads[0],
                "Lead Names": leads[1],
                "Member Emails": members_for_team[0],
                "Member Names": members_for_team[1],
                "Description": str(team.get("description", "")),
                "Active": "Y",
            }
        )
    return pd.DataFrame(rows, columns=TEAM_COLUMNS)


def _sheet_truthy(value) -> bool:
    return str(value).strip().upper() in {"TRUE", "YES", "Y", "1"}


def _budget_team_allocation_lookup(frame: pd.DataFrame) -> dict[str, dict[str, str]]:
    if frame.empty or "Team Name" not in frame.columns:
        return {}
    return {
        str(row.get("Team Name", "")).strip(): {column: str(row.get(column, "")) for column in TEAM_COLUMNS}
        for _, row in frame.iterrows()
        if str(row.get("Team Name", "")).strip()
    }


def _role_people(role_rows: pd.DataFrame, member_lookup: dict, allowed_roles: set[str]) -> tuple[str, str]:
    emails = []
    names = []
    for _, role_row in role_rows.iterrows():
        app_role = str(role_row.get("app_role", "")).strip()
        if app_role not in allowed_roles:
            continue
        member = member_lookup.get(str(role_row.get("member_id", "")), {})
        email = str(member.get("email", "")).strip().lower()
        name = str(member.get("display_name", "") or member.get("name", "")).strip()
        if email and email not in emails:
            emails.append(email)
            names.append(name or email)
    return ", ".join(emails), ", ".join(names)

def get_summary(fiscal_year: str | None = None) -> pd.DataFrame:
    return _get_summary_for_fiscal_year(fiscal_year or get_active_fiscal_year())

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _get_summary_for_fiscal_year(fiscal_year: str) -> pd.DataFrame:
    try:
        ws = _read_ws("Summary", fiscal_year)
        if ws is None:
            return pd.DataFrame(columns=SUMMARY_COLS)
        values = ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame(columns=SUMMARY_COLS)
    except gspread.exceptions.APIError as e:
        _stop_on_sheet_api_error("reading Summary", e)
    # Match rows by category name in col A — works regardless of title/header layout
    data_rows = [r for r in values if r and r[0] in _SUMMARY_CATEGORIES]
    if not data_rows:
        return pd.DataFrame(columns=SUMMARY_COLS)
    n = len(SUMMARY_COLS)
    padded = [r[:n] + [""] * (n - len(r)) for r in data_rows]
    return pd.DataFrame(padded, columns=SUMMARY_COLS)

def get_config_values(fiscal_year: str | None = None) -> list[list[str]]:
    return _get_config_values_for_fiscal_year(fiscal_year or get_active_fiscal_year())

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _get_config_values_for_fiscal_year(fiscal_year: str) -> list[list[str]]:
    try:
        ws = _read_ws("Config", fiscal_year)
        if ws is None:
            return _base_ws("Config").get_all_values()
        return ws.get_all_values()
    except gspread.exceptions.WorksheetNotFound:
        return _base_ws("Config").get_all_values()
    except gspread.exceptions.APIError as e:
        _stop_on_sheet_api_error("reading Config", e)

def get_config(key: str, fiscal_year: str | None = None):
    for row in get_config_values(fiscal_year):
        if row and row[0] == key:
            return row[1] if len(row) > 1 else None
    return None

def get_exchange_rate() -> float:
    val = get_config("AED/USD Exchange Rate")
    try:
        return float(val)
    except (TypeError, ValueError):
        return 3.6725

def get_currency_rates_to_usd() -> dict[str, float]:
    rates = dict(DEFAULT_RATES_TO_USD)
    aed_per_usd = get_exchange_rate()
    rates["AED"] = 1 / aed_per_usd if aed_per_usd else DEFAULT_RATES_TO_USD["AED"]
    for code in ("EUR", "JPY", "GBP"):
        val = get_config(f"{code}/USD Exchange Rate")
        try:
            rates[code] = float(val)
        except (TypeError, ValueError):
            pass
    return rates

# ── Write ─────────────────────────────────────────────────────────────────────

def _next_txn_id(fiscal_year: str) -> str:
    df = get_transactions(fiscal_year)
    date_str = datetime.now(DUBAI_TZ).strftime("%Y%m%d")
    max_seq = 0
    if not df.empty and "Transaction ID" in df.columns:
        for raw_txn_id in df["Transaction ID"].dropna():
            match = re.search(r"-(\d{4,})$", str(raw_txn_id).strip())
            if match:
                max_seq = max(max_seq, int(match.group(1)))
    seq = str(max_seq + 1).zfill(4)
    return f"TXN-{date_str}-{seq}"

def _current_fy() -> str:
    return fiscal_year_for_date(datetime.now(DUBAI_TZ))

def append_transaction(data: dict) -> str:
    """Write one transaction row. Returns the Transaction ID."""
    row_date = data.get("Date") or datetime.now(DUBAI_TZ).strftime("%Y-%m-%d")
    target_fy = str(data.get("Fiscal Year") or "").strip()
    if not target_fy.startswith("FY"):
        target_fy = fiscal_year_for_date(row_date)
    if get_spreadsheet(target_fy, create_if_missing=False) is None:
        raise ValueError(
            f"{target_fy} has not been prepared. Ask a PI to create its dedicated Google Sheet in Settings > Fiscal Year."
        )
    ws = _ws("Transactions", target_fy)
    headers = ensure_transaction_columns(target_fy)
    txn_id = data.get("Transaction ID") or _next_txn_id(target_fy)
    now_str = datetime.now(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S")

    # Build row in TXN_COLUMNS order
    rate = get_exchange_rate()
    rates_to_usd = get_currency_rates_to_usd()
    legacy_aed = float(data.get("Amount (AED)") or 0)
    legacy_usd = float(data.get("Amount (USD)") or 0)
    currency = str(data.get("Currency") or "").upper()
    if currency not in SUPPORTED_CURRENCIES:
        currency = "AED" if legacy_aed else "USD"
    amount = float(data.get("Amount") or 0)
    if amount == 0:
        amount = legacy_aed if currency == "AED" else legacy_usd
    usd_equiv = round_currency(to_usd_equivalent(currency, amount, rates_to_usd))
    aed = amount if currency == "AED" else 0.0
    usd = amount if currency == "USD" else 0.0
    equiv = usd_equiv * rate

    row = {col: "" for col in TXN_COLUMNS}
    row.update({
        "Transaction ID": txn_id,
        "Date": row_date,
        "Fiscal Year": target_fy,
        "Category": data.get("Category", ""),
        "Sub-category": data.get("Sub-category", ""),
        "Vendor / Payee": data.get("Vendor / Payee", ""),
        "Description": data.get("Description", ""),
        "PO Number": data.get("PO Number", ""),
        "Invoice Number": data.get("Invoice Number", ""),
        "Currency": currency,
        "Amount": amount,
        "Amount (USD equiv)": usd_equiv,
        "Amount (AED)": aed,
        "Amount (USD)": usd,
        "Amount (AED equiv)": round_currency(equiv),
        "Status": canonical_budget_status(data.get("Status", "Allocated")),
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
        row["Status"] = "Allocated"
    ws.append_row([row.get(col, "") for col in headers], value_input_option="USER_ENTERED")
    # Invalidate cache
    st.cache_data.clear()
    return txn_id

def update_transaction(txn_id: str, updates: dict, source_fiscal_year: str | None = None):
    """Update specific fields of a transaction row."""
    source_fy = source_fiscal_year or get_active_fiscal_year()
    ws = _ws("Transactions", source_fy)
    ensure_transaction_columns(source_fy)
    all_values = ws.get_all_values()
    if not all_values:
        return
    headers = all_values[0]
    for i, row in enumerate(all_values[1:], start=2):
        if row and row[0] == txn_id:
            explicit_fiscal_year = bool(str(updates.get("Fiscal Year") or "").strip())
            current = {
                header: row[idx] if idx < len(row) else ""
                for idx, header in enumerate(headers)
            }
            if "Date" in updates and "Fiscal Year" in headers:
                row_date = str(
                    updates.get("Date")
                    or current.get("Date")
                    or datetime.now(DUBAI_TZ).strftime("%Y-%m-%d")
                )
                target_fy = str(updates.get("Fiscal Year") or "").strip() or fiscal_year_for_date(row_date)
                updates = {
                    **updates,
                    "Date": row_date,
                    "Fiscal Year": target_fy,
                }
            if (
                {"Currency", "Amount"} & updates.keys()
                and "Amount (USD equiv)" in headers
            ):
                currency = str(updates.get("Currency", current.get("Currency", "USD"))).upper()
                amount = updates.get("Amount", current.get("Amount", 0))
                usd_equiv = round_currency(
                    to_usd_equivalent(currency, amount, get_currency_rates_to_usd())
                )
                updates = {**updates, "Amount (USD equiv)": usd_equiv}
                if "Amount (AED equiv)" in headers:
                    updates["Amount (AED equiv)"] = round_currency(usd_equiv * get_exchange_rate())
                if "Amount (AED)" in headers:
                    updates["Amount (AED)"] = float(amount or 0) if currency == "AED" else 0.0
                if "Amount (USD)" in headers:
                    updates["Amount (USD)"] = float(amount or 0) if currency == "USD" else 0.0
            if (
                {"Amount (AED)", "Amount (USD)"} & updates.keys()
                and "Amount (AED equiv)" in headers
            ):
                aed = updates.get("Amount (AED)", current.get("Amount (AED)", 0))
                usd = updates.get("Amount (USD)", current.get("Amount (USD)", 0))
                recalculated_equiv = round_currency(
                    to_aed_equivalent(aed, usd, get_exchange_rate()),
                )
                updates = {**updates, "Amount (AED equiv)": recalculated_equiv}
                if "Amount (USD equiv)" in headers and not ({"Currency", "Amount"} & updates.keys()):
                    updates["Amount (USD equiv)"] = round_currency(
                        float(recalculated_equiv or 0) / get_exchange_rate()
                    )
            target_fy = str(updates.get("Fiscal Year") or current.get("Fiscal Year") or source_fy).strip()
            if target_fy.startswith("FY") and target_fy != source_fy and explicit_fiscal_year:
                moved_row = {**current, **updates, "Transaction ID": txn_id}
                append_transaction(moved_row)
                ws.delete_rows(i)
                st.cache_data.clear()
                return
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
    status = canonical_budget_status(status)
    update_transaction(txn_id, {
        "Status": status,
        "Approved By": approver_email,
        "Approved At": datetime.now(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S"),
    })

def find_matching_transaction_id(txns: pd.DataFrame, candidate: dict) -> str | None:
    """Find an existing request/import row by team plus a durable document ID.

    Vendor-only matching is intentionally avoided because recurring vendors such
    as PeopleSoft Inventory or NYUAD ERB would otherwise overwrite unrelated PDFs.
    """
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
    """Update a matching request from an import, or append a new allocated budget row."""
    row = dict(data)
    row["Status"] = canonical_budget_status(row.get("Status", "Allocated"))
    txns = get_transactions()
    match_id = find_matching_transaction_id(txns, row)
    if match_id:
        updates = dict(row)
        updates.pop("Transaction ID", None)
        update_transaction(match_id, updates)
        return {"transaction_id": match_id, "matched": True}
    txn_id = append_transaction(row)
    return {"transaction_id": txn_id, "matched": False}

def set_budget_allocation(category: str, aed: float, usd: float, fiscal_year: str | None = None):
    ws = _ws("Summary", fiscal_year)
    all_values = ws.get_all_values()
    rate = get_exchange_rate()
    equiv = round_currency(to_aed_equivalent(aed, usd, rate))
    for i, row in enumerate(all_values, start=1):
        if row and row[0] == category:
            spent_aed = _sheet_number(row[4]) if len(row) > 4 else 0.0
            spent_usd = _sheet_number(row[5]) if len(row) > 5 else 0.0
            spent_equiv = _sheet_number(row[6]) if len(row) > 6 else 0.0
            remaining = round_currency(equiv - spent_equiv)
            pct_used = round_currency(spent_equiv / equiv) if equiv > 0 else 0.0
            ws.update(
                f"B{i}:I{i}",
                [[aed, usd, equiv, spent_aed, spent_usd, spent_equiv, remaining, pct_used]],
                value_input_option="USER_ENTERED",
            )
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

def set_budget_allocations_usd(allocations: dict[str, float], fiscal_year: str | None = None):
    """Save category budget allocations for one fiscal-year ledger in a compact batch."""
    ws = _ws("Summary", fiscal_year)
    _ensure_sheet_columns(ws, len(SUMMARY_COLS))
    all_values = ws.get_all_values()
    if not all_values:
        end_col = _column_label(len(SUMMARY_COLS))
        ws.update(f"A1:{end_col}1", [SUMMARY_COLS], value_input_option="USER_ENTERED")
        all_values = [SUMMARY_COLS]
    rate = get_exchange_rate()
    row_by_category = {
        str(row[0]).strip(): index
        for index, row in enumerate(all_values, start=1)
        if row and str(row[0]).strip()
    }
    updates = []
    missing = []
    for category, raw_usd in allocations.items():
        usd = float(raw_usd or 0)
        equiv = round_currency(to_aed_equivalent(0, usd, rate))
        row_index = row_by_category.get(category)
        if row_index:
            row = all_values[row_index - 1]
            spent_aed = _sheet_number(row[4]) if len(row) > 4 else 0.0
            spent_usd = _sheet_number(row[5]) if len(row) > 5 else 0.0
            spent_equiv = _sheet_number(row[6]) if len(row) > 6 else 0.0
            remaining = round_currency(equiv - spent_equiv)
            pct_used = round_currency(spent_equiv / equiv) if equiv > 0 else 0.0
            updates.append(
                {
                    "range": f"B{row_index}:I{row_index}",
                    "values": [[0, usd, equiv, spent_aed, spent_usd, spent_equiv, remaining, pct_used]],
                }
            )
        else:
            missing.append([category, 0, usd, equiv, 0, 0, 0, equiv, 0, ""])
    if updates:
        ws.batch_update(updates, value_input_option="USER_ENTERED")
    for row in missing:
        ws.append_row(row, value_input_option="USER_ENTERED")
    st.cache_data.clear()

def upsert_team(team_data: dict):
    """Insert or update a team row."""
    ws = _ws("Teams")
    records = ws.get_all_values()
    headers = records[0] if records else []
    for header in TEAM_COLUMNS:
        if header not in headers:
            headers.append(header)
    _ensure_sheet_columns(ws, len(headers))
    end_col = _column_label(len(headers))
    ws.update(f"A1:{end_col}1", [headers])
    team_names = [r[0] for r in records[1:]] if len(records) > 1 else []
    values = {
        "Team Name": team_data.get("Team Name", ""),
        "Allocation (AED)": team_data.get("Allocation (AED)", 0),
        "Allocation (USD)": team_data.get("Allocation (USD)", ""),
        "Budget Manager Emails": team_data.get("Budget Manager Emails", ""),
        "Budget Manager Names": team_data.get("Budget Manager Names", ""),
        "Lead Emails": team_data.get("Lead Emails", ""),
        "Lead Names": team_data.get("Lead Names", ""),
        "Member Emails": team_data.get("Member Emails", ""),
        "Member Names": team_data.get("Member Names", ""),
        "Description": team_data.get("Description", ""),
        "Active": team_data.get("Active", "Y"),
    }
    row = [values.get(header, "") for header in headers]
    if team_data["Team Name"] in team_names:
        row_idx = team_names.index(team_data["Team Name"]) + 2
        ws.update(f"A{row_idx}:{end_col}{row_idx}", [row])
    else:
        ws.append_row(row)
    st.cache_data.clear()

GLOBAL_CONFIG_KEYS = {
    "Current Fiscal Year",
    "Fiscal Year",
    "AED/USD Exchange Rate",
    "EUR/USD Exchange Rate",
    "JPY/USD Exchange Rate",
    "GBP/USD Exchange Rate",
    "Notification Threshold %",
    "Gmail Label",
}

def set_config(key: str, value):
    ws = _ws("Config")
    if key in GLOBAL_CONFIG_KEYS:
        _set_config_in_base(key, value)
    if getattr(get_spreadsheet(), "id", "") == _base_spreadsheet_id() and key in GLOBAL_CONFIG_KEYS:
        st.cache_data.clear()
        return
    records = ws.get_all_values()
    for i, row in enumerate(records, start=1):
        if row and row[0] == key:
            ws.update_cell(i, 2, value)
            st.cache_data.clear()
            return
    ws.append_row([key, value], value_input_option="USER_ENTERED")
    st.cache_data.clear()
