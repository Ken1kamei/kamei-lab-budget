from datetime import date

from django.conf import settings

from budget.member_accounts import validate_member_email
from budget.models import LabMember
from labapps.models import SlackConnection
from labapps.permissions import truthy

from .sheets import (
    append_registry_audit,
    next_identifier,
    snapshot_rows,
    upsert_record,
)


def sync_iap_allowlist_member(payload):
    email = validate_member_email(payload.get("email"))
    global_role = str(payload.get("global_role") or "").strip().lower()
    highest_role = {
        "pi": "pi",
        "admin": "budget_manager",
        "lead": "lead",
        "member": "member",
    }.get(global_role, "member")
    return LabMember.objects.update_or_create(
        email=email,
        defaults={
            "display_name": str(
                payload.get("display_name") or payload.get("name") or email
            ).strip(),
            "highest_role": highest_role,
            "active": truthy(payload.get("active", "TRUE")),
        },
    )[0]


def upsert_member_access(cleaned, *, actor):
    members = snapshot_rows("Members")
    email = validate_member_email(cleaned.get("email"))
    existing = next(
        (
            row
            for row in members
            if str(row.get("email", "")).strip().lower() == email
        ),
        None,
    )
    member_id = existing.get("member_id") if existing else next_identifier("Members", "M")
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
    sync_iap_allowlist_member(payload)
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
    actor = str(actor or "").strip().lower()
    member = next(
        (
            row
            for row in snapshot_rows("Members")
            if str(row.get("member_id", "")).strip() == str(member_id).strip()
        ),
        None,
    )
    if member is None:
        raise ValueError("The selected member no longer exists.")
    email = validate_member_email(member.get("email"))
    if email == settings.PI_EMAIL:
        raise ValueError("The configured PI account cannot be removed.")
    if email == actor:
        raise ValueError("You cannot remove your own Portal access.")

    today = date.today().isoformat()
    for table_name in ("App_Roles", "Member_Teams"):
        for row in snapshot_rows(table_name):
            if (
                str(row.get("member_id", "")).strip() == str(member_id).strip()
                and truthy(row.get("active"))
            ):
                payload = {**row, "active": "FALSE", "end_date": today}
                upsert_record(
                    table_name,
                    payload,
                    actor=actor,
                    action="remove_member_access",
                )

    payload = {**member, "active": "FALSE", "end_date": today}
    upsert_record("Members", payload, actor=actor, action="remove_member_access")
    sync_iap_allowlist_member(payload)
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
