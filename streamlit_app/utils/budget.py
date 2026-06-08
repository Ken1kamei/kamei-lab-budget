import pandas as pd
from decimal import Decimal, ROUND_HALF_UP
from typing import Any
from utils.categories import CATEGORIES

BUDGET_STATUSES = [
    "Allocated",
    "Cancelled",
]
LIFECYCLE_STATUSES = BUDGET_STATUSES
LEGACY_ALLOCATED_STATUSES = {
    "",
    "Allocated",
    "Requested",
    "Approved",
    "Ordered",
    "Pending Review",
    "Delivered",
    "Paid",
}
COMMITTED_STATUSES = LEGACY_ALLOCATED_STATUSES
PAID_STATUSES = set()
DEFAULT_AED_USD_EXCHANGE_RATE = 3.6725
SUPPORTED_CURRENCIES = ["USD", "AED", "EUR", "JPY", "GBP"]
DEFAULT_RATES_TO_USD = {
    "USD": 1.0,
    "AED": 1 / DEFAULT_AED_USD_EXCHANGE_RATE,
    "EUR": 1.08,
    "JPY": 0.0064,
    "GBP": 1.27,
}


def canonical_budget_status(value: str) -> str:
    """Map old order-tracking statuses into the current budget status model."""
    status = str(value or "").strip()
    if status == "Cancelled":
        return "Cancelled"
    if status in LEGACY_ALLOCATED_STATUSES:
        return "Allocated"
    return "Allocated"


def to_aed_equivalent(aed: float, usd: float, exchange_rate: float) -> float:
    """Convert AED plus USD amounts into a single AED-equivalent total."""
    return float(aed or 0) + float(usd or 0) * float(exchange_rate or 0)


def to_usd_equivalent(currency: str, amount: float, rates_to_usd: dict[str, float]) -> float:
    """Convert an amount in a supported currency to USD."""
    code = str(currency or "USD").upper()
    if code not in SUPPORTED_CURRENCIES:
        code = "USD"
    return float(amount or 0) * float(rates_to_usd.get(code, DEFAULT_RATES_TO_USD[code]))


