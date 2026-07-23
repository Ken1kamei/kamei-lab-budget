from unittest.mock import patch
from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from openpyxl import Workbook

from labapps.models import KnowledgeRecord, SheetRecord


pytestmark = pytest.mark.django_db


def add_record(table, record_id, payload, source="registry"):
    SheetRecord.objects.create(
        source=source, table_name=table, record_id=record_id, payload=payload
    )


def signed_in_client():
    user = get_user_model().objects.create_user(
        username="kk4801@nyu.edu", email="kk4801@nyu.edu"
    )
    client = Client()
    client.force_login(user)
    return client


def client_for(email):
    user = get_user_model().objects.create_user(username=email, email=email)
    client = Client()
    client.force_login(user)
    return client


def gantt_upload():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Gantt Import"
    sheet.append(
        [
            "Phase",
            "Task",
            "Assigned to",
            "Start Date",
            "End Date",
            "Progress %",
            "Status",
            "Next Action",
        ]
    )
    sheet.append(
        [
            "Planning",
            "Define scope",
            "kk4801@nyu.edu",
            "2026-09-01",
            "2026-09-05",
            50,
            "In progress",
            "Review scope",
        ]
    )
    buffer = BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(
        "project-gantt.xlsx",
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def invalid_gantt_upload():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Gantt Import"
    sheet.append(["Task", "Start Date", "End Date"])
    sheet.append(["Impossible task", "2026-09-10", "2026-09-01"])
    buffer = BytesIO()
    workbook.save(buffer)
    return SimpleUploadedFile(
        "invalid-gantt.xlsx",
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


def seed_pi():
    add_record(
        "Members", "M001",
        {"member_id": "M001", "email": "kk4801@nyu.edu", "display_name": "Ken", "global_role": "pi", "active": "TRUE"},
    )
    for app_id in ["budget", "project_tracker", "notebooks_protocols"]:
        add_record(
            "App_Roles", f"AR-{app_id}",
            {"member_id": "M001", "app_id": app_id, "app_role": "owner", "scope_team_id": "", "active": "TRUE"},
        )


def test_portal_tracker_and_knowledge_pages_render():
    seed_pi()
    add_record("Projects", "P001", {"project_id": "P001", "project": "Chip study", "owner_member_id": "M001"}, source="tracker")
    KnowledgeRecord.objects.create(
        record_id="P-0001", record_type="protocol", title="GSIS", team="Diabetes",
        metadata={"overview": ["Prepare buffer"]},
    )
    client = signed_in_client()
    portal = client.get("/portal/")
    tracker = client.get("/tracker/")
    knowledge = client.get("/knowledge/")
    assert portal.status_code == tracker.status_code == knowledge.status_code == 200
    assert b"Kamei Lab Apps" in portal.content
    assert b'class="sidebar"' not in portal.content
    assert b"Chip study" in tracker.content
    assert b'href="/tracker/#projects"' in tracker.content
    assert b">Transactions<" not in tracker.content
    assert b">Notebooks / protocols<" not in tracker.content
    assert b"Gantt chart" in tracker.content
    assert b"Kamei_Lab_Gantt_Import_Template.xlsx" in tracker.content
    assert b"Prepare buffer" in knowledge.content
    assert b"Notebook registry" not in knowledge.content
    assert b"Find notebooks and protocols" in knowledge.content
    assert b'href="/knowledge/#protocols"' in knowledge.content
    assert b'href="/knowledge/#search"' in knowledge.content
    assert b'href="/knowledge/upload/"' in knowledge.content
    assert b">Transactions<" not in knowledge.content


@patch("labapps.views.replace_project_gantt")
def test_gantt_upload_previews_then_replaces_only_imported_project_rows(mock_replace):
    seed_pi()
    add_record(
        "Projects",
        "P001",
        {
            "project_id": "P001",
            "project": "Chip study",
            "aim": "Model disease",
            "owner_member_id": "M001",
        },
        source="tracker",
    )
    add_record(
        "Milestones",
        "MS001",
        {
            "milestone_id": "MS001",
            "project_id": "P001",
            "milestone": "Manual milestone",
            "owner_member_id": "M001",
        },
        source="tracker",
    )
    add_record(
        "Milestones",
        "MS-GANTT-OLD",
        {
            "milestone_id": "MS-GANTT-OLD",
            "project_id": "P001",
            "milestone": "Previous import",
            "owner_member_id": "M001",
        },
        source="tracker",
    )
    add_record(
        "Milestones",
        "MS-GANTT-OTHER",
        {
            "milestone_id": "MS-GANTT-OTHER",
            "project_id": "P002",
            "milestone": "Another project",
            "owner_member_id": "M001",
        },
        source="tracker",
    )
    client = signed_in_client()

    preview = client.post(
        "/tracker/",
        {
            "action": "gantt_preview",
            "gantt-project_id": "P001",
            "gantt-default_owner_member_id": "M001",
            "gantt-gantt_file": gantt_upload(),
        },
    )

    assert preview.status_code == 200
    assert b"Import preview" in preview.content
    assert b"Define scope" in preview.content
    stored = client.session["gantt_import_preview"]
    assert stored["project_id"] == "P001"
    assert stored["actor"] == "kk4801@nyu.edu"
    assert len(stored["rows"]) == 1

    confirm = client.post(
        "/tracker/",
        {
            "action": "gantt_confirm",
            "preview_token": stored["token"],
        },
    )

    assert confirm.status_code == 302
    assert "gantt_project=P001" in confirm["Location"]
    assert mock_replace.call_args.args[0] == "P001"
    saved_rows = mock_replace.call_args.args[1]
    assert any(
        row["milestone"] == "Define scope"
        and row["milestone_id"].startswith("MS-GANTT-")
        for row in saved_rows
    )


@patch("labapps.views.replace_project_gantt")
def test_invalid_gantt_preview_cannot_be_confirmed(mock_replace):
    seed_pi()
    add_record(
        "Projects",
        "P001",
        {
            "project_id": "P001",
            "project": "Chip study",
            "owner_member_id": "M001",
        },
        source="tracker",
    )
    client = signed_in_client()

    preview = client.post(
        "/tracker/",
        {
            "action": "gantt_preview",
            "gantt-project_id": "P001",
            "gantt-default_owner_member_id": "M001",
            "gantt-gantt_file": invalid_gantt_upload(),
        },
    )

    assert preview.status_code == 200
    assert b"ends before its start date" in preview.content
    assert "gantt_import_preview" not in client.session
    assert b"Confirm and save to Google Sheets" not in preview.content
    mock_replace.assert_not_called()


@patch("labapps.views.replace_project_gantt")
def test_read_only_project_tracker_role_cannot_upload_gantt(mock_replace):
    add_record(
        "Members",
        "M004",
        {
            "member_id": "M004",
            "email": "viewer@nyu.edu",
            "display_name": "Viewer",
            "active": "TRUE",
        },
    )
    add_record(
        "App_Roles",
        "AR-viewer",
        {
            "member_id": "M004",
            "app_id": "project_tracker",
            "app_role": "viewer",
            "scope_team_id": "",
            "active": "TRUE",
        },
    )
    add_record(
        "Projects",
        "P001",
        {
            "project_id": "P001",
            "project": "Chip study",
            "owner_member_id": "M004",
        },
        source="tracker",
    )
    client = client_for("viewer@nyu.edu")

    response = client.post(
        "/tracker/",
        {
            "action": "gantt_preview",
            "gantt-project_id": "P001",
            "gantt-default_owner_member_id": "M004",
            "gantt-gantt_file": gantt_upload(),
        },
    )

    assert response.status_code == 403
    assert "gantt_import_preview" not in client.session
    mock_replace.assert_not_called()


def test_knowledge_keyword_search_matches_notebooks_and_protocol_content():
    seed_pi()
    KnowledgeRecord.objects.create(
        record_id="P-0001", record_type="protocol", title="GSIS workflow",
        team="Diabetes", metadata={"overview": ["Prepare assay buffer"]},
    )
    KnowledgeRecord.objects.create(
        record_id="N-0001", record_type="notebook", title="Buffer optimization",
        owner="Satoshi", team="IoC", original_filename="buffer-notes.pdf",
    )
    KnowledgeRecord.objects.create(
        record_id="N-0002", record_type="notebook", title="Unrelated imaging log",
        owner="Maab", team="IoC",
    )

    client = signed_in_client()
    response = client.get("/knowledge/?q=buffer")

    assert response.status_code == 200
    assert response.context["search_total"] == 2
    assert b"GSIS workflow" in response.content
    assert b"Buffer optimization" in response.content
    assert b"Unrelated imaging log" not in response.content
    assert b"Notebook registry" not in response.content


def test_scoped_tracker_role_cannot_switch_to_another_team():
    add_record(
        "Members", "M002",
        {"member_id": "M002", "email": "lead@nyu.edu", "display_name": "Lead", "active": "TRUE"},
    )
    add_record(
        "Members", "M003",
        {"member_id": "M003", "email": "other@nyu.edu", "display_name": "Other", "active": "TRUE"},
    )
    add_record("Teams", "T001", {"team_id": "T001", "team_name": "IoC", "active": "TRUE"})
    add_record("Teams", "T002", {"team_id": "T002", "team_name": "Diabetes", "active": "TRUE"})
    add_record(
        "Member_Teams", "MT002",
        {"member_team_id": "MT002", "member_id": "M002", "team_id": "T002", "active": "TRUE"},
    )
    add_record(
        "Member_Teams", "MT003",
        {"member_team_id": "MT003", "member_id": "M003", "team_id": "T001", "active": "TRUE"},
    )
    add_record(
        "App_Roles", "AR002",
        {"member_id": "M002", "app_id": "project_tracker", "app_role": "lead", "scope_team_id": "T002", "active": "TRUE"},
    )
    add_record(
        "Projects", "P001",
        {"project_id": "P001", "project": "Other team project", "owner_member_id": "M003"},
        source="tracker",
    )
    add_record(
        "Projects", "P002",
        {"project_id": "P002", "project": "Scoped project", "owner_member_id": "M002"},
        source="tracker",
    )
    add_record(
        "Milestones", "MS001",
        {
            "milestone_id": "MS001", "project_id": "P001",
            "milestone": "Other team milestone", "owner_member_id": "M003",
            "status": "In progress", "review_status": "Pending",
        },
        source="tracker",
    )

    client = client_for("lead@nyu.edu")
    response = client.get("/tracker/?team=T001")

    assert response.status_code == 200
    assert b"Scoped project" in response.content
    assert b"Other team project" not in response.content
    assert b"Diabetes" in response.content
    assert b"IoC" not in response.content

    update = client.post(
        "/tracker/",
        {
            "action": "update", "table_name": "Milestones", "record_id": "MS001",
            "status": "Completed", "next_action": "Tampered",
        },
    )
    review = client.post(
        "/tracker/",
        {
            "action": "review", "review-record_type": "Milestone",
            "review-record_id": "MS001", "review-review_status": "Approved",
            "review-review_note": "Tampered",
        },
    )

    assert update.status_code == 403
    assert review.status_code == 403
    milestone = SheetRecord.objects.get(table_name="Milestones", record_id="MS001")
    assert milestone.payload["status"] == "In progress"
    assert milestone.payload["review_status"] == "Pending"


@patch("labapps.views.store_knowledge_file", return_value=("knowledge/N1/file.pdf", "abc123"))
def test_private_knowledge_upload_creates_record(mock_store):
    seed_pi()
    client = signed_in_client()
    response = client.post(
        "/knowledge/upload/",
        {
            "record_type": "protocol", "title": "New protocol", "team": "IoC",
            "owner": "Ken", "category": "Assay", "notes": "verified",
            "files": SimpleUploadedFile("protocol.pdf", b"PDF", content_type="application/pdf"),
        },
    )
    assert response.status_code == 302
    record = KnowledgeRecord.objects.get(title="New protocol")
    assert record.object_name == "knowledge/N1/file.pdf"
    assert record.metadata["sha256"] == "abc123"
    mock_store.assert_called_once()
