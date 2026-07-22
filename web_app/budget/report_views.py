from collections import defaultdict
from decimal import Decimal

from django.shortcuts import render

from budget.access import lab_access
from budget.services.calculations import CATEGORIES, money
from budget.views import _scoped_totals, _scoped_transactions, _selected_fiscal_year


@lab_access("member")
def reports(request):
    years, fiscal_year = _selected_fiscal_year(request)
    if fiscal_year is None:
        return render(request, "budget/reports.html", {"years": years, "fiscal_year": None})
    rows = _scoped_transactions(request.lab_member, fiscal_year).exclude(status="Cancelled")
    totals = _scoped_totals(request.lab_member, fiscal_year)
    category_rows = [
        {"name": category, **totals["categories"][category]}
        for category in CATEGORIES
    ]
    team_rows = [
        {"name": name, **values}
        for name, values in sorted(totals["teams"].items())
        if request.lab_member.highest_role in {"pi", "budget_manager"}
        or name in request.lab_member.team_names
    ]
    monthly = defaultdict(lambda: defaultdict(Decimal))
    for row in rows.exclude(date=None):
        monthly[row.date.strftime("%Y-%m")][row.category or "Other"] += row.amount_usd_equiv
    monthly_rows = []
    for month, values in sorted(monthly.items()):
        monthly_rows.append(
            {
                "month": month,
                "total": money(sum(values.values(), Decimal("0"))),
                "categories": [
                    {"name": name, "amount": money(amount)}
                    for name, amount in sorted(values.items())
                ],
            }
        )
    return render(
        request,
        "budget/reports.html",
        {
            "years": years,
            "fiscal_year": fiscal_year,
            "category_rows": category_rows,
            "team_rows": team_rows,
            "monthly_rows": monthly_rows,
            "totals": totals,
        },
    )
