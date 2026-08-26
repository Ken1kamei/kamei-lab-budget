from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command

from labapps.models import KnowledgeRecord, LabAppAudit, SheetRecord


pytestmark = pytest.mark.django_db


def test_delete_registry_members_uses_active_reassignment_target(settings):
    settings.PI_EMAIL = "pi@nyu.edu"
    SheetRecord.objects.create(
        source="registry",
        table_name="Members",
        record_id="M001",
        payload={
            "member_id": "M001",
            "email": "pi@nyu.edu",
            "active": "TRUE",
        },
    )
    SheetRecord.objects.create(
        source="registry",
        table_name="Members",
        record_id="M002",
        payload={
            "member_id": "M002",
            "email": "test@example.edu",
            "active": "FALSE",
        },
    )

    with patch(
        "labapps.management.commands.delete_registry_members.sync_all"
    ), patch(
        "labapps.management.commands.delete_registry_members.delete_member_record"
    ) as delete:
        call_command(
            "delete_registry_members",
            "test@example.edu",
            actor="pi@nyu.edu",
            reassign_to_email="pi@nyu.edu",
        )

    delete.assert_called_once_with(
        "M002",
        actor="pi@nyu.edu",
        confirm_email="test@example.edu",
        reassign_to_member_id="M001",
    )


def test_migrate_knowledge_originals_stores_and_extracts_local_source(
    tmp_path,
):
    source = tmp_path / "protocol.txt"
    source.write_text(
        "Protocol title\nMaterials\nDMEM\nProcedure\n1. Wash cells.",
        encoding="utf-8",
    )
    record = KnowledgeRecord.objects.create(
        record_id="P-LEGACY",
        record_type="protocol",
        title="Legacy protocol",
        source_path=source.name,
        metadata={"notes": "preserve"},
    )

    with patch(
        "labapps.management.commands.migrate_knowledge_originals.store_knowledge_file",
        return_value=("knowledge/P-LEGACY/protocol.txt", "stored-sha"),
    ):
        call_command(
            "migrate_knowledge_originals",
            record_id=["P-LEGACY"],
            actor="qa@nyu.edu",
            source_root=str(tmp_path),
        )

    record.refresh_from_db()
    assert record.object_name == "knowledge/P-LEGACY/protocol.txt"
    assert record.original_filename == "protocol.txt"
    assert record.metadata["notes"] == "preserve"
    assert record.metadata["sha256"] == "stored-sha"
    assert record.metadata["parse_status"] == "parsed"
    assert LabAppAudit.objects.filter(
        target="P-LEGACY",
        action="migrate_original",
        actor="qa@nyu.edu",
    ).exists()


def test_migrate_knowledge_originals_dry_run_does_not_change_record(
    tmp_path,
):
    source = Path(tmp_path) / "notebook.txt"
    source.write_text("Notebook text", encoding="utf-8")
    record = KnowledgeRecord.objects.create(
        record_id="N-LEGACY",
        record_type="notebook",
        title="Legacy notebook",
        source_path=str(source),
    )

    call_command(
        "migrate_knowledge_originals",
        record_id=["N-LEGACY"],
        dry_run=True,
    )

    record.refresh_from_db()
    assert record.object_name == ""
    assert not LabAppAudit.objects.filter(target="N-LEGACY").exists()
