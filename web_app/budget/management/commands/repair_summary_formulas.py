from django.core.management.base import BaseCommand, CommandError

from budget.services.sheets import SheetsGateway, SheetsSourceError


class Command(BaseCommand):
    help = "Restore and verify fixed Summary formulas for one fiscal year."

    def add_arguments(self, parser):
        parser.add_argument("fiscal_year")

    def handle(self, *args, **options):
        fiscal_year = options["fiscal_year"]
        try:
            result = SheetsGateway().repair_summary_formulas(fiscal_year)
        except (SheetsSourceError, ValueError) as error:
            raise CommandError(str(error)) from error
        self.stdout.write(
            self.style.SUCCESS(
                f"Verified {fiscal_year} Summary formulas in "
                f"{len(result['ranges'])} ranges."
            )
        )
