from unittest.mock import MagicMock, patch
import pandas as pd
import pytest

# We patch gspread and st.secrets before importing sheets
@pytest.fixture(autouse=True)
def mock_secrets(monkeypatch):
    import streamlit as st
    monkeypatch.setattr(st, "secrets", {
        "SPREADSHEET_ID": "TEST_ID",
        "PI_EMAIL": "pi@nyu.edu",
        "gcp_service_account": {"type": "service_account"}
    })

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
