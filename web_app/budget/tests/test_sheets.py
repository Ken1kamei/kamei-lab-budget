import re

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from budget.services.sheets import SheetsGateway, SheetsSourceError


class Worksheet:
    def __init__(self, values=None, records=None):
        self.values = values or []
        self.records = records or []

    def get_all_values(self):
        return self.values

    def get_all_records(self):
        return self.records

    def update(self, *, values, range_name, value_input_option=None):
        row_number = int(re.search(r"\d+", range_name).group())
        while len(self.values) < row_number:
            self.values.append([])
        self.values[row_number - 1] = list(values[0])

    def append_row(self, row, value_input_option=None):
        self.values.append(list(row))

    def get(self, range_name):
        row_number = int(re.search(r"\d+", range_name).group())
        return [self.values[row_number - 1]] if len(self.values) >= row_number else []

    def delete_rows(self, row_number):
        del self.values[row_number - 1]


class Workbook:
    def __init__(self, sheets):
        self.sheets = sheets

    def worksheet(self, name):
        return self.sheets[name]


class Client:
    def __init__(self, books):
        self.books = books

    def open_by_key(self, key):
        return self.books[key]


def test_gateway_reads_dedicated_year_and_filters_blank_transaction_ids(settings, monkeypatch):
    settings.MASTER_SPREADSHEET_ID = "master"
    settings.REGISTRY_SPREADSHEET_ID = ""
    master = Workbook(
        {
            "Config": Worksheet(
                values=[
                    ["Current Fiscal Year", "FY2025-26"],
                    ["Spreadsheet ID FY2026-27", "fy-2026"],
                ]
            )
        }
    )
    annual = Workbook(
        {
            "Transactions": Worksheet(
                records=[
                    {"Transaction ID": "TXN-1", "Amount (USD equiv)": "10"},
                    {"Transaction ID": "", "Amount (USD equiv)": "999"},
                ]
            ),
            "Summary": Worksheet(values=[["Consumables", "", "", "1000"]]),
            "Teams": Worksheet(records=[]),
            "Config": Worksheet(values=[["AED/USD Exchange Rate", "3.5"]]),
        }
    )
    gateway = SheetsGateway(client=Client({"master": master, "fy-2026": annual}))
    monkeypatch.setattr("budget.services.sheets._legacy_secrets", lambda: {})

    snapshot = gateway.read_fiscal_year("FY2026-27")

    assert snapshot["spreadsheet_id"] == "fy-2026"
    assert [row["Transaction ID"] for row in snapshot["transactions"]] == ["TXN-1"]
    assert snapshot["summary"][0]["Budgeted (AED equiv)"] == "1000"
    assert snapshot["aed_per_usd"] == "3.5"


def test_invoice_write_is_verified_and_idempotent_by_pdf_hash(settings, monkeypatch):
    settings.MASTER_SPREADSHEET_ID = "master"
    settings.REGISTRY_SPREADSHEET_ID = ""
    settings.ENABLE_SHEET_WRITES = True
    master = Workbook(
        {
            "Config": Worksheet(
                values=[
                    ["Current Fiscal Year", "FY2025-26"],
                    ["Spreadsheet ID FY2026-27", "fy-2026"],
                ]
            ),
            "Transactions": Worksheet(values=[]),
        }
    )
    transactions = Worksheet(values=[])
    annual = Workbook(
        {
            "Transactions": transactions,
            "Config": Worksheet(values=[["AED/USD Exchange Rate", "3.6725"]]),
        }
    )
    gateway = SheetsGateway(client=Client({"master": master, "fy-2026": annual}))
    monkeypatch.setattr("budget.services.sheets._legacy_secrets", lambda: {})
    payload = {
        "date": "2026-03-26",
        "category": "Consumables",
        "subcategory": "Assay kits",
        "vendor": "PeopleSoft Inventory",
        "description": "QUBIT RNA BR ASSAY KIT",
        "po_number": "",
        "invoice_number": "INS6000_9216658",
        "currency": "USD",
        "amount": "151.95",
        "team": "Diabetes",
        "entered_by": "member@nyu.edu",
        "file_name": "INS6000_9216658.PDF",
        "file_sha256": "abc123",
        "notes": "Reviewed",
    }

    first = gateway.write_invoice_transaction("FY2026-27", payload)
    second = gateway.write_invoice_transaction(
        "FY2026-27", {**payload, "description": "Corrected description"}
    )

    assert first["matched"] is False
    assert second["transaction_id"] == first["transaction_id"]
    assert second["matched"] is True
    assert len(transactions.values) == 2
    headers, row = transactions.values
    saved = dict(zip(headers, row, strict=False))
    assert re.fullmatch(r"TXN-\d{8}-WABC123", saved["Transaction ID"])
    assert saved["Description"] == "Corrected description"
    assert saved["Amount (USD equiv)"] == "151.95"
    assert saved["Amount (AED equiv)"] == "558.04"
    assert saved["Status"] == "Allocated"
    assert saved["Team"] == "Diabetes"
    assert "[PDF SHA256:abc123]" in saved["Notes"]


