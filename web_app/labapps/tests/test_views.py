import hashlib
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
import zipfile

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from openpyxl import Workbook

from budget.models import LabMember
from labapps.models import KnowledgeRecord, LabAppAudit, SheetRecord
from labapps.tests.test_knowledge import protocol_docx_bytes


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
    assert b"Kamei_Lab_Protocol_Template.docx" in knowledge.content
    assert b"Download protocol template" in knowledge.content
    assert b">Transactions<" not in knowledge.content


def test_portal_uses_integrated_routes_even_with_legacy_registry_urls():
    seed_pi()
    legacy_urls = {
        "budget": "https://legacy-budget.example.streamlit.app/",
        "project_tracker": "https://legacy-tracker.example.streamlit.app/",
        "notebooks_protocols": "https://legacy-knowledge.example.streamlit.app/",
    }
    for index, (app_id, app_url) in enumerate(legacy_urls.items(), start=1):
        add_record(
            "Apps",
            f"APP-{index}",
            {
                "app_id": app_id,
                "app_name": app_id,
                "app_url": app_url,
                "description": f"{app_id} description",
                "active": "TRUE",
            },
        )

    response = signed_in_client().get("/portal/")

    assert response.status_code == 200
    assert b"streamlit.app" not in response.content
    assert b'href="/"' in response.content
    assert b'href="/tracker/"' in response.content
    assert b'href="/knowledge/"' in response.content


def test_protocol_template_is_valid_and_linked_from_upload_page():
    seed_pi()
    template = (
        Path(__file__).resolve().parents[2]
        / "labapps/static/labapps/Kamei_Lab_Protocol_Template.docx"
    )
    assert template.exists()
    assert zipfile.is_zipfile(template)

    response = signed_in_client().get("/knowledge/upload/")
    assert response.status_code == 200
    assert b"Kamei_Lab_Protocol_Template.docx" in response.content
    assert b"Download protocol template" in response.content


def test_protocol_template_is_available_to_read_only_members():
    add_record(
        "Members",
        "M002",
        {
            "member_id": "M002",
            "email": "member@nyu.edu",
            "display_name": "Lab member",
            "global_role": "member",
            "active": "TRUE",
        },
    )
    add_record(
        "App_Roles",
        "AR-notebooks-reader",
        {
            "member_id": "M002",
            "app_id": "notebooks_protocols",
            "app_role": "viewer",
            "scope_team_id": "",
            "active": "TRUE",
        },
    )

    response = client_for("member@nyu.edu").get("/knowledge/")
    assert response.status_code == 200
    assert b"Kamei_Lab_Protocol_Template.docx" in response.content
    assert b"Download protocol template" in response.content
    assert b'href="/knowledge/upload/"' not in response.content


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


def test_knowledge_record_can_be_archived_and_restored():
    seed_pi()
    record = KnowledgeRecord.objects.create(
        record_id="P-LIFECYCLE",
        record_type="protocol",
        title="Lifecycle protocol",
        status="active",
    )
    client = signed_in_client()

    archived = client.post(
        f"/knowledge/{record.record_id}/status/",
        {"status": "archived"},
    )

    assert archived.status_code == 302
    record.refresh_from_db()
    assert record.status == "archived"
    active_page = client.get("/knowledge/")
    archived_page = client.get("/knowledge/?status=archived")
    assert list(active_page.context["protocols"]) == []
    assert [row.record_id for row in archived_page.context["protocols"]] == [
        "P-LIFECYCLE"
    ]
    audit = LabAppAudit.objects.get(
        target=record.record_id,
        action="status_updated",
    )
    assert audit.before == {"status": "active"}
    assert audit.after == {"status": "archived"}


def test_portal_member_save_updates_budget_iap_allowlist(
    monkeypatch,
    settings,
):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"*"}
    seed_pi()

    def fake_upsert(table_name, payload, **kwargs):
        key = {
            "Members": "member_id",
            "Teams": "team_id",
            "App_Roles": "app_role_id",
            "Member_Teams": "member_team_id",
        }[table_name]
        add_record(table_name, payload[key], payload)
        return payload

    monkeypatch.setattr("labapps.views.upsert_record", fake_upsert)
    monkeypatch.setattr("labapps.views.append_registry_audit", lambda **kwargs: None)
    client = signed_in_client()

    response = client.post(
        "/portal/admin/",
        {
            "action": "member",
            "member-email": "new.member@nyu.edu",
            "member-name": "New Member",
            "member-display_name": "New Member",
            "member-global_role": "member",
            "member-active": "on",
            "member-notes": "",
        },
    )

    assert response.status_code == 302
    allowlisted = LabMember.objects.get(email="new.member@nyu.edu")
    assert allowlisted.display_name == "New Member"
    assert allowlisted.highest_role == "member"
    assert allowlisted.active is True


