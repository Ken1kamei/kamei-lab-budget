from datetime import date

from django.conf import settings

from budget.member_accounts import normalize_member_email, validate_member_email
from budget.models import FiscalYear, LabMember
from labapps.models import SlackConnection
from labapps.permissions import truthy

from .sheets import (
    append_registry_audit,
    replace_table,
    snapshot_rows,
    upsert_record,
)


def _member_by_id(member_id):
    member_id = str(member_id or "").strip()
    return next(
        (
            row
            for row in snapshot_rows("Members")
            if str(row.get("member_id") or "").strip() == member_id
        ),
        None,
    )


def _next_member_identifier():
    """Return an ID never used by the Registry or its member references."""
    identifiers = []
    identifiers.extend(row.get("member_id") for row in snapshot_rows("Members"))
    for table_name, key in (
        ("Member_Teams", "member_id"),
        ("App_Roles", "member_id"),
        ("Projects", "owner_member_id"),
        ("Milestones", "owner_member_id"),
        ("Experiments", "member_id"),
    ):
        identifiers.extend(row.get(key) for row in snapshot_rows(table_name))
    for row in snapshot_rows("Projects"):
        identifiers.extend(_split_reference_ids(row.get("assigned_member_ids")))
    identifiers.extend(
        row.get("target_id")
        for row in snapshot_rows("Audit_Log")
        if str(row.get("target_type") or "").strip().lower() == "member"
    )
    numbers = []
    for raw in identifiers:
        value = str(raw or "").strip()
        suffix = value.removeprefix("M").lstrip("-")
        if value.startswith("M") and suffix.isdigit():
            numbers.append(int(suffix))
    return f"M{max(numbers, default=0) + 1:03d}"


def sync_registry_member_mirror(member_id, *, previous_email=""):
    payload = _member_by_id(member_id)
    if payload is None:
        if previous_email:
            LabMember.objects.filter(
                email=normalize_member_email(previous_email)
            ).delete()
        return None
    email = normalize_member_email(payload.get("email"))
    if not email:
        raise ValueError("The member email is missing.")
    global_role = str(payload.get("global_role") or "").strip().lower()
    active = truthy(payload.get("active", "TRUE"))
    highest_role = {
        "pi": "pi",
        "admin": "budget_manager",
        "lead": "lead",
        "member": "member",
    }.get(global_role, "member")

    team_lookup = {
        str(row.get("team_id") or "").strip(): str(
            row.get("team_name") or ""
        ).strip()
        for row in snapshot_rows("Teams")
        if truthy(row.get("active", "TRUE"))
    }
    central_team_roles = {}
    if active:
        for row in snapshot_rows("Member_Teams"):
            if (
                str(row.get("member_id") or "").strip() != str(member_id).strip()
                or not truthy(row.get("active", "TRUE"))
            ):
                continue
            team_name = team_lookup.get(str(row.get("team_id") or "").strip())
            if not team_name:
                continue
            central_team_roles[team_name] = (
                "lead"
                if str(row.get("team_role") or "").strip().lower() == "lead"
                else "member"
            )
        priority = {"member": 1, "lead": 2, "budget_manager": 3, "pi": 4}
        for row in snapshot_rows("App_Roles"):
            if (
                str(row.get("member_id") or "").strip() != str(member_id).strip()
                or str(row.get("app_id") or "").strip() != "budget"
                or not truthy(row.get("active", "TRUE"))
            ):
                continue
            app_role = str(row.get("app_role") or "").strip().lower()
            resolved_role = {
                "owner": "pi",
                "manager": "budget_manager",
                "lead": "lead",
            }.get(app_role, "member")
            if priority[resolved_role] > priority[highest_role]:
                highest_role = resolved_role
            scoped_team = team_lookup.get(
                str(row.get("scope_team_id") or "").strip()
            )
            if scoped_team and resolved_role in {"lead", "budget_manager", "pi"}:
                central_team_roles[scoped_team] = "lead"

    annual_roles = {}
    for fiscal_year in FiscalYear.objects.all():
        active_names = set(
            fiscal_year.teams.filter(active=True).values_list("name", flat=True)
        )
        scoped = {
            name: team_role
            for name, team_role in central_team_roles.items()
            if name in active_names
        }
        if scoped:
            annual_roles[fiscal_year.label] = scoped

    previous_email = normalize_member_email(previous_email)
    if previous_email and previous_email != email:
        LabMember.objects.filter(email=previous_email).delete()
        SlackConnection.objects.filter(portal_email=previous_email).update(
            portal_email=email
        )
    return LabMember.objects.update_or_create(
        email=email,
        defaults={
            "display_name": str(
                payload.get("display_name") or payload.get("name") or email
            ).strip(),
            "highest_role": highest_role,
            "team_names": sorted(central_team_roles),
            "team_roles": annual_roles,
            "active": active,
        },
    )[0]


