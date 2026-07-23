import hashlib
import json
import mimetypes
import secrets
from datetime import date

from django import forms as django_forms
from django.contrib import messages
from django.db import transaction
from django.db.models import F, Q
from django.core.paginator import Paginator
from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.utils import timezone
from django.views.decorators.http import require_POST
from budget.models import LabMember

from .forms import (
    AppRoleForm,
    ExperimentForm,
    GanttImportForm,
    KnowledgeUploadForm,
    KnowledgeStatusForm,
    MemberForm,
    MilestoneForm,
    ProjectForm,
    ReviewForm,
    TeamForm,
)
from .models import KnowledgeRecord, LabAppAudit, SheetRecord
from .permissions import (
    app_role,
    app_roles,
    can_write,
    can_write_scope,
    current_registry_member,
    is_portal_admin,
    lab_app_access,
    registry_access,
    truthy,
)
from .services.gantt import (
    build_gantt_context,
    parse_gantt_workbook,
    resolve_gantt_rows,
)
from .services.knowledge import (
    EXTRACTED_METADATA_KEYS,
    extract_knowledge_metadata,
)
from .services.knowledge_catalog import (
    AVAILABLE_STATUSES,
    build_document_preview,
    build_search_text,
    public_status,
)
from .services.sheets import (
    append_history,
    append_registry_audit,
    next_identifier,
    replace_project_gantt,
    replace_table,
    snapshot_rows,
    upsert_record,
)
from .services.storage import (
    delete_knowledge_file,
    open_knowledge_file,
    read_knowledge_file,
    store_knowledge_file,
)


def _email(request):
    return str(request.user.email or request.user.username or "").strip().lower()


def _active(rows):
    return [row for row in rows if truthy(row.get("active", "TRUE"))]


def _member_lookup():
    return {row["member_id"]: row for row in snapshot_rows("Members")}


def _team_lookup():
    return {row["team_id"]: row for row in snapshot_rows("Teams")}


def _display_member(member_id, members):
    row = members.get(member_id, {})
    return row.get("display_name") or row.get("name") or member_id


def _sync_iap_allowlist_member(payload):
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        return
    global_role = str(payload.get("global_role") or "").strip().lower()
    highest_role = {
        "pi": "pi",
        "admin": "budget_manager",
        "lead": "lead",
        "member": "member",
    }.get(global_role, "member")
    LabMember.objects.update_or_create(
        email=email,
        defaults={
            "display_name": str(
                payload.get("display_name") or payload.get("name") or email
            ).strip(),
            "highest_role": highest_role,
            "active": truthy(payload.get("active", "TRUE")),
        },
    )


@registry_access
def portal(request):
    member = current_registry_member(request)
    configured = {row["app_id"]: row for row in _active(snapshot_rows("Apps"))}
    cards = [
        {
            "app_id": "budget",
            "name": "Budget Manager",
            "url": reverse("budget:dashboard"),
            "description": configured.get("budget", {}).get("description", "Lab budget and invoice management"),
            "role": (app_role(member, "budget") or {}).get("role", "No access"),
        },
        {
            "app_id": "project_tracker",
            "name": "Project Tracker",
            "url": reverse("labapps:tracker"),
            "description": configured.get("project_tracker", {}).get("description", "Milestones, experiments, and reviews"),
            "role": (app_role(member, "project_tracker") or {}).get("role", "No access"),
        },
        {
            "app_id": "notebooks_protocols",
            "name": "Notebooks / Protocols",
            "url": reverse("labapps:knowledge"),
            "description": configured.get("notebooks_protocols", {}).get("description", "Private lab knowledge library"),
            "role": (app_role(member, "notebooks_protocols") or {}).get("role", "No access"),
        },
    ]
    visible = [card for card in cards if card["role"] != "No access" or is_portal_admin(member)]
    counts = {
        "members": len(_active(snapshot_rows("Members"))),
        "teams": len(_active(snapshot_rows("Teams"))),
        "projects": len(snapshot_rows("Projects")),
        "protocols": KnowledgeRecord.objects.filter(record_type="protocol").count(),
    }
    return render(request, "labapps/portal.html", {"cards": visible, "counts": counts, "member": member})


