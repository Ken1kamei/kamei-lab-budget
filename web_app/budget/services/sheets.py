import fcntl
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


class SheetsSourceError(RuntimeError):
    pass


@contextmanager
def _sheet_write_lock():
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
            return existing_rows, "Registry ID is not configured; using annual Teams worksheet."
        try:
            registry = self._open(registry_id)
            members = registry.worksheet("Members").get_all_records()
            teams = registry.worksheet("Teams").get_all_records()
            memberships = registry.worksheet("Member_Teams").get_all_records()
            app_roles = registry.worksheet("App_Roles").get_all_records()
        except SheetsSourceError:
            return existing_rows, "Registry could not be opened; using annual Teams worksheet."
        except Exception:
            return existing_rows, "Registry tables could not be read; using annual Teams worksheet."

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
        return output or existing_rows, ""

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
        teams, registry_warning = self._registry_teams(teams)
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
        return {
            "fiscal_year": fiscal_year,
            "spreadsheet_id": spreadsheet_id,
            "summary": summary,
            "teams": teams,
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
                value_input_option="USER_ENTERED",
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
                    value_input_option="USER_ENTERED",
                )
                written_index = matched_index
            else:
                worksheet.append_row(output, value_input_option="USER_ENTERED")
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