def test_invoice_hash_cannot_move_a_transaction_to_another_team(settings, monkeypatch):
    settings.MASTER_SPREADSHEET_ID = "master"
    settings.REGISTRY_SPREADSHEET_ID = ""
    settings.ENABLE_SHEET_WRITES = True
    master = Workbook(
        {
            "Config": Worksheet(
                values=[
                    ["Current Fiscal Year", "FY2025-26"],
                    ["Spreadsheet ID FY2026-27", "fy-2026"],
                ]
            ),
            "Transactions": Worksheet(values=[]),
        }
    )
    headers = ["Transaction ID", "Team", "Notes"]
    transactions = Worksheet(
        values=[headers, ["TXN-1", "Diabetes", "[PDF SHA256:abc123]"]]
    )
    annual = Workbook(
        {
            "Transactions": transactions,
            "Config": Worksheet(values=[["AED/USD Exchange Rate", "3.6725"]]),
        }
    )
    gateway = SheetsGateway(client=Client({"master": master, "fy-2026": annual}))
    monkeypatch.setattr("budget.services.sheets._legacy_secrets", lambda: {})

    with pytest.raises(SheetsSourceError, match="another team"):
        gateway.write_invoice_transaction(
            "FY2026-27",
            {
                "date": "2026-03-26",
                "category": "Consumables",
                "vendor": "Vendor",
                "description": "Item",
                "invoice_number": "INV-1",
                "currency": "USD",
                "amount": "10",
                "team": "IoC",
                "file_name": "invoice.pdf",
                "file_sha256": "abc123",
            },
        )


def test_gateway_rejects_writes_when_feature_flag_is_disabled(settings):
    settings.ENABLE_SHEET_WRITES = False
    gateway = SheetsGateway(client=Client({}))

    with pytest.raises(SheetsSourceError, match="disabled"):
        gateway.write_invoice_transaction("FY2026-27", {})

    with pytest.raises(CommandError, match="ENABLE_SHEET_WRITES"):
        call_command(
            "verify_invoice_roundtrip",
            fiscal_year="FY2026-27",
            team="Core Lab",
        )


def test_reimport_does_not_restore_a_cancelled_transaction(settings, monkeypatch):
    settings.MASTER_SPREADSHEET_ID = "master"
    settings.REGISTRY_SPREADSHEET_ID = ""
    settings.ENABLE_SHEET_WRITES = True
    master = Workbook(
        {
            "Config": Worksheet(
                values=[
                    ["Current Fiscal Year", "FY2025-26"],
                    ["Spreadsheet ID FY2026-27", "fy-2026"],
                ]
            ),
            "Transactions": Worksheet(values=[]),
        }
    )
    headers = ["Transaction ID", "Team", "Status", "Notes"]
    transactions = Worksheet(
        values=[
            headers,
            ["TXN-1", "Diabetes", "Cancelled", "[PDF SHA256:abc123]"],
        ]
    )
    annual = Workbook(
        {
            "Transactions": transactions,
            "Config": Worksheet(values=[["AED/USD Exchange Rate", "3.6725"]]),
        }
    )
    gateway = SheetsGateway(client=Client({"master": master, "fy-2026": annual}))
    monkeypatch.setattr("budget.services.sheets._legacy_secrets", lambda: {})

    with pytest.raises(SheetsSourceError, match="Cancelled"):
        gateway.write_invoice_transaction(
            "FY2026-27",
            {
                "date": "2026-03-26",
                "category": "Consumables",
                "vendor": "Vendor",
                "description": "Item",
                "invoice_number": "INV-1",
                "currency": "USD",
                "amount": "10",
                "team": "Diabetes",
                "file_name": "invoice.pdf",
                "file_sha256": "abc123",
            },
        )
    assert transactions.values[1][2] == "Cancelled"