@lab_app_access("budget", admin=True)
def portal_admin(request):
    members = snapshot_rows("Members")
    teams = snapshot_rows("Teams")
    apps = snapshot_rows("Apps")
    roles = snapshot_rows("App_Roles")
    member_form = MemberForm(prefix="member")
    team_form = TeamForm(prefix="team")
    role_form = AppRoleForm(prefix="role", members=_active(members), apps=_active(apps), teams=_active(teams))

    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "member":
                member_form = MemberForm(request.POST, prefix="member")
                if member_form.is_valid():
                    cleaned = member_form.cleaned_data
                    existing = next(
                        (row for row in members if row.get("email", "").lower() == cleaned["email"].lower()),
                        None,
                    )
                    member_id = existing.get("member_id") if existing else next_identifier("Members", "M")
                    payload = {
                        "member_id": member_id,
                        "email": cleaned["email"].lower(),
                        "name": cleaned["name"],
                        "display_name": cleaned["display_name"] or cleaned["name"],
                        "global_role": cleaned["global_role"],
                        "active": "TRUE" if cleaned["active"] else "FALSE",
                        "start_date": (existing or {}).get("start_date") or date.today().isoformat(),
                        "end_date": (existing or {}).get("end_date", ""),
                        "password_hash": (existing or {}).get("password_hash", ""),
                        "password_set_at": (existing or {}).get("password_set_at", ""),
                        "password_must_change": (existing or {}).get("password_must_change", "FALSE"),
                        "notes": cleaned["notes"],
                    }
                    upsert_record("Members", payload, actor=_email(request), action="upsert_member")
                    _sync_iap_allowlist_member(payload)
                    append_registry_audit(
                        actor=_email(request), action="upsert_member", target_type="Member",
                        target_id=member_id, before=existing or {}, after=payload,
                    )
                    messages.success(request, "Member saved and verified in Google Sheets.")
                    return redirect("labapps:portal_admin")
            elif action == "team":
                team_form = TeamForm(request.POST, prefix="team")
                if team_form.is_valid():
                    cleaned = team_form.cleaned_data
                    existing = next(
                        (row for row in teams if row.get("team_name", "").lower() == cleaned["team_name"].lower()),
                        None,
                    )
                    team_id = existing.get("team_id") if existing else next_identifier("Teams", "T")
                    payload = {
                        "team_id": team_id,
                        "team_name": cleaned["team_name"],
                        "description": cleaned["description"],
                        "active": "TRUE" if cleaned["active"] else "FALSE",
                    }
                    upsert_record("Teams", payload, actor=_email(request), action="upsert_team")
                    append_registry_audit(
                        actor=_email(request), action="upsert_team", target_type="Team",
                        target_id=team_id, before=existing or {}, after=payload,
                    )
                    messages.success(request, "Team saved and verified in Google Sheets.")
                    return redirect("labapps:portal_admin")
            elif action == "role":
                role_form = AppRoleForm(
                    request.POST, prefix="role", members=_active(members), apps=_active(apps), teams=_active(teams)
                )
                if role_form.is_valid():
                    cleaned = role_form.cleaned_data
                    existing = next(
                        (
                            row for row in roles
                            if row.get("member_id") == cleaned["member_id"]
                            and row.get("app_id") == cleaned["app_id"]
                            and row.get("scope_team_id", "") == cleaned["scope_team_id"]
                        ),
                        None,
                    )
                    role_id = existing.get("app_role_id") if existing else next_identifier("App_Roles", "AR")
                    payload = {
                        "app_role_id": role_id,
                        "member_id": cleaned["member_id"],
                        "app_id": cleaned["app_id"],
                        "app_role": cleaned["app_role"],
                        "scope_team_id": cleaned["scope_team_id"],
                        "active": "TRUE" if cleaned["active"] else "FALSE",
                        "start_date": (existing or {}).get("start_date") or date.today().isoformat(),
                        "end_date": (existing or {}).get("end_date", ""),
                    }
                    upsert_record("App_Roles", payload, actor=_email(request), action="upsert_app_role")
                    if cleaned["scope_team_id"]:
                        memberships = snapshot_rows("Member_Teams")
                        existing_membership = next(
                            (
                                row
                                for row in memberships
                                if row.get("member_id") == cleaned["member_id"]
                                and row.get("team_id") == cleaned["scope_team_id"]
                            ),
                            None,
                        )
                        membership_payload = {
                            "member_team_id": (
                                existing_membership.get("member_team_id")
                                if existing_membership
                                else next_identifier("Member_Teams", "MT")
                            ),
                            "member_id": cleaned["member_id"],
                            "team_id": cleaned["scope_team_id"],
                            "team_role": (
                                "lead"
                                if cleaned["app_role"] in {"lead", "manager", "owner"}
                                else "member"
                            ),
                            "active": "TRUE" if cleaned["active"] else "FALSE",
                            "start_date": (
                                existing_membership or {}
                            ).get("start_date")
                            or date.today().isoformat(),
                            "end_date": (
                                (existing_membership or {}).get("end_date", "")
                                if cleaned["active"]
                                else date.today().isoformat()
                            ),
                        }
                        upsert_record(
                            "Member_Teams",
                            membership_payload,
                            actor=_email(request),
                            action="upsert_member_team",
                        )
                    append_registry_audit(
                        actor=_email(request), action="upsert_app_role", target_type="AppRole",
                        target_id=role_id, before=existing or {}, after=payload,
                    )
                    messages.success(request, "App role saved and verified in Google Sheets.")
                    return redirect("labapps:portal_admin")
        except Exception as error:
            messages.error(request, str(error))

    return render(
        request,
        "labapps/portal_admin.html",
        {
            "members": members,
            "teams": teams,
            "apps": apps,
            "roles": roles,
            "member_lookup": _member_lookup(),
            "member_form": member_form,
            "team_form": team_form,
            "role_form": role_form,
        },
    )


