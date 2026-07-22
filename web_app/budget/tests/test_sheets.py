import re

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from budget.services.sheets import (
    REGISTRY_APP_ROLE_COLUMNS,
    REGISTRY_MEMBER_COLUMNS,
    REGISTRY_MEMBER_TEAM_COLUMNS,
    SUMMARY_COLUMNS,
    TEAM_COLUMNS,
    TRANSACTION_COLUMNS,
    SheetsGateway,
    SheetsSourceError,
)


def _column_number(label):
    value = 0
    for character in label:
        value = value * 26 + ord(character) - 64
    return value


def _range_parts(range_name):
    match = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", range_name)
    assert match, f"Unsupported fake range: {range_name}"
    start_column, start_row, end_column, end_row = match.groups()
    return (
        _column_number(start_column),
        int(start_row),
        _column_number(end_column),
        int(end_row),
    )


class Worksheet:
    def __init__(self, values=None, records=None):
        self.values = values or []
        self.records = records
        self.col_count = max((len(row) for row in self.values), default=0)

    def get_all_values(self):
        return self.values

    def get_all_records(self):
        if self.records is not None:
            return self.records
        if not self.values:
            return []
        headers = self.values[0]
        return [
            {
                header: row[index] if index < len(row) else ""
                for index, header in enumerate(headers)
            }
            for row in self.values[1:]
            if any(str(value).strip() for value in row)
        ]

    def add_cols(self, count):
        self.col_count += count

    def update(self, *, values, range_name, value_input_option=None):
        start_column, start_row, end_column, end_row = _range_parts(range_name)
        while len(self.values) < end_row:
            self.values.append([])
        for row_offset, incoming in enumerate(values):
            row_number = start_row + row_offset
            assert row_number <= end_row
            row = self.values[row_number - 1]
            while len(row) < end_column:
                row.append("")
            row[start_column - 1 : start_column - 1 + len(incoming)] = list(incoming)
        self.col_count = max(self.col_count, end_column)

    def batch_update(self, data, value_input_option=None):
        for item in data:
            self.update(
                values=item["values"],
                range_name=item["range"],
                value_input_option=value_input_option,
            )

    def append_row(self, row, value_input_option=None):
        self.values.append(list(row))
        self.col_count = max(self.col_count, len(row))

    def get(self, range_name, **kwargs):
        start_column, start_row, end_column, end_row = _range_parts(range_name)
        if len(self.values) < start_row:
            return []
        output = []
        for row_number in range(start_row, min(end_row, len(self.values)) + 1):
            row = self.values[row_number - 1]
            output.append(row[start_column - 1 : end_column])
        return output

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
            "Config": Worksheet(
                values=[
                    ["AED/USD Exchange Rate", "3.5"],
                    ["EUR/USD Exchange Rate", "1.25"],
                    ["JPY/USD Exchange Rate", "0.007"],
                    ["GBP/USD Exchange Rate", "1.4"],
                ]
            ),
        }
    )
    gateway = SheetsGateway(client=Client({"master": master, "fy-2026": annual}))
    monkeypatch.setattr("budget.services.sheets._legacy_secrets", lambda: {})

    snapshot = gateway.read_fiscal_year("FY2026-27")

    assert snapshot["spreadsheet_id"] == "fy-2026"
    assert [row["Transaction ID"] for row in snapshot["transactions"]] == ["TXN-1"]
    assert snapshot["summary"][0]["Budgeted (AED equiv)"] == "1000"
    assert snapshot["aed_per_usd"] == "3.5"
    assert snapshot["exchange_rates"]["EUR"] == "1.25"
    assert snapshot["exchange_rates"]["JPY"] == "0.007"
    assert snapshot["exchange_rates"]["GBP"] == "1.4"


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