def test_invoice_update_preserves_previous_pdf_hash(settings, monkeypatch):
    settings.MASTER_SPREADSHEET_ID = "master"
    settings.REGISTRY_SPREADSHEET_ID = ""
    settings.ENABLE_SHEET_WRITES = True
    master = Workbook(
        {
            "Config": Worksheet(
                values=[
                    ["Current Fiscal Year", "FY2025-26"],
                    ["Spreadsheet ID FY2026-27", "fy-2026"],
                ]
            ),
            "Transactions": Worksheet(values=[]),
        }
    )
    transactions = Worksheet(values=[])
    annual = Workbook(
        {
            "Transactions": transactions,
            "Config": Worksheet(values=[["AED/USD Exchange Rate", "3.6725"]]),
        }
    )
    gateway = SheetsGateway(client=Client({"master": master, "fy-2026": annual}))
    monkeypatch.setattr("budget.services.sheets._legacy_secrets", lambda: {})
    base = {
        "date": "2026-03-26",
        "category": "Consumables",
        "vendor": "Vendor",
        "description": "Item",
        "invoice_number": "INV-1",
        "currency": "USD",
        "amount": "10",
        "team": "Diabetes",
        "file_name": "invoice.pdf",
    }

    first = gateway.write_invoice_transaction(
        "FY2026-27", {**base, "file_sha256": "oldhash"}
    )
    second = gateway.write_invoice_transaction(
        "FY2026-27", {**base, "file_sha256": "newhash"}
    )

    assert second["transaction_id"] == first["transaction_id"]
    assert len(transactions.values) == 2
    headers, row = transactions.values
    saved = dict(zip(headers, row, strict=False))
    assert "[PDF SHA256:oldhash]" in saved["Notes"]
    assert "[PDF SHA256:newhash]" in saved["Notes"]


def test_same_pdf_is_rejected_in_another_fiscal_year(settings, monkeypatch):
    settings.MASTER_SPREADSHEET_ID = "master"
    settings.REGISTRY_SPREADSHEET_ID = ""
    settings.ENABLE_SHEET_WRITES = True
    master = Workbook(
        {
            "Config": Worksheet(
                values=[
                    ["Current Fiscal Year", "FY2025-26"],
                    ["Spreadsheet ID FY2026-27", "fy-2026"],
                ]
            ),
            "Transactions": Worksheet(
                values=[
                    ["Transaction ID", "Notes"],
                    ["TXN-OLD", "[PDF SHA256:abc123]"],
                ]
            ),
        }
    )
    annual = Workbook(
        {
            "Transactions": Worksheet(values=[]),
            "Config": Worksheet(values=[["AED/USD Exchange Rate", "3.6725"]]),
        }
    )
    gateway = SheetsGateway(client=Client({"master": master, "fy-2026": annual}))
    monkeypatch.setattr("budget.services.sheets._legacy_secrets", lambda: {})

    with pytest.raises(SheetsSourceError, match="FY2025-26"):
        gateway.write_invoice_transaction(
            "FY2026-27",
            {
                "date": "2026-03-26",
                "category": "Consumables",
                "vendor": "Vendor",
                "description": "Item",
                "invoice_number": "INV-1",
                "currency": "USD",
                "amount": "10",
                "team": "Diabetes",
                "file_name": "invoice.pdf",
                "file_sha256": "abc123",
            },
        )