def _scope_tracker_rows(request, projects, milestones, experiments):
    member = current_registry_member(request)
    resolved_roles = app_roles(member, "project_tracker")
    allowed_team_ids = {
        role["scope_team_id"]
        for role in resolved_roles
        if role.get("scope_team_id")
    }
    unrestricted = any(not role.get("scope_team_id") for role in resolved_roles)
    requested = request.GET.get("team", "")
    if unrestricted:
        selected = requested
    elif requested in allowed_team_ids:
        selected = requested
    else:
        selected = sorted(allowed_team_ids)[0] if allowed_team_ids else ""
    member_ids = None
    if selected:
        member_ids = {
            row.get("member_id")
            for row in _active(snapshot_rows("Member_Teams"))
            if row.get("team_id") == selected
        }
        projects = [row for row in projects if row.get("owner_member_id") in member_ids]
        project_ids = {row.get("project_id") for row in projects}
        milestones = [
            row for row in milestones
            if row.get("owner_member_id") in member_ids or row.get("project_id") in project_ids
        ]
        milestone_ids = {row.get("milestone_id") for row in milestones}
        experiments = [
            row for row in experiments
            if row.get("member_id") in member_ids or row.get("milestone_id") in milestone_ids
        ]
    return projects, milestones, experiments, selected