def sync_all_member_mirrors():
    member_ids = []
    for row in snapshot_rows("Members"):
        member_id = str(row.get("member_id") or "").strip()
        if member_id:
            member_ids.append(member_id)
            sync_registry_member_mirror(member_id)
    registry_emails = {
        normalize_member_email(row.get("email"))
        for row in snapshot_rows("Members")
        if normalize_member_email(row.get("email"))
    }
    LabMember.objects.exclude(email__in=registry_emails).exclude(
        email=normalize_member_email(settings.PI_EMAIL)
    ).delete()
    return member_ids


def _deactivate_related_access(member_id, *, actor, today):
    for table_name in ("App_Roles", "Member_Teams"):
        for row in snapshot_rows(table_name):
            if (
                str(row.get("member_id") or "").strip()
                == str(member_id).strip()
                and truthy(row.get("active"))
            ):
                upsert_record(
                    table_name,
                    {**row, "active": "FALSE", "end_date": today},
                    actor=actor,
                    action="remove_member_access",
                )


def upsert_member_access(cleaned, *, actor):
    members = snapshot_rows("Members")
    email = validate_member_email(cleaned.get("email"))
    requested_member_id = str(cleaned.get("member_id") or "").strip()
    existing = (
        next(
            (
                row
                for row in members
                if str(row.get("member_id") or "").strip() == requested_member_id
            ),
            None,
        )
        if requested_member_id
        else next(
            (
                row
                for row in members
                if normalize_member_email(row.get("email")) == email
            ),
            None,
        )
    )
    if requested_member_id and existing is None:
        raise ValueError("The selected member no longer exists.")
    duplicate = next(
        (
            row
            for row in members
            if normalize_member_email(row.get("email")) == email
            and str(row.get("member_id") or "").strip()
            != str((existing or {}).get("member_id") or "").strip()
        ),
        None,
    )
    if duplicate:
        raise ValueError("That email is already assigned to another member.")
    previous_email = normalize_member_email((existing or {}).get("email"))
    if previous_email == normalize_member_email(settings.PI_EMAIL):
        if (
            email != previous_email
            or cleaned.get("global_role") != "pi"
            or not cleaned.get("active")
        ):
            raise ValueError(
                "The configured Principal Investigator email, role, and active status are protected."
            )
    member_id = existing.get("member_id") if existing else _next_member_identifier()
    payload = {
        "member_id": member_id,
        "email": email,
        "name": cleaned["name"],
        "display_name": cleaned.get("display_name") or cleaned["name"],
        "global_role": cleaned["global_role"],
        "active": "TRUE" if cleaned.get("active") else "FALSE",
        "start_date": (existing or {}).get("start_date") or date.today().isoformat(),
        "end_date": "" if cleaned.get("active") else date.today().isoformat(),
        "password_hash": (existing or {}).get("password_hash", ""),
        "password_set_at": (existing or {}).get("password_set_at", ""),
        "password_must_change": (existing or {}).get(
            "password_must_change", "FALSE"
        ),
        "notes": cleaned.get("notes", ""),
    }
    upsert_record("Members", payload, actor=actor, action="upsert_member")
    if not cleaned.get("active"):
        _deactivate_related_access(
            member_id, actor=actor, today=date.today().isoformat()
        )
    sync_registry_member_mirror(member_id, previous_email=previous_email)
    append_registry_audit(
        actor=actor,
        action="upsert_member",
        target_type="Member",
        target_id=member_id,
        before=existing or {},
        after=payload,
    )
    return payload


def remove_member_access(member_id, *, actor):
    actor = normalize_member_email(actor)
    member = _member_by_id(member_id)
    if member is None:
        raise ValueError("The selected member no longer exists.")
    email = normalize_member_email(member.get("email"))
    if not email:
        raise ValueError("The selected member has no email address.")
    if email == normalize_member_email(settings.PI_EMAIL):
        raise ValueError("The configured PI account cannot be removed.")
    if str(member.get("global_role") or "").strip().lower() == "pi":
        raise ValueError("Change this Principal Investigator to another role before removing access.")
    if email == actor:
        raise ValueError("You cannot remove your own Portal access.")

    today = date.today().isoformat()
    _deactivate_related_access(member_id, actor=actor, today=today)

    payload = {**member, "active": "FALSE", "end_date": today}
    upsert_record("Members", payload, actor=actor, action="remove_member_access")
    sync_registry_member_mirror(member_id)
    SlackConnection.objects.filter(portal_email=email).delete()
    append_registry_audit(
        actor=actor,
        action="remove_member_access",
        target_type="Member",
        target_id=str(member_id),
        before=member,
        after=payload,
    )
    return payload


