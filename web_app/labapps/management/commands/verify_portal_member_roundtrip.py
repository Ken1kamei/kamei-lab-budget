import json
from datetime import date

from django.core.management.base import BaseCommand, CommandError

from budget.models import LabMember
from labapps.models import LabAppAudit, SlackConnection
from labapps.permissions import truthy
from labapps.services.members import remove_member_access, upsert_member_access
from labapps.services.sheets import (
    _live_table,
    next_identifier,
    replace_table,
    snapshot_rows,
    upsert_record,
)


TABLES = ("Members", "Member_Teams", "App_Roles", "Audit_Log")


class Command(BaseCommand):
    help = "Reversibly verify Portal member add, access removal, and Sheet restoration."

    def add_arguments(self, parser):
        parser.add_argument("--actor", default="kk4801@nyu.edu")
        parser.add_argument("--email", default="codex.portal.verify@nyu.edu")

    def handle(self, *args, **options):
        actor = options["actor"].strip().lower()
        email = options["email"].strip().lower()
        originals = {table: _live_table(table)[2] for table in TABLES}
        if any(
            str(row.get("email", "")).strip().lower() == email
            for row in originals["Members"]
        ):
            raise CommandError(f"Verification account already exists: {email}")

        audits_before = set(LabAppAudit.objects.values_list("id", flat=True))
        member_id = ""
        role_id = ""
        membership_id = ""
        restored = False
        evidence = {"email": email}
        try:
            member = upsert_member_access(
                {
                    "email": email,
                    "name": "Portal verification",
                    "display_name": "Portal verification",
                    "global_role": "member",
                    "active": True,
                    "notes": "Temporary reversible verification",
                },
                actor=actor,
            )
            member_id = member["member_id"]
            active_teams = [
                row
                for row in _live_table("Teams")[2]
                if truthy(row.get("active"))
            ]
            team_id = str(active_teams[0].get("team_id", "")) if active_teams else ""
            role_id = next_identifier("App_Roles", "AR")
            upsert_record(
                "App_Roles",
                {
                    "app_role_id": role_id,
                    "member_id": member_id,
                    "app_id": "budget",
                    "app_role": "viewer",
                    "scope_team_id": team_id,
                    "active": "TRUE",
                    "start_date": date.today().isoformat(),
                    "end_date": "",
                },
                actor=actor,
                action="verification_member_role",
            )
            if team_id:
                membership_id = next_identifier("Member_Teams", "MT")
                upsert_record(
                    "Member_Teams",
                    {
                        "member_team_id": membership_id,
                        "member_id": member_id,
                        "team_id": team_id,
                        "team_role": "member",
                        "active": "TRUE",
                        "start_date": date.today().isoformat(),
                        "end_date": "",
                    },
                    actor=actor,
                    action="verification_member_team",
                )

            added = next(
                row
                for row in _live_table("Members")[2]
                if row.get("member_id") == member_id
            )
            if not truthy(added.get("active")):
                raise CommandError("Temporary member was not active after Sheet readback.")
            if not LabMember.objects.filter(email=email, active=True).exists():
                raise CommandError("Temporary member was not active in the app allowlist.")

            remove_member_access(member_id, actor=actor)
            removed = next(
                row
                for row in _live_table("Members")[2]
                if row.get("member_id") == member_id
            )
            live_roles = _live_table("App_Roles")[2]
            live_memberships = _live_table("Member_Teams")[2]
            if truthy(removed.get("active")):
                raise CommandError("Temporary member remained active after removal.")
            if any(
                row.get("member_id") == member_id and truthy(row.get("active"))
                for row in [*live_roles, *live_memberships]
            ):
                raise CommandError("Temporary member retained an active role or team.")
            if LabMember.objects.filter(email=email, active=True).exists():
                raise CommandError("Temporary member remained active in the app allowlist.")
            evidence.update(
                {
                    "member_id": member_id,
                    "role_id": role_id,
                    "membership_id": membership_id,
                    "add_readback": True,
                    "remove_readback": True,
                }
            )
        finally:
            restore_error = None
            try:
                for table in ("App_Roles", "Member_Teams", "Members", "Audit_Log"):
                    replace_table(
                        table,
                        originals[table],
                        actor=actor,
                        action="verification_member_restore",
                        target=f"{table}:{member_id or email}",
                        before={},
                    )
                restored = all(_live_table(table)[2] == originals[table] for table in TABLES)
            except Exception as error:
                restore_error = error
            finally:
                LabMember.objects.filter(email=email).delete()
                SlackConnection.objects.filter(portal_email=email).delete()
                LabAppAudit.objects.exclude(id__in=audits_before).delete()
            if restore_error is not None:
                raise CommandError("Portal member verification restoration failed.") from restore_error

        if not restored or any(
            row.get("email", "").strip().lower() == email
            for row in snapshot_rows("Members")
        ):
            raise CommandError("Portal member verification data was not fully restored.")
        evidence["restored"] = True
        self.stdout.write(self.style.SUCCESS(json.dumps(evidence, sort_keys=True)))
