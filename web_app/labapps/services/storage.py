import hashlib
from pathlib import Path

from django.conf import settings
from google.cloud import storage


class KnowledgeStorageError(RuntimeError):
    pass


def _safe_name(name):
    cleaned = Path(str(name or "upload")).name.replace(" ", "_")
    return "".join(char for char in cleaned if char.isalnum() or char in "._-") or "upload"


def object_name(record_id, filename):
    return f"{settings.KNOWLEDGE_STORAGE_PREFIX}/{record_id}/{_safe_name(filename)}"


def store_knowledge_file(record_id, filename, content, content_type="application/octet-stream"):
    key = object_name(record_id, filename)
    digest = hashlib.sha256(content).hexdigest()
    if settings.KNOWLEDGE_BUCKET:
        try:
            bucket = storage.Client().bucket(settings.KNOWLEDGE_BUCKET)
            blob = bucket.blob(key)
            blob.upload_from_string(content, content_type=content_type)
            blob.metadata = {"sha256": digest, "record_id": record_id}
            blob.patch()
        except Exception as error:
            raise KnowledgeStorageError("The private lab file could not be stored.") from error
        return key, digest

    local_path = settings.MEDIA_ROOT / key
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(content)
    return key, digest


def read_knowledge_file(key):
    if settings.KNOWLEDGE_BUCKET:
        try:
            return storage.Client().bucket(settings.KNOWLEDGE_BUCKET).blob(key).download_as_bytes()
        except Exception as error:
            raise KnowledgeStorageError("The private lab file could not be read.") from error
    path = settings.MEDIA_ROOT / key
    if not path.exists():
        raise KnowledgeStorageError("The requested private lab file does not exist.")
    return path.read_bytes()


def open_knowledge_file(key):
    if settings.KNOWLEDGE_BUCKET:
        try:
            return storage.Client().bucket(settings.KNOWLEDGE_BUCKET).blob(key).open("rb")
        except Exception as error:
            raise KnowledgeStorageError("The private lab file could not be opened.") from error
    path = settings.MEDIA_ROOT / key
    if not path.exists():
        raise KnowledgeStorageError("The requested private lab file does not exist.")
    return path.open("rb")


def delete_knowledge_file(key):
    if not key:
        return
    if settings.KNOWLEDGE_BUCKET:
        storage.Client().bucket(settings.KNOWLEDGE_BUCKET).blob(key).delete()
        return
    path = settings.MEDIA_ROOT / key
    if path.exists():
        path.unlink()