MEMBER_REFERENCE_FIELDS = (
    ("Projects", "owner_member_id"),
    ("Milestones", "owner_member_id"),
    ("Experiments", "member_id"),
)


def _split_reference_ids(value):
    return [
        item.strip()
        for item in str(value or "").replace(",", ";").replace("|", ";").split(";")
        if item.strip()
    ]


def member_reference_summary(member_id):
    member_id = str(member_id or "").strip()
    summary = [
        {
            "table_name": table_name,
            "count": sum(
                1
                for row in snapshot_rows(table_name)
                if str(row.get(key) or "").strip() == member_id
            ),
        }
        for table_name, key in MEMBER_REFERENCE_FIELDS
    ]
    summary.append(
        {
            "table_name": "Project assignments",
            "count": sum(
                member_id in _split_reference_ids(row.get("assigned_member_ids"))
                for row in snapshot_rows("Projects")
            ),
        }
    )
    return summary


def delete_member_record(
    member_id,
    *,
    actor,
    confirm_email,
    reassign_to_member_id="",
):
    actor = normalize_member_email(actor)
    member = _member_by_id(member_id)
    if member is None:
        raise ValueError("The selected member no longer exists.")
    email = normalize_member_email(member.get("email"))
    if not email or normalize_member_email(confirm_email) != email:
        raise ValueError("The confirmation email does not match the selected member.")
    if truthy(member.get("active", "TRUE")):
        raise ValueError("Deactivate this member before permanent deletion.")
    if email == actor:
        raise ValueError("You cannot delete your own Registry record.")
    if email == normalize_member_email(settings.PI_EMAIL) or str(
        member.get("global_role") or ""
    ).strip().lower() == "pi":
        raise ValueError("Principal Investigator records cannot be deleted.")

    references = [row for row in member_reference_summary(member_id) if row["count"]]
    reassign_to_member_id = str(reassign_to_member_id or "").strip()
    target = _member_by_id(reassign_to_member_id) if reassign_to_member_id else None
    if references and (
        target is None
        or reassign_to_member_id == str(member_id).strip()
        or not truthy(target.get("active", "TRUE"))
    ):
        raise ValueError(
            "Choose a different active member to receive linked tracker records: "
            + ", ".join(
                f"{row['table_name']} ({row['count']})" for row in references
            )
            + "."
        )

    before = dict(member)
    for table_name, key in MEMBER_REFERENCE_FIELDS:
        rows = snapshot_rows(table_name)
        changed = False
        output = []
        for row in rows:
            if str(row.get(key) or "").strip() == str(member_id).strip():
                output.append({**row, key: reassign_to_member_id})
                changed = True
            else:
                output.append(row)
        if changed:
            replace_table(
                table_name,
                output,
                actor=actor,
                action="reassign_before_member_delete",
                target=f"Member:{member_id}->{reassign_to_member_id}",
            )
    projects = snapshot_rows("Projects")
    reassigned_projects = []
    assignments_changed = False
    for row in projects:
        assigned = _split_reference_ids(row.get("assigned_member_ids"))
        if str(member_id).strip() in assigned:
            assigned = [
                reassign_to_member_id if value == str(member_id).strip() else value
                for value in assigned
            ]
            assigned = list(dict.fromkeys(value for value in assigned if value))
            row = {**row, "assigned_member_ids": ";".join(assigned)}
            assignments_changed = True
        reassigned_projects.append(row)
    if assignments_changed:
        replace_table(
            "Projects",
            reassigned_projects,
            actor=actor,
            action="reassign_before_member_delete",
            target=f"Member:{member_id}->{reassign_to_member_id}",
        )
    for table_name in ("App_Roles", "Member_Teams"):
        original = snapshot_rows(table_name)
        rows = [
            row
            for row in original
            if str(row.get("member_id") or "").strip() != str(member_id).strip()
        ]
        if len(rows) != len(original):
            replace_table(
                table_name,
                rows,
                actor=actor,
                action="delete_member_record",
                target=f"Member:{member_id}",
            )
    members = [
        row
        for row in snapshot_rows("Members")
        if str(row.get("member_id") or "").strip() != str(member_id).strip()
    ]
    replace_table(
        "Members",
        members,
        actor=actor,
        action="delete_member_record",
        target=f"Member:{member_id}",
    )
    LabMember.objects.filter(email=email).delete()
    SlackConnection.objects.filter(portal_email=email).delete()
    append_registry_audit(
        actor=actor,
        action="delete_member_record",
        target_type="Member",
        target_id=str(member_id),
        before=before,
        after={
            "deleted": True,
            "reassigned_to_member_id": reassign_to_member_id,
        },
    )
    return before