@lab_app_access("project_tracker")
def tracker(request):
    actor = _email(request)
    member = current_registry_member(request)
    members = _active(snapshot_rows("Members"))
    teams = _active(snapshot_rows("Teams"))
    projects = snapshot_rows("Projects")
    milestones = snapshot_rows("Milestones")
    experiments = snapshot_rows("Experiments")
    projects, milestones, experiments, selected_team = _scope_tracker_rows(
        request, projects, milestones, experiments
    )
    can_edit = can_write_scope(member, "project_tracker", selected_team)
    resolved_roles = app_roles(member, "project_tracker")
    allowed_team_ids = {
        role["scope_team_id"]
        for role in resolved_roles
        if role.get("scope_team_id")
    }
    scope_locked = bool(allowed_team_ids) and not any(
        not role.get("scope_team_id") for role in resolved_roles
    )
    if selected_team:
        scoped_member_ids = {
            row.get("member_id")
            for row in _active(snapshot_rows("Member_Teams"))
            if row.get("team_id") == selected_team
        }
        members = [row for row in members if row.get("member_id") in scoped_member_ids]
    if scope_locked:
        teams = [row for row in teams if row.get("team_id") in allowed_team_ids]

    project_form = ProjectForm(prefix="project", members=members)
    milestone_form = MilestoneForm(prefix="milestone", projects=projects, members=members)
    experiment_form = ExperimentForm(prefix="experiment", milestones=milestones, members=members)
    gantt_import_form = GanttImportForm(
        prefix="gantt",
        projects=projects,
        members=members,
    )
    review_form = ReviewForm(prefix="review")
    gantt_preview = request.session.get("gantt_import_preview")

    if request.method == "POST":
        if not can_edit:
            return HttpResponse("Your Project Tracker role is read-only.", status=403)
        action = request.POST.get("action", "")
        try:
            if action == "gantt_preview":
                gantt_import_form = GanttImportForm(
                    request.POST,
                    request.FILES,
                    prefix="gantt",
                    projects=projects,
                    members=members,
                )
                if gantt_import_form.is_valid():
                    cleaned = gantt_import_form.cleaned_data
                    project = next(
                        (
                            row
                            for row in projects
                            if row["project_id"] == cleaned["project_id"]
                        ),
                        None,
                    )
                    if project is None:
                        return HttpResponse(
                            "This project is outside your permitted team scope.",
                            status=403,
                        )
                    parsed = parse_gantt_workbook(cleaned["gantt_file"])
                    resolved_rows, resolution_warnings = resolve_gantt_rows(
                        parsed.rows,
                        project=project,
                        members=members,
                        default_owner_member_id=cleaned["default_owner_member_id"],
                        updated_at=timezone.now().isoformat(timespec="seconds"),
                    )
                    gantt_preview = {
                        "token": secrets.token_urlsafe(18),
                        "actor": actor,
                        "project_id": project["project_id"],
                        "project": project.get("project", ""),
                        "sheet_name": parsed.sheet_name,
                        "header_row": parsed.header_row,
                        "rows": resolved_rows,
                        "warnings": [*parsed.warnings, *resolution_warnings],
                        "errors": parsed.errors,
                    }
                    if parsed.errors:
                        request.session.pop("gantt_import_preview", None)
                    else:
                        request.session["gantt_import_preview"] = gantt_preview
                    request.session.modified = True
            elif action == "gantt_confirm":
                stored = request.session.get("gantt_import_preview") or {}
                if not secrets.compare_digest(
                    str(request.POST.get("preview_token", "")),
                    str(stored.get("token", "")),
                ) or not secrets.compare_digest(
                    actor,
                    str(stored.get("actor", "")),
                ):
                    raise ValueError("The Gantt preview expired. Upload the workbook again.")
                project = next(
                    (
                        row
                        for row in projects
                        if row["project_id"] == stored.get("project_id")
                    ),
                    None,
                )
                if project is None:
                    return HttpResponse(
                        "This project is outside your permitted team scope.",
                        status=403,
                    )
                imported_rows = stored.get("rows") or []
                if not imported_rows:
                    raise ValueError("The Gantt preview does not contain any task rows.")
                replace_project_gantt(
                    project["project_id"],
                    imported_rows,
                    actor=actor,
                )
                request.session.pop("gantt_import_preview", None)
                request.session.modified = True
                messages.success(
                    request,
                    f"{len(imported_rows)} Gantt tasks were saved and verified in Google Sheets.",
                )
                return redirect(
                    f"{reverse('labapps:tracker')}?gantt_project={project['project_id']}#gantt"
                )
            elif action == "gantt_cancel":
                request.session.pop("gantt_import_preview", None)
                request.session.modified = True
                return redirect(f"{reverse('labapps:tracker')}#gantt")
            elif action == "project":
                project_form = ProjectForm(request.POST, prefix="project", members=members)
                if project_form.is_valid():
                    cleaned = project_form.cleaned_data
                    payload = {
                        "project_id": next_identifier("Projects", "P"),
                        "project": cleaned["project"], "aim": cleaned["aim"],
                        "owner_member_id": cleaned["owner_member_id"],
                        "start_date": cleaned["start_date"].isoformat(),
                        "target_date": cleaned["target_date"].isoformat() if cleaned["target_date"] else "",
                        "notes": cleaned["notes"],
                    }
                    upsert_record("Projects", payload, actor=actor, action="create_project")
                    messages.success(request, "Project saved and verified in Google Sheets.")
                    return redirect("labapps:tracker")
            elif action == "milestone":
                milestone_form = MilestoneForm(
                    request.POST, prefix="milestone", projects=projects, members=members
                )
                if milestone_form.is_valid():
                    cleaned = milestone_form.cleaned_data
                    project = next(row for row in projects if row["project_id"] == cleaned["project_id"])
                    payload = {
                        "milestone_id": next_identifier("Milestones", "MS"),
                        "project_id": project["project_id"], "project": project["project"], "aim": project["aim"],
                        "milestone": cleaned["milestone"], "time_window": cleaned["time_window"],
                        "owner_member_id": cleaned["owner_member_id"],
                        "start_date": cleaned["start_date"].isoformat(), "status": cleaned["status"],
                        "review_status": "Pending", "next_action": cleaned["next_action"],
                        "due_date": cleaned["due_date"].isoformat(),
                        "blocker_reason": cleaned["blocker_reason"], "help_needed_from": cleaned["help_needed_from"],
                        "progress_percent": str(cleaned["progress_percent"] or 0),
                        "updated_at": timezone.now().isoformat(timespec="seconds"),
                    }
                    upsert_record("Milestones", payload, actor=actor, action="create_milestone")
                    append_history(record_type="Milestone", record_id=payload["milestone_id"], actor=actor, new_status=payload["status"], review_status="Pending")
                    messages.success(request, "Milestone saved and verified in Google Sheets.")
                    return redirect("labapps:tracker")
            elif action == "experiment":
                experiment_form = ExperimentForm(
                    request.POST, prefix="experiment", milestones=milestones, members=members
                )
                if experiment_form.is_valid():
                    cleaned = experiment_form.cleaned_data
                    milestone = next(row for row in milestones if row["milestone_id"] == cleaned["milestone_id"])
                    payload = {
                        "experiment_id": next_identifier("Experiments", "EXP"),
                        "milestone_id": milestone["milestone_id"], "project_id": milestone["project_id"],
                        "member_id": cleaned["member_id"], "experiment_title": cleaned["experiment_title"],
                        "experiment_type": cleaned["experiment_type"], "status": cleaned["status"],
                        "review_status": "Pending", "next_action": cleaned["next_action"],
                        "due_date": cleaned["due_date"].isoformat(),
                        "experiment_data_link": cleaned["experiment_data_link"] or "",
                        "protocol_link": cleaned["protocol_link"] or "",
                        "analysis_folder_link": cleaned["analysis_folder_link"] or "",
                        "blocker_reason": cleaned["blocker_reason"], "help_needed_from": cleaned["help_needed_from"],
                        "updated_at": timezone.now().isoformat(timespec="seconds"),
                    }
                    upsert_record("Experiments", payload, actor=actor, action="create_experiment")
                    append_history(record_type="Experiment", record_id=payload["experiment_id"], actor=actor, new_status=payload["status"], review_status="Pending")
                    messages.success(request, "Experiment saved and verified in Google Sheets.")
                    return redirect("labapps:tracker")
            elif action == "update":
                table_name = request.POST.get("table_name", "")
                record_id = request.POST.get("record_id", "")
                if table_name not in {"Milestones", "Experiments"}:
                    raise ValueError("Unsupported tracker record.")
                key = "milestone_id" if table_name == "Milestones" else "experiment_id"
                scoped_rows = milestones if table_name == "Milestones" else experiments
                current = next((row for row in scoped_rows if row.get(key) == record_id), None)
                if current is None:
                    return HttpResponse("This record is outside your permitted team scope.", status=403)
                updated = {
                    **current,
                    "status": request.POST.get("status", current.get("status", "")),
                    "next_action": request.POST.get("next_action", current.get("next_action", "")),
                    "review_status": "Pending",
                    "blocker_reason": request.POST.get(
                        "blocker_reason",
                        current.get("blocker_reason", ""),
                    ),
                    "help_needed_from": request.POST.get(
                        "help_needed_from",
                        current.get("help_needed_from", ""),
                    ),
                    "updated_at": timezone.now().isoformat(timespec="seconds"),
                }
                if table_name == "Milestones":
                    try:
                        progress = float(
                            request.POST.get(
                                "progress_percent",
                                current.get("progress_percent") or 0,
                            )
                        )
                    except ValueError as error:
                        raise ValueError("Progress must be a number from 0 to 100.") from error
                    if not 0 <= progress <= 100:
                        raise ValueError("Progress must be a number from 0 to 100.")
                    updated["progress_percent"] = str(progress)
                else:
                    updated["experiment_data_link"] = django_forms.URLField(
                        required=False,
                        assume_scheme="https",
                    ).clean(
                        request.POST.get(
                            "experiment_data_link",
                            current.get("experiment_data_link", ""),
                        )
                    )
                upsert_record(table_name, updated, actor=actor, action="update_progress")
                append_history(
                    record_type=table_name[:-1], record_id=record_id, actor=actor,
                    update_note=request.POST.get("update_note", ""), old_status=current.get("status", ""),
                    new_status=updated["status"], review_status="Pending",
                )
                messages.success(request, "Progress update saved and verified in Google Sheets.")
                return redirect("labapps:tracker")
            elif action == "review":
                review_form = ReviewForm(request.POST, prefix="review")
                if review_form.is_valid():
                    cleaned = review_form.cleaned_data
                    table_name = f"{cleaned['record_type']}s"
                    key = "milestone_id" if table_name == "Milestones" else "experiment_id"
                    scoped_rows = milestones if table_name == "Milestones" else experiments
                    current = next(
                        (row for row in scoped_rows if row.get(key) == cleaned["record_id"]),
                        None,
                    )
                    if current is None:
                        return HttpResponse("This record is outside your permitted team scope.", status=403)
                    updated = {**current, "review_status": cleaned["review_status"], "updated_at": timezone.now().isoformat(timespec="seconds")}
                    upsert_record(table_name, updated, actor=actor, action="review_record")
                    append_history(
                        record_type=cleaned["record_type"], record_id=cleaned["record_id"], actor="",
                        reviewed_by=actor, review_status=cleaned["review_status"], review_note=cleaned["review_note"],
                    )
                    messages.success(request, "Review saved and verified in Google Sheets.")
                    return redirect("labapps:tracker")
        except Exception as error:
            messages.error(request, str(error))

    pending = [
        {"record_type": "Milestone", "record_id": row["milestone_id"], "title": row["milestone"], **row}
        for row in milestones if row.get("review_status") == "Pending"
    ] + [
        {"record_type": "Experiment", "record_id": row["experiment_id"], "title": row["experiment_title"], **row}
        for row in experiments if row.get("review_status") == "Pending"
    ]
    blocked = sum(row.get("status") == "Blocked" for row in [*milestones, *experiments])
    requested_gantt_project_id = (
        request.POST.get("gantt-project_id", "")
        if request.method == "POST" and request.POST.get("action") == "gantt_preview"
        else request.GET.get("gantt_project", "")
    )
    selected_gantt_project = next(
        (
            project
            for project in projects
            if project.get("project_id") == requested_gantt_project_id
        ),
        projects[0] if projects else None,
    )
    member_lookup = _member_lookup()
    member_display = {
        member_id: _display_member(member_id, member_lookup)
        for member_id in member_lookup
    }
    gantt = build_gantt_context(selected_gantt_project, milestones, member_display)
    return render(
        request,
        "labapps/tracker.html",
        {
            "projects": projects, "milestones": milestones, "experiments": experiments,
            "pending": pending, "teams": teams, "selected_team": selected_team,
            "scope_locked": scope_locked,
            "members": member_lookup, "can_edit": can_edit,
            "counts": {"projects": len(projects), "milestones": len(milestones), "experiments": len(experiments), "pending": len(pending), "blocked": blocked},
            "project_form": project_form, "milestone_form": milestone_form,
            "experiment_form": experiment_form, "review_form": review_form,
            "gantt_import_form": gantt_import_form,
            "gantt_preview": gantt_preview,
            "gantt": gantt,
            "selected_gantt_project": selected_gantt_project,
        },
    )


