from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import call_command

from labapps.models import KnowledgeRecord


pytestmark = pytest.mark.django_db


@patch(
    "labapps.management.commands.sync_lab_apps._seed_payload",
    return_value=[
        {
            "protocol_id": "P-MEF",
            "title": "MEF preparation protocol",
            "team": "Common",
            "status": "active",
            "overview": ["Stale legacy overview"],
            "procedure": ["Stale legacy step"],
            "original_filename": "",
        }
    ],
)
@patch(
    "labapps.management.commands.sync_lab_apps.sync_all",
    return_value={"registry": 1},
)
def test_sync_preserves_extracted_content(mock_sync, mock_seed):
    KnowledgeRecord.objects.create(
        record_id="P-MEF",
        record_type="protocol",
        title="Old title",
        original_filename="MEF_protocol.docx",
        metadata={
            "parse_status": "parsed",
            "sections": [{"heading": "Procedure", "blocks": []}],
            "overview": ["Current extracted overview"],
            "procedure": ["Current extracted step"],
        },
    )

    call_command("sync_lab_apps", stdout=StringIO())

    record = KnowledgeRecord.objects.get(record_id="P-MEF")
    assert record.title == "MEF preparation protocol"
    assert record.metadata["parse_status"] == "parsed"
    assert record.metadata["sections"] == [
        {"heading": "Procedure", "blocks": []}
    ]
    assert record.metadata["overview"] == ["Current extracted overview"]
    assert record.metadata["procedure"] == ["Current extracted step"]
    assert record.metadata["team"] == "Common"
    assert record.original_filename == "MEF_protocol.docx"
    mock_sync.assert_called_once()
    mock_seed.assert_called_once()


@patch(
    "labapps.management.commands.sync_lab_apps._seed_payload",
    return_value=[
        {
            "notebook_id": "N-ORIGINAL",
            "title": "Notebook",
            "status": "indexed",
            "sha256": "b" * 64,
        },
        {
            "notebook_id": "N-COPY",
            "title": "Notebook copy",
            "status": "indexed",
            "sha256": "b" * 64,
        },
        {
            "protocol_id": "P-CANDIDATE",
            "title": "Legacy protocol",
            "status": "candidate",
        },
    ],
)
@patch(
    "labapps.management.commands.sync_lab_apps.sync_all",
    return_value={"registry": 1},
)
def test_sync_builds_search_index_and_groups_verified_duplicates(
    mock_sync,
    mock_seed,
):
    output = StringIO()

    call_command("sync_lab_apps", stdout=output)

    original = KnowledgeRecord.objects.get(record_id="N-ORIGINAL")
    copy = KnowledgeRecord.objects.get(record_id="N-COPY")
    protocol = KnowledgeRecord.objects.get(record_id="P-CANDIDATE")
    assert original.canonical_record_id == original.record_id
    assert copy.canonical_record_id == original.record_id
    assert original.content_sha256 == "b" * 64
    assert "notebook" in original.search_text
    assert protocol.status == "candidate"
    assert protocol.canonical_record_id == protocol.record_id
    assert '"aliases": 1' in output.getvalue()
    assert '"canonical": 2' in output.getvalue()
    mock_sync.assert_called_once()
    mock_seed.assert_called_once()
