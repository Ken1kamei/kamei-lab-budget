from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from budget.member_accounts import normalize_member_email
from labapps.permissions import truthy
from labapps.services.members import delete_member_record
from labapps.services.sheets import snapshot_rows, sync_all


class Command(BaseCommand):
    help = "Permanently delete inactive Registry members after transferring linked work."

    def add_arguments(self, parser):
        parser.add_argument("emails", nargs="+")
        parser.add_argument("--actor", default=settings.PI_EMAIL)
        parser.add_argument("--reassign-to-email", default=settings.PI_EMAIL)

    def handle(self, *args, **options):
        sync_all()
        members = snapshot_rows("Members")
        actor = normalize_member_email(options["actor"])
        reassign_email = normalize_member_email(options["reassign_to_email"])
        target = next(
            (
                row
                for row in members
                if normalize_member_email(row.get("email")) == reassign_email
                and truthy(row.get("active", "TRUE"))
            ),
            None,
        )
        if target is None:
            raise CommandError("The reassignment email is not an active Registry member.")

        deleted = []
        for raw_email in options["emails"]:
            email = normalize_member_email(raw_email)
            member = next(
                (
                    row
                    for row in snapshot_rows("Members")
                    if normalize_member_email(row.get("email")) == email
                ),
                None,
            )
            if member is None:
                raise CommandError(f"Registry member not found: {email}")
            if truthy(member.get("active", "TRUE")):
                raise CommandError(f"Deactivate before deletion: {email}")
            delete_member_record(
                member["member_id"],
                actor=actor,
                confirm_email=email,
                reassign_to_member_id=target["member_id"],
            )
            deleted.append(email)

        self.stdout.write(self.style.SUCCESS(f"Deleted: {', '.join(deleted)}"))
