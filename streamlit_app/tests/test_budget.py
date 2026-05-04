import pandas as pd
import pytest
from utils.budget import (
    get_category_summary,
    get_team_summary,
    get_lab_totals,
)

CATEGORIES = ["Equipment", "Personnel", "Travel", "Other"]

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
        "Category":            ["Equipment", "Personnel", "Travel", "Other"],
        "Budgeted (AED)":      [500000.0, 300000.0, 50000.0, 30000.0],
        "Budgeted (USD)":      [0.0, 0.0, 10000.0, 5000.0],
        "Budgeted (AED equiv)":[500000.0, 300000.0, 86725.0, 48362.5],
    })

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
    assert result["total_budget"] == pytest.approx(935087.5, abs=1)
    assert result["total_spent"] == 1500.0  # 1000 + 500 (cancelled excluded)
    assert result["remaining"] == pytest.approx(935087.5 - 1500.0, abs=1)
