import re
from functools import wraps

from django.conf import settings
from django.http import HttpResponseForbidden
from django.shortcuts import redirect

from .models import SheetRecord


TRUE_VALUES = {"TRUE", "1", "YES", "Y"}
ADMIN_ROLES = {"pi", "admin"}
WRITE_ROLES = {"owner", "manager", "lead"}


def truthy(value):
    return str(value or "").strip().upper() in TRUE_VALUES


def reference_ids(value):
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = re.split(r"[;,|\n]+", str(value or ""))
    return list(
        dict.fromkeys(str(item).strip() for item in values if str(item).strip())
    )


def member_team_ids(member_id, memberships):
    return {
        str(row.get("team_id") or "").strip()
        for row in memberships
        if truthy(row.get("active", "TRUE"))
        and str(row.get("member_id") or "").strip() == str(member_id or "").strip()
        and str(row.get("team_id") or "").strip()
    }


def project_team_ids(project, memberships):
    explicit = set(reference_ids(project.get("assigned_team_ids")))
    if explicit:
        return explicit
    if reference_ids(project.get("assigned_member_ids")):
        return set()
    return member_team_ids(project.get("owner_member_id"), memberships)


def can_view_project(member, project, memberships):
    if is_portal_admin(member):
        return True
    if not member:
        return False
    member_id = str(member.get("member_id") or "").strip()
    if not member_id:
        return False
    if member_id == str(project.get("owner_member_id") or "").strip():
        return True
    if member_id in reference_ids(project.get("assigned_member_ids")):
        return True
    return bool(
        member_team_ids(member_id, memberships)
        & project_team_ids(project, memberships)
    )


def scope_tracker_records(member, projects, milestones, experiments, memberships):
    if is_portal_admin(member):
        return list(projects), list(milestones), list(experiments)

    visible_projects = [
        row for row in projects if can_view_project(member, row, memberships)
    ]
    project_ids = {
        str(row.get("project_id") or "").strip()
        for row in visible_projects
        if str(row.get("project_id") or "").strip()
    }
    member_id = str((member or {}).get("member_id") or "").strip()
    visible_team_ids = member_team_ids(member_id, memberships)

    def member_or_team_visible(row, owner_key):
        owner_id = str(row.get(owner_key) or "").strip()
        return bool(
            owner_id
            and (
                owner_id == member_id
                or member_team_ids(owner_id, memberships) & visible_team_ids
            )
        )

    visible_milestones = [
        row
        for row in milestones
        if (
            str(row.get("project_id") or "").strip() in project_ids
            if str(row.get("project_id") or "").strip()
            else member_or_team_visible(row, "owner_member_id")
        )
    ]
    milestone_ids = {
        str(row.get("milestone_id") or "").strip()
        for row in visible_milestones
        if str(row.get("milestone_id") or "").strip()
    }
    visible_experiments = [
        row
        for row in experiments
        if (
            str(row.get("project_id") or "").strip() in project_ids
            if str(row.get("project_id") or "").strip()
            else (
                str(row.get("milestone_id") or "").strip() in milestone_ids
                if str(row.get("milestone_id") or "").strip()
                else member_or_team_visible(row, "member_id")
            )
        )
    ]
    return visible_projects, visible_milestones, visible_experiments


def current_registry_member(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return None
    email = str(request.user.email or request.user.username or "").strip().lower()
    records = SheetRecord.objects.filter(source="registry", table_name="Members")
    for record in records:
        payload = record.payload
        if str(payload.get("email", "")).strip().lower() == email and truthy(
            payload.get("active", "")
        ):
            return payload
    if email == settings.PI_EMAIL:
        return {
            "member_id": "PI",
            "email": email,
            "name": "Ken Kamei",
            "display_name": "Ken",
            "global_role": "pi",
            "active": "TRUE",
        }
    return None


def is_portal_admin(member):
    return bool(member and str(member.get("global_role", "")).lower() in ADMIN_ROLES)


def app_role(member, app_id):
    roles = app_roles(member, app_id)
    return roles[0] if roles else None


def app_roles(member, app_id):
    if is_portal_admin(member):
        return [{"role": "owner", "scope_team_id": ""}]
    if not member:
        return []
    member_id = str(member.get("member_id", ""))
    priority = {"viewer": 1, "member": 2, "lead": 3, "manager": 4, "owner": 5}
    resolved = []
    for record in SheetRecord.objects.filter(source="registry", table_name="App_Roles"):
        payload = record.payload
        if (
            str(payload.get("member_id", "")) == member_id
            and str(payload.get("app_id", "")) == app_id
            and truthy(payload.get("active", ""))
        ):
            resolved.append(
                {
                "role": str(payload.get("app_role", "viewer")).lower(),
                "scope_team_id": str(payload.get("scope_team_id", "")),
                }
            )
    return sorted(
        resolved,
        key=lambda item: (
            -priority.get(item["role"], 0),
            item["scope_team_id"],
        ),
    )


def can_write(member, app_id):
    return any(resolved["role"] in WRITE_ROLES for resolved in app_roles(member, app_id))


def can_write_scope(member, app_id, scope_team_id=""):
    requested_scope = str(scope_team_id or "")
    return any(
        resolved["role"] in WRITE_ROLES
        and (
            not requested_scope
            or not resolved.get("scope_team_id")
            or resolved.get("scope_team_id") == requested_scope
        )
        for resolved in app_roles(member, app_id)
    )


def lab_app_access(app_id, *, write=False, admin=False):
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect("budget:login")
            member = current_registry_member(request)
            if member is None:
                return HttpResponseForbidden("Your NYU email is not in the Kamei Lab allowlist.")
            if admin and not is_portal_admin(member):
                return HttpResponseForbidden("Portal administration requires PI or admin access.")
            if not admin:
                resolved = app_role(member, app_id)
                if resolved is None:
                    return HttpResponseForbidden("You do not have access to this lab app.")
                if write and resolved["role"] not in WRITE_ROLES:
                    return HttpResponseForbidden("Your app role is read-only.")
            request.registry_member = member
            request.lab_app_role = app_role(member, app_id)
            return view(request, *args, **kwargs)

        return wrapped

    return decorator


def registry_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect("budget:login")
        member = current_registry_member(request)
        if member is None:
            return HttpResponseForbidden("Your NYU email is not in the Kamei Lab allowlist.")
        request.registry_member = member
        return view(request, *args, **kwargs)

    return wrapped