def _mutation_gateway(
    settings,
    monkeypatch,
    *,
    source_transactions=None,
    target_transactions=None,
    target_summary=None,
    target_teams=None,
    target_config=None,
    registry=None,
):
    settings.MASTER_SPREADSHEET_ID = "master"
    settings.REGISTRY_SPREADSHEET_ID = "registry" if registry else ""
    settings.ENABLE_SHEET_WRITES = True
    master_config = Worksheet(
        values=[
            ["Current Fiscal Year", "FY2025-26"],
            ["Spreadsheet ID FY2026-27", "fy-2026"],
            ["AED/USD Exchange Rate", "3.6725"],
            ["EUR/USD Exchange Rate", "1.08"],
            ["JPY/USD Exchange Rate", "0.0064"],
            ["GBP/USD Exchange Rate", "1.27"],
        ]
    )
    master = Workbook(
        {
            "Config": master_config,
            "Transactions": source_transactions or Worksheet(values=[]),
            "Summary": Worksheet(values=[SUMMARY_COLUMNS]),
            "Teams": Worksheet(values=[TEAM_COLUMNS]),
        }
    )
    annual = Workbook(
        {
            "Config": target_config
            or Worksheet(
                values=[
                    ["AED/USD Exchange Rate", "3.6725"],
                    ["EUR/USD Exchange Rate", "1.10"],
                    ["JPY/USD Exchange Rate", "0.0064"],
                    ["GBP/USD Exchange Rate", "1.25"],
                ]
            ),
            "Transactions": target_transactions or Worksheet(values=[]),
            "Summary": target_summary or Worksheet(values=[SUMMARY_COLUMNS]),
            "Teams": target_teams or Worksheet(values=[TEAM_COLUMNS]),
        }
    )
    books = {"master": master, "fy-2026": annual}
    if registry:
        books["registry"] = registry
    monkeypatch.setattr("budget.services.sheets._legacy_secrets", lambda: {})
    return SheetsGateway(client=Client(books)), master, annual


def _manual_candidate(**overrides):
    candidate = {
        "date": "2026-10-01",
        "category": "Consumables",
        "subcategory": "Reagents",
        "vendor": "Vendor",
        "description": "Manual item",
        "po_number": "PO-1",
        "invoice_number": "INV-1",
        "currency": "JPY",
        "amount": "10000",
        "status": "Allocated",
        "receipt_confirmed": "FALSE",
        "pdf_link": "https://example.test/invoice.pdf",
        "email_thread_id": "thread-1",
        "entered_by": "member@nyu.edu",
        "entry_method": "Manual",
        "notes": "Checked",
        "team": "Diabetes",
        "approved_by": "lead@nyu.edu",
        "approved_at": "2026-10-01 10:00:00",
    }
    candidate.update(overrides)
    return candidate


def test_write_transaction_writes_all_26_columns_and_converts_currency(
    settings, monkeypatch
):
    gateway, _, annual = _mutation_gateway(settings, monkeypatch)

    result = gateway.write_transaction("FY2026-27", _manual_candidate())

    saved_values = annual.sheets["Transactions"].values
    assert saved_values[0] == TRANSACTION_COLUMNS
    assert len(saved_values[1]) == 26
    saved = dict(zip(saved_values[0], saved_values[1], strict=False))
    assert result["row"] == saved
    assert saved["Amount"] == "10000.00"
    assert saved["Amount (USD equiv)"] == "64.00"
    assert saved["Amount (AED equiv)"] == "235.04"
    assert saved["Amount (AED)"] == "0"
    assert saved["Amount (USD)"] == "0"
    assert saved["Status"] == "Allocated"
    assert saved["Email Thread ID"] == "thread-1"
    assert saved["Approved By"] == "lead@nyu.edu"


def test_write_transaction_can_resume_an_identical_stable_id(settings, monkeypatch):
    gateway, _, annual = _mutation_gateway(settings, monkeypatch)
    first = gateway.write_transaction(
        "FY2026-27", _manual_candidate(), transaction_id="TXN-WEB-STABLE"
    )

    resumed = gateway.write_transaction(
        "FY2026-27",
        _manual_candidate(),
        transaction_id="TXN-WEB-STABLE",
        allow_existing=True,
    )

    assert resumed["matched"] is True
    assert resumed["transaction_id"] == first["transaction_id"]
    assert len(annual.sheets["Transactions"].values) == 2


