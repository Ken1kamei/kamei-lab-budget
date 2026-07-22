from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


CATEGORIES = [
    "Equipment",
    "Consumables",
    "Personnel",
    "Travel",
    "Publications",
    "Memberships",
    "Other",
]
SUPPORTED_CURRENCIES = {"USD", "AED", "EUR", "JPY", "GBP"}
DEFAULT_AED_PER_USD = Decimal("3.6725")
DEFAULT_RATES_TO_USD = {
    "USD": Decimal("1"),
    "AED": Decimal("1") / DEFAULT_AED_PER_USD,
    "EUR": Decimal("1.08"),
    "JPY": Decimal("0.0064"),
    "GBP": Decimal("1.27"),
}


def decimal_value(value, default="0") -> Decimal:
    if isinstance(value, Decimal):
        return value
    text = str(value if value is not None else default).strip().replace(",", "")
    if not text:
        text = default
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return Decimal(default)


def money(value) -> Decimal:
    return decimal_value(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def fiscal_year_for_date(value) -> str:
    if isinstance(value, datetime):
        parsed = value.date()
    elif isinstance(value, date):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value)).date()
    start_year = parsed.year if parsed.month >= 9 else parsed.year - 1
    return f"FY{start_year}-{str(start_year + 1)[2:]}"


def canonical_status(value) -> str:
    return "Cancelled" if str(value or "").strip() == "Cancelled" else "Allocated"


def split_emails(value) -> list[str]:
    return sorted(
        {
            item.strip().lower()
            for item in str(value or "").replace(";", ",").split(",")
            if item.strip()
        }
    )


def transaction_usd_equivalent(record: dict, rates=None) -> Decimal:
    rates = {**DEFAULT_RATES_TO_USD, **(rates or {})}
    explicit = decimal_value(record.get("Amount (USD equiv)"))
    currency = str(record.get("Currency") or "").strip().upper()
    amount = decimal_value(record.get("Amount"))
    legacy_aed = decimal_value(record.get("Amount (AED)"))
    legacy_usd = decimal_value(record.get("Amount (USD)"))
    if currency not in SUPPORTED_CURRENCIES:
        currency = "AED" if legacy_aed else "USD"
    if amount == 0:
        amount = legacy_usd if legacy_usd else legacy_aed
    derived = money(amount * decimal_value(rates.get(currency), str(DEFAULT_RATES_TO_USD[currency])))
    return money(explicit if explicit or derived == 0 else derived)


def summary_budget_usd(record: dict, aed_per_usd=DEFAULT_AED_PER_USD) -> Decimal:
    if "Budgeted (USD equiv)" in record:
        return money(record.get("Budgeted (USD equiv)"))
    usd = decimal_value(record.get("Budgeted (USD)"))
    aed = decimal_value(record.get("Budgeted (AED)"))
    aed_equiv = decimal_value(record.get("Budgeted (AED equiv)"))
    if usd and not aed:
        return money(usd)
    if aed_equiv:
        return money(aed_equiv / decimal_value(aed_per_usd, str(DEFAULT_AED_PER_USD)))
    return money(usd + (aed / decimal_value(aed_per_usd, str(DEFAULT_AED_PER_USD))))


def snapshot_totals(snapshot: dict) -> dict:
    rates = {code: decimal_value(value) for code, value in snapshot.get("exchange_rates", {}).items()}
    aed_per_usd = decimal_value(snapshot.get("aed_per_usd"), str(DEFAULT_AED_PER_USD))
    categories = {
        category: {"budget": Decimal("0.00"), "allocated": Decimal("0.00"), "available": Decimal("0.00")}
        for category in CATEGORIES
    }
    for row in snapshot.get("summary", []):
        category = str(row.get("Category", "")).strip()
        if category in categories:
            categories[category]["budget"] = summary_budget_usd(row, aed_per_usd)
    active_count = 0
    for row in snapshot.get("transactions", []):
        if canonical_status(row.get("Status")) == "Cancelled":
            continue
        active_count += 1
        category = str(row.get("Category", "")).strip()
        if category in categories:
            categories[category]["allocated"] += transaction_usd_equivalent(row, rates)
    for values in categories.values():
        values["budget"] = money(values["budget"])
        values["allocated"] = money(values["allocated"])
        values["available"] = money(values["budget"] - values["allocated"])
    teams = {}
    for row in snapshot.get("teams", []):
        if str(row.get("Active", "Y")).strip().upper() not in {"Y", "YES", "TRUE", "1"}:
            continue
        name = str(row.get("Team Name", "")).strip()
        if not name:
            continue
        if str(row.get("Allocation (USD)", "")).strip() != "":
            allocation = decimal_value(row.get("Allocation (USD)"))
        else:
            allocation = decimal_value(row.get("Allocation (AED)")) / DEFAULT_AED_PER_USD
        teams[name] = {"budget": money(allocation), "allocated": Decimal("0.00"), "available": Decimal("0.00")}
    for row in snapshot.get("transactions", []):
        if canonical_status(row.get("Status")) == "Cancelled":
            continue
        team_name = str(row.get("Team", "")).strip()
        if team_name in teams:
            teams[team_name]["allocated"] += transaction_usd_equivalent(row, rates)
    for values in teams.values():
        values["allocated"] = money(values["allocated"])
        values["available"] = money(values["budget"] - values["allocated"])
    total_budget = money(sum((v["budget"] for v in categories.values()), Decimal("0")))
    total_allocated = money(sum((v["allocated"] for v in categories.values()), Decimal("0")))
    return {
        "total_budget": total_budget,
        "total_allocated": total_allocated,
        "available": money(total_budget - total_allocated),
        "transaction_count": active_count,
        "categories": categories,
        "teams": teams,
    }


def compare_totals(source: dict, mirror: dict, tolerance=Decimal("0.01")) -> dict:
    differences = {}
    for key in ("total_budget", "total_allocated", "available"):
        source_value = money(source.get(key, 0))
        mirror_value = money(mirror.get(key, 0))
        delta = money(mirror_value - source_value)
        if abs(delta) > tolerance:
            differences[key] = {
                "source": str(source_value),
                "mirror": str(mirror_value),
                "delta": str(delta),
            }
    source_count = int(source.get("transaction_count", 0))
    mirror_count = int(mirror.get("transaction_count", 0))
    if source_count != mirror_count:
        differences["transaction_count"] = {
            "source": source_count,
            "mirror": mirror_count,
            "delta": mirror_count - source_count,
        }
    for group in ("categories", "teams"):
        source_rows = source.get(group, {})
        mirror_rows = mirror.get(group, {})
        for name in sorted(set(source_rows) | set(mirror_rows)):
            for metric in ("budget", "allocated", "available"):
                source_value = money(source_rows.get(name, {}).get(metric, 0))
                mirror_value = money(mirror_rows.get(name, {}).get(metric, 0))
                delta = money(mirror_value - source_value)
                if abs(delta) > tolerance:
                    differences[f"{group}.{name}.{metric}"] = {
                        "source": str(source_value),
                        "mirror": str(mirror_value),
                        "delta": str(delta),
                    }
    return {"matches": not differences, "differences": differences}
