import sys
from decimal import Decimal
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from budget.models import FiscalYear
from budget.services.calculations import compare_totals, money
from budget.services.sheets import SheetsGateway, SheetsSourceError
from budget.services.sync import database_totals


class Command(BaseCommand):
    help = "Run the existing Streamlit calculation functions and compare them with Django."

    def add_arguments(self, parser):
        parser.add_argument("--fy", action="append", dest="years")

    def handle(self, *args, **options):
        try:
            import pandas as pd
        except ImportError as error:
            raise CommandError("Install requirements-dev.txt to run Streamlit parity.") from error

        streamlit_root = Path(__file__).resolve().parents[4] / "streamlit_app"
        sys.path.insert(0, str(streamlit_root))
        from utils.budget import (  # noqa: PLC0415
            DEFAULT_RATES_TO_USD,
            get_category_summary,
            get_lab_totals,
            get_team_summary,
            monthly_spending,
            normalize_usd_equivalent,
        )

        gateway = SheetsGateway()
        years = options["years"] or gateway.fiscal_year_options()
        failures = []
        for label in years:
            try:
                snapshot = gateway.read_fiscal_year(label)
                fiscal_year = FiscalYear.objects.get(label=label)
            except (SheetsSourceError, FiscalYear.DoesNotExist) as error:
                failures.append(f"{label}: {error}")
                continue

            transactions = pd.DataFrame(snapshot["transactions"])
            summary = pd.DataFrame(snapshot["summary"])
            teams = pd.DataFrame(snapshot["teams"])
            transactions = normalize_usd_equivalent(transactions, DEFAULT_RATES_TO_USD)
            category_summary = get_category_summary(
                transactions, summary, float(snapshot.get("aed_per_usd", "3.6725"))
            )
            lab = get_lab_totals(
                transactions, summary, float(snapshot.get("aed_per_usd", "3.6725"))
            )
            team_summary = get_team_summary(transactions, teams)
            active_count = (
                int((transactions["Status"].astype(str) != "Cancelled").sum())
                if "Status" in transactions.columns
                else len(transactions)
            )
            legacy = {
                "total_budget": money(lab["total_budget"]),
                "total_allocated": money(lab["total_committed"]),
                "available": money(lab["remaining"]),
                "transaction_count": active_count,
                "categories": {
                    category: {
                        "budget": money(values["budget_equiv"]),
                        "allocated": money(values["committed_equiv"]),
                        "available": money(values["remaining"]),
                    }
                    for category, values in category_summary.items()
                },
                "teams": {
                    team: {
                        "budget": money(values["allocated"]),
                        "allocated": money(values["committed"]),
                        "available": money(values["remaining"]),
                    }
                    for team, values in team_summary.items()
                },
            }
            mirror = database_totals(fiscal_year)
            comparison = compare_totals(legacy, mirror)

            streamlit_monthly = {
                (str(row["month"]), str(row["category"])): money(row["amount_equiv"])
                for _, row in monthly_spending(transactions).iterrows()
            }
            django_monthly = {}
            for txn in fiscal_year.transactions.exclude(status="Cancelled").exclude(date=None):
                key = (txn.date.strftime("%Y-%m"), txn.category)
                django_monthly[key] = money(
                    django_monthly.get(key, Decimal("0")) + txn.amount_usd_equiv
                )
            monthly_differences = {
                str(key): {
                    "streamlit": str(streamlit_monthly.get(key, Decimal("0.00"))),
                    "django": str(django_monthly.get(key, Decimal("0.00"))),
                }
                for key in set(streamlit_monthly) | set(django_monthly)
                if streamlit_monthly.get(key, Decimal("0.00"))
                != django_monthly.get(key, Decimal("0.00"))
            }
            if comparison["matches"] and not monthly_differences:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"{label}: exact Streamlit/Django match; rows={active_count}; "
                        f"budget={legacy['total_budget']}; allocated={legacy['total_allocated']}; "
                        f"available={legacy['available']}"
                    )
                )
            else:
                failures.append(
                    f"{label}: totals={comparison['differences']}; monthly={monthly_differences}"
                )
        if failures:
            raise CommandError(" | ".join(failures))
