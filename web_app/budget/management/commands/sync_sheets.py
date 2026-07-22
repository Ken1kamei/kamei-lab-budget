from django.core.management.base import BaseCommand, CommandError

from budget.services.sheets import SheetsGateway, SheetsSourceError
from budget.services.sync import sync_fiscal_year


class Command(BaseCommand):
    help = "Refresh the read-only Django mirror from one or all registered fiscal-year Sheets."

    def add_arguments(self, parser):
        parser.add_argument("--fy", action="append", dest="years")

    def handle(self, *args, **options):
        try:
            gateway = SheetsGateway()
            years = options["years"] or gateway.fiscal_year_options()
            if not years:
                raise CommandError("No fiscal years are registered in the master Config worksheet.")
            failures = []
            for fiscal_year in years:
                snapshot = gateway.read_fiscal_year(fiscal_year)
                run = sync_fiscal_year(snapshot, actor="management-command")
                self.stdout.write(
                    f"{fiscal_year}: {run.status}; source={run.source_transaction_count}; "
                    f"mirror={run.mirror_transaction_count}; differences={len(run.differences)}"
                )
                if run.status != "matched":
                    failures.append(fiscal_year)
            if failures:
                raise CommandError(f"Parity mismatch for: {', '.join(failures)}")
        except SheetsSourceError as error:
            raise CommandError(str(error)) from error
