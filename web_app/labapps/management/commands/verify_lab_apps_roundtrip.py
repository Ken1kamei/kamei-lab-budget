import json
import secrets
import tempfile
from datetime import date, timedelta
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import Client, override_settings
from django.utils import timezone
from numbers_parser import Document

from labapps.models import LabAppAudit, SheetRecord
from labapps.permissions import truthy
from labapps.services.gantt import parse_gantt_file
from labapps.services.sheets import _live_table, replace_table, snapshot_rows
from labapps.services.storage import delete_knowledge_file, read_knowledge_file, store_knowledge_file


def _verify_gantt_file_parsers():
    csv_upload = SimpleUploadedFile(
        "verification-gantt.csv",
        b"Task,Start Date,End Date\nCSV verification,2026-09-01,2026-09-03\n",
        content_type="text/csv",
    )
    csv_result = parse_gantt_file(csv_upload)
    if csv_result.errors or [row["task"] for row in csv_result.rows] != [
        "CSV verification"
    ]:
        raise CommandError(f"CSV Gantt parser verification failed: {csv_result.errors}")

    with tempfile.TemporaryDirectory() as temporary_directory:
        numbers_path = Path(temporary_directory) / "verification-gantt.numbers"
        document = Document(
            sheet_name="Gantt Import",
            table_name="Gantt Import",
            num_header_rows=1,
            num_header_cols=0,
            num_rows=2,
            num_cols=3,
        )
        table = document.sheets[0].tables[0]
        for row_number, row in enumerate(
            (
                ("Task", "Start Date", "End Date"),
                ("Numbers verification", "2026-09-01", "2026-09-03"),
            )
        ):
            for column_number, value in enumerate(row):
                table.write(row_number, column_number, value)
        document.save(numbers_path)
        numbers_upload = SimpleUploadedFile(
            numbers_path.name,
            numbers_path.read_bytes(),
            content_type="application/vnd.apple.numbers",
        )
    numbers_result = parse_gantt_file(numbers_upload)
    if numbers_result.errors or [row["task"] for row in numbers_result.rows] != [
        "Numbers verification"
    ]:
        raise CommandError(
            f"Apple Numbers Gantt parser verification failed: {numbers_result.errors}"
        )