@lab_app_access("notebooks_protocols")
def knowledge(request):
    member = current_registry_member(request)
    can_edit = can_write(member, "notebooks_protocols")
    status_filter = request.GET.get("status", "available").strip().lower()
    allowed_status_filters = {
        "available",
        "all",
        "active",
        "candidate",
        "indexed",
        "draft",
        "archived",
    }
    if status_filter not in allowed_status_filters:
        status_filter = "available"
    if not can_edit and status_filter in {"draft", "archived", "all"}:
        status_filter = "available"
    team_filter = request.GET.get("team", "").strip()
    category_filter = request.GET.get("category", "").strip()
    type_filter = request.GET.get("type", "").strip().lower()
    if type_filter not in {"", "protocol", "notebook"}:
        type_filter = ""
    browse_all = request.GET.get("browse", "") == "1"
    search_query = request.GET.get("q", "").strip()[:120]
    search_terms = search_query.casefold().split()

    records_queryset = KnowledgeRecord.objects.all()
    if status_filter == "available":
        records_queryset = records_queryset.filter(status__in=AVAILABLE_STATUSES)
    elif status_filter != "all":
        records_queryset = records_queryset.filter(status=status_filter)
    if team_filter:
        records_queryset = records_queryset.filter(team=team_filter)
    if category_filter:
        records_queryset = records_queryset.filter(category=category_filter)
    if type_filter:
        records_queryset = records_queryset.filter(record_type=type_filter)

    canonical_filter = Q(canonical_record_id="") | Q(
        canonical_record_id=F("record_id")
    )
    canonical_queryset = records_queryset.filter(canonical_filter)
    available_canonical = KnowledgeRecord.objects.filter(
        status__in=AVAILABLE_STATUSES
    ).filter(canonical_filter)
    protocols = list(
        available_canonical.filter(record_type="protocol")
        .only("record_id", "record_type", "title", "status")
        .order_by("title", "record_id")
    )
    notebooks = list(
        available_canonical.filter(record_type="notebook")
        .only("record_id", "record_type", "title", "status")
        .order_by("title", "record_id")
    )

    matched_ids = set()
    if search_terms:
        indexed_matches = records_queryset.exclude(search_text="")
        for term in search_terms:
            indexed_matches = indexed_matches.filter(search_text__icontains=term)
        for record_id, canonical_id in indexed_matches.values_list(
            "record_id", "canonical_record_id"
        ):
            matched_ids.add(canonical_id or record_id)
        for row in records_queryset.filter(search_text=""):
            haystack = " ".join(
                [
                    row.record_id,
                    row.title,
                    row.team,
                    row.owner,
                    row.category,
                    row.original_filename,
                    json.dumps(row.metadata, ensure_ascii=False, default=str),
                ]
            ).casefold()
            if all(term in haystack for term in search_terms):
                matched_ids.add(row.canonical_record_id or row.record_id)

    show_results = bool(
        search_query
        or browse_all
        or team_filter
        or category_filter
        or type_filter
        or status_filter != "available"
    )
    if search_terms:
        result_queryset = canonical_queryset.filter(record_id__in=matched_ids)
    elif show_results:
        result_queryset = canonical_queryset
    else:
        result_queryset = canonical_queryset.none()
    result_queryset = result_queryset.only(
        "record_id",
        "record_type",
        "title",
        "team",
        "owner",
        "category",
        "status",
        "object_name",
        "original_filename",
        "updated_at",
    ).order_by("-updated_at", "title", "record_id")
    paginator = Paginator(result_queryset, 20)
    search_page = paginator.get_page(request.GET.get("page", 1))
    for row in search_page.object_list:
        row.public_status = public_status(row.status)

    selected_id = (
        request.GET.get("record", "")
        or request.GET.get("protocol", "")
    ).strip()
    selected_record = None
    selected_aliases = []
    selected_preview = {}
    original_previewable = False
    if selected_id:
        selected_lookup = KnowledgeRecord.objects.filter(
            record_id=selected_id
        ).only("record_id", "canonical_record_id", "status").first()
        if selected_lookup:
            canonical_id = (
                selected_lookup.canonical_record_id
                or selected_lookup.record_id
            )
            selected_record = KnowledgeRecord.objects.filter(
                record_id=canonical_id
            ).first()
            if (
                selected_record
                and not can_edit
                and selected_record.status in {"draft", "archived"}
            ):
                selected_record = None
            elif selected_record:
                selected_record.public_status = public_status(
                    selected_record.status
                )
                selected_aliases = list(
                    KnowledgeRecord.objects.filter(
                        canonical_record_id=selected_record.record_id
                    )
                    .exclude(record_id=selected_record.record_id)
                    .only("record_id", "title", "source_path")
                    .order_by("record_id")
                )
                selected_preview = build_document_preview(
                    selected_record.metadata
                )
                selected_content_type = (
                    selected_record.metadata.get("content_type")
                    or mimetypes.guess_type(
                        selected_record.original_filename
                    )[0]
                    or ""
                )
                original_previewable = selected_content_type in {
                    "application/pdf",
                    "text/plain",
                    "text/markdown",
                    "image/png",
                    "image/jpeg",
                    "image/gif",
                    "image/webp",
                }

    query_params = request.GET.copy()
    query_params.pop("record", None)
    query_params.pop("protocol", None)
    query_params.pop("page", None)
    return render(
        request,
        "labapps/knowledge.html",
        {
            "protocols": protocols,
            "notebooks": notebooks,
            "selected_record": selected_record,
            "selected_aliases": selected_aliases,
            "selected_preview": selected_preview,
            "original_previewable": original_previewable,
            "can_edit": can_edit,
            "counts": {
                "protocols": len(protocols),
                "notebooks": len(notebooks),
                "duplicates": KnowledgeRecord.objects.filter(
                    status__in=AVAILABLE_STATUSES
                )
                .exclude(canonical_record_id="")
                .exclude(canonical_record_id=F("record_id"))
                .count(),
            },
            "search_query": search_query,
            "search_page": search_page,
            "search_results": search_page.object_list,
            "search_total": paginator.count,
            "show_results": show_results,
            "status_filter": status_filter,
            "team_filter": team_filter,
            "category_filter": category_filter,
            "type_filter": type_filter,
            "browse_all": browse_all,
            "query_base": query_params.urlencode(),
            "team_choices": list(
                KnowledgeRecord.objects.exclude(team="")
                .order_by("team")
                .values_list("team", flat=True)
                .distinct()
            ),
            "category_choices": list(
                KnowledgeRecord.objects.exclude(category="")
                .order_by("category")
                .values_list("category", flat=True)
                .distinct()
            ),
        },
    )


