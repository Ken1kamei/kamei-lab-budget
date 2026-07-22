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
    if is_portal_admin(member):
        return {"role": "owner", "scope_team_id": ""}
    if not member:
        return None
    member_id = str(member.get("member_id", ""))
    priority = {"viewer": 1, "member": 2, "lead": 3, "manager": 4, "owner": 5}
    best = None
    for record in SheetRecord.objects.filter(source="registry", table_name="App_Roles"):
        payload = record.payload
        if (
            str(payload.get("member_id", "")) == member_id
            and str(payload.get("app_id", "")) == app_id
            and truthy(payload.get("active", ""))
        ):
            candidate = {
                "role": str(payload.get("app_role", "viewer")).lower(),
                "scope_team_id": str(payload.get("scope_team_id", "")),
            }
            if not best or priority.get(candidate["role"], 0) > priority.get(best["role"], 0):
                best = candidate
    return best


def can_write(member, app_id):
    resolved = app_role(member, app_id)
    return bool(resolved and resolved["role"] in WRITE_ROLES)


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
