from unittest.mock import MagicMock, call, patch
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

@patch("utils.sheets.ensure_fiscal_year_spreadsheet")
@patch("utils.sheets._existing_spreadsheet_id_for_fiscal_year", return_value=None)
def test_get_transactions_for_unprepared_fiscal_year_does_not_create_sheet(_sheet_id, mock_ensure):
    from utils.sheets import TXN_COLUMNS, get_transactions

    df = get_transactions("FY2099-00")

    assert df.empty
    assert list(df.columns) == TXN_COLUMNS
    mock_ensure.assert_not_called()

@patch("utils.sheets._read_config_from_base")
@patch("utils.sheets._set_config_in_base")
@patch("utils.sheets._create_fiscal_year_spreadsheet")
def test_ensure_fiscal_year_spreadsheet_creates_a_dedicated_workbook(
    mock_create, mock_set_config, mock_read_config
):
    from utils.sheets import ensure_fiscal_year_spreadsheet
    mock_read_config.side_effect = lambda key: {
        "Spreadsheet ID FY2026-27": None,
        "Current Fiscal Year": "FY2025-26",
        "Fiscal Year": "FY2025-26",
    }.get(key)
    workbook = MagicMock()
    workbook.id = "FY2026_ID"
    mock_create.return_value = workbook

    result = ensure_fiscal_year_spreadsheet("FY2026-27")

    assert result is workbook
    mock_create.assert_called_once_with("FY2026-27")
    mock_set_config.assert_called_once_with("Spreadsheet ID FY2026-27", "FY2026_ID")


@patch("utils.sheets._share_with_pi")
@patch("utils.sheets._initialize_new_fiscal_year_workbook")
@patch("utils.sheets.ensure_fiscal_year_template")
@patch("utils.sheets._copy_fiscal_year_workbook")
def test_create_fiscal_year_spreadsheet_copies_the_template(
    mock_copy, mock_template, mock_initialize, mock_share
):
    from utils.sheets import _create_fiscal_year_spreadsheet

    template = MagicMock()
    template.id = "TEMPLATE_ID"
    workbook = MagicMock()
    workbook.id = "FY2027_ID"
    mock_template.return_value = template
    mock_copy.return_value = workbook

    result = _create_fiscal_year_spreadsheet("FY2027-28")

    assert result is workbook
    mock_copy.assert_called_once_with(
        "TEMPLATE_ID",
        "KameiLab Budget FY2027-28",
    )
    mock_share.assert_called_once_with(workbook)
    mock_initialize.assert_called_once_with(workbook, "FY2027-28")


@patch("utils.sheets._open_spreadsheet")
@patch("utils.sheets._drive_session")
@patch("utils.sheets._require_fiscal_year_shared_drive_folder", return_value="SHARED_FOLDER")
def test_copy_fiscal_year_workbook_uses_configured_shared_drive_folder(
    _folder_id, mock_drive_session, mock_open_spreadsheet
):
    from utils.sheets import _copy_fiscal_year_workbook

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"id": "NEW_WORKBOOK_ID"}
    mock_drive_session.return_value.post.return_value = response
    workbook = MagicMock()
    mock_open_spreadsheet.return_value = workbook

    result = _copy_fiscal_year_workbook("SOURCE_ID", "KameiLab Budget FY2027-28")

    assert result is workbook
    mock_drive_session.return_value.post.assert_called_once_with(
        "https://www.googleapis.com/drive/v3/files/SOURCE_ID/copy",
        params={"supportsAllDrives": "true", "fields": "id,name"},
        json={
            "name": "KameiLab Budget FY2027-28",
            "mimeType": "application/vnd.google-apps.spreadsheet",
            "parents": ["SHARED_FOLDER"],
        },
        timeout=45,
    )
    mock_open_spreadsheet.assert_called_once_with("NEW_WORKBOOK_ID")


@patch("utils.sheets._drive_session")
@patch("utils.sheets.fiscal_year_shared_drive_folder_id", return_value="SHARED_FOLDER")
def test_shared_drive_preflight_requires_a_writable_shared_drive_folder(_folder_id, mock_drive_session):
    from utils.sheets import _require_fiscal_year_shared_drive_folder

    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {
        "id": "SHARED_FOLDER",
        "driveId": "SHARED_DRIVE",
        "capabilities": {"canAddChildren": True},
    }
    mock_drive_session.return_value.get.return_value = response

    assert _require_fiscal_year_shared_drive_folder() == "SHARED_FOLDER"
    mock_drive_session.return_value.get.assert_called_once_with(
        "https://www.googleapis.com/drive/v3/files/SHARED_FOLDER",
        params={"supportsAllDrives": "true", "fields": "id,driveId,capabilities(canAddChildren)"},
        timeout=30,
    )


