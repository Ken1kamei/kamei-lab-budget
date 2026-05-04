import pandas as pd
from typing import Any

CATEGORIES = ["Equipment", "Personnel", "Travel", "Other"]


def get_category_summary(
    txns: pd.DataFrame,
    summary_df: pd.DataFrame,
    exchange_rate: float,
) -> dict[str, dict[str, Any]]:
    """
    Returns per-category dict with keys:
      budget_aed, budget_usd, budget_equiv,
      spent_aed, spent_usd, spent_equiv,
      remaining, pct_used
    """
    active = txns[txns["Status"] != "Cancelled"] if "Status" in txns.columns else txns
    result = {}
    for cat in CATEGORIES:
        # Budget from Summary sheet
        cat_row = summary_df[summary_df["Category"] == cat] if "Category" in summary_df.columns else pd.DataFrame()
        budget_aed   = float(cat_row["Budgeted (AED)"].iloc[0])   if not cat_row.empty else 0.0
        budget_usd   = float(cat_row["Budgeted (USD)"].iloc[0])   if not cat_row.empty else 0.0
        budget_equiv = float(cat_row["Budgeted (AED equiv)"].iloc[0]) if not cat_row.empty else budget_aed + budget_usd * exchange_rate

        # Actuals from transactions
        cat_txns    = active[active["Category"] == cat] if "Category" in active.columns else pd.DataFrame()
        spent_aed   = float(cat_txns["Amount (AED)"].sum())        if not cat_txns.empty else 0.0
        spent_usd   = float(cat_txns["Amount (USD)"].sum())        if not cat_txns.empty else 0.0
        spent_equiv = float(cat_txns["Amount (AED equiv)"].sum())  if not cat_txns.empty else 0.0

        remaining = budget_equiv - spent_equiv
        pct_used  = (spent_equiv / budget_equiv) if budget_equiv > 0 else 0.0

        result[cat] = {
            "budget_aed":   budget_aed,
            "budget_usd":   budget_usd,
            "budget_equiv": budget_equiv,
            "spent_aed":    spent_aed,
            "spent_usd":    spent_usd,
            "spent_equiv":  spent_equiv,
            "remaining":    remaining,
            "pct_used":     pct_used,
        }
    return result


def get_team_summary(
    txns: pd.DataFrame,
    teams_df: pd.DataFrame,
) -> dict[str, dict[str, Any]]:
    """
    Returns per-team dict with keys: allocated, spent, remaining, pct_used
    """
    active = txns[txns["Status"] != "Cancelled"] if "Status" in txns.columns else txns
    result = {}
    active_teams = teams_df[teams_df["Active"] == "Y"] \
        if "Active" in teams_df.columns else teams_df

    for _, team_row in active_teams.iterrows():
        name      = team_row["Team Name"]
        allocated = float(team_row.get("Allocation (AED)", 0))
        team_txns = active[active["Team"] == name] if "Team" in active.columns else pd.DataFrame()
        spent     = float(team_txns["Amount (AED equiv)"].sum()) if not team_txns.empty else 0.0
        remaining = allocated - spent
        pct_used  = (spent / allocated) if allocated > 0 else 0.0
        result[name] = {
            "allocated": allocated,
            "spent":     spent,
            "remaining": remaining,
            "pct_used":  pct_used,
        }
    return result


def get_lab_totals(
    txns: pd.DataFrame,
    summary_df: pd.DataFrame,
    exchange_rate: float,
) -> dict[str, float]:
    """Overall lab totals across all categories."""
    cat_summary = get_category_summary(txns, summary_df, exchange_rate)
    total_budget = sum(v["budget_equiv"] for v in cat_summary.values())
    total_spent  = sum(v["spent_equiv"]  for v in cat_summary.values())
    return {
        "total_budget": total_budget,
        "total_spent":  total_spent,
        "remaining":    total_budget - total_spent,
        "pct_used":     (total_spent / total_budget) if total_budget > 0 else 0.0,
    }


def monthly_spending(txns: pd.DataFrame) -> pd.DataFrame:
    """Returns DataFrame with columns: month, category, amount_equiv."""
    active = txns[txns["Status"] != "Cancelled"] if "Status" in txns.columns else txns
    if active.empty or "Date" not in active.columns:
        return pd.DataFrame(columns=["month", "category", "amount_equiv"])
    df = active.copy()
    df["month"] = pd.to_datetime(df["Date"], errors="coerce").dt.to_period("M").astype(str)
    return (
        df.groupby(["month", "Category"])["Amount (AED equiv)"]
        .sum()
        .reset_index()
        .rename(columns={"Category": "category", "Amount (AED equiv)": "amount_equiv"})
    )