def test_portal_member_demotion_revokes_budget_pi_role(
    monkeypatch,
    settings,
):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"*"}
    seed_pi()
    LabMember.objects.create(
        email="former.pi@nyu.edu",
        display_name="Former PI",
        highest_role="pi",
        active=True,
    )
    add_record(
        "Members",
        "M009",
        {
            "member_id": "M009",
            "email": "former.pi@nyu.edu",
            "name": "Former PI",
            "display_name": "Former PI",
            "global_role": "pi",
            "active": "TRUE",
        },
    )

    def fake_upsert(table_name, payload, **kwargs):
        SheetRecord.objects.update_or_create(
            source="registry",
            table_name=table_name,
            record_id=payload["member_id"],
            defaults={"payload": payload},
        )
        return payload

    monkeypatch.setattr("labapps.views.upsert_record", fake_upsert)
    monkeypatch.setattr("labapps.views.append_registry_audit", lambda **kwargs: None)

    response = signed_in_client().post(
        "/portal/admin/",
        {
            "action": "member",
            "member-email": "former.pi@nyu.edu",
            "member-name": "Former PI",
            "member-display_name": "Former PI",
            "member-global_role": "member",
            "member-active": "on",
            "member-notes": "",
        },
    )

    assert response.status_code == 302
    assert LabMember.objects.get(
        email="former.pi@nyu.edu"
    ).highest_role == "member"


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


def test_tracker_member_with_two_scoped_roles_can_switch_between_both_teams():
    add_record(
        "Members",
        "M002",
        {
            "member_id": "M002",
            "email": "multiteam@nyu.edu",
            "display_name": "Multi Team",
            "active": "TRUE",
        },
    )
    for team_id, team_name in (("T001", "IoC"), ("T002", "Diabetes")):
        add_record(
            "Teams",
            team_id,
            {"team_id": team_id, "team_name": team_name, "active": "TRUE"},
        )
        add_record(
            "Member_Teams",
            f"MT-{team_id}",
            {
                "member_team_id": f"MT-{team_id}",
                "member_id": "M002",
                "team_id": team_id,
                "active": "TRUE",
            },
        )
        add_record(
            "App_Roles",
            f"AR-{team_id}",
            {
                "member_id": "M002",
                "app_id": "project_tracker",
                "app_role": "lead",
                "scope_team_id": team_id,
                "active": "TRUE",
            },
        )
        add_record(
            "Projects",
            f"P-{team_id}",
            {
                "project_id": f"P-{team_id}",
                "project": f"{team_name} project",
                "owner_member_id": "M002",
            },
            source="tracker",
        )

    client = client_for("multiteam@nyu.edu")
    ioc = client.get("/tracker/?team=T001")
    diabetes = client.get("/tracker/?team=T002")

    assert ioc.status_code == diabetes.status_code == 200
    assert b"IoC project" in ioc.content
    assert b"Diabetes project" in diabetes.content


def test_tracker_viewer_scope_stays_read_only_when_another_scope_is_lead():
    add_record(
        "Members",
        "M002",
        {
            "member_id": "M002",
            "email": "mixed@nyu.edu",
            "display_name": "Mixed Role",
            "active": "TRUE",
        },
    )
    add_record(
        "Members",
        "M003",
        {
            "member_id": "M003",
            "email": "owner@nyu.edu",
            "display_name": "Owner",
            "active": "TRUE",
        },
    )
    for team_id, team_name, role in (
        ("T001", "IoC", "viewer"),
        ("T002", "Diabetes", "lead"),
    ):
        add_record(
            "Teams",
            team_id,
            {"team_id": team_id, "team_name": team_name, "active": "TRUE"},
        )
        add_record(
            "App_Roles",
            f"AR-{team_id}",
            {
                "member_id": "M002",
                "app_id": "project_tracker",
                "app_role": role,
                "scope_team_id": team_id,
                "active": "TRUE",
            },
        )
    add_record(
        "Member_Teams",
        "MT-OWNER",
        {
            "member_team_id": "MT-OWNER",
            "member_id": "M003",
            "team_id": "T001",
            "active": "TRUE",
        },
    )
    add_record(
        "Milestones",
        "MS-VIEW",
        {
            "milestone_id": "MS-VIEW",
            "milestone": "Viewer-only milestone",
            "owner_member_id": "M003",
            "status": "In progress",
            "review_status": "Pending",
        },
        source="tracker",
    )

    response = client_for("mixed@nyu.edu").post(
        "/tracker/?team=T001",
        {
            "action": "update",
            "table_name": "Milestones",
            "record_id": "MS-VIEW",
            "status": "Completed",
            "next_action": "Tampered",
        },
    )

    assert response.status_code == 403
    assert SheetRecord.objects.get(
        table_name="Milestones",
        record_id="MS-VIEW",
    ).payload["status"] == "In progress"


