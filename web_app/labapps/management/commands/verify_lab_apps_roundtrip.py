import json
import secrets
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from labapps.models import LabAppAudit, SheetRecord
from labapps.services.sheets import _live_table, replace_table, snapshot_rows
from labapps.services.storage import delete_knowledge_file, read_knowledge_file, store_knowledge_file


class Command(BaseCommand):
    help = "Run reversible Google Sheet and private object-storage verification."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="kk4801@nyu.edu")

    def handle(self, *args, **options):
        actor = options["actor"].strip().lower()
        _, _, original_projects = _live_table("Projects")
        _, _, original_milestones = _live_table("Milestones")
        token = secrets.token_hex(5).upper()
        project_id = f"VERIFY-{token}"
        milestone_id = f"MS-GANTT-VERIFY-{token}"
        today = date.today()
        project_probe = {
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
        milestone_probe = {
            "milestone_id": milestone_id,
            "project_id": project_id,
            "project": project_probe["project"],
            "aim": project_probe["aim"],
            "milestone": "Temporary Gantt verification task",
            "time_window": "Verification",
            "owner_member_id": "",
            "start_date": today.isoformat(),
            "status": "In progress",
            "review_status": "Pending",
            "next_action": "Verify Gantt Sheet round trip",
            "due_date": (today + timedelta(days=2)).isoformat(),
            "blocker_reason": "",
            "help_needed_from": "",
            "progress_percent": "50",
            "updated_at": timezone.now().isoformat(timespec="seconds"),
        }
        audits_before = set(LabAppAudit.objects.values_list("id", flat=True))
        restored = False
        object_key = ""
        try:
            replace_table(
                "Projects", [*original_projects, project_probe], actor=actor,
                action="verification_create", target=f"Projects:{project_id}",
                before={"rows": original_projects},
            )
            replace_table(
                "Milestones", [*original_milestones, milestone_probe], actor=actor,
                action="verification_gantt_create", target=f"Milestones:{milestone_id}",
                before={"rows": original_milestones},
            )
            _, _, project_rows = _live_table("Projects")
            _, _, milestone_rows = _live_table("Milestones")
            if not any(row.get("project_id") == project_id for row in project_rows):
                raise CommandError("Temporary Project was not read back from Google Sheets.")
            if not any(
                row.get("milestone_id") == milestone_id
                and row.get("progress_percent") == "50"
                for row in milestone_rows
            ):
                raise CommandError("Temporary Gantt task was not read back from Google Sheets.")
            if not SheetRecord.objects.filter(source="tracker", table_name="Projects", record_id=project_id).exists():
                raise CommandError("Temporary Project was not mirrored to PostgreSQL.")
            if not SheetRecord.objects.filter(
                source="tracker", table_name="Milestones", record_id=milestone_id
            ).exists():
                raise CommandError("Temporary Gantt task was not mirrored to PostgreSQL.")

            content = f"Kamei Lab private storage verification {token}".encode()
            object_key, digest = store_knowledge_file(project_id, "verification.txt", content, "text/plain")
            if read_knowledge_file(object_key) != content:
                raise CommandError("Private storage readback did not match the uploaded bytes.")

            replace_table(
                "Milestones", original_milestones, actor=actor,
                action="verification_gantt_restore", target=f"Milestones:{milestone_id}",
                before={"rows": [*original_milestones, milestone_probe]},
            )
            replace_table(
                "Projects", original_projects, actor=actor,
                action="verification_restore", target=f"Projects:{project_id}",
                before={"rows": [*original_projects, project_probe]},
            )
            _, _, restored_projects = _live_table("Projects")
            _, _, restored_milestones = _live_table("Milestones")
            mirror_projects = snapshot_rows("Projects")
            mirror_milestones = snapshot_rows("Milestones")
            key = lambda row: str(row.get("project_id", ""))
            milestone_key = lambda row: str(row.get("milestone_id", ""))
            if (
                restored_projects != original_projects
                or restored_milestones != original_milestones
                or sorted(mirror_projects, key=key)
                != sorted(original_projects, key=key)
                or sorted(mirror_milestones, key=milestone_key)
                != sorted(original_milestones, key=milestone_key)
            ):
                raise CommandError(
                    "Project and Gantt Sheet restoration did not reproduce the original rows."
                )
            restored = True
        finally:
            if object_key:
                delete_knowledge_file(object_key)
            if not restored:
                replace_table(
                    "Milestones", original_milestones, actor=actor,
                    action="verification_gantt_emergency_restore",
                    target=f"Milestones:{milestone_id}", before={},
                )
                replace_table(
                    "Projects", original_projects, actor=actor,
                    action="verification_emergency_restore", target=f"Projects:{project_id}", before={},
                )
            LabAppAudit.objects.exclude(id__in=audits_before).delete()
        self.stdout.write(
            self.style.SUCCESS(
                json.dumps(
                    {
                        "sheet_restored": True,
                        "gantt_sheet_restored": True,
                        "private_storage_restored": True,
                        "project_id": project_id,
                        "milestone_id": milestone_id,
                    }
                )
            )
        )
