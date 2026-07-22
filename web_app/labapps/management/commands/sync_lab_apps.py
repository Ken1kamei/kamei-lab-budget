import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from google.cloud import storage

from labapps.models import KnowledgeRecord
from labapps.services.sheets import sync_all


def _seed_payload(path):
    if path:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    if not settings.KNOWLEDGE_BUCKET or not settings.KNOWLEDGE_SEED_OBJECT:
        return []
    blob = storage.Client().bucket(settings.KNOWLEDGE_BUCKET).blob(settings.KNOWLEDGE_SEED_OBJECT)
    if not blob.exists():
        return []
    return json.loads(blob.download_as_text())


def _records(payload):
    if isinstance(payload, dict):
        payload = payload.get("records", [])
    if not isinstance(payload, list):
        raise CommandError("Knowledge seed must be a JSON list or an object with a records list.")
    return payload


class Command(BaseCommand):
    help = "Synchronize the Portal/Tracker Sheets and private knowledge metadata."

    def add_arguments(self, parser):
        parser.add_argument("--knowledge-seed", default="")

    def handle(self, *args, **options):
        counts = sync_all()
        seeded = 0
        for raw in _records(_seed_payload(options["knowledge_seed"])):
            record_id = str(raw.get("protocol_id") or raw.get("notebook_id") or raw.get("record_id") or "").strip()
            if not record_id:
                continue
            record_type = "protocol" if raw.get("protocol_id") or raw.get("record_type") == "protocol" else "notebook"
            title = str(raw.get("title") or raw.get("original_filename") or record_id).strip()
            metadata = dict(raw)
            KnowledgeRecord.objects.update_or_create(
                record_id=record_id,
                defaults={
                    "record_type": record_type,
                    "title": title,
                    "team": str(raw.get("team", "")),
                    "owner": str(raw.get("owner") or raw.get("researcher") or ""),
                    "category": str(raw.get("category", "")),
                    "status": str(raw.get("protocol_status") or raw.get("status") or "active"),
                    "source_path": str(raw.get("source_path", "")),
                    "original_filename": str(raw.get("original_filename", "")),
                    "metadata": metadata,
                },
            )
            seeded += 1
        self.stdout.write(self.style.SUCCESS(json.dumps({"sheets": counts, "knowledge": seeded}, sort_keys=True)))
