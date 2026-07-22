import hashlib
import json
import time
from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from budget.services.calculations import compare_totals, snapshot_totals
from budget.services.sheets import SheetsGateway
from budget.services.sync import database_totals, sync_fiscal_year


class Command(BaseCommand):
    help = "Write, read, mirror, and remove one dummy invoice transaction."

    def add_arguments(self, parser):
        parser.add_argument("--fiscal-year", required=True)
        parser.add_argument("--team", required=True)

    def handle(self, *args, **options):
        if not settings.ENABLE_SHEET_WRITES:
            raise CommandError("ENABLE_SHEET_WRITES must be true for this verification command.")
        fiscal_year = options["fiscal_year"]
        team = options["team"]
        gateway = SheetsGateway()
        digest = hashlib.sha256(
            f"kamei-web-verification:{fiscal_year}:{team}".encode()
        ).hexdigest()
        gateway.delete_transactions_by_pdf_hash(fiscal_year, digest)
        before = gateway.read_fiscal_year(fiscal_year)
        before_totals = snapshot_totals(before)
        before_rows = json.dumps(
            sorted(before["transactions"], key=lambda row: str(row.get("Transaction ID", ""))),
            sort_keys=True,
            default=str,
        )
        result = None
        restored = False
        evidence = {
            "fiscal_year": fiscal_year,
            "team": team,
            "before_count": before_totals["transaction_count"],
        }
        try:
            result = gateway.write_invoice_transaction(
                fiscal_year,
                {
                    "date": date.today(),
                    "category": "Other",
                    "subcategory": "System verification",
                    "vendor": "Kamei Lab Verification",
                    "description": "Reversible Google Sheet write verification",
                    "po_number": "",
                    "invoice_number": f"VERIFY-{digest[:12].upper()}",
                    "currency": "USD",
                    "amount": "0.01",
                    "team": team,
                    "entered_by": "codex-verification",
                    "file_name": "verification.pdf",
                    "file_sha256": digest,
                    "notes": "Temporary row; removed by verify_invoice_roundtrip.",
                },
            )
            written = gateway.read_fiscal_year(fiscal_year)
            matches = [
                row
                for row in written["transactions"]
                if str(row.get("Transaction ID")) == result["transaction_id"]
            ]
            if len(matches) != 1:
                raise CommandError("The written transaction was not read back exactly once.")
            run = sync_fiscal_year(written, actor="codex-verification")
            if run.status != "matched":
                raise CommandError("The Django mirror did not match the Google Sheet.")
            evidence.update(
                {
                    "transaction_id": result["transaction_id"],
                    "sheet_readback_count": len(matches),
                    "mirror_status": run.status,
                    "mirror_total_allocated": str(database_totals(run.fiscal_year)["total_allocated"]),
                }
            )
        finally:
            cleanup_error = None
            for attempt in range(1, 4):
                try:
                    gateway.delete_transactions_by_pdf_hash(fiscal_year, digest)
                    cleanup_error = None
                    break
                except Exception as error:
                    cleanup_error = error
                    if attempt < 3:
                        time.sleep(attempt)
            if cleanup_error is not None:
                recovery = {
                    "fiscal_year": fiscal_year,
                    "transaction_id": (result or {}).get("transaction_id", "unknown"),
                    "pdf_sha256": digest,
                }
                raise CommandError(
                    f"Cleanup failed after three attempts. Recovery identity: {json.dumps(recovery)}"
                ) from cleanup_error
            after = gateway.read_fiscal_year(fiscal_year)
            sync_fiscal_year(after, actor="codex-verification-restore")
            after_rows = json.dumps(
                sorted(
                    after["transactions"],
                    key=lambda row: str(row.get("Transaction ID", "")),
                ),
                sort_keys=True,
                default=str,
            )
            restored = (
                compare_totals(before_totals, snapshot_totals(after))["matches"]
                and before_rows == after_rows
            )
            evidence.update(
                {
                    "after_count": snapshot_totals(after)["transaction_count"],
                    "restored": restored,
                    "row_set_restored": before_rows == after_rows,
                }
            )
        if not restored:
            raise CommandError(f"Verification data was not restored: {json.dumps(evidence)}")
        self.stdout.write(json.dumps(evidence, sort_keys=True))