@lab_app_access("notebooks_protocols", write=True)
def knowledge_upload(request):
    form = KnowledgeUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        upload = form.cleaned_data["files"]
        record_type = form.cleaned_data["record_type"]
        prefix = "P" if record_type == "protocol" else "N"
        record_id = f"{prefix}-{timezone.localtime().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2).upper()}"
        try:
            content = upload.read()
            parsed = extract_knowledge_metadata(
                upload.name,
                content,
                upload.content_type or "",
            )
            metadata = {
                "notes": form.cleaned_data["notes"],
                "content_type": upload.content_type or "",
            }
            metadata.update(parsed)
            key, digest = store_knowledge_file(
                record_id,
                upload.name,
                content,
                upload.content_type or "application/octet-stream",
            )
            metadata["sha256"] = digest
            duplicate = (
                KnowledgeRecord.objects.filter(
                    record_type=record_type,
                    content_sha256=digest,
                )
                .only("record_id", "canonical_record_id")
                .order_by("created_at", "record_id")
                .first()
            )
            canonical_record_id = (
                duplicate.canonical_record_id or duplicate.record_id
                if duplicate
                else record_id
            )
            try:
                with transaction.atomic():
                    record = KnowledgeRecord.objects.create(
                        record_id=record_id, record_type=record_type, title=form.cleaned_data["title"],
                        team=form.cleaned_data["team"], owner=form.cleaned_data["owner"],
                        category=form.cleaned_data["category"],
                        status=form.cleaned_data["status"],
                        object_name=key,
                        original_filename=upload.name, uploaded_by=_email(request),
                        content_sha256=digest,
                        canonical_record_id=canonical_record_id,
                        search_text=build_search_text(
                            record_id=record_id,
                            record_type=record_type,
                            title=form.cleaned_data["title"],
                            team=form.cleaned_data["team"],
                            owner=form.cleaned_data["owner"],
                            category=form.cleaned_data["category"],
                            original_filename=upload.name,
                            metadata=metadata,
                        ),
                        metadata=metadata,
                    )
                    LabAppAudit.objects.create(
                        actor=_email(request), app_id="notebooks_protocols", action="upload",
                        target=record.record_id,
                        after={
                            "record_id": record.record_id,
                            "sha256": digest,
                            "canonical_record_id": canonical_record_id,
                            "parse_status": parsed.get("parse_status"),
                            "section_count": parsed.get("section_count", 0),
                        },
                    )
            except Exception:
                try:
                    delete_knowledge_file(key)
                except Exception:
                    pass
                raise
            if parsed.get("parse_status") == "parsed":
                messages.success(
                    request,
                    f"Private file uploaded and parsed into {parsed.get('section_count', 0)} sections.",
                )
            else:
                messages.warning(
                    request,
                    "Private file uploaded, but automatic text extraction was not completed. "
                    + parsed.get("parse_message", ""),
                )
            return redirect(
                f"{reverse('labapps:knowledge')}?record={canonical_record_id}#record"
            )
        except Exception as error:
            messages.error(request, str(error))
    return render(request, "labapps/knowledge_upload.html", {"form": form})


