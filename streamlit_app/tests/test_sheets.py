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
    assert row[:4] == ["Consumables", 1000, 10, 1036.72]

def test_find_matching_transaction_id_prefers_po_invoice_then_vendor_team():
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
    assert find_matching_transaction_id(txns, {"Vendor / Payee": " sigma aldrich ", "Team": "Synbio"}) == "TXN-003"
    assert find_matching_transaction_id(txns, {"PO Number": "PO-7", "Team": "Imaging"}) is None

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
    mock_append.assert_not_called()
