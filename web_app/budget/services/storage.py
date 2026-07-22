import io
import mimetypes
import os
import uuid
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation
from google.cloud import storage as gcs_storage


@dataclass(frozen=True)
class StoredInvoice:
    object_key: str
    content_type: str
    size: int


def _validated_object_key(object_key: str) -> str:
    key = str(object_key or "").strip().replace("\\", "/")
    path = PurePosixPath(key)
    prefix = settings.INVOICE_STORAGE_PREFIX or "invoices"
    if not key or path.is_absolute() or ".." in path.parts or path.parts[0] != prefix:
        raise SuspiciousFileOperation("Invalid invoice storage object key.")
    return path.as_posix()


def _new_object_key(filename: str) -> str:
    safe_name = Path(str(filename or "invoice.pdf")).name.replace("\x00", "") or "invoice.pdf"
    today = date.today()
    return _validated_object_key(
        f"{settings.INVOICE_STORAGE_PREFIX or 'invoices'}/{today:%Y/%m}/"
        f"{uuid.uuid4().hex}-{safe_name}"
    )


def _read_bytes(content) -> bytes:
    if isinstance(content, bytes):
        return content
    if isinstance(content, bytearray):
        return bytes(content)
    if hasattr(content, "seek"):
        content.seek(0)
    payload = content.read()
    if not isinstance(payload, bytes):
        raise TypeError("Invoice content must be binary.")
    return payload


def _content_type(filename: str, explicit: str | None) -> str:
    return explicit or mimetypes.guess_type(filename)[0] or "application/octet-stream"


def _gcs_bucket():
    return gcs_storage.Client().bucket(settings.INVOICE_BUCKET)


def _local_path(object_key: str) -> Path:
    root = Path(settings.MEDIA_ROOT).resolve()
    candidate = (root / object_key).resolve()
    if root != candidate and root not in candidate.parents:
        raise SuspiciousFileOperation("Invoice storage path escapes MEDIA_ROOT.")
    return candidate


def _backend() -> str:
    if settings.INVOICE_BUCKET:
        return "gcs"
    if settings.DEBUG:
        return "local"
    raise ImproperlyConfigured(
        "INVOICE_BUCKET must be configured outside DEBUG mode; local invoice storage is disabled."
    )


def save_invoice(content, *, filename: str, content_type: str | None = None,
                 object_key: str | None = None) -> StoredInvoice:
    key = _validated_object_key(object_key) if object_key else _new_object_key(filename)
    payload = _read_bytes(content)
    media_type = _content_type(filename, content_type)

    if _backend() == "gcs":
        blob = _gcs_bucket().blob(key)
        blob.upload_from_file(io.BytesIO(payload), rewind=True, content_type=media_type)
    else:
        path = _local_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(payload)
        os.replace(temporary, path)

    return StoredInvoice(object_key=key, content_type=media_type, size=len(payload))


def open_invoice(object_key: str):
    key = _validated_object_key(object_key)
    if _backend() == "gcs":
        return io.BytesIO(_gcs_bucket().blob(key).download_as_bytes())
    return _local_path(key).open("rb")


def delete_invoice(object_key: str) -> None:
    key = _validated_object_key(object_key)
    if _backend() == "gcs":
        _gcs_bucket().blob(key).delete()
        return
    try:
        _local_path(key).unlink()
    except FileNotFoundError:
        return