@require_POST
@lab_app_access("notebooks_protocols", write=True)
def knowledge_reprocess(request, record_id):
    try:
        record = KnowledgeRecord.objects.get(record_id=record_id)
    except KnowledgeRecord.DoesNotExist as error:
        raise Http404 from error
    if not record.object_name:
        raise Http404("The original file has not been migrated to private storage yet.")

    content = read_knowledge_file(record.object_name)
    expected_digest = str(record.metadata.get("sha256") or "")
    actual_digest = hashlib.sha256(content).hexdigest()
    if expected_digest and not secrets.compare_digest(expected_digest, actual_digest):
        LabAppAudit.objects.create(
            actor=_email(request),
            app_id="notebooks_protocols",
            action="reprocess_checksum_mismatch",
            target=record.record_id,
            before={"sha256": expected_digest},
            after={"sha256": actual_digest},
        )
        messages.error(
            request,
            "Reprocessing stopped because the stored original does not match its recorded checksum.",
        )
        return redirect(
            f"{reverse('labapps:knowledge')}?record={record.canonical_record_id or record.record_id}#record"
        )

    parsed = extract_knowledge_metadata(
        record.original_filename,
        content,
        record.metadata.get("content_type", ""),
    )
    before = {
        "parse_status": record.metadata.get("parse_status", ""),
        "section_count": record.metadata.get("section_count", 0),
    }
    metadata = dict(record.metadata)
    reprocessed_at = timezone.now().isoformat()
    if parsed.get("parse_status") == "parsed":
        for key in EXTRACTED_METADATA_KEYS:
            metadata.pop(key, None)
        metadata.update(parsed)
        metadata.update(
            {
                "last_reprocess_status": "success",
                "last_reprocess_error": "",
                "last_reprocess_at": reprocessed_at,
            }
        )
    else:
        error_message = parsed.get("parse_message", "")
        metadata.update(
            {
                "last_reprocess_status": "failed",
                "last_reprocess_error": error_message,
                "last_reprocess_at": reprocessed_at,
            }
        )
        if not metadata.get("sections"):
            metadata.update(
                {
                    "parse_status": parsed.get("parse_status"),
                    "parser": parsed.get("parser"),
                    "parse_message": error_message,
                }
            )
    with transaction.atomic():
        record.metadata = metadata
        record.search_text = build_search_text(
            record_id=record.record_id,
            record_type=record.record_type,
            title=record.title,
            team=record.team,
            owner=record.owner,
            category=record.category,
            original_filename=record.original_filename,
            metadata=metadata,
        )
        record.save(update_fields=["metadata", "search_text", "updated_at"])
        LabAppAudit.objects.create(
            actor=_email(request),
            app_id="notebooks_protocols",
            action="reprocess_content",
            target=record.record_id,
            before=before,
            after={
                "parse_status": metadata.get("parse_status"),
                "section_count": metadata.get("section_count", 0),
            },
        )
    if parsed.get("parse_status") == "parsed":
        messages.success(
            request,
            f"Document content reprocessed into {parsed.get('section_count', 0)} sections.",
        )
    else:
        messages.error(
            request,
            "Automatic text extraction failed. " + parsed.get("parse_message", ""),
        )
    return redirect(
        f"{reverse('labapps:knowledge')}?record={record.canonical_record_id or record.record_id}#record"
    )


