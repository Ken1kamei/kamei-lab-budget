import fcntl
import hashlib
import json
import os
import re
import secrets
import tomllib
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import gspread
import google.auth
from django.conf import settings
from django.db import connection
from google.oauth2.service_account import Credentials

from budget.services.calculations import (
    DEFAULT_RATES_TO_USD,
    SUPPORTED_CURRENCIES,
    decimal_value,
    fiscal_year_for_date,
    money,
)


READ_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
WRITE_SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
DUBAI_TZ = ZoneInfo("Asia/Dubai")
TRANSACTION_COLUMNS = [
    "Transaction ID",
    "Date",
    "Fiscal Year",
    "Category",
    "Sub-category",
    "Vendor / Payee",
    "Description",
    "PO Number",
    "Invoice Number",
    "Currency",
    "Amount",
    "Amount (USD equiv)",
    "Amount (AED)",
    "Amount (USD)",
    "Amount (AED equiv)",
    "Status",
    "Receipt Confirmed",
    "PDF Link",
    "Email Thread ID",
    "Entered By",
    "Entry Method",
    "Notes",
    "Last Modified",
    "Team",
    "Approved By",
    "Approved At",
]
SUMMARY_COLUMNS = [
    "Category",
    "Budgeted (AED)",
    "Budgeted (USD)",
    "Budgeted (AED equiv)",
    "Spent (AED)",
    "Spent (USD)",
    "Spent (AED equiv)",
    "Remaining (AED equiv)",
    "% Used",
    "Visual",
]
SUMMARY_CATEGORIES = {
    "Equipment",
    "Consumables",
    "Personnel",
    "Travel",
    "Publications",
    "Memberships",
    "Other",
    "TOTAL",
}
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
EXCHANGE_RATE_CONFIG_KEYS = {
    "AED/USD Exchange Rate",
    "EUR/USD Exchange Rate",
    "JPY/USD Exchange Rate",
    "GBP/USD Exchange Rate",
}
TRANSACTION_MONEY_COLUMNS = {
    "Amount",
    "Amount (USD equiv)",
    "Amount (AED)",
    "Amount (USD)",
    "Amount (AED equiv)",
}
REGISTRY_MEMBER_COLUMNS = [
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
REGISTRY_MEMBER_TEAM_COLUMNS = [
    "member_team_id",
    "member_id",
    "team_id",
    "team_role",
    "active",
    "start_date",
    "end_date",
]
REGISTRY_APP_ROLE_COLUMNS = [
    "app_role_id",
    "member_id",
    "app_id",
    "app_role",
    "scope_team_id",
    "active",
    "start_date",
    "end_date",
]


class SheetsSourceError(RuntimeError):
    pass


@contextmanager
def _sheet_write_lock():
    if connection.vendor == "postgresql":
        lock_id = int.from_bytes(
            hashlib.sha256(b"kamei-budget-google-sheet-write").digest()[:8],
            byteorder="big",
            signed=True,
        )
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [lock_id])
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [lock_id])
        return
    lock_path = os.environ.get("SHEET_WRITE_LOCK_PATH", "/tmp/kamei-budget-sheet-write.lock")
    with open(lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _truthy(value) -> bool:
    return str(value or "").strip().upper() in {"TRUE", "YES", "Y", "1"}


def _legacy_secrets() -> dict:
    if not settings.DEBUG:
        return {}
    path = Path(settings.BASE_DIR).parent / "streamlit_app" / ".streamlit" / "secrets.toml"
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _service_account_info() -> dict:
    raw = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if raw:
        try:
            return json.loads(raw)
        except json.JSONDecodeError as error:
            raise SheetsSourceError("GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON.") from error
    return dict(_legacy_secrets().get("gcp_service_account", {}))


def _master_spreadsheet_id() -> str:
    return (
        settings.MASTER_SPREADSHEET_ID
        or str(_legacy_secrets().get("SPREADSHEET_ID", ""))
    ).strip()


def _registry_spreadsheet_id() -> str:
    return (
        settings.REGISTRY_SPREADSHEET_ID
        or str(_legacy_secrets().get("REGISTRY_SPREADSHEET_ID", ""))
    ).strip()


def _split_values(value) -> list[str]:
    return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]


def _role_people(rows, member_lookup, allowed_roles):
    emails = []
    names = []
    for row in rows:
        if str(row.get("app_role", "")).strip() not in allowed_roles:
            continue
        member = member_lookup.get(str(row.get("member_id", "")), {})
        email = str(member.get("email", "")).strip().lower()
        name = str(member.get("display_name", "") or member.get("name", "")).strip()
        if email and email not in emails:
            emails.append(email)
            names.append(name or email)
    return ", ".join(emails), ", ".join(names)


