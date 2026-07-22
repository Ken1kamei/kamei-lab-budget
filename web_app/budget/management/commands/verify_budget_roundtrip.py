import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from budget.services.calculations import compare_totals, money, snapshot_totals
from budget.services.sheets import SheetsGateway
from budget.services.sync import database_totals, sync_fiscal_year


class Command(BaseCommand):
    help = "Temporarily write one category budget, verify Sheet and dashboard data, then restore it."

    def add_arguments(self, parser):
        parser.add_argument("--fiscal-year", required=True)
        parser.add_argument("--category", default="Consumables")
        parser.add_argument("--amount", default="10000")

    def handle(self, *args, **options):
        if not settings.ENABLE_SHEET_WRITES:
            raise CommandError("ENABLE_SHEET_WRITES must be true for this verification command.")
        fiscal_year = options["fiscal_year"]
        category = options["category"]
        dummy_amount = money(options["amount"])
        gateway = SheetsGateway()
        before = gateway.read_fiscal_year(fiscal_year)
        before_totals = snapshot_totals(before)
        if category not in before_totals["categories"]:
            raise CommandError(f"Unknown budget category: {category}")
        original_amount = money(before_totals["categories"][category]["budget"])
        evidence = {
            "fiscal_year": fiscal_year,
            "category": category,
            "dummy_amount": str(dummy_amount),
            "original_amount": str(original_amount),
        }
        restored = False
        try:
            gateway.write_category_allocations(fiscal_year, {category: dummy_amount})
            written = gateway.read_fiscal_year(fiscal_year)
            written_totals = snapshot_totals(written)
            sheet_value = money(written_totals["categories"][category]["budget"])
            if sheet_value != dummy_amount:
                raise CommandError(
                    f"Google Sheet readback was {sheet_value}, expected {dummy_amount}."
                )
            run = sync_fiscal_year(written, actor="codex-budget-verification")
            mirror_value = money(
                database_totals(run.fiscal_year)["categories"][category]["budget"]
            )
            if run.status != "matched" or mirror_value != dummy_amount:
                raise CommandError("The web dashboard mirror did not receive the dummy budget.")
            evidence.update(
                {
                    "sheet_readback": str(sheet_value),
                    "mirror_readback": str(mirror_value),
                    "mirror_status": run.status,
                }
            )
        finally:
            restore_error = None
            for attempt in range(1, 4):
                try:
                    gateway.write_category_allocations(
                        fiscal_year, {category: original_amount}
                    )
                    restore_error = None
                    break
                except Exception as error:
                    restore_error = error
                    if attempt < 3:
                        time.sleep(attempt)
            if restore_error is not None:
                raise CommandError(
                    "Budget restoration failed after three attempts. "
                    f"Restore {fiscal_year} {category} to {original_amount}."
                ) from restore_error
            after = gateway.read_fiscal_year(fiscal_year)
            restored_run = sync_fiscal_year(after, actor="codex-budget-verification-restore")
            after_totals = snapshot_totals(after)
            restored = (
                money(after_totals["categories"][category]["budget"])
                == original_amount
                and compare_totals(before_totals, after_totals)["matches"]
                and restored_run.status == "matched"
            )
            evidence.update(
                {
                    "restored": restored,
                    "restored_sheet_value": str(
                        money(after_totals["categories"][category]["budget"])
                    ),
                    "restored_mirror_value": str(
                        money(
                            database_totals(restored_run.fiscal_year)["categories"][
                                category
                            ]["budget"]
                        )
                    ),
                }
            )
        if not restored:
            raise CommandError(f"Verification data was not restored: {json.dumps(evidence)}")
        self.stdout.write(json.dumps(evidence, sort_keys=True))
