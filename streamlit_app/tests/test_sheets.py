from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

# We patch gspread and st.secrets before importing sheets
@pytest.fixture(autouse=True)
def mock_secrets(monkeypatch):
    import streamlit as st
    st.cache_data.clear()
    st.cache_resource.clear()
    monkeypatch.setattr(st, "secrets", {
        "SPREADSHEET_ID": "TEST_ID",
        "PI_EMAIL": "pi@nyu.edu",
        "gcp_service_account": {"type": "service_account"}
    })
    yield
    st.cache_data.clear()
    st.cache_resource.clear()

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
    assert df.iloc[0]["Status"] == "Allocated"

@patch("utils.sheets.get_spreadsheet")
def test_get_transactions_reuses_cached_sheet_read(mock_ss):
    from utils.sheets import get_transactions
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = [
        {"Transaction ID": "TXN-001", "Category": "Equipment"}
    ]
    mock_ss.return_value.worksheet.return_value = mock_ws

    first = get_transactions()
    second = get_transactions()

    assert first.equals(second)
    assert mock_ws.get_all_records.call_count == 1

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
def test_get_config_reuses_single_config_sheet_read_for_multiple_keys(mock_ss):
    from utils.sheets import get_config
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        ["AED/USD Exchange Rate", "3.6725"],
        ["Current Fiscal Year", "FY2026-27"],
        ["Gmail Label", "Budget/Invoices"],
    ]
    mock_ss.return_value.worksheet.return_value = mock_ws

    assert get_config("Current Fiscal Year") == "FY2026-27"
    assert get_config("Gmail Label") == "Budget/Invoices"

    assert mock_ws.get_all_values.call_count == 1

@patch("utils.sheets.get_spreadsheet")
def test_get_summary_includes_all_budget_categories(mock_ss):
    from utils.sheets import get_summary
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        ["Kamei Lab Budget"],
        ["Category", "Budgeted (AED)", "Budgeted (USD)", "Budgeted (AED equiv)"],
        ["Equipment", "500000", "0", "500000"],
        ["Consumables", "50000", "0", "50000"],
        ["Publications", "25000", "5000", "43362.5"],
        ["Memberships", "10000", "1000", "13672.5"],
        ["TOTAL", "585000", "6000", "607035"],
    ]
    mock_ss.return_value.worksheet.return_value = mock_ws

    df = get_summary()

    assert df["Category"].tolist() == [
        "Equipment",
        "Consumables",
        "Publications",
        "Memberships",
        "TOTAL",
    ]

@patch("utils.sheets.get_spreadsheet")
def test_append_transaction_calls_append_row(mock_ss):
    from utils.sheets import append_transaction
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = []
    mock_ws.get_all_values.return_value = [["Transaction ID"]]
    mock_ws.row_values.return_value = ["Transaction ID"]
    mock_ss.return_value.worksheet.return_value = mock_ws
    row_data = {"Transaction ID": "TXN-002", "Category": "Equipment",
                "Amount (AED)": 200, "Team": "Synbio"}
    append_transaction(row_data)
    mock_ws.append_row.assert_called_once()
    appended = mock_ws.append_row.call_args.args[0]
    from utils.sheets import TXN_COLUMNS
    assert len(appended) == len(TXN_COLUMNS)
    assert "Approved By" in TXN_COLUMNS
    assert "Approved At" in TXN_COLUMNS
    assert "Currency" in TXN_COLUMNS
    assert "Amount" in TXN_COLUMNS
    assert "Amount (USD equiv)" in TXN_COLUMNS

@patch("utils.sheets.get_currency_rates_to_usd", return_value={"USD": 1.0, "AED": 1 / 3.6725, "EUR": 1.08, "JPY": 0.0064, "GBP": 1.27})
@patch("utils.sheets.get_spreadsheet")
def test_append_transaction_writes_selected_currency_amount_and_usd_equiv(mock_ss, _rates):
    from utils.sheets import TXN_COLUMNS, append_transaction
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = []
    mock_ws.get_all_values.return_value = [TXN_COLUMNS]
    mock_ws.row_values.return_value = TXN_COLUMNS
    mock_ss.return_value.worksheet.return_value = mock_ws

    append_transaction({
        "Transaction ID": "TXN-003",
        "Category": "Consumables",
        "Currency": "EUR",
        "Amount": 100,
        "Team": "Synbio",
    })

    appended = mock_ws.append_row.call_args.args[0]
    assert appended[TXN_COLUMNS.index("Currency")] == "EUR"
    assert appended[TXN_COLUMNS.index("Amount")] == 100.0
    assert appended[TXN_COLUMNS.index("Amount (USD equiv)")] == 108.0