@lab_app_access("notebooks_protocols")
def knowledge_download(request, record_id):
    try:
        record = KnowledgeRecord.objects.get(record_id=record_id)
    except KnowledgeRecord.DoesNotExist as error:
        raise Http404 from error
    if not record.object_name:
        raise Http404("The original file has not been migrated to private storage yet.")
    content_type = record.metadata.get("content_type") or mimetypes.guess_type(record.original_filename)[0] or "application/octet-stream"
    response = FileResponse(
        open_knowledge_file(record.object_name),
        content_type=content_type,
    )
    response["Content-Disposition"] = content_disposition_header(
        True,
        record.original_filename or record.record_id,
    )
    return response


@lab_app_access("notebooks_protocols")
def knowledge_original(request, record_id):
    try:
        record = KnowledgeRecord.objects.get(record_id=record_id)
    except KnowledgeRecord.DoesNotExist as error:
        raise Http404 from error
    if not record.object_name:
        raise Http404("The original file has not been migrated to private storage yet.")
    content_type = (
        record.metadata.get("content_type")
        or mimetypes.guess_type(record.original_filename)[0]
        or "application/octet-stream"
    )
    inline_types = {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "image/png",
        "image/jpeg",
        "image/gif",
        "image/webp",
    }
    if content_type not in inline_types:
        return redirect("labapps:knowledge_download", record_id=record.record_id)
    response = FileResponse(
        open_knowledge_file(record.object_name),
        content_type=content_type,
    )
    response["Content-Disposition"] = content_disposition_header(
        False,
        record.original_filename or record.record_id,
    )
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_POST
@lab_app_access("notebooks_protocols", write=True)
def knowledge_status(request, record_id):
    try:
        record = KnowledgeRecord.objects.get(record_id=record_id)
    except KnowledgeRecord.DoesNotExist as error:
        raise Http404 from error
    form = KnowledgeStatusForm(request.POST)
    if not form.is_valid():
        return HttpResponse("Select a valid knowledge-record status.", status=400)
    before = {"status": record.status}
    record.status = form.cleaned_data["status"]
    record.save(update_fields=["status", "updated_at"])
    LabAppAudit.objects.create(
        actor=_email(request),
        app_id="notebooks_protocols",
        action="status_updated",
        target=record.record_id,
        before=before,
        after={"status": record.status},
    )
    messages.success(request, f"{record.title} is now {record.status}.")
    return redirect(
        f"{reverse('labapps:knowledge')}?status={record.status}&record={record.canonical_record_id or record.record_id}#record"
    )
