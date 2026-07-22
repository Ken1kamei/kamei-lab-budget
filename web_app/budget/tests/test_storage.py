import io

import pytest
from django.core.exceptions import ImproperlyConfigured, SuspiciousFileOperation

from budget.services.storage import delete_invoice, open_invoice, save_invoice


def test_local_storage_round_trip_is_private_and_deletable(settings, tmp_path):
    settings.DEBUG = True
    settings.INVOICE_BUCKET = ""
    settings.INVOICE_STORAGE_PREFIX = "invoices"
    settings.MEDIA_ROOT = tmp_path

    stored = save_invoice(
        io.BytesIO(b"private-pdf"),
        filename="invoice.pdf",
        content_type="application/pdf",
    )

    assert stored.object_key.startswith("invoices/")
    assert stored.content_type == "application/pdf"
    assert stored.size == 11
    with open_invoice(stored.object_key) as handle:
        assert handle.read() == b"private-pdf"
    assert (tmp_path / stored.object_key).exists()

    delete_invoice(stored.object_key)
    assert not (tmp_path / stored.object_key).exists()


def test_storage_requires_private_bucket_outside_debug(settings):
    settings.DEBUG = False
    settings.INVOICE_BUCKET = ""

    with pytest.raises(ImproperlyConfigured, match="INVOICE_BUCKET"):
        save_invoice(b"pdf", filename="invoice.pdf")


def test_storage_rejects_keys_outside_invoice_namespace(settings, tmp_path):
    settings.DEBUG = True
    settings.INVOICE_BUCKET = ""
    settings.INVOICE_STORAGE_PREFIX = "invoices"
    settings.MEDIA_ROOT = tmp_path

    with pytest.raises(SuspiciousFileOperation):
        save_invoice(b"pdf", filename="invoice.pdf", object_key="../invoice.pdf")


def test_gcs_storage_uses_private_blob_operations(settings, monkeypatch):
    settings.DEBUG = False
    settings.INVOICE_BUCKET = "private-invoices"
    settings.INVOICE_STORAGE_PREFIX = "invoices"

    class Blob:
        def __init__(self):
            self.payload = b""
            self.content_type = ""
            self.deleted = False

        def upload_from_file(self, handle, *, rewind, content_type, if_generation_match=None):
            assert rewind is True
            assert if_generation_match == 0
            self.payload = handle.read()
            self.content_type = content_type

        def download_as_bytes(self):
            return self.payload

        def delete(self):
            self.deleted = True

        def make_public(self):
            raise AssertionError("Invoice blobs must never be made public.")

    class Bucket:
        def __init__(self):
            self.blobs = {}

        def blob(self, key):
            return self.blobs.setdefault(key, Blob())

    bucket = Bucket()
    monkeypatch.setattr("budget.services.storage._gcs_bucket", lambda: bucket)

    stored = save_invoice(b"gcs-pdf", filename="invoice.pdf")
    blob = bucket.blobs[stored.object_key]
    assert blob.payload == b"gcs-pdf"
    assert blob.content_type == "application/pdf"
    with open_invoice(stored.object_key) as handle:
        assert handle.read() == b"gcs-pdf"

    delete_invoice(stored.object_key)
    assert blob.deleted is True
