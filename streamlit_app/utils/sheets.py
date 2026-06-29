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
def _get_client():
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=SCOPES
    )
    return gspread.authorize(creds, http_client=gspread.BackOffHTTPClient)

@st.cache_resource(show_spinner=False)
def _open_spreadsheet(spreadsheet_id: str):
    return _get_client().open_by_key(spreadsheet_id)

def _base_spreadsheet_id() -> str:
    return st.secrets[BASE_SPREADSHEET_SECRET]

def _base_spreadsheet():
    return _open_spreadsheet(_base_spreadsheet_id())

def _base_ws(name: str):
    return _base_spreadsheet().worksheet(name)

def _read_config_from_base(key: str):
    try:
        for row in _base_ws("Config").get_all_values():
            if row and row[0] == key:
                return row[1] if len(row) > 1 else ""
    except Exception:
        return None
    return None

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

def _default_fiscal_year() -> str:
    return fiscal_year_for_date(datetime.now(DUBAI_TZ))

def get_active_fiscal_year() -> str:
    return st.session_state.get("selected_fiscal_year") or _default_fiscal_year()

def fiscal_year_options() -> list[str]:
    options = {_default_fiscal_year(), get_active_fiscal_year()}
    try:
        for row in _base_ws("Config").get_all_values():
            if not row:
                continue
            key = str(row[0] or "")
            if key.startswith(FY_SPREADSHEET_CONFIG_PREFIX):
                options.add(key.removeprefix(FY_SPREADSHEET_CONFIG_PREFIX))
            elif key in {"Current Fiscal Year", "Fiscal Year"} and len(row) > 1 and str(row[1]).startswith("FY"):
                options.add(str(row[1]))
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

def _register_fiscal_year_spreadsheet(fiscal_year: str, spreadsheet_id: str) -> None:
    _set_config_in_base(f"{FY_SPREADSHEET_CONFIG_PREFIX}{fiscal_year}", spreadsheet_id)

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
    copied = _get_client().copy(
        base_id,
        title=f"KameiLab Budget {fy}",
        copy_permissions=True,
    )
    _clear_new_fiscal_year_transactions(copied, fy)
    _register_fiscal_year_spreadsheet(fy, copied.id)
    return copied

def get_spreadsheet(fiscal_year: str | None = None):
    try:
        return ensure_fiscal_year_spreadsheet(fiscal_year)
    except gspread.exceptions.APIError as e:
        st.error(
            f"Cannot open spreadsheet. Check that SPREADSHEET_ID is correct and "
            f"the service account has been shared on the sheet. API error: {e}"
        )
        st.stop()

def _ws(name: str, fiscal_year: str | None = None):
    return get_spreadsheet(fiscal_year).worksheet(name)

def _normalize_key(value) -> str:
    return " ".join(str(value or "").strip().casefold().split())

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
        records = _ws("Transactions", fiscal_year).get_all_records()
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

def get_teams(fiscal_year: str | None = None) -> pd.DataFrame:
    return _get_teams_for_fiscal_year(fiscal_year or get_active_fiscal_year())

@st.cache_data(ttl=CACHE_TTL_SECONDS, show_spinner=False)
def _get_teams_for_fiscal_year(fiscal_year: str) -> pd.DataFrame:
    try:
        records = _ws("Teams", fiscal_year).get_all_records()
        df = pd.DataFrame(records) if records else pd.DataFrame(columns=TEAM_COLUMNS)
        for col in TEAM_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        registry_df = _get_budget_teams_from_portal_registry(fiscal_year, df)
        return registry_df if registry_df is not None else df
    except gspread.exceptions.WorksheetNotFound:
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
        values = _ws("Summary", fiscal_year).get_all_values()
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
        return _ws("Config", fiscal_year).get_all_values()
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
    target_fy = fiscal_year_for_date(row_date)
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
                updates = {
                    **updates,
                    "Date": row_date,
                    "Fiscal Year": fiscal_year_for_date(row_date),
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

def set_budget_allocation(category: str, aed: float, usd: float):
    ws = _ws("Summary")
    all_values = ws.get_all_values()
    rate = get_exchange_rate()
    equiv = round_currency(to_aed_equivalent(aed, usd, rate))
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
    if key in GLOBAL_CONFIG_KEYS:
        _set_config_in_base(key, value)
    ws = _ws("Config")
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
