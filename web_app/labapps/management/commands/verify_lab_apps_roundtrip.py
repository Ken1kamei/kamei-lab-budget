import json
import secrets

from django.core.management.base import BaseCommand, CommandError

from labapps.models import LabAppAudit, SheetRecord
from labapps.services.sheets import _live_table, replace_table, snapshot_rows
from labapps.services.storage import delete_knowledge_file, read_knowledge_file, store_knowledge_file


class Command(BaseCommand):
    help = "Run reversible Google Sheet and private object-storage verification."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="kk4801@nyu.edu")

    def handle(self, *args, **options):
        actor = options["actor"].strip().lower()
        _, _, original = _live_table("Projects")
        token = secrets.token_hex(5).upper()
        project_id = f"VERIFY-{token}"
        probe = {
            "project_id": project_id,
            "project": "Temporary Web verification",
            "aim": "Reversible Sheet write/read/restore test",
            "owner_member_id": "",
            # Keep date cells empty so locale-specific Sheet formatting cannot
            # turn a verification value into a different display string.
            "start_date": "",
            "target_date": "",
            "notes": token,
        }
        audits_before = set(LabAppAudit.objects.values_list("id", flat=True))
        restored = False
        object_key = ""
        try:
            replace_table(
                "Projects", [*original, probe], actor=actor,
                action="verification_create", target=f"Projects:{project_id}", before={"rows": original},
            )
            _, _, sheet_rows = _live_table("Projects")
            if not any(row.get("project_id") == project_id for row in sheet_rows):
                raise CommandError("Temporary Project was not read back from Google Sheets.")
            if not SheetRecord.objects.filter(source="tracker", table_name="Projects", record_id=project_id).exists():
                raise CommandError("Temporary Project was not mirrored to PostgreSQL.")

            content = f"Kamei Lab private storage verification {token}".encode()
            object_key, digest = store_knowledge_file(project_id, "verification.txt", content, "text/plain")
            if read_knowledge_file(object_key) != content:
                raise CommandError("Private storage readback did not match the uploaded bytes.")

            replace_table(
                "Projects", original, actor=actor,
                action="verification_restore", target=f"Projects:{project_id}", before={"rows": [*original, probe]},
            )
            _, _, restored_rows = _live_table("Projects")
            mirror_rows = snapshot_rows("Projects")
            key = lambda row: str(row.get("project_id", ""))
            if restored_rows != original or sorted(mirror_rows, key=key) != sorted(original, key=key):
                raise CommandError("Project Sheet restoration did not reproduce the original rows.")
            restored = True
        finally:
            if object_key:
                delete_knowledge_file(object_key)
            if not restored:
                replace_table(
                    "Projects", original, actor=actor,
                    action="verification_emergency_restore", target=f"Projects:{project_id}", before={},
                )
            LabAppAudit.objects.exclude(id__in=audits_before).delete()
        self.stdout.write(
            self.style.SUCCESS(json.dumps({"sheet_restored": True, "private_storage_restored": True, "project_id": project_id}))
        )