def test_update_and_cancel_transaction_recalculate_and_reject_legacy_statuses(
    settings, monkeypatch
):
    gateway, _, _ = _mutation_gateway(settings, monkeypatch)
    created = gateway.write_transaction("FY2026-27", _manual_candidate())

    updated = gateway.update_transaction(
        "FY2026-27",
        created["transaction_id"],
        {"currency": "EUR", "amount": "10", "description": "Corrected"},
    )
    assert updated["row"]["Description"] == "Corrected"
    assert updated["row"]["Amount (USD equiv)"] == "11.00"
    assert updated["row"]["Amount (AED equiv)"] == "40.40"
    assert updated["row"]["Status"] == "Allocated"

    cancelled = gateway.cancel_transaction("FY2026-27", created["transaction_id"])
    assert cancelled["row"]["Status"] == "Cancelled"
    with pytest.raises(ValueError, match="Allocated or Cancelled"):
        gateway.update_transaction(
            "FY2026-27", created["transaction_id"], {"status": "Paid"}
        )


def test_update_transaction_moves_only_after_target_verification(
    settings, monkeypatch
):
    gateway, master, annual = _mutation_gateway(settings, monkeypatch)
    created = gateway.write_transaction(
        "FY2025-26",
        _manual_candidate(date="2026-08-31", currency="USD", amount="25"),
        transaction_id="TXN-MOVE-1",
    )

    moved = gateway.update_transaction(
        "FY2025-26",
        created["transaction_id"],
        {"date": "2026-09-01", "amount": "30"},
        target_fiscal_year="FY2026-27",
    )

    source = dict(
        zip(
            master.sheets["Transactions"].values[0],
            master.sheets["Transactions"].values[1],
            strict=False,
        )
    )
    target = dict(
        zip(
            annual.sheets["Transactions"].values[0],
            annual.sheets["Transactions"].values[1],
            strict=False,
        )
    )
    assert moved["moved"] is True
    assert source["Status"] == "Cancelled"
    assert source["Fiscal Year"] == "FY2025-26"
    assert target["Status"] == "Allocated"
    assert target["Fiscal Year"] == "FY2026-27"
    assert target["Amount"] == "30.00"


def test_update_transaction_can_delete_source_after_verified_move(settings, monkeypatch):
    gateway, master, annual = _mutation_gateway(settings, monkeypatch)
    gateway.write_transaction(
        "FY2025-26", _manual_candidate(date="2026-08-30"), transaction_id="TXN-MOVE-2"
    )

    result = gateway.update_transaction(
        "FY2025-26",
        "TXN-MOVE-2",
        {"date": "2026-09-02", "source_disposition": "delete"},
        target_fiscal_year="FY2026-27",
    )

    assert result["source"]["deleted"] is True
    assert len(master.sheets["Transactions"].values) == 1
    assert annual.sheets["Transactions"].values[1][0] == "TXN-MOVE-2"


class CorruptingWorksheet(Worksheet):
    def __init__(self, *, corrupt_column, **kwargs):
        super().__init__(**kwargs)
        self.corrupt_column = corrupt_column

    def get(self, range_name):
        rows = super().get(range_name)
        if rows and self.corrupt_column < len(rows[0]):
            rows = [list(rows[0])]
            rows[0][self.corrupt_column] = "CORRUPTED"
        return rows


def test_failed_target_readback_rolls_back_copy_and_leaves_source_allocated(
    settings, monkeypatch
):
    corrupt_target = CorruptingWorksheet(
        values=[], corrupt_column=TRANSACTION_COLUMNS.index("Team")
    )
    gateway, master, _ = _mutation_gateway(
        settings, monkeypatch, target_transactions=corrupt_target
    )
    gateway.write_transaction(
        "FY2025-26", _manual_candidate(date="2026-08-31"), transaction_id="TXN-MOVE-3"
    )

    with pytest.raises(SheetsSourceError, match="Team value did not verify"):
        gateway.update_transaction(
            "FY2025-26",
            "TXN-MOVE-3",
            {"date": "2026-09-01"},
            target_fiscal_year="FY2026-27",
        )

    source = dict(
        zip(
            master.sheets["Transactions"].values[0],
            master.sheets["Transactions"].values[1],
            strict=False,
        )
    )
    assert source["Status"] == "Allocated"
    assert corrupt_target.values == [TRANSACTION_COLUMNS]


