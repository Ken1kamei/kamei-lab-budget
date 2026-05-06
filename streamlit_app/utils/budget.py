import pandas as pd
from typing import Any

CATEGORIES = ["Equipment", "Personnel", "Travel", "Other"]
LIFECYCLE_STATUSES = [
    "Requested",
    "Approved",
    "Ordered",
    "Pending Review",
    "Delivered",
    "Paid",
    "Cancelled",
]
COMMITTED_STATUSES = {
    "Requested",
    "Approved",
    "Ordered",
    "Pending Review",
    "Delivered",
    "Paid",
}
PAID_STATUSES = {"Paid"}


def fiscal_year_for_date(value: str | pd.Timestamp) -> str:
    """Return the NYUAD fiscal year label for a date. FY starts September 1."""
    dt = pd.to_datetime(value, errors="raise")
    year = int(dt.year)
    if int(dt.month) >= 9:
        return f"FY{year}-{str(year + 1)[2:]}"
    return f"FY{year - 1}-{str(year)[2:]}"


def _active_transactions(txns: pd.DataFrame) -> pd.DataFrame:
    if txns.empty or "Status" not in txns.columns:
        return txns
    return txns[txns["Status"] != "Cancelled"]


def _sum_equiv(txns: pd.DataFrame) -> float:
    if txns.empty or "Amount (AED equiv)" not in txns.columns:
        return 0.0
    return float(pd.to_numeric(txns["Amount (AED equiv)"], errors="coerce").fillna(0).sum())


def split_commitments(txns: pd.DataFrame) -> dict[str, float]:
    """Split non-cancelled transactions into committed and paid AED-equivalent totals."""
    active = _active_transactions(txns)
    if active.empty or "Status" not in active.columns:
        return {"committed": _sum_equiv(active), "paid": 0.0}
    committed = active[active["Status"].isin(COMMITTED_STATUSES)]
    paid = active[active["Status"].isin(PAID_STATUSES)]
    return {
        "committed": _sum_equiv(committed),
        "paid": _sum_equiv(paid),
    }


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
    active = _active_transactions(txns)
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
        spent_equiv = _sum_equiv(cat_txns)
        split = split_commitments(cat_txns)

        remaining = budget_equiv - split["committed"]
        pct_used  = (split["committed"] / budget_equiv) if budget_equiv > 0 else 0.0

        result[cat] = {
            "budget_aed":   budget_aed,
            "budget_usd":   budget_usd,
            "budget_equiv": budget_equiv,
            "spent_aed":    spent_aed,
            "spent_usd":    spent_usd,
            "spent_equiv":  spent_equiv,
            "committed_equiv": split["committed"],
            "paid_equiv": split["paid"],
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
    active = _active_transactions(txns)
    result = {}
    active_teams = teams_df[teams_df["Active"] == "Y"] \
        if "Active" in teams_df.columns else teams_df

    for _, team_row in active_teams.iterrows():
        name      = team_row["Team Name"]
        allocated = float(team_row.get("Allocation (AED)", 0))
        team_txns = active[active["Team"] == name] if "Team" in active.columns else pd.DataFrame()
        split = split_commitments(team_txns)
        spent = split["committed"]
        paid = split["paid"]
        remaining = allocated - spent
        pct_used  = (spent / allocated) if allocated > 0 else 0.0
        result[name] = {
            "allocated": allocated,
            "spent":     spent,
            "committed": spent,
            "paid": paid,
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
    total_spent  = sum(v["committed_equiv"]  for v in cat_summary.values())
    total_paid = sum(v["paid_equiv"] for v in cat_summary.values())
    return {
        "total_budget": total_budget,
        "total_spent":  total_spent,
        "total_committed": total_spent,
        "total_paid": total_paid,
        "remaining":    total_budget - total_spent,
        "pct_used":     (total_spent / total_budget) if total_budget > 0 else 0.0,
    }


def monthly_spending(txns: pd.DataFrame) -> pd.DataFrame:
    """Returns DataFrame with columns: month, category, amount_equiv."""
    active = _active_transactions(txns)
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