def test_tracker_rejects_unsafe_experiment_data_url():
    seed_pi()
    add_record(
        "Experiments",
        "EXP-URL",
        {
            "experiment_id": "EXP-URL",
            "experiment_title": "URL validation",
            "member_id": "M001",
            "status": "In progress",
            "review_status": "Pending",
            "experiment_data_link": "https://example.com/data",
        },
        source="tracker",
    )

    response = signed_in_client().post(
        "/tracker/",
        {
            "action": "update",
            "table_name": "Experiments",
            "record_id": "EXP-URL",
            "status": "In progress",
            "next_action": "Keep safe",
            "experiment_data_link": "javascript:alert(1)",
        },
    )

    assert response.status_code == 200
    assert SheetRecord.objects.get(
        table_name="Experiments",
        record_id="EXP-URL",
    ).payload["experiment_data_link"] == "https://example.com/data"


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
    assert record.metadata["parse_status"] == "failed"
    mock_store.assert_called_once()


@patch(
    "labapps.views.store_knowledge_file",
    return_value=("knowledge/P1/mef.docx", "docx-sha"),
)
def test_protocol_upload_extracts_and_displays_structured_content(mock_store):
    seed_pi()
    client = signed_in_client()
    content = protocol_docx_bytes()

    response = client.post(
        "/knowledge/upload/",
        {
            "record_type": "protocol",
            "title": "MEF preparation protocol",
            "team": "Common",
            "owner": "Ken",
            "category": "Cell culture",
            "notes": "Uploaded from the lab template",
            "files": SimpleUploadedFile(
                "MEF_protocol.docx",
                content,
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
        },
    )

    assert response.status_code == 302
    record = KnowledgeRecord.objects.get(title="MEF preparation protocol")
    assert record.metadata["parse_status"] == "parsed"
    assert record.metadata["section_count"] == 3
    assert record.metadata["procedure"] == [
        "Collect each embryo separately.",
        "Plate cells in complete medium.",
    ]
    assert mock_store.call_args.args[2] == content

    detail = client.get(f"/knowledge/?protocol={record.record_id}")
    assert b"Prepare primary MEFs from individual embryos." in detail.content
    assert b"DMEM" in detail.content
    assert b"Collect each embryo separately." in detail.content
    assert f"/knowledge/{record.record_id}/reprocess/".encode() in detail.content


def test_upload_deletes_new_object_when_database_persistence_fails():
    seed_pi()
    client = signed_in_client()
    with (
        patch(
            "labapps.views.store_knowledge_file",
            return_value=("knowledge/P-ORPHAN/protocol.docx", "stored-sha"),
        ),
        patch(
            "labapps.views.KnowledgeRecord.objects.create",
            side_effect=RuntimeError("database unavailable"),
        ),
        patch("labapps.views.delete_knowledge_file") as mock_delete,
    ):
        response = client.post(
            "/knowledge/upload/",
            {
                "record_type": "protocol",
                "title": "Atomic protocol",
                "team": "Common",
                "owner": "Ken",
                "category": "Cell culture",
                "notes": "",
                "files": SimpleUploadedFile(
                    "protocol.docx",
                    protocol_docx_bytes(),
                    content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                ),
            },
        )

    assert response.status_code == 200
    assert b"database unavailable" in response.content
    mock_delete.assert_called_once_with(
        "knowledge/P-ORPHAN/protocol.docx"
    )


@patch("labapps.views.read_knowledge_file", return_value=protocol_docx_bytes())
def test_existing_protocol_can_be_reprocessed_without_losing_metadata(mock_read):
    seed_pi()
    record = KnowledgeRecord.objects.create(
        record_id="P-MEF",
        record_type="protocol",
        title="MEF preparation protocol",
        team="Common",
        owner="Ken",
        status="active",
        object_name="knowledge/P-MEF/mef.docx",
        original_filename="MEF_protocol.docx",
        metadata={
            "notes": "Keep this note",
            "sha256": hashlib.sha256(mock_read.return_value).hexdigest(),
            "content_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )
    client = signed_in_client()

    response = client.post(f"/knowledge/{record.record_id}/reprocess/")

    assert response.status_code == 302
    record.refresh_from_db()
    assert record.metadata["notes"] == "Keep this note"
    assert record.metadata["sha256"] == hashlib.sha256(
        mock_read.return_value
    ).hexdigest()
    assert record.metadata["parse_status"] == "parsed"
    assert record.metadata["section_count"] == 3
    mock_read.assert_called_once_with("knowledge/P-MEF/mef.docx")
    assert LabAppAudit.objects.filter(
        target="P-MEF",
        action="reprocess_content",
    ).exists()


@patch("labapps.views.read_knowledge_file", return_value=b"changed")
def test_reprocess_stops_when_original_checksum_changed(mock_read):
    seed_pi()
    record = KnowledgeRecord.objects.create(
        record_id="P-CHECKSUM",
        record_type="protocol",
        title="Checksum protocol",
        object_name="knowledge/P-CHECKSUM/protocol.docx",
        original_filename="protocol.docx",
        metadata={"sha256": hashlib.sha256(b"original").hexdigest()},
    )

    response = signed_in_client().post(
        f"/knowledge/{record.record_id}/reprocess/"
    )

    assert response.status_code == 302
    record.refresh_from_db()
    assert "sections" not in record.metadata
    assert LabAppAudit.objects.filter(
        target="P-CHECKSUM",
        action="reprocess_checksum_mismatch",
    ).exists()
    mock_read.assert_called_once()


@patch("labapps.views.read_knowledge_file", return_value=b"broken-docx")
def test_failed_reprocess_preserves_old_content_and_shows_stale_warning(mock_read):
    seed_pi()
    record = KnowledgeRecord.objects.create(
        record_id="P-STALE",
        record_type="protocol",
        title="Previously parsed protocol",
        object_name="knowledge/P-STALE/protocol.docx",
        original_filename="protocol.docx",
        metadata={
            "sha256": hashlib.sha256(b"broken-docx").hexdigest(),
            "parse_status": "parsed",
            "section_count": 1,
            "sections": [
                {
                    "heading": "Procedure",
                    "blocks": [
                        {"kind": "paragraph", "text": "Previously extracted step"}
                    ],
                }
            ],
        },
    )
    client = signed_in_client()

    response = client.post(f"/knowledge/{record.record_id}/reprocess/")

    assert response.status_code == 302
    record.refresh_from_db()
    assert record.metadata["parse_status"] == "parsed"
    assert record.metadata["last_reprocess_status"] == "failed"
    assert record.metadata["sections"][0]["heading"] == "Procedure"

    detail = client.get(f"/knowledge/?protocol={record.record_id}")
    assert b"Previously extracted step" in detail.content
    assert b"latest reprocessing attempt failed" in detail.content
    mock_read.assert_called_once()


@patch("labapps.views.read_knowledge_file")
def test_read_only_member_cannot_reprocess_protocol(mock_read):
    add_record(
        "Members",
        "M002",
        {
            "member_id": "M002",
            "email": "member@nyu.edu",
            "display_name": "Lab member",
            "global_role": "member",
            "active": "TRUE",
        },
    )
    add_record(
        "App_Roles",
        "AR-notebooks-reader",
        {
            "member_id": "M002",
            "app_id": "notebooks_protocols",
            "app_role": "viewer",
            "scope_team_id": "",
            "active": "TRUE",
        },
    )
    KnowledgeRecord.objects.create(
        record_id="P-LOCKED",
        record_type="protocol",
        title="Locked protocol",
        object_name="knowledge/P-LOCKED/protocol.docx",
        original_filename="protocol.docx",
    )

    response = client_for("member@nyu.edu").post(
        "/knowledge/P-LOCKED/reprocess/"
    )

    assert response.status_code == 403
    mock_read.assert_not_called()