@patch("utils.sheets.get_currency_rates_to_usd", return_value={"USD": 1.0, "AED": 1 / 3.6725, "EUR": 1.08, "JPY": 0.0064, "GBP": 1.27})
@patch("utils.sheets.get_spreadsheet")
def test_append_transaction_routes_to_fiscal_year_from_date(mock_ss, _rates):
    from utils.sheets import TXN_COLUMNS, append_transaction
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = []
    mock_ws.get_all_values.return_value = [TXN_COLUMNS]
    mock_ws.row_values.return_value = TXN_COLUMNS
    mock_ss.return_value.worksheet.return_value = mock_ws

    append_transaction({
        "Transaction ID": "TXN-004",
        "Date": "2026-09-01",
        "Category": "Consumables",
        "Currency": "USD",
        "Amount": 100,
    })

    assert any(call.args == ("FY2026-27",) for call in mock_ss.call_args_list)
    appended = mock_ws.append_row.call_args.args[0]
    assert appended[TXN_COLUMNS.index("Fiscal Year")] == "FY2026-27"
    assert appended[TXN_COLUMNS.index("Amount (AED)")] == 0.0
    assert appended[TXN_COLUMNS.index("Amount (USD)")] == 100.0

@patch("utils.sheets.get_currency_rates_to_usd", return_value={"USD": 1.0, "AED": 1 / 3.6725, "EUR": 1.08, "JPY": 0.0064, "GBP": 1.27})
@patch("utils.sheets.get_spreadsheet")
def test_append_transaction_can_use_explicit_fiscal_year(mock_ss, _rates):
    from utils.sheets import TXN_COLUMNS, append_transaction
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = []
    mock_ws.get_all_values.return_value = [TXN_COLUMNS]
    mock_ws.row_values.return_value = TXN_COLUMNS
    mock_ss.return_value.worksheet.return_value = mock_ws

    append_transaction({
        "Transaction ID": "TXN-005",
        "Date": "2026-09-01",
        "Fiscal Year": "FY2025-26",
        "Category": "Consumables",
        "Currency": "USD",
        "Amount": 100,
    })

    assert any(call.args == ("FY2025-26",) for call in mock_ss.call_args_list)
    appended = mock_ws.append_row.call_args.args[0]
    assert appended[TXN_COLUMNS.index("Fiscal Year")] == "FY2025-26"

@patch("utils.sheets.get_exchange_rate", return_value=3.6725)
@patch("utils.sheets.get_spreadsheet")
def test_update_transaction_recalculates_aed_equiv_when_amounts_change(mock_ss, _rate):
    from utils.sheets import TXN_COLUMNS, update_transaction
    mock_ws = MagicMock()
    row = [""] * len(TXN_COLUMNS)
    row[TXN_COLUMNS.index("Transaction ID")] = "TXN-001"
    row[TXN_COLUMNS.index("Amount (AED)")] = "0"
    row[TXN_COLUMNS.index("Amount (USD)")] = "0"
    row[TXN_COLUMNS.index("Amount (AED equiv)")] = "0"
    mock_ws.get_all_values.return_value = [TXN_COLUMNS, row]
    mock_ws.row_values.return_value = TXN_COLUMNS
    mock_ss.return_value.worksheet.return_value = mock_ws

    update_transaction("TXN-001", {"Amount (AED)": 0, "Amount (USD)": 2506})

    calls = [call.args[:3] for call in mock_ws.update_cell.call_args_list]
    assert (2, TXN_COLUMNS.index("Amount (AED equiv)") + 1, 9203.29) in calls

@patch("utils.sheets.get_currency_rates_to_usd", return_value={"USD": 1.0, "AED": 1 / 3.6725, "EUR": 1.08, "JPY": 0.0064, "GBP": 1.27})
@patch("utils.sheets.get_spreadsheet")
def test_update_transaction_recalculates_usd_equiv_when_currency_amount_changes(mock_ss, _rates):
    from utils.sheets import TXN_COLUMNS, update_transaction
    mock_ws = MagicMock()
    row = [""] * len(TXN_COLUMNS)
    row[TXN_COLUMNS.index("Transaction ID")] = "TXN-001"
    row[TXN_COLUMNS.index("Currency")] = "USD"
    row[TXN_COLUMNS.index("Amount")] = "0"
    row[TXN_COLUMNS.index("Amount (USD equiv)")] = "0"
    mock_ws.get_all_values.return_value = [TXN_COLUMNS, row]
    mock_ws.row_values.return_value = TXN_COLUMNS
    mock_ss.return_value.worksheet.return_value = mock_ws

    update_transaction("TXN-001", {"Currency": "GBP", "Amount": 100})

    calls = [call.args[:3] for call in mock_ws.update_cell.call_args_list]
    assert (2, TXN_COLUMNS.index("Amount (USD equiv)") + 1, 127.0) in calls

