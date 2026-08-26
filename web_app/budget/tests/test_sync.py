from decimal import Decimal

import pytest

from budget.models import CategoryAllocation, FiscalYear, LabMember, Team, Transaction
from budget.services.sync import sync_fiscal_year


@pytest.mark.django_db
def test_sync_fiscal_year_replaces_read_only_mirror_atomically():
    snapshot = {
        "fiscal_year": "FY2026-27",
        "spreadsheet_id": "sheet-2026",
        "exchange_rates": {"USD": "1", "AED": str(1 / 3.6725)},
        "summary": [{"Category": "Consumables", "Budgeted (USD equiv)": "10000"}],
        "teams": [
            {
                "Team Name": "Diabetes",
                "Allocation (USD)": "6000",
                "Budget Manager Emails": "kk4801@nyu.edu",
                "Budget Manager Names": "Ken Kamei",
                "Lead Emails": "mb9386@nyu.edu",
                "Lead Names": "Maab",
                "Member Emails": "si2381@nyu.edu",
                "Member Names": "Satoshi",
                "Active": "Y",
            }
        ],
        "transactions": [
            {
                "Transaction ID": "TXN-20260901-0001",
                "Date": "2026-09-01",
                "Fiscal Year": "FY2026-27",
                "Category": "Consumables",
                "Vendor / Payee": "Bio-Rad",
                "Currency": "USD",
                "Amount": "125.50",
                "Amount (USD equiv)": "125.50",
                "Status": "Allocated",
                "Team": "Diabetes",
            }
        ],
    }

    run = sync_fiscal_year(snapshot, actor="test")

    fiscal_year = FiscalYear.objects.get(label="FY2026-27")
    assert run.status == "matched"
    assert fiscal_year.spreadsheet_id == "sheet-2026"
    assert CategoryAllocation.objects.get(fiscal_year=fiscal_year, category="Consumables").budget_usd == Decimal("10000.00")
    assert Transaction.objects.get(fiscal_year=fiscal_year).amount_usd_equiv == Decimal("125.50")
    assert Transaction.objects.get(fiscal_year=fiscal_year).date.isoformat() == "2026-09-01"
    assert fiscal_year.exchange_rates["USD"] == "1"
    assert Team.objects.get(fiscal_year=fiscal_year, name="Diabetes").allocation_usd == Decimal("6000.00")
    assert LabMember.objects.get(email="mb9386@nyu.edu").highest_role == "lead"
    assert LabMember.objects.get(email="mb9386@nyu.edu").team_roles == {
        "FY2026-27": {"Diabetes": "lead"}
    }


@pytest.mark.django_db
def test_sync_failure_keeps_previous_mirror_data():
    fiscal_year = FiscalYear.objects.create(label="FY2026-27", spreadsheet_id="existing")
    Transaction.objects.create(
        fiscal_year=fiscal_year,
        transaction_id="TXN-KEEP",
        category="Consumables",
        currency="USD",
        amount=Decimal("10"),
        amount_usd_equiv=Decimal("10"),
        status="Allocated",
    )

    with pytest.raises(ValueError):
        sync_fiscal_year({"fiscal_year": "FY2026-27", "transactions": "invalid"}, actor="test")

    assert Transaction.objects.filter(transaction_id="TXN-KEEP").exists()


@pytest.mark.django_db
def test_registry_sync_deactivates_removed_member_access():
    stale = LabMember.objects.create(
        email="former@nyu.edu",
        highest_role="member",
        team_names=["Diabetes"],
        active=True,
        last_synced_at="2026-01-01T00:00:00Z",
    )
    snapshot = {
        "fiscal_year": "FY2026-27",
        "spreadsheet_id": "sheet",
        "summary": [],
        "teams": [],
        "transactions": [],
    }

    sync_fiscal_year(snapshot, actor="test")

    stale.refresh_from_db()
    assert stale.active is False


@pytest.mark.django_db
def test_syncing_empty_new_year_does_not_deactivate_member_from_another_year():
    first_year = {
        "fiscal_year": "FY2025-26",
        "spreadsheet_id": "sheet-old",
        "summary": [],
        "teams": [
            {
                "Team Name": "Diabetes",
                "Lead Emails": "lead@nyu.edu",
                "Lead Names": "Lab Lead",
                "Active": "Y",
            }
        ],
        "transactions": [],
    }
    empty_new_year = {
        "fiscal_year": "FY2026-27",
        "spreadsheet_id": "sheet-new",
        "summary": [],
        "teams": [],
        "transactions": [],
    }

    sync_fiscal_year(first_year, actor="test")
    sync_fiscal_year(empty_new_year, actor="test")

    member = LabMember.objects.get(email="lead@nyu.edu")
    assert member.active is True
    assert member.highest_role == "lead"
    assert member.team_names == ["Diabetes"]
    assert member.display_name == "Lab Lead"


@pytest.mark.django_db
def test_legacy_aed_only_transaction_keeps_aed_currency_and_amount():
    snapshot = {
        "fiscal_year": "FY2025-26",
        "spreadsheet_id": "sheet",
        "summary": [],
        "teams": [],
        "transactions": [
            {
                "Transaction ID": "TXN-AED",
                "Date": "2026-02-01",
                "Category": "Consumables",
                "Amount (AED)": "367.25",
                "Status": "Allocated",
            }
        ],
    }

    sync_fiscal_year(snapshot, actor="test")

    row = Transaction.objects.get(transaction_id="TXN-AED")
    assert row.currency == "AED"
    assert row.amount == Decimal("367.25")
