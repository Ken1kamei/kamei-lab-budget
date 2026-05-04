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
