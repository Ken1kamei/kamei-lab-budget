import json
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from budget.services.sheets import (
    SheetsGateway,
    SheetsSourceError,
    _registry_spreadsheet_id,
    _sheet_write_lock,
)
from labapps.models import LabAppAudit, SheetRecord


DUBAI = ZoneInfo("Asia/Dubai")
DEFAULT_REGISTRY_SPREADSHEET_ID = "1gZU_0tG10O2JuliAq6Hdy3GONVCSBAAuiQAKXNug2Lk"
REGISTRY_HEADERS = {
    "Members": [
        "member_id", "email", "name", "display_name", "global_role", "active",
        "start_date", "end_date", "password_hash", "password_set_at",
        "password_must_change", "notes",
    ],
    "Teams": ["team_id", "team_name", "description", "active"],
    "Member_Teams": [
        "member_team_id", "member_id", "team_id", "team_role", "active",
        "start_date", "end_date",
    ],
    "Apps": [
        "app_id", "app_name", "app_url", "description", "category", "active", "sort_order",
    ],
    "App_Roles": [
        "app_role_id", "member_id", "app_id", "app_role", "scope_team_id",
        "active", "start_date", "end_date",
    ],
    "Audit_Log": [
        "audit_id", "timestamp", "actor_email", "action", "target_type",
        "target_id", "before", "after",
    ],
}
TRACKER_HEADERS = {
    "Projects": [
        "project_id", "project", "aim", "owner_member_id", "start_date",
        "target_date", "notes",
    ],
    "Milestones": [
        "milestone_id", "project_id", "project", "aim", "milestone", "time_window",
        "owner_member_id", "start_date", "status", "review_status", "next_action",
        "due_date", "blocker_reason", "help_needed_from", "progress_percent",
        "updated_at",
    ],
    "Experiments": [
        "experiment_id", "milestone_id", "project_id", "member_id", "experiment_title",
        "experiment_type", "status", "review_status", "next_action", "due_date",
        "experiment_data_link", "protocol_link", "analysis_folder_link", "blocker_reason",
        "help_needed_from", "updated_at",
    ],
    "Updates_Reviews": [
        "update_id", "record_type", "record_id", "updated_by", "update_note",
        "old_status", "new_status", "reviewed_by", "review_status", "review_note", "timestamp",
    ],
}
KEY_COLUMNS = {
    "Members": "member_id",
    "Teams": "team_id",
    "Member_Teams": "member_team_id",
    "Apps": "app_id",
    "App_Roles": "app_role_id",
    "Audit_Log": "audit_id",
    "Projects": "project_id",
    "Milestones": "milestone_id",
    "Experiments": "experiment_id",
    "Updates_Reviews": "update_id",
}


def _source_for(table_name):
    return "registry" if table_name in REGISTRY_HEADERS else "tracker"


def _spreadsheet_id(source):
    registry_id = (
        settings.REGISTRY_SPREADSHEET_ID
        or _registry_spreadsheet_id()
        or DEFAULT_REGISTRY_SPREADSHEET_ID
    )
    spreadsheet_id = registry_id if source == "registry" else (
        settings.PROGRESS_SPREADSHEET_ID or registry_id
    )
    if not spreadsheet_id:
        raise SheetsSourceError(f"The {source} spreadsheet ID is not configured.")
    return spreadsheet_id


def _headers(table_name):
    return (REGISTRY_HEADERS | TRACKER_HEADERS)[table_name]


def _normalize_rows(table_name, rows):
    headers = _headers(table_name)
    normalized = []
    for raw in rows:
        row = {header: str(raw.get(header, "") or "").strip() for header in headers}
        if any(row.values()):
            normalized.append(row)
    return normalized


def _live_table(table_name, gateway=None):
    source = _source_for(table_name)
    gateway = gateway or SheetsGateway()
    workbook = gateway._open(_spreadsheet_id(source))
    worksheet = workbook.worksheet(table_name)
    return gateway, worksheet, _normalize_rows(table_name, worksheet.get_all_records())


def sync_table(table_name, gateway=None):
    gateway, _, rows = _live_table(table_name, gateway)
    source = _source_for(table_name)
    key_column = KEY_COLUMNS[table_name]
    now = timezone.now()
    seen = []
    with transaction.atomic():
        for position, row in enumerate(rows, start=1):
            record_id = row.get(key_column) or f"row-{position}"
            seen.append(record_id)
            SheetRecord.objects.update_or_create(
                source=source,
                table_name=table_name,
                record_id=record_id,
                defaults={"payload": row, "synced_at": now},
            )
        SheetRecord.objects.filter(source=source, table_name=table_name).exclude(
            record_id__in=seen
        ).delete()
    return rows


def sync_all():
    gateway = SheetsGateway()
    counts = {}
    for table_name in [*REGISTRY_HEADERS, *TRACKER_HEADERS]:
        counts[table_name] = len(sync_table(table_name, gateway))
    return counts


def snapshot_rows(table_name):
    source = _source_for(table_name)
    return [
        record.payload
        for record in SheetRecord.objects.filter(source=source, table_name=table_name)
    ]


