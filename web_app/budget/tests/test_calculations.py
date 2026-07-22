from decimal import Decimal

from budget.services.calculations import (
    compare_totals,
    fiscal_year_for_date,
    snapshot_totals,
)


def test_fiscal_year_starts_on_september_first():
    assert fiscal_year_for_date("2026-08-31") == "FY2025-26"
    assert fiscal_year_for_date("2026-09-01") == "FY2026-27"


def test_snapshot_totals_match_streamlit_status_and_currency_semantics():
    snapshot = {
        "exchange_rates": {"USD": "1", "AED": str(1 / 3.6725), "EUR": "1.08"},
        "summary": [
            {"Category": "Consumables", "Budgeted (USD equiv)": "10000"},
            {"Category": "Travel", "Budgeted (USD)": "5000"},
        ],
        "transactions": [
            {
                "Transaction ID": "TXN-1",
                "Category": "Consumables",
                "Status": "Allocated",
                "Currency": "USD",
                "Amount": "2500",
                "Amount (USD equiv)": "2500",
            },
            {
                "Transaction ID": "TXN-2",
                "Category": "Consumables",
                "Status": "Paid",
                "Currency": "AED",
                "Amount": "3672.50",
                "Amount (USD equiv)": "",
            },
            {
                "Transaction ID": "TXN-3",
                "Category": "Travel",
                "Status": "Cancelled",
                "Currency": "EUR",
                "Amount": "1000",
                "Amount (USD equiv)": "1080",
            },
        ],
    }

    totals = snapshot_totals(snapshot)

    assert totals["total_budget"] == Decimal("15000.00")
    assert totals["total_allocated"] == Decimal("3500.00")
    assert totals["available"] == Decimal("11500.00")
    assert totals["transaction_count"] == 2
    assert totals["categories"]["Consumables"]["allocated"] == Decimal("3500.00")


def test_compare_totals_uses_cent_tolerance_and_reports_material_differences():
    source = {
        "total_budget": Decimal("10000.00"),
        "total_allocated": Decimal("1200.00"),
        "available": Decimal("8800.00"),
        "transaction_count": 3,
    }
    mirror = {
        "total_budget": Decimal("10000.00"),
        "total_allocated": Decimal("1200.01"),
        "available": Decimal("8799.99"),
        "transaction_count": 3,
    }
    assert compare_totals(source, mirror)["matches"] is True

    mirror["total_allocated"] = Decimal("1200.02")
    result = compare_totals(source, mirror)
    assert result["matches"] is False
    assert "total_allocated" in result["differences"]


def test_zero_team_usd_allocation_is_not_replaced_by_aed_value():
    totals = snapshot_totals(
        {
            "teams": [
                {
                    "Team Name": "Diabetes",
                    "Allocation (USD)": "0",
                    "Allocation (AED)": "36725",
                    "Active": "Y",
                }
            ]
        }
    )
    assert totals["teams"]["Diabetes"]["budget"] == Decimal("0.00")


def test_summary_aed_budget_uses_selected_sheet_exchange_rate():
    totals = snapshot_totals(
        {
            "aed_per_usd": "4",
            "summary": [{"Category": "Travel", "Budgeted (AED)": "4000"}],
        }
    )
    assert totals["categories"]["Travel"]["budget"] == Decimal("1000.00")