def test_write_category_allocations_preserves_summary_formula_cells(
    settings, monkeypatch
):
    existing = [
        "Consumables",
        "0",
        "100",
        "367.25",
        "0",
        "27.22",
        "100",
        "267.25",
        "0.27",
        "bar",
    ]
    existing[6] = "=SUM(F2:G2)"
    existing[7] = "=D2-G2"
    existing[8] = "=IFERROR(G2/D2,0)"
    travel = ["Travel", "0", "0", "0", "0", "0", "=SUM(F3:G3)", "=D3-G3", "=IFERROR(G3/D3,0)", "bar"]
    summary = Worksheet(values=[SUMMARY_COLUMNS, existing, travel])
    gateway, _, _ = _mutation_gateway(
        settings, monkeypatch, target_summary=summary
    )

    result = gateway.write_category_allocations(
        "FY2026-27", {"Consumables": "1000", "Travel": "250"}
    )

    assert result["rows"]["Consumables"]["Budgeted (USD)"] == "1000.00"
    assert result["rows"]["Travel"]["Budgeted (AED equiv)"] == "918.13"
    assert [row[0] for row in summary.values[1:]] == ["Consumables", "Travel"]
    assert summary.values[1][6:10] == [
        "=SUM(F2:G2)",
        "=D2-G2",
        "=IFERROR(G2/D2,0)",
        "bar",
    ]


def test_repair_summary_formulas_restores_all_calculation_columns(settings, monkeypatch):
    categories = [
        "Equipment",
        "Consumables",
        "Personnel",
        "Travel",
        "Publications",
        "Memberships",
        "Other",
    ]
    summary = Worksheet(
        values=[SUMMARY_COLUMNS]
        + [[category, "0", "100", "367.25", "", "", "", "", "", ""] for category in categories]
        + [["TOTAL", "", "", "", "", "", "", "", "", ""]]
    )
    gateway, _, _ = _mutation_gateway(
        settings, monkeypatch, target_summary=summary
    )

    result = gateway.repair_summary_formulas("FY2026-27")

    assert len(result["ranges"]) == 8
    assert summary.values[1][4].startswith("=SUMIFS('Transactions'!$M:$M")
    assert summary.values[1][7] == "=D2-G2"
    assert summary.values[1][8] == "=IFERROR(G2/D2,0)"
    assert summary.values[8][1] == "=SUM(B2:B8)"


def test_upsert_team_updates_existing_and_accepts_form_field_names(settings, monkeypatch):
    teams = Worksheet(
        values=[
            TEAM_COLUMNS,
            ["Diabetes", "0", "1000", "old@nyu.edu", "", "", "", "", "", "Old", "Y"],
        ]
    )
    gateway, _, _ = _mutation_gateway(settings, monkeypatch, target_teams=teams)

    updated = gateway.upsert_team(
        "FY2026-27",
        {
            "name": "Diabetes",
            "allocation_usd": "55000",
            "manager_emails": "manager@nyu.edu",
            "lead_emails": "lead@nyu.edu",
            "member_emails": "member@nyu.edu",
            "description": "Updated",
            "active": True,
        },
    )
    inserted = gateway.upsert_team(
        "FY2026-27", {"name": "IoC", "allocation_usd": "42000", "active": False}
    )

    assert updated["matched"] is True
    assert updated["row"]["Allocation (USD)"] == "55000"
    assert updated["row"]["Budget Manager Emails"] == "manager@nyu.edu"
    assert inserted["matched"] is False
    assert inserted["row"]["Active"] == "N"
    assert len(teams.values) == 3


def test_set_config_updates_and_appends_supported_exchange_rates(settings, monkeypatch):
    config = Worksheet(
        values=[
            ["AED/USD Exchange Rate", "3.6725"],
            ["EUR/USD Exchange Rate", "1.08"],
        ]
    )
    gateway, _, _ = _mutation_gateway(settings, monkeypatch, target_config=config)

    updated = gateway.set_config("FY2026-27", "EUR/USD Exchange Rate", "1.12")
    inserted = gateway.set_config("FY2026-27", "JPY/USD Exchange Rate", "0.0065")

    assert updated == {
        "matched": True,
        "key": "EUR/USD Exchange Rate",
        "value": "1.12",
        "spreadsheet_id": "fy-2026",
    }
    assert inserted["matched"] is False
    assert config.values[-1] == ["JPY/USD Exchange Rate", "0.0065"]
    with pytest.raises(ValueError, match="supported exchange-rate"):
        gateway.set_config("FY2026-27", "Current Fiscal Year", "FY2027-28")