@patch("utils.sheets.get_spreadsheet")
def test_update_transaction_recalculates_fiscal_year_when_date_changes(mock_ss):
    from utils.sheets import TXN_COLUMNS, update_transaction
    mock_ws = MagicMock()
    row = [""] * len(TXN_COLUMNS)
    row[TXN_COLUMNS.index("Transaction ID")] = "TXN-001"
    row[TXN_COLUMNS.index("Date")] = "2026-08-31"
    row[TXN_COLUMNS.index("Fiscal Year")] = "FY2025-26"
    mock_ws.get_all_values.return_value = [TXN_COLUMNS, row]
    mock_ws.row_values.return_value = TXN_COLUMNS
    mock_ss.return_value.worksheet.return_value = mock_ws

    update_transaction("TXN-001", {"Date": "2026-09-01"})

    calls = [call.args[:3] for call in mock_ws.update_cell.call_args_list]
    assert (2, TXN_COLUMNS.index("Fiscal Year") + 1, "FY2026-27") in calls

@patch("utils.sheets.get_spreadsheet")
def test_update_transaction_preserves_existing_date_when_import_date_is_blank(mock_ss):
    from utils.sheets import TXN_COLUMNS, update_transaction
    mock_ws = MagicMock()
    row = [""] * len(TXN_COLUMNS)
    row[TXN_COLUMNS.index("Transaction ID")] = "TXN-001"
    row[TXN_COLUMNS.index("Date")] = "2026-08-31"
    row[TXN_COLUMNS.index("Fiscal Year")] = "FY2025-26"
    mock_ws.get_all_values.return_value = [TXN_COLUMNS, row]
    mock_ws.row_values.return_value = TXN_COLUMNS
    mock_ss.return_value.worksheet.return_value = mock_ws

    update_transaction("TXN-001", {"Date": "", "Notes": "Imported PDF without date"})

    calls = [call.args[:3] for call in mock_ws.update_cell.call_args_list]
    assert (2, TXN_COLUMNS.index("Date") + 1, "2026-08-31") in calls
    assert (2, TXN_COLUMNS.index("Fiscal Year") + 1, "FY2025-26") in calls

@patch("utils.sheets.append_transaction")
@patch("utils.sheets.get_spreadsheet")
def test_update_transaction_moves_row_when_explicit_fiscal_year_changes(mock_ss, mock_append):
    from utils.sheets import TXN_COLUMNS, update_transaction
    mock_ws = MagicMock()
    row = [""] * len(TXN_COLUMNS)
    row[TXN_COLUMNS.index("Transaction ID")] = "TXN-001"
    row[TXN_COLUMNS.index("Date")] = "2026-08-31"
    row[TXN_COLUMNS.index("Fiscal Year")] = "FY2025-26"
    row[TXN_COLUMNS.index("Category")] = "Equipment"
    mock_ws.get_all_values.return_value = [TXN_COLUMNS, row]
    mock_ws.row_values.return_value = TXN_COLUMNS
    mock_ss.return_value.worksheet.return_value = mock_ws

    update_transaction(
        "TXN-001",
        {"Date": "2026-09-01", "Fiscal Year": "FY2026-27", "Notes": "move"},
        source_fiscal_year="FY2025-26",
    )

    mock_append.assert_called_once()
    moved = mock_append.call_args.args[0]
    assert moved["Transaction ID"] == "TXN-001"
    assert moved["Fiscal Year"] == "FY2026-27"
    assert moved["Date"] == "2026-09-01"
    mock_ws.delete_rows.assert_called_once_with(2)

@patch("utils.sheets.get_exchange_rate", return_value=3.6725)
@patch("utils.sheets.get_spreadsheet")
def test_set_budget_allocation_inserts_missing_category_before_total(mock_ss, _rate):
    from utils.sheets import set_budget_allocation
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        ["Category", "Budgeted (AED)", "Budgeted (USD)", "Budgeted (AED equiv)"],
        ["Equipment", "500000", "0", "500000"],
        ["TOTAL", "500000", "0", "500000"],
    ]
    mock_ss.return_value.worksheet.return_value = mock_ws

    set_budget_allocation("Consumables", 1000, 10)

    mock_ws.insert_row.assert_called_once()
    row, index = mock_ws.insert_row.call_args.args[:2]
    assert index == 3
    assert row[:4] == ["Consumables", 1000, 10, 1036.73]

