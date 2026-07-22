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
    assert Team.objects.get(fiscal_year=fiscal_year, name="Diabetes").allocation_usd == Decimal("6000.00")
    assert LabMember.objects.get(email="mb9386@nyu.edu").highest_role == "lead"


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
