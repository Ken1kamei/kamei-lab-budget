import hashlib
import mimetypes
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from labapps.models import KnowledgeRecord, LabAppAudit
from labapps.services.knowledge import extract_knowledge_metadata
from labapps.services.storage import store_knowledge_file


class Command(BaseCommand):
    help = (
        "Copy legacy notebook/protocol source files into private knowledge storage "
        "and extract searchable content."
    )

    def add_arguments(self, parser):
        parser.add_argument("--record-id", action="append", dest="record_ids")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--dry-run", action="store_true")
        parser.add_argument("--actor", default="knowledge-migration")
        parser.add_argument(
            "--source-root",
            default="",
            help="Base directory for legacy relative source_path values.",
        )

    def handle(self, *args, **options):
        records = KnowledgeRecord.objects.filter(object_name="").exclude(source_path="")
        if options["record_ids"]:
            records = records.filter(record_id__in=options["record_ids"])
        records = records.order_by("record_id")
        if options["limit"] > 0:
            records = records[: options["limit"]]

        migrated = 0
        missing = []
        failed = []
        source_root = (
            Path(options["source_root"]).expanduser()
            if options["source_root"]
            else None
        )
        for record in records:
            source = Path(record.source_path).expanduser()
            if not source.is_absolute() and source_root is not None:
                source = source_root / source
            if not source.is_file():
                missing.append(f"{record.record_id}:{source}")
                continue
            if options["dry_run"]:
                self.stdout.write(f"would migrate {record.record_id}: {source}")
                migrated += 1
                continue
            try:
                content = source.read_bytes()
                content_type = (
                    mimetypes.guess_type(source.name)[0]
                    or "application/octet-stream"
                )
                object_key, digest = store_knowledge_file(
                    record.record_id,
                    source.name,
                    content,
                    content_type,
                )
                parsed = extract_knowledge_metadata(
                    source.name,
                    content,
                    content_type,
                )
                before = {
                    "object_name": record.object_name,
                    "original_filename": record.original_filename,
                    "metadata": record.metadata,
                }
                metadata = dict(record.metadata or {})
                metadata.update(parsed)
                metadata.update(
                    {
                        "sha256": digest or hashlib.sha256(content).hexdigest(),
                        "content_type": content_type,
                        "migrated_from": str(source),
                    }
                )
                with transaction.atomic():
                    record.object_name = object_key
                    record.original_filename = source.name
                    record.metadata = metadata
                    record.save(
                        update_fields=[
                            "object_name",
                            "original_filename",
                            "metadata",
                            "updated_at",
                        ]
                    )
                    LabAppAudit.objects.create(
                        actor=options["actor"],
                        app_id="notebooks_protocols",
                        action="migrate_original",
                        target=record.record_id,
                        before=before,
                        after={
                            "object_name": object_key,
                            "original_filename": source.name,
                            "sha256": metadata["sha256"],
                            "parse_status": metadata.get("parse_status", ""),
                        },
                    )
                migrated += 1
                self.stdout.write(
                    self.style.SUCCESS(f"migrated {record.record_id}: {source.name}")
                )
            except Exception as error:
                failed.append(f"{record.record_id}:{error}")

        self.stdout.write(
            f"migrated={migrated} missing={len(missing)} failed={len(failed)}"
        )
        for value in missing:
            self.stderr.write(f"missing {value}")
        if failed:
            raise CommandError(" | ".join(failed))