@patch("utils.sheets.get_spreadsheet", return_value=None)
def test_append_transaction_rejects_an_unprepared_fiscal_year(mock_spreadsheet):
    from utils.sheets import append_transaction

    with pytest.raises(ValueError, match="has not been prepared"):
        append_transaction({"Date": "2026-09-01", "Category": "Consumables"})

    mock_spreadsheet.assert_called_once_with("FY2026-27", create_if_missing=False)


@patch("utils.sheets.get_spreadsheet", return_value=None)
def test_ws_rejects_all_unprepared_fiscal_year_writes(mock_spreadsheet):
    from utils.sheets import _ws

    with pytest.raises(ValueError, match="has not been prepared"):
        _ws("Teams", "FY2027-28")

    mock_spreadsheet.assert_called_once_with("FY2027-28", create_if_missing=False)


@patch("utils.sheets._set_config_in_base")
@patch("utils.sheets._ws", side_effect=ValueError("FY2027-28 has not been prepared"))
def test_set_config_does_not_write_global_values_when_the_selected_year_is_unprepared(
    _worksheet, mock_set_base
):
    from utils.sheets import set_config

    with pytest.raises(ValueError, match="has not been prepared"):
        set_config("AED/USD Exchange Rate", 3.67)

    mock_set_base.assert_not_called()


@patch("utils.sheets._set_config_in_base")
@patch("utils.sheets._create_fiscal_year_spreadsheet")
@patch("utils.sheets._base_spreadsheet")
@patch("utils.sheets.fiscal_year_uses_legacy_tabs", return_value=True)
def test_migrate_fiscal_year_copies_legacy_tabs_without_rewriting_values(
    _legacy_tabs, mock_base, mock_create, mock_set_config
):
    from utils.sheets import migrate_fiscal_year_to_dedicated_workbook

    source = MagicMock()
    source_transaction = MagicMock()
    source_summary = MagicMock()
    source_teams = MagicMock()
    source_config = MagicMock()
    source.worksheet.side_effect = {
        "Transactions FY2026-27": source_transaction,
        "Summary FY2026-27": source_summary,
        "Teams FY2026-27": source_teams,
        "Config FY2026-27": source_config,
    }.get
    source_transaction.copy_to.return_value = {"sheetId": 101}
    source_summary.copy_to.return_value = {"sheetId": 102}
    source_teams.copy_to.return_value = {"sheetId": 103}
    source_config.copy_to.return_value = {"sheetId": 104}
    mock_base.return_value = source

    target = MagicMock()
    target.id = "FY2026_ID"
    target_transaction = MagicMock()
    target_summary = MagicMock()
    target_teams = MagicMock()
    target_config = MagicMock()
    target.worksheet.side_effect = {
        "Transactions": target_transaction,
        "Summary": target_summary,
        "Teams": target_teams,
        "Config": target_config,
    }.get
    copied_transaction = MagicMock()
    copied_summary = MagicMock()
    copied_teams = MagicMock()
    copied_config = MagicMock()
    target.get_worksheet_by_id.side_effect = {
        101: copied_transaction,
        102: copied_summary,
        103: copied_teams,
        104: copied_config,
    }.get
    mock_create.return_value = target

    result = migrate_fiscal_year_to_dedicated_workbook("FY2026-27")

    assert result is target
    mock_create.assert_called_once_with("FY2026-27")
    source_transaction.copy_to.assert_called_once_with("FY2026_ID")
    source_summary.copy_to.assert_called_once_with("FY2026_ID")
    source_teams.copy_to.assert_called_once_with("FY2026_ID")
    source_config.copy_to.assert_called_once_with("FY2026_ID")
    assert target.del_worksheet.call_args_list == [
        call(target_transaction),
        call(target_summary),
        call(target_teams),
        call(target_config),
    ]
    copied_transaction.update_title.assert_called_once_with("Transactions")
    copied_summary.update_title.assert_called_once_with("Summary")
    copied_teams.update_title.assert_called_once_with("Teams")
    copied_config.update_title.assert_called_once_with("Config")
    mock_set_config.assert_called_once_with("Spreadsheet ID FY2026-27", "FY2026_ID")


