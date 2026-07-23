from contextlib import nullcontext
from unittest.mock import patch

import pytest

from labapps.models import LabAppAudit
from labapps.services.sheets import TRACKER_HEADERS, replace_project_gantt


pytestmark = pytest.mark.django_db


class FakeGateway:
    @staticmethod
    def _column_label(column):
        return chr(64 + column)


class FakeWorksheet:
    def __init__(self):
        self.rows = []
        self.cleared = []

    def update(self, *, values, range_name, value_input_option):
        assert range_name == "A1"
        assert value_input_option == "RAW"
        headers = values[0]
        self.rows = [
            dict(zip(headers, row, strict=True))
            for row in values[1:]
        ]

    def batch_clear(self, ranges):
        self.cleared.extend(ranges)

    def get_all_records(self):
        return self.rows


def test_replace_project_gantt_merges_against_latest_sheet_rows():
    live_before = [
        {
            "milestone_id": "MS001",
            "project_id": "P001",
            "milestone": "Concurrent manual update",
        },
        {
            "milestone_id": "MS-GANTT-OLD",
            "project_id": "P001",
            "milestone": "Old imported task",
        },
        {
            "milestone_id": "MS-GANTT-OTHER",
            "project_id": "P002",
            "milestone": "Other project task",
        },
    ]
    imported = [
        {
            "milestone_id": "MS-GANTT-NEW",
            "project_id": "P001",
            "milestone": "New imported task",
            "progress_percent": "50",
        }
    ]
    worksheet = FakeWorksheet()

    with (
        patch("labapps.services.sheets._assert_write_allowed"),
        patch("labapps.services.sheets._sheet_write_lock", return_value=nullcontext()),
        patch(
            "labapps.services.sheets._live_table",
            return_value=(FakeGateway(), worksheet, live_before),
        ),
        patch("labapps.services.sheets.sync_table") as sync_table,
    ):
        saved = replace_project_gantt(
            "P001",
            imported,
            actor="kk4801@nyu.edu",
        )

    ids = {row["milestone_id"] for row in saved}
    assert ids == {"MS001", "MS-GANTT-OTHER", "MS-GANTT-NEW"}
    assert "MS-GANTT-OLD" not in ids
    assert worksheet.rows == saved
    assert list(worksheet.rows[0]) == TRACKER_HEADERS["Milestones"]
    sync_table.assert_called_once()
    audit = LabAppAudit.objects.get()
    assert audit.action == "import_project_gantt"
    assert {
        row["milestone_id"] for row in audit.before["rows"]
    } == {"MS001", "MS-GANTT-OLD", "MS-GANTT-OTHER"}
