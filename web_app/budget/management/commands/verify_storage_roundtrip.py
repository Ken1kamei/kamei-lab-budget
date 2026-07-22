import json
from datetime import datetime, timezone

from django.core.management.base import BaseCommand, CommandError
from google.api_core.exceptions import NotFound

from budget.services.storage import delete_invoice, open_invoice, save_invoice


class Command(BaseCommand):
    help = "Write, read, and remove a temporary private invoice object."

    def handle(self, *args, **options):
        payload = b"Kamei Lab private invoice storage verification"
        stored = None
        readback_matches = False
        removed = False
        try:
            stored = save_invoice(
                payload,
                filename="storage-verification.pdf",
                content_type="application/pdf",
            )
            with open_invoice(stored.object_key) as handle:
                readback_matches = handle.read() == payload
            if not readback_matches:
                raise CommandError("The private invoice object did not match its source bytes.")

            delete_invoice(stored.object_key)
            try:
                with open_invoice(stored.object_key):
                    pass
            except (FileNotFoundError, NotFound):
                removed = True
            if not removed:
                raise CommandError("The temporary private invoice object was not removed.")
        finally:
            if stored is not None and not removed:
                delete_invoice(stored.object_key)

        self.stdout.write(
            json.dumps(
                {
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "readback_matches": readback_matches,
                    "removed": removed,
                    "size": len(payload),
                },
                sort_keys=True,
            )
        )