@patch("utils.sheets._base_ws")
def test_config_rows_for_a_new_fiscal_year_exclude_workbook_registry_keys(mock_base_ws):
    from utils.sheets import _config_rows_for_fiscal_year

    mock_base_ws.return_value.get_all_values.return_value = [
        ["Current Fiscal Year", "FY2025-26"],
        ["Spreadsheet ID FY2025-26", "MASTER_ID"],
        ["Spreadsheet ID FY2026-27", "FY2026_ID"],
        ["Fiscal Year Template Spreadsheet ID", "TEMPLATE_ID"],
        ["Gmail Label", "Budget/Invoices"],
    ]

    rows = _config_rows_for_fiscal_year("FY2027-28")
    values = {row[0]: row[1] for row in rows}

    assert values["Current Fiscal Year"] == "FY2027-28"
    assert values["Fiscal Year"] == "FY2027-28"
    assert "Spreadsheet ID FY2025-26" not in values
    assert "Spreadsheet ID FY2026-27" not in values
    assert "Fiscal Year Template Spreadsheet ID" not in values

@patch("utils.sheets._base_fiscal_year", return_value="FY2025-26")
@patch("utils.sheets._spreadsheet_id_for_fiscal_year", return_value="TEST_ID")
def test_worksheet_name_uses_fiscal_year_tabs_when_registered_to_base(_registered, _base_fy):
    from utils.sheets import _worksheet_name

    assert _worksheet_name("Summary", "FY2026-27") == "Summary FY2026-27"

@patch("utils.sheets._base_fiscal_year", return_value="FY2025-26")
@patch("utils.sheets._spreadsheet_id_for_fiscal_year", return_value="TEST_ID")
@patch("utils.sheets.get_spreadsheet")
def test_ws_reads_fiscal_year_tab_from_base_workbook(mock_ss, _registered, _base_fy):
    from utils.sheets import _ws
    workbook = MagicMock()
    mock_ss.return_value = workbook

    _ws("Summary", "FY2026-27")

    workbook.worksheet.assert_called_once_with("Summary FY2026-27")

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

@patch("utils.sheets._get_budget_teams_from_portal_registry")
@patch("utils.sheets.get_spreadsheet")
def test_get_teams_can_skip_registry_for_fast_budget_views(mock_ss, mock_registry):
    from utils.sheets import get_teams
    mock_ws = MagicMock()
    mock_ws.get_all_records.return_value = [
        {"Team Name": "Diabetes", "Allocation (USD)": 55000, "Active": "Y"}
    ]
    mock_ss.return_value.worksheet.return_value = mock_ws

    df = get_teams("FY2026-27", include_registry=False)

    assert df.iloc[0]["Team Name"] == "Diabetes"
    assert df.iloc[0]["Allocation (USD)"] == 55000
    mock_registry.assert_not_called()

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

@patch("utils.sheets.get_exchange_rate", return_value=3.6725)
@patch("utils.sheets.get_spreadsheet")
def test_set_budget_allocation_writes_to_selected_fiscal_year(mock_ss, _rate):
    from utils.sheets import set_budget_allocation
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        ["Category", "Budgeted (AED)", "Budgeted (USD)", "Budgeted (AED equiv)"],
        ["Equipment", "500000", "0", "500000"],
    ]
    mock_ss.return_value.worksheet.return_value = mock_ws

    set_budget_allocation("Equipment", 0, 25000, "FY2026-27")

    mock_ss.assert_any_call("FY2026-27", create_if_missing=False)
    mock_ws.update.assert_called_once_with(
        "B2:I2",
        [[0, 25000, 91812.5, 0.0, 0.0, 0.0, 91812.5, 0.0]],
        value_input_option="USER_ENTERED",
    )

@patch("utils.sheets.get_exchange_rate", return_value=3.6725)
@patch("utils.sheets.get_spreadsheet")
def test_set_budget_allocations_usd_batches_selected_fiscal_year(mock_ss, _rate):
    from utils.sheets import set_budget_allocations_usd
    mock_ws = MagicMock()
    mock_ws.get_all_values.return_value = [
        ["Category", "Budgeted (AED)", "Budgeted (USD)", "Budgeted (AED equiv)"],
        ["Equipment", "500000", "0", "500000"],
        ["Consumables", "0", "0", "0"],
    ]
    mock_ss.return_value.worksheet.return_value = mock_ws

    set_budget_allocations_usd({"Equipment": 25000, "Consumables": 109500}, "FY2026-27")

    mock_ss.assert_any_call("FY2026-27", create_if_missing=False)
    mock_ws.batch_update.assert_called_once()
    updates = mock_ws.batch_update.call_args.args[0]
    assert {"range": "B2:I2", "values": [[0, 25000.0, 91812.5, 0.0, 0.0, 0.0, 91812.5, 0.0]]} in updates
    assert {"range": "B3:I3", "values": [[0, 109500.0, 402138.75, 0.0, 0.0, 0.0, 402138.75, 0.0]]} in updates

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