class SheetsGateway:
    """Read and write adapter for the fiscal-year Google Sheet topology."""

    def __init__(self, client=None):
        if client is not None:
            self.client = client
            return
        info = _service_account_info()
        scopes = WRITE_SCOPES if settings.ENABLE_SHEET_WRITES else READ_SCOPES
        if info:
            credentials = Credentials.from_service_account_info(info, scopes=scopes)
        else:
            try:
                credentials, _ = google.auth.default(scopes=scopes)
            except google.auth.exceptions.DefaultCredentialsError as error:
                raise SheetsSourceError(
                    "Google Application Default Credentials are not configured."
                ) from error
        self.client = gspread.authorize(credentials, http_client=gspread.BackOffHTTPClient)

    def _open(self, spreadsheet_id):
        try:
            return self.client.open_by_key(spreadsheet_id)
        except Exception as error:
            raise SheetsSourceError("The configured Google Sheet could not be opened.") from error

    @staticmethod
    def _config_map(workbook):
        try:
            rows = workbook.worksheet("Config").get_all_values()
        except Exception as error:
            raise SheetsSourceError("The master Config worksheet could not be read.") from error
        return {
            str(row[0]).strip(): str(row[1]).strip() if len(row) > 1 else ""
            for row in rows
            if row and str(row[0]).strip()
        }

    def fiscal_year_options(self):
        master_id = _master_spreadsheet_id()
        if not master_id:
            raise SheetsSourceError("MASTER_SPREADSHEET_ID is not configured.")
        config = self._config_map(self._open(master_id))
        years = {
            key.removeprefix("Spreadsheet ID ")
            for key in config
            if key.startswith("Spreadsheet ID FY")
        }
        for key in ("Current Fiscal Year", "Fiscal Year"):
            if config.get(key, "").startswith("FY"):
                years.add(config[key])
        return sorted(years, reverse=True)

    def _workbook_for_year(self, fiscal_year):
        master_id = _master_spreadsheet_id()
        if not master_id:
            raise SheetsSourceError("MASTER_SPREADSHEET_ID is not configured.")
        master = self._open(master_id)
        config = self._config_map(master)
        spreadsheet_id = config.get(f"Spreadsheet ID {fiscal_year}")
        base_year = config.get("Current Fiscal Year") or config.get("Fiscal Year")
        if not spreadsheet_id and fiscal_year == base_year:
            spreadsheet_id = master_id
        if not spreadsheet_id:
            raise SheetsSourceError(f"No Google Sheet is registered for {fiscal_year}.")
        return self._open(spreadsheet_id), spreadsheet_id, master, base_year

    @staticmethod
    def _worksheet_name(name, fiscal_year, spreadsheet_id, master_id, base_year):
        if spreadsheet_id == master_id and fiscal_year != base_year:
            return f"{name} {fiscal_year}"
        return name

    @staticmethod
    def _summary_rows(worksheet):
        rows = worksheet.get_all_values()
        result = []
        for row in rows:
            if not row or str(row[0]).strip() not in SUMMARY_CATEGORIES:
                continue
            padded = row[: len(SUMMARY_COLUMNS)] + [""] * max(0, len(SUMMARY_COLUMNS) - len(row))
            result.append(dict(zip(SUMMARY_COLUMNS, padded, strict=False)))
        return result

    def _registry_teams(self, existing_rows):
        registry_id = _registry_spreadsheet_id()
        if not registry_id:
            return existing_rows, [], "Registry ID is not configured; using annual Teams worksheet."
        try:
            registry = self._open(registry_id)
            members = registry.worksheet("Members").get_all_records()
            teams = registry.worksheet("Teams").get_all_records()
            memberships = registry.worksheet("Member_Teams").get_all_records()
            app_roles = registry.worksheet("App_Roles").get_all_records()
        except SheetsSourceError:
            return existing_rows, [], "Registry could not be opened; using annual Teams worksheet."
        except Exception:
            return existing_rows, [], "Registry tables could not be read; using annual Teams worksheet."

        active_members = {str(row.get("member_id", "")): row for row in members if _truthy(row.get("active"))}
        active_teams = [row for row in teams if _truthy(row.get("active"))]
        active_memberships = [row for row in memberships if _truthy(row.get("active"))]
        roles = [
            row
            for row in app_roles
            if _truthy(row.get("active")) and str(row.get("app_id", "")) == "budget"
        ]
        global_ids = {
            member_id
            for member_id, row in active_members.items()
            if str(row.get("global_role", "")).strip().lower() in {"pi", "admin"}
        }
        roles.extend(
            {
                "member_id": member_id,
                "app_role": "owner",
                "scope_team_id": "",
                "active": "TRUE",
            }
            for member_id in global_ids
        )
        allocations = {str(row.get("Team Name", "")).strip(): row for row in existing_rows}
        output = []
        team_names_by_id = {
            str(row.get("team_id", "")): str(row.get("team_name", "")).strip()
            for row in active_teams
            if str(row.get("team_id", "")).strip()
            and str(row.get("team_name", "")).strip()
        }
        for team in active_teams:
            team_id = str(team.get("team_id", ""))
            name = str(team.get("team_name", "")).strip()
            if not name:
                continue
            team_member_ids = {
                str(row.get("member_id", ""))
                for row in active_memberships
                if str(row.get("team_id", "")) == team_id
            }
            scoped = [
                row
                for row in roles
                if str(row.get("member_id", "")) in active_members
                and (
                    str(row.get("member_id", "")) in team_member_ids
                    or str(row.get("member_id", "")) in global_ids
                )
                and str(row.get("scope_team_id", "")) in {"", team_id}
            ]
            managers = _role_people(scoped, active_members, {"owner", "manager"})
            leads = _role_people(scoped, active_members, {"lead"})
            viewers = _role_people(scoped, active_members, {"editor", "viewer"})
            if not any((managers[0], leads[0], viewers[0])):
                continue
            existing = allocations.get(name, {})
            output.append(
                {
                    "Team Name": name,
                    "Allocation (AED)": existing.get("Allocation (AED)", ""),
                    "Allocation (USD)": existing.get("Allocation (USD)", ""),
                    "Budget Manager Emails": managers[0],
                    "Budget Manager Names": managers[1],
                    "Lead Emails": leads[0],
                    "Lead Names": leads[1],
                    "Member Emails": viewers[0],
                    "Member Names": viewers[1],
                    "Description": str(team.get("description", "")),
                    "Active": "Y",
                }
            )
        access_rows = []
        for member_id, member in active_members.items():
            email = str(member.get("email", "")).strip().lower()
            if not email:
                continue
            member_roles = [
                row for row in roles if str(row.get("member_id", "")) == member_id
            ]
            global_roles = {
                str(row.get("app_role", "")).strip().lower()
                for row in member_roles
                if not str(row.get("scope_team_id", "")).strip()
            }
            global_role = str(member.get("global_role", "")).strip().lower()
            if global_role in {"pi", "admin"} or "owner" in global_roles:
                budget_role = "pi"
            elif "manager" in global_roles:
                budget_role = "budget_manager"
            else:
                budget_role = "member"
            team_roles = {}
            for membership in active_memberships:
                if str(membership.get("member_id", "")) != member_id:
                    continue
                team_id = str(membership.get("team_id", ""))
                team_name = team_names_by_id.get(team_id)
                if not team_name:
                    continue
                scoped_roles = {
                    str(row.get("app_role", "")).strip().lower()
                    for row in member_roles
                    if str(row.get("scope_team_id", "")) == team_id
                }
                membership_role = str(membership.get("team_role", "")).strip().lower()
                if scoped_roles.intersection({"owner", "manager", "lead"}) or membership_role == "lead":
                    team_roles[team_name] = "lead"
                else:
                    team_roles[team_name] = "member"
            if budget_role not in {"pi", "budget_manager"} and any(
                role == "lead" for role in team_roles.values()
            ):
                budget_role = "lead"
            access_rows.append(
                {
                    "email": email,
                    "display_name": str(
                        member.get("display_name") or member.get("name") or email
                    ).strip(),
                    "role": budget_role,
                    "team_roles": team_roles,
                    "active": True,
                }
            )
        return output or existing_rows, access_rows, ""

    def read_fiscal_year(self, fiscal_year):
        workbook, spreadsheet_id, master, base_year = self._workbook_for_year(fiscal_year)
        master_id = _master_spreadsheet_id()
        worksheet_name = lambda name: self._worksheet_name(
            name, fiscal_year, spreadsheet_id, master_id, base_year
        )
        try:
            transactions = workbook.worksheet(worksheet_name("Transactions")).get_all_records()
            summary = self._summary_rows(workbook.worksheet(worksheet_name("Summary")))
            teams = workbook.worksheet(worksheet_name("Teams")).get_all_records()
            try:
                config_rows = workbook.worksheet(worksheet_name("Config")).get_all_values()
            except gspread.exceptions.WorksheetNotFound:
                config_rows = master.worksheet("Config").get_all_values()
        except Exception as error:
            raise SheetsSourceError(f"The {fiscal_year} workbook is missing a required worksheet.") from error
        transactions = [
            row for row in transactions if str(row.get("Transaction ID", "")).strip()
        ]
        teams, members, registry_warning = self._registry_teams(teams)
        config = {
            str(row[0]).strip(): str(row[1]).strip() if len(row) > 1 else ""
            for row in config_rows
            if row
        }
        rates = {code: str(value) for code, value in DEFAULT_RATES_TO_USD.items()}
        aed_per_usd = "3.6725"
        try:
            configured_aed_per_usd = float(config.get("AED/USD Exchange Rate", "3.6725"))
            if configured_aed_per_usd > 0:
                aed_per_usd = str(configured_aed_per_usd)
        except (TypeError, ValueError, ZeroDivisionError):
            pass
        rates["AED"] = str(Decimal("1") / decimal_value(aed_per_usd, "3.6725"))
        for code in ("EUR", "JPY", "GBP"):
            configured = decimal_value(
                config.get(f"{code}/USD Exchange Rate"),
                str(DEFAULT_RATES_TO_USD[code]),
            )
            if configured > 0:
                rates[code] = str(configured)
        return {
            "fiscal_year": fiscal_year,
            "spreadsheet_id": spreadsheet_id,
            "summary": summary,
            "teams": teams,
            "members": members,
            "transactions": transactions,
            "exchange_rates": rates,
            "aed_per_usd": aed_per_usd,
            "warnings": [registry_warning] if registry_warning else [],
        }

    @staticmethod
    def _column_label(index):
        label = ""
        while index:
            index, remainder = divmod(index - 1, 26)
            label = chr(65 + remainder) + label
        return label

    @staticmethod
    def _normalize_key(value):
        return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())

    @staticmethod
    def _row_mapping(headers, row):
        return {
            header: row[index] if index < len(row) else ""
            for index, header in enumerate(headers)
        }

    def _transaction_sheet(self, fiscal_year):
        workbook, spreadsheet_id, _, base_year = self._workbook_for_year(fiscal_year)
        worksheet_name = self._worksheet_name(
            "Transactions",
            fiscal_year,
            spreadsheet_id,
            _master_spreadsheet_id(),
            base_year,
        )
        try:
            return workbook.worksheet(worksheet_name), workbook, spreadsheet_id, base_year
        except Exception as error:
            raise SheetsSourceError(
                f"The {fiscal_year} workbook is missing its Transactions worksheet."
            ) from error

    @staticmethod
    def _configured_rates(workbook, master, fiscal_year, spreadsheet_id, base_year):
        worksheet_name = SheetsGateway._worksheet_name(
            "Config", fiscal_year, spreadsheet_id, _master_spreadsheet_id(), base_year
        )
        try:
            values = workbook.worksheet(worksheet_name).get_all_values()
        except Exception:
            values = master.worksheet("Config").get_all_values()
        config = {
            str(row[0]).strip(): str(row[1]).strip() if len(row) > 1 else ""
            for row in values
            if row and str(row[0]).strip()
        }
        rates = dict(DEFAULT_RATES_TO_USD)
        aed_per_usd = decimal_value(config.get("AED/USD Exchange Rate"), "3.6725")
        if aed_per_usd > 0:
            rates["AED"] = Decimal("1") / aed_per_usd
        else:
            aed_per_usd = Decimal("3.6725")
        for code in ("EUR", "JPY", "GBP"):
            configured = decimal_value(config.get(f"{code}/USD Exchange Rate"), "0")
            if configured > 0:
                rates[code] = configured
        return rates, aed_per_usd

    def _ensure_transaction_headers(self, worksheet, values):
        headers = list(values[0]) if values else []
        missing = [header for header in TRANSACTION_COLUMNS if header not in headers]
        if not headers:
            headers = list(TRANSACTION_COLUMNS)
        else:
            headers.extend(missing)
        if not values or missing:
            current_columns = getattr(worksheet, "col_count", len(headers))
            if current_columns < len(headers):
                worksheet.add_cols(len(headers) - current_columns)
            end_column = self._column_label(len(headers))
            worksheet.update(
                values=[headers],
                range_name=f"A1:{end_column}1",
                value_input_option="RAW",
            )
        return headers

    def _new_transaction_id(self, existing_ids, pdf_hash=""):
        date_part = datetime.now(DUBAI_TZ).strftime("%Y%m%d")
        if pdf_hash:
            candidate = f"TXN-{date_part}-W{pdf_hash[:12].upper()}"
            if candidate not in existing_ids:
                return candidate
        for _ in range(10):
            candidate = f"TXN-{date_part}-W{secrets.token_hex(4).upper()}"
            if candidate not in existing_ids:
                return candidate
        raise SheetsSourceError("A unique transaction ID could not be generated.")

    @staticmethod
    def _require_writes():
        if not settings.ENABLE_SHEET_WRITES:
            raise SheetsSourceError("Google Sheet writes are disabled in this environment.")

    @staticmethod
    def _validate_fiscal_year(fiscal_year):
        fiscal_year = str(fiscal_year or "").strip()
        if not re.fullmatch(r"FY\d{4}-\d{2}", fiscal_year):
            raise ValueError("Fiscal year must look like FY2026-27.")
        return fiscal_year

    @staticmethod
    def _candidate_value(candidate, current, sheet_name, snake_name, default=""):
        for key in (snake_name, sheet_name):
            if key in candidate:
                return candidate[key]
        return current.get(sheet_name, default)

    def _worksheet_for_year(self, fiscal_year, sheet_name):
        fiscal_year = self._validate_fiscal_year(fiscal_year)
        workbook, spreadsheet_id, master, base_year = self._workbook_for_year(fiscal_year)
        worksheet_name = self._worksheet_name(
            sheet_name,
            fiscal_year,
            spreadsheet_id,
            _master_spreadsheet_id(),
            base_year,
        )
        try:
            worksheet = workbook.worksheet(worksheet_name)
        except Exception as error:
            raise SheetsSourceError(
                f"The {fiscal_year} workbook is missing its {sheet_name} worksheet."
            ) from error
        return worksheet, workbook, spreadsheet_id, master, base_year

    @staticmethod
    def _ensure_headers(worksheet, values, required_headers):
        headers = list(values[0]) if values else []
        missing = [header for header in required_headers if header not in headers]
        if not headers:
            headers = list(required_headers)
        else:
            headers.extend(missing)
        if not values or missing:
            current_columns = getattr(worksheet, "col_count", len(headers))
            if current_columns < len(headers):
                worksheet.add_cols(len(headers) - current_columns)
            end_column = SheetsGateway._column_label(len(headers))
            worksheet.update(
                values=[headers],
                range_name=f"A1:{end_column}1",
                value_input_option="RAW",
            )
        return headers

    @staticmethod
    def _transaction_match(values, headers, transaction_id):
        matches = [
            (row_number, SheetsGateway._row_mapping(headers, raw_row))
            for row_number, raw_row in enumerate(values[1:], start=2)
            if str(
                SheetsGateway._row_mapping(headers, raw_row).get("Transaction ID") or ""
            ).strip()
            == transaction_id
        ]
        if len(matches) > 1:
            raise SheetsSourceError(
                f"Transaction {transaction_id} appears more than once in Google Sheets."
            )
        return matches[0] if matches else (None, None)

    def _build_transaction_row(
        self,
        fiscal_year,
        candidate,
        current,
        transaction_id,
        rates,
        aed_per_usd,
    ):
        transaction_date = self._candidate_value(
            candidate, current, "Date", "date"
        )
        if isinstance(transaction_date, date):
            transaction_date = transaction_date.isoformat()
        else:
            transaction_date = str(transaction_date or "").strip()
        if not transaction_date:
            raise ValueError("Transaction date is required.")
        try:
            inferred_fiscal_year = fiscal_year_for_date(transaction_date)
        except (TypeError, ValueError) as error:
            raise ValueError("Transaction date must be a valid ISO date.") from error

        currency = str(
            self._candidate_value(candidate, current, "Currency", "currency") or ""
        ).strip().upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise ValueError("Unsupported currency.")
        amount = money(
            self._candidate_value(candidate, current, "Amount", "amount")
        )
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")
        team = str(
            self._candidate_value(candidate, current, "Team", "team") or ""
        ).strip()
        if not team:
            raise ValueError("Team is required.")
        status = str(
            self._candidate_value(
                candidate, current, "Status", "status", "Allocated"
            )
            or "Allocated"
        ).strip()
        if status not in {"Allocated", "Cancelled"}:
            raise ValueError("Status must be Allocated or Cancelled.")

        amount_usd = money(amount * decimal_value(rates[currency]))
        amount_aed_equiv = money(amount_usd * aed_per_usd)
        notes = str(
            self._candidate_value(candidate, current, "Notes", "notes") or ""
        ).strip()
        override_note = (
            f"[FY OVERRIDE: date implies {inferred_fiscal_year}]"
            if inferred_fiscal_year != fiscal_year
            else ""
        )
        if override_note and override_note not in notes:
            notes = "\n".join(part for part in (notes, override_note) if part)
        now_text = datetime.now(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
        row = {column: current.get(column, "") for column in TRANSACTION_COLUMNS}
        row.update(
            {
                "Transaction ID": transaction_id,
                "Date": transaction_date,
                "Fiscal Year": fiscal_year,
                "Category": str(
                    self._candidate_value(candidate, current, "Category", "category")
                    or ""
                ).strip(),
                "Sub-category": str(
                    self._candidate_value(
                        candidate, current, "Sub-category", "subcategory"
                    )
                    or ""
                ).strip(),
                "Vendor / Payee": str(
                    self._candidate_value(
                        candidate, current, "Vendor / Payee", "vendor"
                    )
                    or ""
                ).strip(),
                "Description": str(
                    self._candidate_value(
                        candidate, current, "Description", "description"
                    )
                    or ""
                ).strip(),
                "PO Number": str(
                    self._candidate_value(
                        candidate, current, "PO Number", "po_number"
                    )
                    or ""
                ).strip(),
                "Invoice Number": str(
                    self._candidate_value(
                        candidate, current, "Invoice Number", "invoice_number"
                    )
                    or ""
                ).strip(),
                "Currency": currency,
                "Amount": str(amount),
                "Amount (USD equiv)": str(amount_usd),
                "Amount (AED)": str(
                    amount if currency == "AED" else Decimal("0")
                ),
                "Amount (USD)": str(
                    amount if currency == "USD" else Decimal("0")
                ),
                "Amount (AED equiv)": str(amount_aed_equiv),
                "Status": status,
                "Receipt Confirmed": str(
                    self._candidate_value(
                        candidate,
                        current,
                        "Receipt Confirmed",
                        "receipt_confirmed",
                        "FALSE",
                    )
                    or "FALSE"
                ),
                "PDF Link": str(
                    self._candidate_value(
                        candidate, current, "PDF Link", "pdf_link"
                    )
                    or ""
                ).strip(),
                "Email Thread ID": str(
                    self._candidate_value(
                        candidate,
                        current,
                        "Email Thread ID",
                        "email_thread_id",
                    )
                    or ""
                ).strip(),
                "Entered By": str(
                    self._candidate_value(
                        candidate, current, "Entered By", "entered_by"
                    )
                    or ""
                ).strip(),
                "Entry Method": str(
                    self._candidate_value(
                        candidate, current, "Entry Method", "entry_method", "Manual"
                    )
                    or "Manual"
                ).strip(),
                "Notes": notes,
                "Last Modified": now_text,
                "Team": team,
                "Approved By": str(
                    self._candidate_value(
                        candidate, current, "Approved By", "approved_by"
                    )
                    or ""
                ).strip(),
                "Approved At": str(
                    self._candidate_value(
                        candidate, current, "Approved At", "approved_at"
                    )
                    or ""
                ).strip(),
            }
        )
        return row

    def _verify_transaction_row(self, expected, actual, ignore=()):
        for column in TRANSACTION_COLUMNS:
            if column in ignore:
                continue
            expected_value = expected.get(column, "")
            actual_value = actual.get(column, "")
            if column in TRANSACTION_MONEY_COLUMNS:
                verified = money(actual_value) == money(expected_value)
            else:
                verified = str(actual_value).strip() == str(expected_value).strip()
            if not verified:
                raise SheetsSourceError(
                    f"The written Google Sheet {column} value did not verify."
                )

    def _write_verified_transaction_row(
        self, worksheet, headers, row, row_index=None
    ):
        output = [row.get(header, "") for header in headers]
        end_column = self._column_label(len(headers))
        try:
            if row_index is None:
                worksheet.append_row(output, value_input_option="RAW")
                row_index = len(worksheet.get_all_values())
            else:
                worksheet.update(
                    values=[output],
                    range_name=f"A{row_index}:{end_column}{row_index}",
                    value_input_option="RAW",
                )
            written_values = worksheet.get(
                f"A{row_index}:{end_column}{row_index}"
            )
        except Exception as error:
            raise SheetsSourceError(
                "The transaction could not be written to Google Sheets."
            ) from error
        if not written_values:
            raise SheetsSourceError(
                "Google Sheets did not return the written transaction row."
            )
        written = self._row_mapping(headers, written_values[0])
        self._verify_transaction_row(row, written)
        return written

    def _transaction_context(self, fiscal_year):
        fiscal_year = self._validate_fiscal_year(fiscal_year)
        worksheet, workbook, spreadsheet_id, base_year = self._transaction_sheet(
            fiscal_year
        )
        master = self._open(_master_spreadsheet_id())
        try:
            values = worksheet.get_all_values()
            headers = self._ensure_transaction_headers(worksheet, values)
            if not values:
                values = [headers]
            rates, aed_per_usd = self._configured_rates(
                workbook, master, fiscal_year, spreadsheet_id, base_year
            )
        except SheetsSourceError:
            raise
        except Exception as error:
            raise SheetsSourceError(
                "The transaction worksheet could not be prepared."
            ) from error
        return {
            "fiscal_year": fiscal_year,
            "worksheet": worksheet,
            "spreadsheet_id": spreadsheet_id,
            "values": values,
            "headers": headers,
            "rates": rates,
            "aed_per_usd": aed_per_usd,
        }

    def write_transaction(
        self,
        fiscal_year,
        candidate,
        transaction_id="",
        allow_existing=False,
    ):
        """Create and read back one 26-column transaction row."""
        self._require_writes()
        with _sheet_write_lock():
            context = self._transaction_context(fiscal_year)
            existing_ids = {
                str(self._row_mapping(context["headers"], raw).get("Transaction ID") or "").strip()
                for raw in context["values"][1:]
            }
            transaction_id = str(
                transaction_id
                or candidate.get("transaction_id")
                or candidate.get("Transaction ID")
                or ""
            ).strip()
            existing_index = None
            existing_row = None
            if transaction_id and transaction_id in existing_ids:
                existing_index, existing_row = self._transaction_match(
                    context["values"], context["headers"], transaction_id
                )
                if not allow_existing:
                    raise SheetsSourceError(
                        f"Transaction {transaction_id} already exists in {context['fiscal_year']}."
                    )
            if not transaction_id:
                transaction_id = self._new_transaction_id(existing_ids)
            row = self._build_transaction_row(
                context["fiscal_year"],
                candidate,
                existing_row or {},
                transaction_id,
                context["rates"],
                context["aed_per_usd"],
            )
            if existing_index is not None:
                self._verify_transaction_row(
                    row,
                    existing_row,
                    ignore={"Last Modified"},
                )
                written = existing_row
            else:
                written = self._write_verified_transaction_row(
                    context["worksheet"], context["headers"], row
                )
            return {
                "transaction_id": transaction_id,
                "matched": existing_index is not None,
                "row": written,
                "spreadsheet_id": context["spreadsheet_id"],
            }

    def update_transaction(
        self,
        source_fiscal_year,
        transaction_id,
        candidate,
        target_fiscal_year=None,
    ):
        """Update one transaction, optionally moving it after target verification."""
        self._require_writes()
        with _sheet_write_lock():
            source = self._transaction_context(source_fiscal_year)
            transaction_id = str(transaction_id or "").strip()
            source_index, current = self._transaction_match(
                source["values"], source["headers"], transaction_id
            )
            if source_index is None:
                raise SheetsSourceError(
                    f"Transaction {transaction_id} was not found in {source['fiscal_year']}."
                )
            requested_target = (
                target_fiscal_year
                or candidate.get("fiscal_year")
                or candidate.get("Fiscal Year")
                or source["fiscal_year"]
            )
            requested_target = self._validate_fiscal_year(requested_target)
            if requested_target == source["fiscal_year"]:
                row = self._build_transaction_row(
                    source["fiscal_year"],
                    candidate,
                    current,
                    transaction_id,
                    source["rates"],
                    source["aed_per_usd"],
                )
                written = self._write_verified_transaction_row(
                    source["worksheet"], source["headers"], row, source_index
                )
                return {
                    "transaction_id": transaction_id,
                    "matched": True,
                    "moved": False,
                    "row": written,
                    "spreadsheet_id": source["spreadsheet_id"],
                }

            target = self._transaction_context(requested_target)
            target_index, _ = self._transaction_match(
                target["values"], target["headers"], transaction_id
            )
            if target_index is not None:
                raise SheetsSourceError(
                    f"Transaction {transaction_id} already exists in {requested_target}."
                )
            moved_candidate = {**current, **candidate, "Fiscal Year": requested_target}
            target_row = self._build_transaction_row(
                requested_target,
                moved_candidate,
                current,
                transaction_id,
                target["rates"],
                target["aed_per_usd"],
            )
            try:
                target_written = self._write_verified_transaction_row(
                    target["worksheet"], target["headers"], target_row
                )
            except Exception:
                self._delete_transaction_locked(requested_target, transaction_id)
                raise
            disposition = str(
                candidate.get("source_disposition") or "cancel"
            ).strip().lower()
            if disposition not in {"cancel", "delete"}:
                self._delete_transaction_locked(requested_target, transaction_id)
                raise ValueError("source_disposition must be cancel or delete.")
            try:
                if disposition == "delete":
                    self._delete_transaction_locked(source["fiscal_year"], transaction_id)
                    source_result = {"deleted": True}
                else:
                    cancelled_row = self._build_transaction_row(
                        source["fiscal_year"],
                        {"Status": "Cancelled"},
                        current,
                        transaction_id,
                        source["rates"],
                        source["aed_per_usd"],
                    )
                    source_written = self._write_verified_transaction_row(
                        source["worksheet"],
                        source["headers"],
                        cancelled_row,
                        source_index,
                    )
                    source_result = {"deleted": False, "row": source_written}
            except Exception:
                try:
                    self._delete_transaction_locked(requested_target, transaction_id)
                except Exception as rollback_error:
                    raise SheetsSourceError(
                        "The source cleanup failed and the verified target row could not be rolled back."
                    ) from rollback_error
                raise
            return {
                "transaction_id": transaction_id,
                "matched": True,
                "moved": True,
                "source_fiscal_year": source["fiscal_year"],
                "target_fiscal_year": requested_target,
                "source_disposition": disposition,
                "source": source_result,
                "row": target_written,
                "spreadsheet_id": target["spreadsheet_id"],
            }

    def cancel_transaction(self, fiscal_year, transaction_id):
        return self.update_transaction(
            fiscal_year, transaction_id, {"Status": "Cancelled"}
        )

    def write_category_allocations(self, fiscal_year, allocations):
        """Atomically update only budget cells, preserving Summary formulas."""
        self._require_writes()
        with _sheet_write_lock():
            worksheet, workbook, spreadsheet_id, master, base_year = self._worksheet_for_year(
                fiscal_year, "Summary"
            )
            values = worksheet.get_all_values()
            headers = self._ensure_headers(worksheet, values, SUMMARY_COLUMNS)
            if not values:
                raise SheetsSourceError("The Summary template has no category rows.")
            _, aed_per_usd = self._configured_rates(
                workbook, master, fiscal_year, spreadsheet_id, base_year
            )
            prepared = []
            for category, raw_usd in allocations.items():
                category = str(category or "").strip()
                if category not in SUMMARY_CATEGORIES - {"TOTAL"}:
                    raise ValueError(f"Unsupported budget category: {category}")
                usd = money(raw_usd)
                if usd < 0:
                    raise ValueError("Category allocations cannot be negative.")
                matches = [
                    (index, self._row_mapping(headers, raw_row))
                    for index, raw_row in enumerate(values[1:], start=2)
                    if str(self._row_mapping(headers, raw_row).get("Category") or "").strip()
                    == category
                ]
                if len(matches) != 1:
                    raise SheetsSourceError(
                        f"Category {category} must appear exactly once in Summary."
                    )
                row_index, _ = matches[0]
                budget_aed_equiv = money(usd * aed_per_usd)
                prepared.append((category, row_index, usd, budget_aed_equiv))
            budget_columns = [
                headers.index("Budgeted (AED)") + 1,
                headers.index("Budgeted (USD)") + 1,
                headers.index("Budgeted (AED equiv)") + 1,
            ]
            if budget_columns != list(range(budget_columns[0], budget_columns[0] + 3)):
                raise SheetsSourceError("Summary budget columns must remain contiguous.")
            start_column = self._column_label(budget_columns[0])
            end_column = self._column_label(budget_columns[-1])
            worksheet.batch_update(
                [
                    {
                        "range": f"{start_column}{row_index}:{end_column}{row_index}",
                        "values": [["0", str(usd), str(aed_equiv)]],
                    }
                    for _, row_index, usd, aed_equiv in prepared
                ],
                value_input_option="RAW",
            )
            results = {}
            for category, row_index, usd, budget_aed_equiv in prepared:
                written_values = worksheet.get(
                    f"{start_column}{row_index}:{end_column}{row_index}"
                )
                if not written_values:
                    raise SheetsSourceError(
                        f"Google Sheets did not return the {category} Summary row."
                    )
                written = written_values[0]
                expected = [Decimal("0"), usd, budget_aed_equiv]
                if len(written) < 3 or any(
                    money(actual) != money(expected_value)
                    for actual, expected_value in zip(written[:3], expected, strict=True)
                ):
                    raise SheetsSourceError(
                        f"The written Summary {category} budget values did not verify."
                    )
                results[category] = {
                    "Category": category,
                    "Budgeted (AED)": written[0],
                    "Budgeted (USD)": written[1],
                    "Budgeted (AED equiv)": written[2],
                }
            return {"spreadsheet_id": spreadsheet_id, "rows": results}

    def repair_summary_formulas(self, fiscal_year):
        """Restore fixed Summary calculation formulas without touching budget inputs."""
        self._require_writes()
        with _sheet_write_lock():
            worksheet, _, spreadsheet_id, _, base_year = self._worksheet_for_year(
                fiscal_year, "Summary"
            )
            values = worksheet.get_all_values()
            row_by_category = {
                str(row[0]).strip(): index
                for index, row in enumerate(values, start=1)
                if row and str(row[0]).strip()
            }
            category_rows = [
                row_by_category[category]
                for category in (
                    "Equipment",
                    "Consumables",
                    "Personnel",
                    "Travel",
                    "Publications",
                    "Memberships",
                    "Other",
                )
                if category in row_by_category
            ]
            if len(category_rows) != 7:
                raise SheetsSourceError("Summary does not contain all standard category rows.")
            master_id = _master_spreadsheet_id()
            transaction_title = self._worksheet_name(
                "Transactions", fiscal_year, spreadsheet_id, master_id, base_year
            ).replace("'", "''")
            updates = []
            for row_index in category_rows:
                formulas = [
                    f'=SUMIFS(\'{transaction_title}\'!$M:$M,\'{transaction_title}\'!$D:$D,$A{row_index},\'{transaction_title}\'!$P:$P,"<>Cancelled")',
                    f'=SUMIFS(\'{transaction_title}\'!$N:$N,\'{transaction_title}\'!$D:$D,$A{row_index},\'{transaction_title}\'!$P:$P,"<>Cancelled")',
                    f'=SUMIFS(\'{transaction_title}\'!$O:$O,\'{transaction_title}\'!$D:$D,$A{row_index},\'{transaction_title}\'!$P:$P,"<>Cancelled")',
                    f"=D{row_index}-G{row_index}",
                    f"=IFERROR(G{row_index}/D{row_index},0)",
                    f'=IFERROR(SPARKLINE(I{row_index},{{"charttype","bar";"max",1;"color1",IF(I{row_index}>0.9,"#cc0000",IF(I{row_index}>0.7,"#ff9900","#34a853"))}}),"")',
                ]
                updates.append(
                    {"range": f"E{row_index}:J{row_index}", "values": [formulas]}
                )
            total_row = row_by_category.get("TOTAL")
            if total_row:
                first_row, last_row = min(category_rows), max(category_rows)
                total_formulas = [
                    f"=SUM(B{first_row}:B{last_row})",
                    f"=SUM(C{first_row}:C{last_row})",
                    f"=SUM(D{first_row}:D{last_row})",
                    f"=SUM(E{first_row}:E{last_row})",
                    f"=SUM(F{first_row}:F{last_row})",
                    f"=SUM(G{first_row}:G{last_row})",
                    f"=D{total_row}-G{total_row}",
                    f"=IFERROR(G{total_row}/D{total_row},0)",
                    f'=IFERROR(SPARKLINE(I{total_row},{{"charttype","bar";"max",1;"color1",IF(I{total_row}>0.9,"#cc0000",IF(I{total_row}>0.7,"#ff9900","#34a853"))}}),"")',
                ]
                updates.append(
                    {"range": f"B{total_row}:J{total_row}", "values": [total_formulas]}
                )
            verification_updates = [
                {"range": update["range"], "values": update["values"]}
                for update in updates
            ]
            worksheet.batch_update(updates, value_input_option="USER_ENTERED")
            for update in verification_updates:
                written = worksheet.get(
                    update["range"], value_render_option="FORMULA"
                )
                expected = [
                    re.sub(r"'([A-Za-z0-9_]+)'!", r"\1!", formula)
                    for formula in update["values"][0]
                ]
                actual = [
                    re.sub(r"'([A-Za-z0-9_]+)'!", r"\1!", formula)
                    for formula in (written[0] if written else [])
                ]
                if actual != expected:
                    raise SheetsSourceError(
                        f"Summary formula readback failed for {update['range']}."
                    )
            return {
                "fiscal_year": fiscal_year,
                "spreadsheet_id": spreadsheet_id,
                "ranges": [update["range"] for update in verification_updates],
            }

    def upsert_team(self, fiscal_year, team_data):
        """Insert or update one annual Teams row and verify all standard columns."""
        self._require_writes()
        with _sheet_write_lock():
            worksheet, _, spreadsheet_id, _, _ = self._worksheet_for_year(
                fiscal_year, "Teams"
            )
            values = worksheet.get_all_values()
            headers = self._ensure_headers(worksheet, values, TEAM_COLUMNS)
            if not values:
                values = [headers]
            team_name = str(
                team_data.get("Team Name")
                or team_data.get("team_name")
                or team_data.get("name")
                or ""
            ).strip()
            if not team_name:
                raise ValueError("Team Name is required.")
            matches = [
                (index, self._row_mapping(headers, raw_row))
                for index, raw_row in enumerate(values[1:], start=2)
                if str(self._row_mapping(headers, raw_row).get("Team Name") or "").strip()
                == team_name
            ]
            if len(matches) > 1:
                raise SheetsSourceError(
                    f"Team {team_name} appears more than once in Google Sheets."
                )
            row_index, current = matches[0] if matches else (None, {})
            matched = row_index is not None
            row = {header: current.get(header, "") for header in headers}
            row["Team Name"] = team_name
            aliases = {
                "Allocation (AED)": "allocation_aed",
                "Allocation (USD)": "allocation_usd",
                "Budget Manager Emails": "budget_manager_emails",
                "Budget Manager Names": "budget_manager_names",
                "Lead Emails": "lead_emails",
                "Lead Names": "lead_names",
                "Member Emails": "member_emails",
                "Member Names": "member_names",
                "Description": "description",
                "Active": "active",
            }
            form_aliases = {
                "Budget Manager Emails": "manager_emails",
                "Lead Emails": "lead_emails",
                "Member Emails": "member_emails",
            }
            for column, alias in aliases.items():
                if alias in team_data:
                    row[column] = team_data[alias]
                elif form_aliases.get(column) in team_data:
                    row[column] = team_data[form_aliases[column]]
                elif column in team_data:
                    row[column] = team_data[column]
                elif row_index is None and column == "Active":
                    row[column] = "Y"
                elif row_index is None and column.startswith("Allocation"):
                    row[column] = "0"
            if isinstance(row.get("Active"), bool):
                row["Active"] = "Y" if row["Active"] else "N"
            for column in ("Allocation (AED)", "Allocation (USD)"):
                if money(row.get(column, 0)) < 0:
                    raise ValueError("Team allocations cannot be negative.")
            output = [row.get(header, "") for header in headers]
            end_column = self._column_label(len(headers))
            if row_index is None:
                worksheet.append_row(output, value_input_option="RAW")
                row_index = len(worksheet.get_all_values())
            else:
                worksheet.update(
                    values=[output],
                    range_name=f"A{row_index}:{end_column}{row_index}",
                    value_input_option="RAW",
                )
            written_values = worksheet.get(f"A{row_index}:{end_column}{row_index}")
            if not written_values:
                raise SheetsSourceError("Google Sheets did not return the Teams row.")
            written = self._row_mapping(headers, written_values[0])
            for column in TEAM_COLUMNS:
                if column.startswith("Allocation"):
                    verified = money(written.get(column, 0)) == money(row.get(column, 0))
                else:
                    verified = str(written.get(column, "")).strip() == str(
                        row.get(column, "")
                    ).strip()
                if not verified:
                    raise SheetsSourceError(
                        f"The written Teams {column} value did not verify."
                    )
            return {
                "matched": matched,
                "row": written,
                "spreadsheet_id": spreadsheet_id,
            }

    def upsert_registry_team(self, team_data):
        """Reconcile one central team, its memberships, and scoped Budget roles."""
        self._require_writes()
        registry_id = _registry_spreadsheet_id()
        if not registry_id:
            raise SheetsSourceError("REGISTRY_SPREADSHEET_ID is not configured.")
        team_name = str(team_data.get("name") or team_data.get("Team Name") or "").strip()
        if not team_name:
            raise ValueError("Team name is required.")
        active = team_data.get("active", True)
        active = active if isinstance(active, bool) else _truthy(active)
        desired_by_role = {
            "manager": {email.lower() for email in _split_values(team_data.get("manager_emails"))},
            "lead": {email.lower() for email in _split_values(team_data.get("lead_emails"))},
            "viewer": {email.lower() for email in _split_values(team_data.get("member_emails"))},
        }
        assigned = [email for emails in desired_by_role.values() for email in emails]
        if len(assigned) != len(set(assigned)):
            raise ValueError("Each person can have only one role in a team.")
        all_desired = set().union(*desired_by_role.values()) if active else set()
        today = datetime.now(DUBAI_TZ).date().isoformat()

        with _sheet_write_lock():
            registry = self._open(registry_id)
            members_ws, members_headers, members = self._registry_table(
                registry, "Members", REGISTRY_MEMBER_COLUMNS
            )
            teams_ws, teams_headers, teams = self._registry_table(
                registry, "Teams", ["team_id", "team_name", "description", "active"]
            )
            memberships_ws, memberships_headers, memberships = self._registry_table(
                registry, "Member_Teams", REGISTRY_MEMBER_TEAM_COLUMNS
            )
            roles_ws, roles_headers, roles = self._registry_table(
                registry, "App_Roles", REGISTRY_APP_ROLE_COLUMNS
            )
            del members_ws, members_headers

            matches = [
                row for row in teams
                if str(row.get("team_name", "")).strip().lower() == team_name.lower()
            ]
            if len(matches) > 1:
                raise SheetsSourceError(f"Registry team {team_name} appears more than once.")
            if matches:
                team = matches[0]
                team_id = str(team.get("team_id", "")).strip()
            else:
                team_id = self._next_registry_id(teams, "team_id", "T")
                team = {header: "" for header in teams_headers}
                team["team_id"] = team_id
                teams.append(team)
            team.update(
                {
                    "team_name": team_name,
                    "description": str(team_data.get("description") or ""),
                    "active": "TRUE" if active else "FALSE",
                }
            )

            members_by_email = {
                str(row.get("email", "")).strip().lower(): row
                for row in members
                if _truthy(row.get("active")) and str(row.get("email", "")).strip()
            }
            missing = sorted(all_desired.difference(members_by_email))
            if missing:
                raise ValueError(
                    "Add these people to the lab roster before assigning the team: "
                    + ", ".join(missing)
                )
            desired_ids = {
                str(members_by_email[email].get("member_id", "")): role
                for role, emails in desired_by_role.items()
                for email in emails
            }
            if any(not member_id for member_id in desired_ids):
                raise SheetsSourceError("A selected registry member has no member_id.")

            for row in memberships:
                if str(row.get("team_id", "")) == team_id:
                    row["active"] = "FALSE"
                    row["end_date"] = today
            for member_id, app_role in desired_ids.items():
                member_matches = [
                    row for row in memberships
                    if str(row.get("team_id", "")) == team_id
                    and str(row.get("member_id", "")) == member_id
                ]
                membership = member_matches[0] if member_matches else None
                if membership is None:
                    membership = {header: "" for header in memberships_headers}
                    membership.update(
                        {
                            "member_team_id": self._next_registry_id(
                                memberships, "member_team_id", "MT"
                            ),
                            "member_id": member_id,
                            "team_id": team_id,
                            "start_date": today,
                        }
                    )
                    memberships.append(membership)
                membership.update(
                    {
                        "team_role": "lead" if app_role in {"manager", "lead"} else "member",
                        "active": "TRUE",
                        "end_date": "",
                    }
                )

            for row in roles:
                if (
                    str(row.get("app_id", "")) == "budget"
                    and str(row.get("scope_team_id", "")) == team_id
                ):
                    row["active"] = "FALSE"
                    row["end_date"] = today
            for member_id, app_role in desired_ids.items():
                role_matches = [
                    row for row in roles
                    if str(row.get("member_id", "")) == member_id
                    and str(row.get("app_id", "")) == "budget"
                    and str(row.get("scope_team_id", "")) == team_id
                    and str(row.get("app_role", "")) == app_role
                ]
                role_row = role_matches[0] if role_matches else None
                if role_row is None:
                    role_row = {header: "" for header in roles_headers}
                    role_row.update(
                        {
                            "app_role_id": self._next_registry_id(
                                roles, "app_role_id", "AR"
                            ),
                            "member_id": member_id,
                            "app_id": "budget",
                            "app_role": app_role,
                            "scope_team_id": team_id,
                            "start_date": today,
                        }
                    )
                    roles.append(role_row)
                role_row.update({"active": "TRUE", "end_date": ""})

            self._write_registry_table(teams_ws, teams_headers, teams)
            self._write_registry_table(memberships_ws, memberships_headers, memberships)
            self._write_registry_table(roles_ws, roles_headers, roles)

            verified_teams = teams_ws.get_all_records()
            verified = [
                row for row in verified_teams
                if str(row.get("team_id", "")) == team_id
            ]
            if len(verified) != 1 or str(verified[0].get("team_name", "")).strip() != team_name:
                raise SheetsSourceError("The registry team readback did not verify.")
            verified_memberships = [
                (
                    str(row.get("member_id", "")).strip(),
                    str(row.get("team_role", "")).strip(),
                )
                for row in memberships_ws.get_all_records()
                if str(row.get("team_id", "")).strip() == team_id
                and _truthy(row.get("active"))
            ]
            expected_memberships = [
                (
                    member_id,
                    "lead" if app_role in {"manager", "lead"} else "member",
                )
                for member_id, app_role in desired_ids.items()
            ]
            if sorted(verified_memberships) != sorted(expected_memberships):
                raise SheetsSourceError(
                    "The registry team membership readback did not verify."
                )
            verified_roles = [
                (
                    str(row.get("member_id", "")).strip(),
                    str(row.get("app_role", "")).strip(),
                )
                for row in roles_ws.get_all_records()
                if str(row.get("app_id", "")).strip() == "budget"
                and str(row.get("scope_team_id", "")).strip() == team_id
                and _truthy(row.get("active"))
            ]
            if sorted(verified_roles) != sorted(desired_ids.items()):
                raise SheetsSourceError("The registry team role readback did not verify.")
            return {"team_id": team_id, "team_name": team_name, "active": active}

    def set_config(self, fiscal_year, key, value):
        """Set and exactly read back one annual exchange-rate Config value."""
        self._require_writes()
        key = str(key or "").strip()
        if key not in EXCHANGE_RATE_CONFIG_KEYS:
            raise ValueError("Only supported exchange-rate Config keys may be changed.")
        numeric_value = decimal_value(value)
        if numeric_value <= 0:
            raise ValueError("Exchange rates must be greater than zero.")
        normalized_value = str(numeric_value)
        with _sheet_write_lock():
            worksheet, _, spreadsheet_id, _, _ = self._worksheet_for_year(
                fiscal_year, "Config"
            )
            values = worksheet.get_all_values()
            matches = [
                index
                for index, row in enumerate(values, start=1)
                if row and str(row[0]).strip() == key
            ]
            if len(matches) > 1:
                raise SheetsSourceError(
                    f"Config key {key} appears more than once in Google Sheets."
                )
            if matches:
                row_index = matches[0]
                worksheet.update(
                    values=[[key, normalized_value]],
                    range_name=f"A{row_index}:B{row_index}",
                    value_input_option="RAW",
                )
                matched = True
            else:
                worksheet.append_row(
                    [key, normalized_value], value_input_option="RAW"
                )
                row_index = len(worksheet.get_all_values())
                matched = False
            written_values = worksheet.get(f"A{row_index}:B{row_index}")
            if not written_values or len(written_values[0]) < 2:
                raise SheetsSourceError("Google Sheets did not return the Config row.")
            written_key, written_value = written_values[0][:2]
            if str(written_key).strip() != key or decimal_value(
                written_value
            ) != numeric_value:
                raise SheetsSourceError(
                    f"The written Config {key} value did not verify."
                )
            return {
                "matched": matched,
                "key": key,
                "value": str(written_value).strip(),
                "spreadsheet_id": spreadsheet_id,
            }

    def queue_fiscal_year_creation(self, fiscal_year):
        """Queue the existing PI-owned GAS workbook creator and verify its token."""
        self._require_writes()
        fiscal_year = self._validate_fiscal_year(fiscal_year)
        with _sheet_write_lock():
            master_id = _master_spreadsheet_id()
            if not master_id:
                raise SheetsSourceError("MASTER_SPREADSHEET_ID is not configured.")
            master = self._open(master_id)
            worksheet = master.worksheet("Config")
            values = worksheet.get_all_values()
            config = {
                str(row[0]).strip(): str(row[1]).strip() if len(row) > 1 else ""
                for row in values
                if row and str(row[0]).strip()
            }
            registered_id = config.get(f"Spreadsheet ID {fiscal_year}", "").strip()
            base_year = config.get("Current Fiscal Year") or config.get("Fiscal Year")
            if registered_id or fiscal_year == base_year:
                raise SheetsSourceError(f"{fiscal_year} is already registered.")
            key = f"Fiscal Year Creation Request {fiscal_year}"
            token = (
                f"Queued {datetime.now(DUBAI_TZ).isoformat(timespec='seconds')} "
                f"{secrets.token_hex(4)}"
            )
            matches = [
                index
                for index, row in enumerate(values, start=1)
                if row and str(row[0]).strip() == key
            ]
            if len(matches) > 1:
                raise SheetsSourceError(
                    f"Config key {key} appears more than once in Google Sheets."
                )
            if matches:
                row_index = matches[0]
                worksheet.update(
                    values=[[key, token]],
                    range_name=f"A{row_index}:B{row_index}",
                    value_input_option="RAW",
                )
            else:
                worksheet.append_row([key, token], value_input_option="RAW")
                row_index = len(worksheet.get_all_values())
            written = worksheet.get(f"A{row_index}:B{row_index}")
            if not written or written[0][:2] != [key, token]:
                raise SheetsSourceError(
                    "The fiscal-year creation request did not verify in master Config."
                )
            return {
                "fiscal_year": fiscal_year,
                "key": key,
                "token": token,
                "spreadsheet_id": master_id,
            }

    @staticmethod
    def _next_registry_id(rows, column, prefix):
        numbers = []
        for row in rows:
            value = str(row.get(column, ""))
            suffix = value.removeprefix(prefix)
            if value.startswith(prefix) and suffix.isdigit():
                numbers.append(int(suffix))
        return f"{prefix}{max(numbers, default=0) + 1:03d}"

    def _registry_table(self, registry, table_name, columns):
        try:
            worksheet = registry.worksheet(table_name)
            values = worksheet.get_all_values()
            headers = self._ensure_headers(worksheet, values, columns)
        except Exception as error:
            raise SheetsSourceError(
                f"The registry {table_name} table could not be prepared."
            ) from error
        if not values:
            values = [headers]
        rows = [self._row_mapping(headers, raw_row) for raw_row in values[1:]]
        return worksheet, headers, rows

    def _write_registry_table(self, worksheet, headers, rows):
        end_column = self._column_label(len(headers))
        try:
            for index, row in enumerate(rows, start=2):
                worksheet.update(
                    values=[[row.get(header, "") for header in headers]],
                    range_name=f"A{index}:{end_column}{index}",
                    value_input_option="RAW",
                )
        except Exception as error:
            raise SheetsSourceError("A central registry table could not be written.") from error

    def upsert_registry_member(self, member_data):
        """Upsert one member and exactly reconcile Budget memberships and roles."""
        self._require_writes()
        registry_id = _registry_spreadsheet_id()
        if not registry_id:
            raise SheetsSourceError("REGISTRY_SPREADSHEET_ID is not configured.")
        email = str(member_data.get("email") or "").strip().lower()
        if not email.endswith("@nyu.edu"):
            raise ValueError("Email must end with @nyu.edu.")
        display_name = str(member_data.get("display_name") or "").strip() or email
        role = str(member_data.get("role") or "member").strip().lower()
        if role not in {"pi", "budget_manager", "lead", "member"}:
            raise ValueError("Unsupported Budget role.")
        raw_team_names = member_data.get("team_names") or []
        if isinstance(raw_team_names, str):
            raw_team_names = _split_values(raw_team_names)
        team_names = sorted({str(name).strip() for name in raw_team_names if str(name).strip()})
        raw_active = member_data.get("active", True)
        active = raw_active if isinstance(raw_active, bool) else _truthy(raw_active)
        today = datetime.now(DUBAI_TZ).date().isoformat()

        with _sheet_write_lock():
            registry = self._open(registry_id)
            members_ws, members_headers, members = self._registry_table(
                registry, "Members", REGISTRY_MEMBER_COLUMNS
            )
            teams_ws, teams_headers, teams = self._registry_table(
                registry, "Teams", ["team_id", "team_name", "description", "active"]
            )
            memberships_ws, memberships_headers, memberships = self._registry_table(
                registry, "Member_Teams", REGISTRY_MEMBER_TEAM_COLUMNS
            )
            roles_ws, roles_headers, roles = self._registry_table(
                registry, "App_Roles", REGISTRY_APP_ROLE_COLUMNS
            )
            del teams_ws, teams_headers

            member_matches = [
                row
                for row in members
                if str(row.get("email") or "").strip().lower() == email
            ]
            if len(member_matches) > 1:
                raise SheetsSourceError(f"Member email {email} appears more than once.")
            if member_matches:
                member = member_matches[0]
                member_id = str(member.get("member_id") or "").strip()
                if not member_id:
                    raise SheetsSourceError("The existing member has no member_id.")
            else:
                member_id = self._next_registry_id(members, "member_id", "M")
                member = {header: "" for header in members_headers}
                member.update(
                    {
                        "member_id": member_id,
                        "start_date": today,
                        "notes": "Added from Budget web app",
                    }
                )
                members.append(member)
            member.update(
                {
                    "email": email,
                    "name": display_name,
                    "display_name": display_name,
                    "global_role": "pi" if role == "pi" else "member",
                    "active": "TRUE" if active else "FALSE",
                    "end_date": "" if active else today,
                }
            )

            active_teams = {
                str(row.get("team_name") or "").strip(): str(row.get("team_id") or "").strip()
                for row in teams
                if _truthy(row.get("active"))
                and str(row.get("team_name") or "").strip()
                and str(row.get("team_id") or "").strip()
            }
            missing_teams = [name for name in team_names if name not in active_teams]
            if missing_teams:
                raise ValueError(
                    "Unknown active team(s): " + ", ".join(missing_teams)
                )
            desired_team_ids = {active_teams[name] for name in team_names} if active else set()
            membership_role = "lead" if role in {"pi", "budget_manager", "lead"} else "member"
            for row in memberships:
                if str(row.get("member_id") or "") == member_id:
                    row["active"] = "FALSE"
                    row["end_date"] = today
            for team_id in sorted(desired_team_ids):
                matches = [
                    row
                    for row in memberships
                    if str(row.get("member_id") or "") == member_id
                    and str(row.get("team_id") or "") == team_id
                ]
                membership = matches[0] if matches else None
                if membership is None:
                    membership = {header: "" for header in memberships_headers}
                    membership.update(
                        {
                            "member_team_id": self._next_registry_id(
                                memberships, "member_team_id", "MT"
                            ),
                            "member_id": member_id,
                            "team_id": team_id,
                            "start_date": today,
                        }
                    )
                    memberships.append(membership)
                membership.update(
                    {
                        "team_role": membership_role,
                        "active": "TRUE",
                        "end_date": "",
                    }
                )

            for row in roles:
                if (
                    str(row.get("member_id") or "") == member_id
                    and str(row.get("app_id") or "") == "budget"
                ):
                    row["active"] = "FALSE"
                    row["end_date"] = today
            desired_roles = []
            if active:
                if role == "pi":
                    desired_roles = [("owner", "")]
                elif role == "budget_manager":
                    desired_roles = [("manager", "")]
                else:
                    app_role = "lead" if role == "lead" else "viewer"
                    desired_roles = [(app_role, team_id) for team_id in sorted(desired_team_ids)]
            for app_role, scope_team_id in desired_roles:
                matches = [
                    row
                    for row in roles
                    if str(row.get("member_id") or "") == member_id
                    and str(row.get("app_id") or "") == "budget"
                    and str(row.get("app_role") or "") == app_role
                    and str(row.get("scope_team_id") or "") == scope_team_id
                ]
                role_row = matches[0] if matches else None
                if role_row is None:
                    role_row = {header: "" for header in roles_headers}
                    role_row.update(
                        {
                            "app_role_id": self._next_registry_id(
                                roles, "app_role_id", "AR"
                            ),
                            "member_id": member_id,
                            "app_id": "budget",
                            "app_role": app_role,
                            "scope_team_id": scope_team_id,
                            "start_date": today,
                        }
                    )
                    roles.append(role_row)
                role_row.update({"active": "TRUE", "end_date": ""})

            self._write_registry_table(members_ws, members_headers, members)
            self._write_registry_table(
                memberships_ws, memberships_headers, memberships
            )
            self._write_registry_table(roles_ws, roles_headers, roles)

            verified_members = members_ws.get_all_records()
            verified_memberships = memberships_ws.get_all_records()
            verified_roles = roles_ws.get_all_records()
            verified_member = [
                row
                for row in verified_members
                if str(row.get("member_id") or "") == member_id
            ]
            if len(verified_member) != 1:
                raise SheetsSourceError("The registry member readback did not verify.")
            verified_member = verified_member[0]
            member_expectations = {
                "email": email,
                "display_name": display_name,
                "global_role": "pi" if role == "pi" else "member",
                "active": "TRUE" if active else "FALSE",
            }
            if any(
                str(verified_member.get(key, "")).strip().lower()
                != str(value).strip().lower()
                for key, value in member_expectations.items()
            ):
                raise SheetsSourceError("The registry member fields did not verify.")
            verified_active_teams = {
                str(row.get("team_id") or "")
                for row in verified_memberships
                if str(row.get("member_id") or "") == member_id
                and _truthy(row.get("active"))
            }
            if verified_active_teams != desired_team_ids:
                raise SheetsSourceError("The registry member teams did not verify.")
            verified_active_roles = {
                (
                    str(row.get("app_role") or ""),
                    str(row.get("scope_team_id") or ""),
                )
                for row in verified_roles
                if str(row.get("member_id") or "") == member_id
                and str(row.get("app_id") or "") == "budget"
                and _truthy(row.get("active"))
            }
            if verified_active_roles != set(desired_roles):
                raise SheetsSourceError("The registry Budget roles did not verify.")
            return {
                "member_id": member_id,
                "member": verified_member,
                "team_ids": sorted(verified_active_teams),
                "roles": sorted(verified_active_roles),
                "registry_spreadsheet_id": registry_id,
            }

    def write_invoice_transaction(self, fiscal_year, candidate):
        if not settings.ENABLE_SHEET_WRITES:
            raise SheetsSourceError("Google Sheet writes are disabled in this environment.")
        with _sheet_write_lock():
            return self._write_invoice_transaction_locked(fiscal_year, candidate)

    def _write_invoice_transaction_locked(self, fiscal_year, candidate):
        """Upsert one reviewed PDF transaction and verify the written Sheet row."""
        fiscal_year = str(fiscal_year or "").strip()
        if not re.fullmatch(r"FY\d{4}-\d{2}", fiscal_year):
            raise ValueError("Fiscal year must look like FY2026-27.")
        transaction_date = candidate.get("date")
        if isinstance(transaction_date, date):
            transaction_date = transaction_date.isoformat()
        else:
            transaction_date = str(transaction_date or "").strip()
        if not transaction_date:
            raise ValueError("Transaction date is required.")
        currency = str(candidate.get("currency") or "").strip().upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise ValueError("Unsupported currency.")
        amount = money(candidate.get("amount"))
        if amount <= 0:
            raise ValueError("Amount must be greater than zero.")
        team = str(candidate.get("team") or "").strip()
        if not team:
            raise ValueError("Team is required.")

        worksheet, workbook, spreadsheet_id, base_year = self._transaction_sheet(fiscal_year)
        master = self._open(_master_spreadsheet_id())
        try:
            values = worksheet.get_all_values()
            original_row_count = len(values)
            headers = self._ensure_transaction_headers(worksheet, values)
            if not values:
                values = [headers]
            rates, aed_per_usd = self._configured_rates(
                workbook, master, fiscal_year, spreadsheet_id, base_year
            )
        except SheetsSourceError:
            raise
        except Exception as error:
            raise SheetsSourceError("The transaction worksheet could not be prepared.") from error

        pdf_hash = str(candidate.get("file_sha256") or "").strip().lower()
        marker = f"[PDF SHA256:{pdf_hash}]" if pdf_hash else ""
        if marker:
            for other_year in self.fiscal_year_options():
                if other_year == fiscal_year:
                    continue
                other_worksheet, _, _, _ = self._transaction_sheet(other_year)
                other_values = other_worksheet.get_all_values()
                if not other_values:
                    continue
                other_headers = other_values[0]
                if any(
                    marker
                    in str(self._row_mapping(other_headers, raw_row).get("Notes") or "")
                    for raw_row in other_values[1:]
                ):
                    raise SheetsSourceError(
                        f"This PDF is already registered in {other_year}."
                    )
        normalized_team = self._normalize_key(team)
        normalized_vendor = self._normalize_key(candidate.get("vendor"))
        normalized_invoice = self._normalize_key(candidate.get("invoice_number"))
        matched_index = None
        matched_current = None
        existing_ids = set()
        for row_index, raw_row in enumerate(values[1:], start=2):
            current = self._row_mapping(headers, raw_row)
            transaction_id = str(current.get("Transaction ID") or "").strip()
            if transaction_id:
                existing_ids.add(transaction_id)
            same_team = self._normalize_key(current.get("Team")) == normalized_team
            same_hash = bool(marker and marker in str(current.get("Notes") or ""))
            if same_hash and not same_team:
                raise SheetsSourceError(
                    "This PDF is already registered to another team."
                )
            same_invoice_identity = bool(
                normalized_invoice
                and normalized_vendor
                and self._normalize_key(current.get("Vendor / Payee")) == normalized_vendor
                and self._normalize_key(current.get("Invoice Number")) == normalized_invoice
            )
            if same_hash or (same_team and same_invoice_identity):
                matched_index = row_index
                matched_current = current
                break

        if matched_current and str(matched_current.get("Status") or "").strip() == "Cancelled":
            raise SheetsSourceError(
                "This invoice is Cancelled. Restore it explicitly from Transactions instead of re-importing it."
            )

        transaction_id = (
            str(matched_current.get("Transaction ID") or "").strip()
            if matched_current
            else self._new_transaction_id(existing_ids, pdf_hash)
        )
        amount_usd = money(amount * decimal_value(rates[currency]))
        amount_aed_equiv = money(amount_usd * aed_per_usd)
        current_notes = str((matched_current or {}).get("Notes") or "").strip()
        user_notes = str(candidate.get("notes") or "").strip()
        source_note = f"Imported from {candidate.get('file_name', 'PDF invoice')}"
        inferred_fiscal_year = fiscal_year_for_date(transaction_date)
        override_note = (
            f"[FY OVERRIDE: date implies {inferred_fiscal_year}]"
            if inferred_fiscal_year != fiscal_year
            else ""
        )
        notes = "\n".join(
            dict.fromkeys(
                part
                for part in (current_notes, user_notes, source_note, marker, override_note)
                if part
            )
        )
        now_text = datetime.now(DUBAI_TZ).strftime("%Y-%m-%d %H:%M:%S")
        current = matched_current or {}
        row = {header: current.get(header, "") for header in headers}
        row.update(
            {
                "Transaction ID": transaction_id,
                "Date": transaction_date,
                "Fiscal Year": fiscal_year,
                "Category": str(candidate.get("category") or "").strip(),
                "Sub-category": str(candidate.get("subcategory") or "").strip(),
                "Vendor / Payee": str(candidate.get("vendor") or "").strip(),
                "Description": str(candidate.get("description") or "").strip(),
                "PO Number": str(candidate.get("po_number") or "").strip(),
                "Invoice Number": str(candidate.get("invoice_number") or "").strip(),
                "Currency": currency,
                "Amount": str(amount),
                "Amount (USD equiv)": str(amount_usd),
                "Amount (AED)": str(amount if currency == "AED" else Decimal("0")),
                "Amount (USD)": str(amount if currency == "USD" else Decimal("0")),
                "Amount (AED equiv)": str(amount_aed_equiv),
                "Status": "Allocated",
                "Receipt Confirmed": current.get("Receipt Confirmed") or "FALSE",
                "Entered By": current.get("Entered By")
                or str(candidate.get("entered_by") or "").strip(),
                "Entry Method": "Auto-PDF",
                "Notes": notes,
                "Last Modified": now_text,
                "Team": team,
            }
        )
        output = [row.get(header, "") for header in headers]
        try:
            if matched_index:
                end_column = self._column_label(len(headers))
                worksheet.update(
                    values=[output],
                    range_name=f"A{matched_index}:{end_column}{matched_index}",
                    value_input_option="RAW",
                )
                written_index = matched_index
            else:
                worksheet.append_row(output, value_input_option="RAW")
                written_index = max(original_row_count + 1, 2)
            if marker:
                refreshed = worksheet.get_all_values()
                matching_rows = [
                    row_number
                    for row_number, raw_row in enumerate(refreshed[1:], start=2)
                    if marker in str(self._row_mapping(headers, raw_row).get("Notes") or "")
                ]
                if len(matching_rows) != 1:
                    raise SheetsSourceError(
                        "The PDF identity did not resolve to exactly one Sheet row."
                    )
                written_index = matching_rows[0]
            end_column = self._column_label(len(headers))
            written_values = worksheet.get(f"A{written_index}:{end_column}{written_index}")
        except Exception as error:
            raise SheetsSourceError("The transaction could not be written to Google Sheets.") from error
        if not written_values:
            raise SheetsSourceError("Google Sheets did not return the written transaction row.")
        written = self._row_mapping(headers, written_values[0])
        money_columns = {
            "Amount",
            "Amount (USD equiv)",
            "Amount (AED)",
            "Amount (USD)",
            "Amount (AED equiv)",
        }
        for column in TRANSACTION_COLUMNS:
            expected = row.get(column, "")
            actual = written.get(column, "")
            if column in money_columns:
                if money(actual) != money(expected):
                    raise SheetsSourceError(
                        f"The written Google Sheet {column} value did not verify."
                    )
            elif str(actual).strip() != str(expected).strip():
                raise SheetsSourceError(
                    f"The written Google Sheet {column} value did not verify."
                )
        if marker not in str(written.get("Notes") or ""):
            raise SheetsSourceError("The written Google Sheet PDF identity did not verify.")
        return {
            "transaction_id": transaction_id,
            "matched": bool(matched_index),
            "row": written,
            "spreadsheet_id": spreadsheet_id,
        }

    def delete_transaction(self, fiscal_year, transaction_id, expected_pdf_hash=""):
        """Delete one exact transaction and verify removal.

        This is intentionally not exposed as a web action. It supports reversible
        deployment verification where leaving a Cancelled dummy row is undesirable.
        """
        if not settings.ENABLE_SHEET_WRITES:
            raise SheetsSourceError("Google Sheet writes are disabled in this environment.")
        with _sheet_write_lock():
            return self._delete_transaction_locked(
                fiscal_year, transaction_id, expected_pdf_hash
            )

    def _delete_transaction_locked(self, fiscal_year, transaction_id, expected_pdf_hash=""):
        worksheet, _, _, _ = self._transaction_sheet(fiscal_year)
        try:
            values = worksheet.get_all_values()
            if not values:
                return False
            headers = values[0]
            marker = (
                f"[PDF SHA256:{str(expected_pdf_hash).strip().lower()}]"
                if expected_pdf_hash
                else ""
            )
            target_index = None
            for row_index, raw_row in enumerate(values[1:], start=2):
                row = self._row_mapping(headers, raw_row)
                if str(row.get("Transaction ID") or "").strip() != transaction_id:
                    continue
                if marker and marker not in str(row.get("Notes") or ""):
                    raise SheetsSourceError(
                        "The verification transaction PDF identity did not match."
                    )
                target_index = row_index
                break
            if target_index is None:
                return False
            worksheet.delete_rows(target_index)
            remaining = worksheet.get_all_values()
        except SheetsSourceError:
            raise
        except Exception as error:
            raise SheetsSourceError("The transaction could not be deleted safely.") from error
        for raw_row in remaining[1:]:
            row = self._row_mapping(headers, raw_row)
            if str(row.get("Transaction ID") or "").strip() == transaction_id:
                raise SheetsSourceError("The transaction still exists after deletion.")
        return True

    def delete_transactions_by_pdf_hash(self, fiscal_year, pdf_hash):
        """Remove all rows for one exact verification hash and confirm cleanup."""
        if not settings.ENABLE_SHEET_WRITES:
            raise SheetsSourceError("Google Sheet writes are disabled in this environment.")
        with _sheet_write_lock():
            return self._delete_transactions_by_pdf_hash_locked(fiscal_year, pdf_hash)

    def _delete_transactions_by_pdf_hash_locked(self, fiscal_year, pdf_hash):
        marker = f"[PDF SHA256:{str(pdf_hash).strip().lower()}]"
        worksheet, _, _, _ = self._transaction_sheet(fiscal_year)
        try:
            values = worksheet.get_all_values()
            if not values:
                return 0
            headers = values[0]
            matches = [
                row_index
                for row_index, raw_row in enumerate(values[1:], start=2)
                if marker in str(self._row_mapping(headers, raw_row).get("Notes") or "")
            ]
            for row_index in reversed(matches):
                worksheet.delete_rows(row_index)
            remaining = worksheet.get_all_values()
        except Exception as error:
            raise SheetsSourceError("Verification rows could not be cleaned up.") from error
        if any(
            marker in str(self._row_mapping(headers, raw_row).get("Notes") or "")
            for raw_row in remaining[1:]
        ):
            raise SheetsSourceError("A verification row still exists after cleanup.")
        return len(matches)
