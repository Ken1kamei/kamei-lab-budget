import json
import uuid

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from budget.services.calculations import compare_totals, money, snapshot_totals
from budget.services.sheets import SheetsGateway
from budget.services.sync import database_totals, sync_fiscal_year


class Command(BaseCommand):
    help = (
        "Temporarily write a Planned transaction, verify Sheet and dashboard totals, "
        "then delete it and verify restoration."
    )

    def add_arguments(self, parser):
        parser.add_argument("--fiscal-year", required=True)
        parser.add_argument("--team", default="")
        parser.add_argument("--category", default="Other")
        parser.add_argument("--amount", default="0.01")

    def handle(self, *args, **options):
        if not settings.ENABLE_SHEET_WRITES:
            raise CommandError("ENABLE_SHEET_WRITES must be true for this verification command.")
        fiscal_year = options["fiscal_year"]
        amount = money(options["amount"])
        if amount <= 0:
            raise CommandError("Verification amount must be greater than zero.")
        start_year = fiscal_year[2:6]
        if len(start_year) != 4 or not start_year.isdigit():
            raise CommandError("Fiscal year must look like FY2026-27.")

        gateway = SheetsGateway()
        before = gateway.read_fiscal_year(fiscal_year)
        before_totals = snapshot_totals(before)
        active_teams = [
            str(row.get("Team Name") or "").strip()
            for row in before.get("teams", [])
            if str(row.get("Active", "Y")).strip().upper() in {"Y", "YES", "TRUE", "1"}
            and str(row.get("Team Name") or "").strip()
        ]
        team = options["team"].strip() or (active_teams[0] if active_teams else "")
        if not team or team not in active_teams:
            raise CommandError(f"Select an active team in {fiscal_year}.")

        transaction_id = f"TXN-VERIFY-PLANNED-{uuid.uuid4().hex[:12].upper()}"
        payload = {
            "date": f"{start_year}-10-01",
            "category": options["category"],
            "subcategory": "Deployment verification",
            "vendor": "Codex verification",
            "description": "Temporary Planned status roundtrip",
            "currency": "USD",
            "amount": amount,
            "status": "Planned",
            "team": team,
            "entered_by": "codex-budget-verification",
            "entry_method": "Verification",
            "notes": f"Temporary row; remove after verification [{transaction_id}]",
        }
        evidence = {
            "fiscal_year": fiscal_year,
            "team": team,
            "amount": str(amount),
            "transaction_id": transaction_id,
        }
        written = False
        restored = False
        try:
            result = gateway.write_transaction(
                fiscal_year,
                payload,
                transaction_id=transaction_id,
                allow_existing=True,
            )
            written = True
            if result["row"].get("Status") != "Planned":
                raise CommandError("Google Sheet did not preserve Planned status.")
            readback = gateway.read_fiscal_year(fiscal_year)
            matches = [
                row
                for row in readback.get("transactions", [])
                if str(row.get("Transaction ID") or "").strip() == transaction_id
            ]
            if len(matches) != 1 or matches[0].get("Status") != "Planned":
                raise CommandError("Planned transaction readback did not match exactly once.")
            run = sync_fiscal_year(readback, actor="codex-planned-verification")
            mirror = database_totals(run.fiscal_year)
            expected_planned = money(before_totals["total_planned"] + amount)
            if run.status != "matched" or mirror["total_planned"] != expected_planned:
                raise CommandError("The web mirror did not reflect the Planned amount.")
            evidence.update(
                {
                    "sheet_status": matches[0]["Status"],
                    "mirror_status": run.status,
                    "planned_before": str(before_totals["total_planned"]),
                    "planned_during": str(mirror["total_planned"]),
                    "available_delta": str(
                        money(mirror["available"] - before_totals["available"])
                    ),
                }
            )
        finally:
            if written:
                gateway.delete_transaction(fiscal_year, transaction_id)
                after = gateway.read_fiscal_year(fiscal_year)
                restored_run = sync_fiscal_year(
                    after, actor="codex-planned-verification-restore"
                )
                after_totals = snapshot_totals(after)
                restored = (
                    not any(
                        str(row.get("Transaction ID") or "").strip() == transaction_id
                        for row in after.get("transactions", [])
                    )
                    and compare_totals(before_totals, after_totals)["matches"]
                    and after_totals["total_planned"] == before_totals["total_planned"]
                    and restored_run.status == "matched"
                )
                evidence.update(
                    {
                        "restored": restored,
                        "planned_after": str(after_totals["total_planned"]),
                    }
                )
        if not restored:
            raise CommandError(f"Verification data was not restored: {json.dumps(evidence)}")
        self.stdout.write(json.dumps(evidence, sort_keys=True))
