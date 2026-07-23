from io import BytesIO

from openpyxl import Workbook

from labapps.services.gantt import (
    build_gantt_context,
    merge_project_gantt,
    parse_gantt_workbook,
    resolve_gantt_rows,
)


def vertex_style_workbook():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Project schedule"
    sheet.append(["", "TASK", "ASSIGNED TO", "PROGRESS", "START", "END"])
    sheet.append(["", "Planning", "", "", "", ""])
    sheet.append(["", "Define scope", "member@nyu.edu", 0.5, "09/01/2026", "09/05/2026"])
    sheet.append(["", "Run pilot", "Unknown Person", 100, "09/06/2026", "09/12/2026"])
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_parse_vertex_style_gantt_workbook():
    result = parse_gantt_workbook(vertex_style_workbook())

    assert result.sheet_name == "Project schedule"
    assert result.errors == []
    assert len(result.rows) == 2
    assert result.rows[0] == {
        "source_row": 3,
        "milestone_id": "",
        "phase": "Planning",
        "task": "Define scope",
        "assigned_to": "member@nyu.edu",
        "progress_percent": 50.0,
        "start_date": "2026-09-01",
        "due_date": "2026-09-05",
        "status": "In progress",
        "next_action": "",
    }
    assert result.rows[1]["status"] == "Completed"


def test_parse_rejects_non_excel_content():
    result = parse_gantt_workbook(b"not an Excel workbook")

    assert result.rows == []
    assert result.errors
    assert "could not be read safely" in result.errors[0]


def test_resolve_and_merge_gantt_rows_are_idempotent_and_preserve_manual_rows():
    parsed = parse_gantt_workbook(vertex_style_workbook())
    project = {"project_id": "P001", "project": "Chip study", "aim": "Model disease"}
    members = [
        {
            "member_id": "M001",
            "email": "member@nyu.edu",
            "name": "Lab Member",
            "display_name": "Member",
        },
        {"member_id": "M002", "email": "lead@nyu.edu", "display_name": "Lead"},
    ]

    first, warnings = resolve_gantt_rows(
        parsed.rows,
        project=project,
        members=members,
        default_owner_member_id="M002",
        updated_at="2026-07-23T12:00:00+04:00",
    )
    second, _ = resolve_gantt_rows(
        parsed.rows,
        project=project,
        members=members,
        default_owner_member_id="M002",
        updated_at="2026-07-23T12:00:00+04:00",
    )

    assert [row["milestone_id"] for row in first] == [
        row["milestone_id"] for row in second
    ]
    assert first[0]["owner_member_id"] == "M001"
    assert first[1]["owner_member_id"] == "M002"
    assert "Unknown Person" in warnings[0]

    existing = [
        {"milestone_id": "MS001", "project_id": "P001", "milestone": "Manual"},
        {"milestone_id": "MS-GANTT-OLD", "project_id": "P001", "milestone": "Old"},
        {"milestone_id": "MS-GANTT-OTHER", "project_id": "P002", "milestone": "Other"},
    ]
    merged = merge_project_gantt(existing, "P001", first)
    ids = {row["milestone_id"] for row in merged}

    assert "MS001" in ids
    assert "MS-GANTT-OLD" not in ids
    assert "MS-GANTT-OTHER" in ids
    assert {row["milestone_id"] for row in first}.issubset(ids)


def test_build_gantt_context_uses_project_specific_rows():
    project = {"project_id": "P001", "project": "Chip study"}
    milestones = [
        {
            "milestone_id": "MS1",
            "project_id": "P001",
            "milestone": "Pilot",
            "time_window": "Setup",
            "owner_member_id": "M001",
            "start_date": "2026-09-01",
            "due_date": "2026-09-10",
            "progress_percent": "60",
            "status": "In progress",
        },
        {
            "milestone_id": "MS2",
            "project_id": "P002",
            "milestone": "Outside scope",
            "start_date": "2026-08-01",
            "due_date": "2026-12-01",
        },
    ]

    gantt = build_gantt_context(project, milestones, {"M001": "Ken"})

    assert len(gantt["rows"]) == 1
    assert gantt["rows"][0]["milestone"] == "Pilot"
    assert gantt["rows"][0]["owner"] == "Ken"
    assert gantt["rows"][0]["progress_width"] == 60.0
    assert gantt["start_date"].isoformat() == "2026-09-01"
    assert gantt["end_date"].isoformat() == "2026-09-10"
