import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from google.cloud import storage

from labapps.models import KnowledgeRecord
from labapps.services.knowledge import EXTRACTED_METADATA_KEYS
from labapps.services.knowledge_catalog import (
    build_search_text,
    refresh_knowledge_indexes,
)
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
            existing = KnowledgeRecord.objects.filter(record_id=record_id).first()
            record_type = (
                "protocol"
                if raw.get("protocol_id") or raw.get("record_type") == "protocol"
                else existing.record_type if existing else "notebook"
            )
            title = str(
                raw.get("title")
                or raw.get("original_filename")
                or (existing.title if existing else "")
                or record_id
            ).strip()
            metadata = dict(existing.metadata) if existing else {}
            metadata.update(raw)
            if existing and existing.metadata.get("parse_status") == "parsed":
                for key in EXTRACTED_METADATA_KEYS:
                    if key in existing.metadata:
                        metadata[key] = existing.metadata[key]

            def value(key):
                incoming = raw.get(key)
                if incoming not in (None, ""):
                    return str(incoming)
                return str(getattr(existing, key, "") if existing else "")

            KnowledgeRecord.objects.update_or_create(
                record_id=record_id,
                defaults={
                    "record_type": record_type,
                    "title": title,
                    "team": value("team"),
                    "owner": str(
                        raw.get("owner")
                        or raw.get("researcher")
                        or (existing.owner if existing else "")
                    ),
                    "category": value("category"),
                    "status": str(
                        raw.get("protocol_status")
                        or raw.get("status")
                        or (existing.status if existing else "")
                        or "active"
                    ),
                    "source_path": value("source_path"),
                    "original_filename": value("original_filename"),
                    "content_sha256": str(
                        raw.get("sha256")
                        or raw.get("content_sha256")
                        or (existing.content_sha256 if existing else "")
                    ).strip().casefold(),
                    "search_text": build_search_text(
                        record_id=record_id,
                        record_type=record_type,
                        title=title,
                        team=value("team"),
                        owner=str(
                            raw.get("owner")
                            or raw.get("researcher")
                            or (existing.owner if existing else "")
                        ),
                        category=value("category"),
                        original_filename=value("original_filename"),
                        metadata=metadata,
                    ),
                    "metadata": metadata,
                },
            )
            seeded += 1
        catalog = refresh_knowledge_indexes()
        self.stdout.write(
            self.style.SUCCESS(
                json.dumps(
                    {
                        "sheets": counts,
                        "knowledge": seeded,
                        "catalog": catalog,
                    },
                    sort_keys=True,
                )
            )
        )