class Command(BaseCommand):
    help = "Run reversible Google Sheet and private object-storage verification."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="kk4801@nyu.edu")

    def handle(self, *args, **options):
        actor = options["actor"].strip().lower()
        _verify_gantt_file_parsers()
        call_command("collectstatic", clear=True, interactive=False, verbosity=0)
        _, _, original_projects = _live_table("Projects")
        _, _, original_milestones = _live_table("Milestones")
        token = secrets.token_hex(5).upper()
        project_id = f"VERIFY-{token}"
        milestone_id = f"MS-GANTT-VERIFY-{token}"
        today = date.today()
        _, _, live_members = _live_table("Members")
        _, _, live_teams = _live_table("Teams")
        registry_members = [
            row for row in live_members if truthy(row.get("active", "TRUE"))
        ]
        registry_teams = [
            row for row in live_teams if truthy(row.get("active", "TRUE"))
        ]
        assigned_member = next(
            (
                row
                for row in registry_members
                if str(row.get("email") or "").strip().lower() == actor
            ),
            registry_members[0] if registry_members else None,
        )
        assigned_team = registry_teams[0] if registry_teams else None
        if not assigned_member or not assigned_team:
            raise CommandError(
                "At least one active Registry member and team are required for verification."
            )
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
            "assigned_team_ids": assigned_team["team_id"],
            "assigned_member_ids": assigned_member["member_id"],
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
        verification_user = None
        created_verification_user = False
        privacy_user = None
        privacy_email = f"roundtrip-viewer-{token.lower()}@nyu.edu"
        privacy_member_id = f"VERIFY-MEMBER-{token}"
        privacy_role_id = f"VERIFY-ROLE-{token}"
        privacy_membership_id = f"VERIFY-MT-{token}"
        unassigned_project_hidden = False
        assigned_team_project_visible = False
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
            if not any(
                row.get("project_id") == project_id
                and row.get("assigned_team_ids") == assigned_team["team_id"]
                and row.get("assigned_member_ids") == assigned_member["member_id"]
                for row in project_rows
            ):
                raise CommandError("Temporary Project was not read back from Google Sheets.")
            if not any(
                row.get("milestone_id") == milestone_id
                and row.get("progress_percent") == "50"
                for row in milestone_rows
            ):
                raise CommandError("Temporary Gantt task was not read back from Google Sheets.")
            project_mirror = SheetRecord.objects.filter(
                source="tracker", table_name="Projects", record_id=project_id
            ).first()
            if not project_mirror or (
                project_mirror.payload.get("assigned_team_ids")
                != assigned_team["team_id"]
                or project_mirror.payload.get("assigned_member_ids")
                != assigned_member["member_id"]
            ):
                raise CommandError("Temporary Project was not mirrored to PostgreSQL.")
            if not SheetRecord.objects.filter(
                source="tracker", table_name="Milestones", record_id=milestone_id
            ).exists():
                raise CommandError("Temporary Gantt task was not mirrored to PostgreSQL.")

            SheetRecord.objects.create(
                source="registry",
                table_name="Members",
                record_id=privacy_member_id,
                payload={
                    "member_id": privacy_member_id,
                    "email": privacy_email,
                    "display_name": "Temporary privacy verifier",
                    "global_role": "member",
                    "active": "TRUE",
                },
            )
            SheetRecord.objects.create(
                source="registry",
                table_name="App_Roles",
                record_id=privacy_role_id,
                payload={
                    "app_role_id": privacy_role_id,
                    "member_id": privacy_member_id,
                    "app_id": "project_tracker",
                    "app_role": "viewer",
                    "scope_team_id": "",
                    "active": "TRUE",
                },
            )
            privacy_user = get_user_model().objects.create_user(
                username=f"roundtrip-viewer-{token}",
                email=privacy_email,
            )
            privacy_client = Client()
            privacy_client.force_login(privacy_user)
            privacy_session = privacy_client.session
            privacy_session["gantt_import_preview"] = {
                "token": token,
                "actor": privacy_email,
                "project_id": project_id,
                "project": project_probe["project"],
                "sheet_name": "verification-gantt.csv",
                "header_row": 1,
                "rows": [milestone_probe],
                "warnings": [],
                "errors": [],
            }
            privacy_session.save()
            with override_settings(
                IAP_EXPECTED_AUDIENCE="", ALLOWED_HOSTS=["testserver"]
            ):
                hidden_response = privacy_client.get(
                    f"/tracker/?gantt_project={project_id}", secure=True
                )
            hidden_rendered = hidden_response.content.decode(
                "utf-8", errors="replace"
            )
            if (
                hidden_response.status_code != 200
                or project_probe["project"] in hidden_rendered
                or milestone_probe["milestone"] in hidden_rendered
                or "gantt_import_preview" in privacy_client.session
            ):
                raise CommandError(
                    "An unassigned member could see a private Project Gantt chart."
                )
            unassigned_project_hidden = True

            SheetRecord.objects.create(
                source="registry",
                table_name="Member_Teams",
                record_id=privacy_membership_id,
                payload={
                    "member_team_id": privacy_membership_id,
                    "member_id": privacy_member_id,
                    "team_id": assigned_team["team_id"],
                    "team_role": "member",
                    "active": "TRUE",
                },
            )
            with override_settings(
                IAP_EXPECTED_AUDIENCE="", ALLOWED_HOSTS=["testserver"]
            ):
                visible_response = privacy_client.get(
                    f"/tracker/?gantt_project={project_id}", secure=True
                )
            visible_rendered = visible_response.content.decode(
                "utf-8", errors="replace"
            )
            if (
                visible_response.status_code != 200
                or project_probe["project"] not in visible_rendered
                or milestone_probe["milestone"] not in visible_rendered
                or 'class="gantt-track"' not in visible_rendered
            ):
                raise CommandError(
                    "An assigned team member could not see the Project Gantt chart."
                )
            assigned_team_project_visible = True

            verification_user = get_user_model().objects.create_user(
                username=f"roundtrip-{token}",
                email=actor,
            )
            created_verification_user = True
            client = Client()
            client.force_login(verification_user)
            session = client.session
            session["gantt_import_preview"] = {
                "token": token,
                "actor": actor,
                "project_id": project_id,
                "project": project_probe["project"],
                "sheet_name": "verification-gantt.csv",
                "header_row": 1,
                "rows": [milestone_probe],
                "warnings": [],
                "errors": [],
            }
            session.save()
            # The job is not reached through Cloud Run's IAP proxy, so it has no
            # signed IAP assertion. Exercise the authenticated view directly.
            with override_settings(
                IAP_EXPECTED_AUDIENCE="", ALLOWED_HOSTS=["testserver"]
            ):
                response = client.get("/tracker/", secure=True)
            rendered = response.content.decode("utf-8", errors="replace")
            member_name = (
                assigned_member.get("display_name")
                or assigned_member.get("name")
                or assigned_member["member_id"]
            )
            team_name = assigned_team.get("team_name") or assigned_team["team_id"]
            expected_values = (project_probe["project"], member_name, team_name)
            missing_values = [
                value for value in expected_values if value not in rendered
            ]
            if response.status_code != 200 or missing_values:
                raise CommandError(
                    "Temporary Project assignments were not visible in the Tracker HTML "
                    f"(status={response.status_code}, missing={missing_values})."
                )
            preview_markers = (
                "Gantt chart preview",
                "Save 1 task and show chart",
                "Review imported task details (1)",
                'class="gantt-track"',
            )
            missing_preview_markers = [
                marker for marker in preview_markers if marker not in rendered
            ]
            if missing_preview_markers:
                raise CommandError(
                    "The imported Gantt chart preview was not rendered in the Tracker "
                    f"HTML (missing={missing_preview_markers})."
                )

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
            for table_name, record_id in (
                ("Members", privacy_member_id),
                ("App_Roles", privacy_role_id),
                ("Member_Teams", privacy_membership_id),
            ):
                SheetRecord.objects.filter(
                    source="registry",
                    table_name=table_name,
                    record_id=record_id,
                ).delete()
            if privacy_user is not None:
                privacy_user.delete()
            if created_verification_user and verification_user is not None:
                verification_user.delete()
        self.stdout.write(
            self.style.SUCCESS(
                json.dumps(
                    {
                        "sheet_restored": True,
                        "gantt_sheet_restored": True,
                        "private_storage_restored": True,
                        "tracker_ui_verified": True,
                        "gantt_preview_chart_verified": True,
                        "unassigned_project_hidden": unassigned_project_hidden,
                        "assigned_team_project_visible": assigned_team_project_visible,
                        "csv_gantt_parser_verified": True,
                        "numbers_gantt_parser_verified": True,
                        "assigned_team_id": assigned_team["team_id"],
                        "assigned_member_id": assigned_member["member_id"],
                        "project_id": project_id,
                        "milestone_id": milestone_id,
                    }
                )
            )
        )
