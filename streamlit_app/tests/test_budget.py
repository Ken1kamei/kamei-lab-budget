import pandas as pd
import pytest
from utils.budget import (
    CATEGORIES,
    get_category_summary,
    get_team_summary,
    get_lab_totals,
    fiscal_year_for_date,
    split_commitments,
)

def make_txns(**kwargs):
    """Build a minimal transactions DataFrame."""
    defaults = {
        "Transaction ID": ["TXN-001", "TXN-002", "TXN-003"],
        "Category":       ["Equipment", "Travel", "Equipment"],
        "Amount (AED)":   [1000.0, 500.0, 200.0],
        "Amount (USD)":   [0.0, 0.0, 0.0],
        "Amount (AED equiv)": [1000.0, 500.0, 200.0],
        "Status":         ["Paid", "Paid", "Cancelled"],
        "Team":           ["Synbio", "Imaging", "Synbio"],
        "Fiscal Year":    ["FY2025-26", "FY2025-26", "FY2025-26"],
    }
    defaults.update(kwargs)
    return pd.DataFrame(defaults)

def make_summary_df():
    return pd.DataFrame({
        "Category":            CATEGORIES,
        "Budgeted (AED)":      [500000.0, 50000.0, 300000.0, 50000.0, 25000.0, 10000.0, 30000.0],
        "Budgeted (USD)":      [0.0, 0.0, 0.0, 10000.0, 5000.0, 1000.0, 5000.0],
        "Budgeted (AED equiv)":[500000.0, 50000.0, 300000.0, 86725.0, 43362.5, 13672.5, 48362.5],
    })

def test_categories_include_requested_lab_categories():
    assert CATEGORIES == [
        "Equipment",
        "Consumables",
        "Personnel",
        "Travel",
        "Publications",
        "Memberships",
        "Other",
    ]

def test_category_summary_excludes_cancelled():
    txns = make_txns()
    summary_df = make_summary_df()
    result = get_category_summary(txns, summary_df, 3.6725)
    # Equipment: TXN-001 paid (1000), TXN-003 cancelled (excluded)
    assert result["Equipment"]["spent_equiv"] == 1000.0
    assert result["Equipment"]["budget_equiv"] == 500000.0

def test_category_summary_pct_used():
    txns = make_txns()
    summary_df = make_summary_df()
    result = get_category_summary(txns, summary_df, 3.6725)
    pct = result["Equipment"]["pct_used"]
    assert 0.001 < pct < 0.01  # 1000/500000 = 0.2%

def test_category_summary_tracks_new_categories():
    txns = make_txns(
        **{
            "Transaction ID": ["TXN-001", "TXN-002", "TXN-003"],
            "Category": ["Consumables", "Publications", "Memberships"],
            "Amount (AED)": [1250.0, 0.0, 400.0],
            "Amount (USD)": [0.0, 1000.0, 0.0],
            "Amount (AED equiv)": [1250.0, 3672.5, 400.0],
            "Status": ["Requested", "Paid", "Paid"],
            "Team": ["Synbio", "Synbio", "Synbio"],
            "Fiscal Year": ["FY2026-27", "FY2026-27", "FY2026-27"],
        }
    )
    result = get_category_summary(txns, make_summary_df(), 3.6725)
    assert result["Consumables"]["committed_equiv"] == 1250.0
    assert result["Publications"]["paid_equiv"] == 3672.5
    assert result["Memberships"]["remaining"] == 13272.5

def test_get_team_summary():
    txns = make_txns()
    teams_df = pd.DataFrame({
        "Team Name": ["Synbio", "Imaging"],
        "Allocation (AED)": [400000.0, 280000.0],
        "Active": ["Y", "Y"],
    })
    result = get_team_summary(txns, teams_df)
    # Synbio: TXN-001 (1000), TXN-003 cancelled → spent = 1000
    assert result["Synbio"]["spent"] == 1000.0
    assert result["Synbio"]["allocated"] == 400000.0
    assert result["Imaging"]["spent"] == 500.0

def test_get_lab_totals():
    txns = make_txns()
    summary_df = make_summary_df()
    result = get_lab_totals(txns, summary_df, 3.6725)
    assert result["total_budget"] == pytest.approx(1042122.5, abs=1)
    assert result["total_spent"] == 1500.0  # 1000 + 500 (cancelled excluded)
    assert result["remaining"] == pytest.approx(1042122.5 - 1500.0, abs=1)

def test_fiscal_year_starts_on_september_first():
    assert fiscal_year_for_date("2026-08-31") == "FY2025-26"
    assert fiscal_year_for_date("2026-09-01") == "FY2026-27"

def test_split_commitments_counts_requested_as_committed_and_paid_separately():
    txns = make_txns(
        **{
            "Transaction ID": ["TXN-001", "TXN-002", "TXN-003", "TXN-004"],
            "Category": ["Equipment", "Travel", "Other", "Personnel"],
            "Amount (AED)": [100.0, 200.0, 300.0, 400.0],
            "Amount (USD)": [0.0, 0.0, 0.0, 0.0],
            "Status": ["Requested", "Approved", "Paid", "Cancelled"],
            "Amount (AED equiv)": [100.0, 200.0, 300.0, 400.0],
            "Team": ["Synbio", "Synbio", "Synbio", "Synbio"],
            "Fiscal Year": ["FY2026-27", "FY2026-27", "FY2026-27", "FY2026-27"],
        }
    )
    result = split_commitments(txns)
    assert result["committed"] == 600.0
    assert result["paid"] == 300.0

def test_team_summary_exposes_committed_paid_and_remaining():
    txns = make_txns(
        **{
            "Transaction ID": ["TXN-001", "TXN-002", "TXN-003"],
            "Team": ["Synbio", "Synbio", "Synbio"],
            "Status": ["Requested", "Paid", "Cancelled"],
            "Amount (AED equiv)": [100.0, 300.0, 999.0],
        }
    )
    teams_df = pd.DataFrame({
        "Team Name": ["Synbio"],
        "Allocation (AED)": [1000.0],
        "Active": ["Y"],
    })
    result = get_team_summary(txns, teams_df)
    assert result["Synbio"]["committed"] == 400.0
    assert result["Synbio"]["paid"] == 300.0
    assert result["Synbio"]["remaining"] == 600.0
    assert result["Synbio"]["pct_used"] == 0.4