def round_currency(value: float) -> float:
    """Round currency values to cents using half-up accounting rounding."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def normalize_usd_equivalent(txns: pd.DataFrame, rates_to_usd: dict[str, float]) -> pd.DataFrame:
    """Populate Currency, Amount, and Amount (USD equiv), including legacy AED/USD rows."""
    if txns.empty:
        return txns
    df = txns.copy()
    for col in ("Currency", "Amount", "Amount (USD equiv)", "Amount (AED)", "Amount (USD)"):
        if col not in df.columns:
            df[col] = ""

    currency = df["Currency"].astype(str).str.upper().str.strip()
    amount = pd.to_numeric(df["Amount"], errors="coerce")
    usd_equiv = pd.to_numeric(df["Amount (USD equiv)"], errors="coerce")
    legacy_aed = pd.to_numeric(df["Amount (AED)"], errors="coerce").fillna(0.0)
    legacy_usd = pd.to_numeric(df["Amount (USD)"], errors="coerce").fillna(0.0)

    legacy_currency = pd.Series("USD", index=df.index)
    legacy_currency = legacy_currency.mask(legacy_aed != 0, "AED")
    legacy_currency = legacy_currency.mask(legacy_usd != 0, "USD")
    legacy_amount = legacy_usd.mask(legacy_usd == 0, legacy_aed)

    missing_currency = ~currency.isin(SUPPORTED_CURRENCIES)
    df["Currency"] = currency.mask(missing_currency, legacy_currency)
    df["Amount"] = amount.mask(amount.isna() | (amount == 0), legacy_amount).fillna(0.0)

    derived = [
        round_currency(to_usd_equivalent(curr, amt, rates_to_usd))
        for curr, amt in zip(df["Currency"], df["Amount"], strict=False)
    ]
    derived_series = pd.Series(derived, index=df.index)
    needs_repair = usd_equiv.isna() | ((usd_equiv == 0) & (derived_series != 0))
    df["Amount (USD equiv)"] = usd_equiv.mask(needs_repair, derived_series).fillna(0.0)
    return df


def normalize_aed_equivalent(txns: pd.DataFrame, exchange_rate: float) -> pd.DataFrame:
    """Repair missing or zero AED-equivalent values from raw AED/USD amounts."""
    if txns.empty:
        return txns
    df = txns.copy()
    for col in ("Amount (AED)", "Amount (USD)", "Amount (AED equiv)"):
        if col not in df.columns:
            df[col] = 0.0
    aed = pd.to_numeric(df["Amount (AED)"], errors="coerce").fillna(0.0)
    usd = pd.to_numeric(df["Amount (USD)"], errors="coerce").fillna(0.0)
    equiv = pd.to_numeric(df["Amount (AED equiv)"], errors="coerce")
    derived = (aed + usd * float(exchange_rate or 0)).map(round_currency)
    needs_repair = equiv.isna() | ((equiv == 0) & (derived != 0))
    df["Amount (AED equiv)"] = equiv.mask(needs_repair, derived).fillna(0.0)
    return df


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
    if txns.empty:
        return 0.0
    if "Amount (USD equiv)" in txns.columns:
        return float(pd.to_numeric(txns["Amount (USD equiv)"], errors="coerce").fillna(0).sum())
    if "Amount (AED equiv)" in txns.columns:
        return float(
            pd.to_numeric(txns["Amount (AED equiv)"], errors="coerce")
            .fillna(0)
            .sum()
            / DEFAULT_AED_USD_EXCHANGE_RATE
        )
    return 0.0


def split_commitments(txns: pd.DataFrame) -> dict[str, float]:
    """Split non-cancelled transactions into committed and paid USD-equivalent totals."""
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
      budget_equiv, spent_equiv,
      remaining, pct_used
    """
    active = _active_transactions(txns)
    result = {}
    for cat in CATEGORIES:
        # Budget from Summary sheet
        cat_row = summary_df[summary_df["Category"] == cat] if "Category" in summary_df.columns else pd.DataFrame()
        budget_aed = float(cat_row["Budgeted (AED)"].iloc[0]) if not cat_row.empty and "Budgeted (AED)" in cat_row.columns else 0.0
        budget_usd = float(cat_row["Budgeted (USD)"].iloc[0]) if not cat_row.empty and "Budgeted (USD)" in cat_row.columns else 0.0
        if not cat_row.empty and "Budgeted (USD equiv)" in cat_row.columns:
            budget_equiv = float(cat_row["Budgeted (USD equiv)"].iloc[0] or 0)
        elif budget_usd and not budget_aed:
            budget_equiv = budget_usd
        elif not cat_row.empty and "Budgeted (AED equiv)" in cat_row.columns:
            budget_equiv = float(cat_row["Budgeted (AED equiv)"].iloc[0] or 0) / exchange_rate
        else:
            budget_equiv = budget_usd + (budget_aed / exchange_rate if exchange_rate else 0)

        # Actuals from transactions
        cat_txns    = active[active["Category"] == cat] if "Category" in active.columns else pd.DataFrame()
        spent_equiv = _sum_equiv(cat_txns)
        split = split_commitments(cat_txns)

        remaining = budget_equiv - split["committed"]
        pct_used  = (split["committed"] / budget_equiv) if budget_equiv > 0 else 0.0

        result[cat] = {
            "budget_equiv": budget_equiv,
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
        if "Allocation (USD)" in team_row.index and str(team_row.get("Allocation (USD)", "")).strip() != "":
            allocated = float(team_row.get("Allocation (USD)", 0) or 0)
        else:
            allocated = float(team_row.get("Allocation (AED)", 0) or 0) / DEFAULT_AED_USD_EXCHANGE_RATE
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
    """Returns DataFrame with columns: month, category, amount_equiv in USD."""
    active = _active_transactions(txns)
    if active.empty or "Date" not in active.columns:
        return pd.DataFrame(columns=["month", "category", "amount_equiv"])
    df = active.copy()
    df["month"] = pd.to_datetime(df["Date"], errors="coerce").dt.to_period("M").astype(str)
    if "Amount (USD equiv)" not in df.columns:
        df["Amount (USD equiv)"] = pd.to_numeric(
            df.get("Amount (AED equiv)", 0), errors="coerce"
        ).fillna(0) / DEFAULT_AED_USD_EXCHANGE_RATE
    return (
        df.groupby(["month", "Category"])["Amount (USD equiv)"]
        .sum()
        .reset_index()
        .rename(columns={"Category": "category", "Amount (USD equiv)": "amount_equiv"})
    )