@patch("utils.sheets.get_spreadsheet")
def test_upsert_team_expands_columns_before_header_update(mock_ss):
    from utils.sheets import TEAM_COLUMNS, upsert_team
    mock_ws = MagicMock()
    mock_ws.col_count = 6
    mock_ws.get_all_values.return_value = [[
        "Team Name",
        "Allocation (AED)",
        "Allocation (USD)",
        "Lead Emails",
        "Member Emails",
        "Active",
    ]]
    mock_ss.return_value.worksheet.return_value = mock_ws

    upsert_team({
        "Team Name": "Diabetes",
        "Allocation (USD)": 55000,
        "Budget Manager Emails": "manager@nyu.edu",
        "Budget Manager Names": "Budget Manager",
        "Lead Emails": "lead@nyu.edu",
        "Lead Names": "Team Lead",
        "Member Emails": "ra@nyu.edu",
        "Member Names": "Lab Member",
        "Active": "Y",
    })

    mock_ws.add_cols.assert_called_once_with(len(TEAM_COLUMNS) - 6)
    expected_headers = [
        "Team Name",
        "Allocation (AED)",
        "Allocation (USD)",
        "Lead Emails",
        "Member Emails",
        "Active",
        "Budget Manager Emails",
        "Budget Manager Names",
        "Lead Names",
        "Member Names",
        "Description",
    ]
    mock_ws.update.assert_any_call("A1:K1", [expected_headers])
    mock_ws.update_cell.assert_not_called()
    appended = mock_ws.append_row.call_args.args[0]
    assert appended[expected_headers.index("Budget Manager Emails")] == "manager@nyu.edu"
    assert appended[expected_headers.index("Lead Names")] == "Team Lead"

def test_find_matching_transaction_id_prefers_po_invoice_and_ignores_vendor_only():
    from utils.sheets import find_matching_transaction_id
    txns = pd.DataFrame([
        {"Transaction ID": "TXN-001", "PO Number": "PO-7", "Invoice Number": "",
         "Vendor / Payee": "Fisher Scientific", "Team": "Synbio"},
        {"Transaction ID": "TXN-002", "PO Number": "", "Invoice Number": "INV-9",
         "Vendor / Payee": "VWR", "Team": "Imaging"},
        {"Transaction ID": "TXN-003", "PO Number": "", "Invoice Number": "",
         "Vendor / Payee": "Sigma Aldrich", "Team": "Synbio"},
    ])
    assert find_matching_transaction_id(txns, {"PO Number": "PO-7", "Team": "Synbio"}) == "TXN-001"
    assert find_matching_transaction_id(txns, {"Invoice Number": "INV-9", "Team": "Imaging"}) == "TXN-002"
    assert find_matching_transaction_id(txns, {"Vendor / Payee": " sigma aldrich ", "Team": "Synbio"}) is None
    assert find_matching_transaction_id(txns, {"PO Number": "PO-7", "Team": "Imaging"}) is None


@patch("utils.sheets.get_transactions")
def test_next_txn_id_uses_next_available_sequence(mock_get):
    from utils.sheets import _next_txn_id
    mock_get.return_value = pd.DataFrame([
        {"Transaction ID": "TXN-20260628-0001"},
        {"Transaction ID": "TXN-20260628-0007"},
        {"Transaction ID": "legacy-id"},
    ])
    txn_id = _next_txn_id("FY2025-26")
    assert txn_id.startswith("TXN-")
    assert txn_id.endswith("-0008")

@patch("utils.sheets.update_transaction")
@patch("utils.sheets.append_transaction")
@patch("utils.sheets.get_transactions")
def test_upsert_imported_transaction_updates_existing_match(mock_get, mock_append, mock_update):
    from utils.sheets import upsert_imported_transaction
    mock_get.return_value = pd.DataFrame([
        {"Transaction ID": "TXN-001", "PO Number": "PO-7", "Team": "Synbio"}
    ])
    result = upsert_imported_transaction({
        "PO Number": "PO-7",
        "Team": "Synbio",
        "Status": "Pending Review",
    })
    assert result == {"transaction_id": "TXN-001", "matched": True}
    mock_update.assert_called_once()
    assert mock_update.call_args.args[1]["Status"] == "Allocated"
    mock_append.assert_not_called()