def test_queue_fiscal_year_creation_writes_verified_master_config_token(
    settings, monkeypatch
):
    gateway, master, _ = _mutation_gateway(settings, monkeypatch)

    result = gateway.queue_fiscal_year_creation("FY2027-28")

    assert result["key"] == "Fiscal Year Creation Request FY2027-28"
    assert result["token"].startswith("Queued ")
    assert master.sheets["Config"].values[-1] == [result["key"], result["token"]]
    with pytest.raises(SheetsSourceError, match="already registered"):
        gateway.queue_fiscal_year_creation("FY2026-27")


def test_upsert_registry_member_preserves_id_and_reconciles_teams_and_roles(
    settings, monkeypatch
):
    registry = Workbook(
        {
            "Members": Worksheet(
                values=[
                    REGISTRY_MEMBER_COLUMNS,
                    [
                        "M007",
                        "member@nyu.edu",
                        "Old Name",
                        "Old Name",
                        "member",
                        "TRUE",
                        "2025-01-01",
                        "",
                        "hash",
                        "",
                        "FALSE",
                        "Existing",
                    ],
                ]
            ),
            "Teams": Worksheet(
                values=[
                    ["team_id", "team_name", "description", "active"],
                    ["T001", "Diabetes", "", "TRUE"],
                    ["T002", "IoC", "", "TRUE"],
                ]
            ),
            "Member_Teams": Worksheet(
                values=[
                    REGISTRY_MEMBER_TEAM_COLUMNS,
                    ["MT001", "M007", "T001", "member", "TRUE", "2025-01-01", ""],
                    ["MT002", "M007", "T002", "member", "TRUE", "2025-01-01", ""],
                ]
            ),
            "App_Roles": Worksheet(
                values=[
                    REGISTRY_APP_ROLE_COLUMNS,
                    ["AR001", "M007", "budget", "viewer", "T001", "TRUE", "2025-01-01", ""],
                    ["AR002", "M007", "budget", "viewer", "T002", "TRUE", "2025-01-01", ""],
                ]
            ),
        }
    )
    gateway, _, _ = _mutation_gateway(
        settings, monkeypatch, registry=registry
    )

    result = gateway.upsert_registry_member(
        {
            "display_name": "Updated Member",
            "email": "MEMBER@nyu.edu",
            "role": "lead",
            "team_names": ["IoC"],
            "active": True,
        }
    )

    assert result["member_id"] == "M007"
    assert result["team_ids"] == ["T002"]
    assert result["roles"] == [("lead", "T002")]
    member = registry.sheets["Members"].get_all_records()[0]
    assert member["display_name"] == "Updated Member"
    memberships = registry.sheets["Member_Teams"].get_all_records()
    assert next(row for row in memberships if row["team_id"] == "T001")["active"] == "FALSE"
    assert next(row for row in memberships if row["team_id"] == "T002")["active"] == "TRUE"
    roles = registry.sheets["App_Roles"].get_all_records()
    assert {
        (row["app_role"], row["scope_team_id"])
        for row in roles
        if row["member_id"] == "M007" and row["active"] == "TRUE"
    } == {("lead", "T002")}

    disabled = gateway.upsert_registry_member(
        {
            "display_name": "Updated Member",
            "email": "member@nyu.edu",
            "role": "member",
            "team_names": [],
            "active": False,
        }
    )
    assert disabled["member_id"] == "M007"
    assert disabled["team_ids"] == []
    assert disabled["roles"] == []


