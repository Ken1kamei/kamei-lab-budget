import json

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from google.cloud import storage

from labapps.models import KnowledgeRecord, SheetRecord
from labapps.services.sheets import REGISTRY_HEADERS, TRACKER_HEADERS, _live_table


def _knowledge_seed():
    if not settings.KNOWLEDGE_BUCKET or not settings.KNOWLEDGE_SEED_OBJECT:
        return []
    blob = storage.Client().bucket(settings.KNOWLEDGE_BUCKET).blob(
        settings.KNOWLEDGE_SEED_OBJECT
    )
    if not blob.exists():
        raise CommandError("The private knowledge seed object does not exist.")
    payload = json.loads(blob.download_as_text())
    return payload.get("records", []) if isinstance(payload, dict) else payload


def _knowledge_id(record):
    return str(
        record.get("protocol_id")
        or record.get("notebook_id")
        or record.get("record_id")
        or ""
    ).strip()


class Command(BaseCommand):
    help = "Compare every Portal/Tracker Google Sheet row count with the PostgreSQL mirror."

    def handle(self, *args, **options):
        results = {}
        mismatches = {}
        for table_name in [*REGISTRY_HEADERS, *TRACKER_HEADERS]:
            _, _, source_rows = _live_table(table_name)
            source = "registry" if table_name in REGISTRY_HEADERS else "tracker"
            mirror_count = SheetRecord.objects.filter(source=source, table_name=table_name).count()
            results[table_name] = {"sheet": len(source_rows), "mirror": mirror_count}
            if len(source_rows) != mirror_count:
                mismatches[table_name] = results[table_name]
        seed_records = _knowledge_seed()
        seed_id_list = [_knowledge_id(record) for record in seed_records]
        duplicate_seed_ids = sorted(
            record_id
            for record_id in set(seed_id_list)
            if record_id and seed_id_list.count(record_id) > 1
        )
        seed_ids = set(seed_id_list)
        seed_ids.discard("")
        mirror_ids = set(KnowledgeRecord.objects.values_list("record_id", flat=True))
        missing_ids = seed_ids - mirror_ids
        results["Knowledge"] = {
            "seed": len(seed_ids),
            "mirror": len(mirror_ids),
            "web_added": len(mirror_ids - seed_ids),
            "metadata_only": KnowledgeRecord.objects.filter(object_name="").count(),
            "canonical": KnowledgeRecord.objects.filter(
                canonical_record_id=models.F("record_id")
            ).count(),
            "aliases": KnowledgeRecord.objects.exclude(
                canonical_record_id=models.F("record_id")
            ).exclude(canonical_record_id="").count(),
        }
        if missing_ids or duplicate_seed_ids:
            mismatches["Knowledge"] = {
                **results["Knowledge"],
                "missing": sorted(missing_ids),
                "duplicate_seed_ids": duplicate_seed_ids,
            }
        self.stdout.write(json.dumps(results, sort_keys=True))
        if mismatches:
            raise CommandError(f"Lab app parity mismatch: {json.dumps(mismatches, sort_keys=True)}")
        self.stdout.write(
            self.style.SUCCESS(
                "Portal, Project Tracker, and Knowledge parity matched."
            )
        )
