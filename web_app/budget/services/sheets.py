import json
import os
import tomllib
from pathlib import Path

import gspread
import google.auth
from django.conf import settings
from google.oauth2.service_account import Credentials

from budget.services.calculations import DEFAULT_RATES_TO_USD


SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
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
    """Read-only adapter for the current fiscal-year Google Sheet topology."""

    def __init__(self, client=None):
        if client is not None:
            self.client = client
            return
        info = _service_account_info()
        if info:
            credentials = Credentials.from_service_account_info(info, scopes=SCOPES)
        else:
            try:
                credentials, _ = google.auth.default(scopes=SCOPES)
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