def _assert_write_allowed(actor):
    if not settings.ENABLE_SHEET_WRITES:
        raise SheetsSourceError("Google Sheet writes are disabled in this environment.")
    allowed = settings.SHEET_WRITE_ALLOWED_EMAILS
    actor = str(actor or "").strip().lower()
    if "*" not in allowed and actor not in allowed:
        raise SheetsSourceError("This account is not enabled for the Web parallel-write period.")


def replace_table(table_name, rows, *, actor, action, target, before=None):
    _assert_write_allowed(actor)
    source = _source_for(table_name)
    headers = _headers(table_name)
    rows = _normalize_rows(table_name, rows)
    with _sheet_write_lock():
        gateway, worksheet, live_before = _live_table(table_name)
        values = [headers, *[[row.get(header, "") for header in headers] for row in rows]]
        worksheet.update(values=values, range_name="A1", value_input_option="RAW")
        old_last_row = len(live_before) + 1
        if old_last_row > len(values):
            end_column = gateway._column_label(len(headers))
            worksheet.batch_clear([f"A{len(values) + 1}:{end_column}{old_last_row}"])
        readback = _normalize_rows(table_name, worksheet.get_all_records())
        if readback != rows:
            raise SheetsSourceError(f"{table_name} write verification failed.")
        sync_table(table_name, gateway)
    LabAppAudit.objects.create(
        actor=actor,
        app_id=source,
        action=action,
        target=target,
        before=before if before is not None else {"rows": live_before},
        after={"rows": rows},
    )
    return rows


def replace_project_gantt(project_id, imported_rows, *, actor):
    _assert_write_allowed(actor)
    table_name = "Milestones"
    source = _source_for(table_name)
    headers = _headers(table_name)
    imported_rows = _normalize_rows(table_name, imported_rows)
    with _sheet_write_lock():
        gateway, worksheet, live_before = _live_table(table_name)
        live_before = _normalize_rows(table_name, live_before)
        preserved = [
            row
            for row in live_before
            if not (
                row.get("project_id") == project_id
                and row.get("milestone_id", "").startswith("MS-GANTT-")
            )
        ]
        rows = [*preserved, *imported_rows]
        values = [headers, *[[row.get(header, "") for header in headers] for row in rows]]
        worksheet.update(values=values, range_name="A1", value_input_option="RAW")
        old_last_row = len(live_before) + 1
        if old_last_row > len(values):
            end_column = gateway._column_label(len(headers))
            worksheet.batch_clear([f"A{len(values) + 1}:{end_column}{old_last_row}"])
        readback = _normalize_rows(table_name, worksheet.get_all_records())
        if readback != rows:
            raise SheetsSourceError("Milestones Gantt import verification failed.")
        sync_table(table_name, gateway)
    LabAppAudit.objects.create(
        actor=actor,
        app_id=source,
        action="import_project_gantt",
        target=f"Projects:{project_id}:gantt",
        before={"rows": live_before},
        after={"rows": rows},
    )
    return rows


def next_identifier(table_name, prefix):
    key = KEY_COLUMNS[table_name]
    numbers = []
    for row in snapshot_rows(table_name):
        value = str(row.get(key, ""))
        suffix = value.removeprefix(prefix).lstrip("-")
        if value.startswith(prefix) and suffix.isdigit():
            numbers.append(int(suffix))
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def upsert_record(table_name, payload, *, actor, action="upsert"):
    rows = snapshot_rows(table_name)
    key = KEY_COLUMNS[table_name]
    record_id = str(payload.get(key, "")).strip()
    if not record_id:
        raise ValueError(f"{key} is required.")
    before = next((row for row in rows if str(row.get(key, "")) == record_id), {})
    replaced = False
    output = []
    for row in rows:
        if str(row.get(key, "")) == record_id:
            output.append({**row, **payload})
            replaced = True
        else:
            output.append(row)
    if not replaced:
        output.append(payload)
    return replace_table(
        table_name,
        output,
        actor=actor,
        action=action,
        target=f"{table_name}:{record_id}",
        before=before,
    )


def append_history(*, record_type, record_id, actor, update_note="", old_status="", new_status="", reviewed_by="", review_status="", review_note=""):
    payload = {
        "update_id": f"UPD-{secrets.token_hex(5).upper()}",
        "record_type": record_type,
        "record_id": record_id,
        "updated_by": actor,
        "update_note": update_note,
        "old_status": old_status,
        "new_status": new_status,
        "reviewed_by": reviewed_by,
        "review_status": review_status,
        "review_note": review_note,
        "timestamp": datetime.now(DUBAI).isoformat(timespec="seconds"),
    }
    return upsert_record("Updates_Reviews", payload, actor=actor, action="append_history")


def append_registry_audit(*, actor, action, target_type, target_id, before, after):
    payload = {
        "audit_id": f"AUD-{secrets.token_hex(6).upper()}",
        "timestamp": datetime.now(DUBAI).isoformat(timespec="seconds"),
        "actor_email": actor,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "before": json.dumps(before, sort_keys=True),
        "after": json.dumps(after, sort_keys=True),
    }
    return upsert_record("Audit_Log", payload, actor=actor, action="append_audit")
