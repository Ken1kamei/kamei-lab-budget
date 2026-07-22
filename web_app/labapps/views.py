import mimetypes
import secrets
from datetime import date

from django.contrib import messages
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    AppRoleForm,
    ExperimentForm,
    KnowledgeUploadForm,
    MemberForm,
    MilestoneForm,
    ProjectForm,
    ReviewForm,
    TeamForm,
)
from .models import KnowledgeRecord, LabAppAudit, SheetRecord
from .permissions import (
    app_role,
    can_write,
    current_registry_member,
    is_portal_admin,
    lab_app_access,
    registry_access,
    truthy,
)
from .services.sheets import (
    append_history,
    append_registry_audit,
    next_identifier,
    snapshot_rows,
    upsert_record,
)
from .services.storage import read_knowledge_file, store_knowledge_file


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


@registry_access
def portal(request):
    member = current_registry_member(request)
    base = request.build_absolute_uri("/").rstrip("/")
    configured = {row["app_id"]: row for row in _active(snapshot_rows("Apps"))}
    cards = [
        {
            "app_id": "budget",
            "name": "Budget Manager",
            "url": f"{base}/",
            "description": configured.get("budget", {}).get("description", "Lab budget and invoice management"),
            "role": (app_role(member, "budget") or {}).get("role", "No access"),
        },
        {
            "app_id": "project_tracker",
            "name": "Project Tracker",
            "url": f"{base}/tracker/",
            "description": configured.get("project_tracker", {}).get("description", "Milestones, experiments, and reviews"),
            "role": (app_role(member, "project_tracker") or {}).get("role", "No access"),
        },
        {
            "app_id": "notebooks_protocols",
            "name": "Notebooks / Protocols",
            "url": f"{base}/knowledge/",
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
    resolved = app_role(member, "project_tracker") or {}
    team_id = resolved.get("scope_team_id", "")
    selected = team_id or request.GET.get("team", "")
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
    can_edit = can_write(member, "project_tracker")
    members = _active(snapshot_rows("Members"))
    teams = _active(snapshot_rows("Teams"))
    projects = snapshot_rows("Projects")
    milestones = snapshot_rows("Milestones")
    experiments = snapshot_rows("Experiments")
    projects, milestones, experiments, selected_team = _scope_tracker_rows(
        request, projects, milestones, experiments
    )
    scope_locked = bool((app_role(member, "project_tracker") or {}).get("scope_team_id"))
    if selected_team:
        scoped_member_ids = {
            row.get("member_id")
            for row in _active(snapshot_rows("Member_Teams"))
            if row.get("team_id") == selected_team
        }
        members = [row for row in members if row.get("member_id") in scoped_member_ids]
    if scope_locked:
        teams = [row for row in teams if row.get("team_id") == selected_team]

    project_form = ProjectForm(prefix="project", members=members)
    milestone_form = MilestoneForm(prefix="milestone", projects=projects, members=members)
    experiment_form = ExperimentForm(prefix="experiment", milestones=milestones, members=members)
    review_form = ReviewForm(prefix="review")

    if request.method == "POST":
        if not can_edit:
            return HttpResponse("Your Project Tracker role is read-only.", status=403)
        action = request.POST.get("action", "")
        try:
            if action == "project":
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
                    "updated_at": timezone.now().isoformat(timespec="seconds"),
                }
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
    return render(
        request,
        "labapps/tracker.html",
        {
            "projects": projects, "milestones": milestones, "experiments": experiments,
            "pending": pending, "teams": teams, "selected_team": selected_team,
            "scope_locked": scope_locked,
            "members": _member_lookup(), "can_edit": can_edit,
            "counts": {"projects": len(projects), "milestones": len(milestones), "experiments": len(experiments), "pending": len(pending), "blocked": blocked},
            "project_form": project_form, "milestone_form": milestone_form,
            "experiment_form": experiment_form, "review_form": review_form,
        },
    )


@lab_app_access("notebooks_protocols")
def knowledge(request):
    member = current_registry_member(request)
    protocols = KnowledgeRecord.objects.filter(record_type="protocol")
    notebooks = KnowledgeRecord.objects.filter(record_type="notebook")
    selected_id = request.GET.get("protocol", "")
    selected_protocol = protocols.filter(record_id=selected_id).first() if selected_id else protocols.first()
    return render(
        request,
        "labapps/knowledge.html",
        {
            "protocols": protocols, "notebooks": notebooks, "selected_protocol": selected_protocol,
            "can_edit": can_write(member, "notebooks_protocols"),
            "counts": {"protocols": protocols.count(), "notebooks": notebooks.count()},
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
            key, digest = store_knowledge_file(
                record_id, upload.name, upload.read(), upload.content_type or "application/octet-stream"
            )
            record = KnowledgeRecord.objects.create(
                record_id=record_id, record_type=record_type, title=form.cleaned_data["title"],
                team=form.cleaned_data["team"], owner=form.cleaned_data["owner"],
                category=form.cleaned_data["category"], status="active", object_name=key,
                original_filename=upload.name, uploaded_by=_email(request),
                metadata={"notes": form.cleaned_data["notes"], "sha256": digest, "content_type": upload.content_type or ""},
            )
            LabAppAudit.objects.create(
                actor=_email(request), app_id="notebooks_protocols", action="upload",
                target=record.record_id, after={"record_id": record.record_id, "sha256": digest},
            )
            messages.success(request, "Private file uploaded and registered.")
            return redirect("labapps:knowledge")
        except Exception as error:
            messages.error(request, str(error))
    return render(request, "labapps/knowledge_upload.html", {"form": form})


@lab_app_access("notebooks_protocols")
def knowledge_download(request, record_id):
    try:
        record = KnowledgeRecord.objects.get(record_id=record_id)
    except KnowledgeRecord.DoesNotExist as error:
        raise Http404 from error
    if not record.object_name:
        raise Http404("The original file has not been migrated to private storage yet.")
    content = read_knowledge_file(record.object_name)
    content_type = record.metadata.get("content_type") or mimetypes.guess_type(record.original_filename)[0] or "application/octet-stream"
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{record.original_filename}"'
    return response
