from django.core.management.base import BaseCommand, CommandError

from budget.models import FiscalYear
from budget.services.calculations import compare_totals


class Command(BaseCommand):
    help = "Fail unless every fiscal year's latest Google Sheet comparison matches exactly."

    def handle(self, *args, **options):
        failures = []
        for fiscal_year in FiscalYear.objects.order_by("label"):
            run = fiscal_year.sync_runs.first()
            if run is None:
                failures.append(f"{fiscal_year.label}: never checked")
                continue
            comparison = compare_totals(run.source_totals, run.mirror_totals)
            if run.status != "matched" or not comparison["matches"]:
                failures.append(f"{fiscal_year.label}: {len(comparison['differences'])} differences")
            else:
                self.stdout.write(self.style.SUCCESS(f"{fiscal_year.label}: exact match"))
        if failures:
            raise CommandError("; ".join(failures))