def test_upsert_registry_team_reconciles_memberships_and_scoped_roles(
    settings, monkeypatch
):
    registry = Workbook(
        {
            "Members": Worksheet(
                values=[
                    REGISTRY_MEMBER_COLUMNS,
                    ["M001", "manager@nyu.edu", "Manager", "Manager", "member", "TRUE"],
                    ["M002", "lead@nyu.edu", "Lead", "Lead", "member", "TRUE"],
                    ["M003", "member@nyu.edu", "Member", "Member", "member", "TRUE"],
                ]
            ),
            "Teams": Worksheet(values=[["team_id", "team_name", "description", "active"]]),
            "Member_Teams": Worksheet(values=[REGISTRY_MEMBER_TEAM_COLUMNS]),
            "App_Roles": Worksheet(values=[REGISTRY_APP_ROLE_COLUMNS]),
        }
    )
    gateway, _, _ = _mutation_gateway(settings, monkeypatch, registry=registry)

    created = gateway.upsert_registry_team(
        {
            "name": "Diabetes",
            "manager_emails": "manager@nyu.edu",
            "lead_emails": "lead@nyu.edu",
            "member_emails": "member@nyu.edu",
            "description": "Diabetes team",
            "active": True,
        }
    )

    assert created == {"team_id": "T001", "team_name": "Diabetes", "active": True}
    teams = registry.sheets["Teams"].get_all_records()
    assert teams == [
        {
            "team_id": "T001",
            "team_name": "Diabetes",
            "description": "Diabetes team",
            "active": "TRUE",
        }
    ]
    memberships = registry.sheets["Member_Teams"].get_all_records()
    assert {
        (row["member_id"], row["team_role"], row["active"])
        for row in memberships
    } == {
        ("M001", "lead", "TRUE"),
        ("M002", "lead", "TRUE"),
        ("M003", "member", "TRUE"),
    }
    roles = registry.sheets["App_Roles"].get_all_records()
    assert {
        (row["member_id"], row["app_role"], row["scope_team_id"], row["active"])
        for row in roles
    } == {
        ("M001", "manager", "T001", "TRUE"),
        ("M002", "lead", "T001", "TRUE"),
        ("M003", "viewer", "T001", "TRUE"),
    }


def test_upsert_registry_team_rejects_corrupt_membership_readback(settings, monkeypatch):
    class CorruptMembershipWorksheet(Worksheet):
        def get_all_records(self):
            records = super().get_all_records()
            if records:
                records[0]["team_role"] = "member"
            return records

    registry = Workbook(
        {
            "Members": Worksheet(
                values=[
                    REGISTRY_MEMBER_COLUMNS,
                    ["M001", "lead@nyu.edu", "Lead", "Lead", "member", "TRUE"],
                ]
            ),
            "Teams": Worksheet(values=[["team_id", "team_name", "description", "active"]]),
            "Member_Teams": CorruptMembershipWorksheet(
                values=[REGISTRY_MEMBER_TEAM_COLUMNS]
            ),
            "App_Roles": Worksheet(values=[REGISTRY_APP_ROLE_COLUMNS]),
        }
    )
    gateway, _, _ = _mutation_gateway(settings, monkeypatch, registry=registry)

    with pytest.raises(SheetsSourceError, match="membership readback"):
        gateway.upsert_registry_team(
            {"name": "Diabetes", "lead_emails": "lead@nyu.edu", "active": True}
        )


def test_all_public_mutations_honor_write_feature_flag(settings):
    settings.ENABLE_SHEET_WRITES = False
    settings.REGISTRY_SPREADSHEET_ID = "registry"
    gateway = SheetsGateway(client=Client({}))

    calls = [
        lambda: gateway.write_transaction("FY2026-27", {}),
        lambda: gateway.update_transaction("FY2026-27", "TXN-1", {}),
        lambda: gateway.write_category_allocations("FY2026-27", {}),
        lambda: gateway.upsert_team("FY2026-27", {}),
        lambda: gateway.upsert_registry_team({"name": "Diabetes"}),
        lambda: gateway.set_config("FY2026-27", "EUR/USD Exchange Rate", "1"),
        lambda: gateway.queue_fiscal_year_creation("FY2027-28"),
        lambda: gateway.upsert_registry_member(
            {
                "email": "member@nyu.edu",
                "display_name": "Member",
                "role": "member",
                "team_names": [],
            }
        ),
    ]
    for call in calls:
        with pytest.raises(SheetsSourceError, match="disabled"):
            call()
