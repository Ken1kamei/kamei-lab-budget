import hashlib

import pytest

from budget.models import InvoiceDraft, LabMember
from budget.services.invoices import create_invoice_drafts


class Upload:
    def __init__(self, name, payload):
        self.name = name
        self._payload = payload

    def read(self):
        return self._payload


@pytest.mark.django_db
def test_multiple_invoice_uploads_create_distinct_review_drafts(monkeypatch):
    LabMember.objects.create(email="member@nyu.edu", highest_role="member", active=True)
    monkeypatch.setattr(
        "budget.services.invoices.parse_pdf_bytes",
        lambda payload, filename: {
            "vendor": filename,
            "invoice_number": hashlib.sha256(payload).hexdigest()[:8],
            "total_amount": 100,
            "currency": "USD",
            "suggested_category": "Consumables",
            "missing_fields": [],
        },
    )

    drafts = create_invoice_drafts(
        [Upload("first.pdf", b"first"), Upload("second.pdf", b"second")],
        uploader_email="member@nyu.edu",
    )

    assert len(drafts) == 2
    assert InvoiceDraft.objects.count() == 2
    assert {draft.file_name for draft in drafts} == {"first.pdf", "second.pdf"}


@pytest.mark.django_db
def test_reupload_preserves_imported_state(monkeypatch):
    payload = b"same-pdf"
    digest = hashlib.sha256(payload).hexdigest()
    imported = InvoiceDraft.objects.create(
        uploader_email="member@nyu.edu",
        file_name="invoice.pdf",
        file_sha256=digest,
        parsed_data={"total_amount": 10},
        status="imported",
        imported_fiscal_year="FY2025-26",
        imported_transaction_id="TXN-1",
    )
    monkeypatch.setattr(
        "budget.services.invoices.parse_pdf_bytes",
        lambda payload, filename: {"total_amount": 11, "missing_fields": []},
    )

    [draft] = create_invoice_drafts(
        [Upload("renamed.pdf", payload)], uploader_email="member@nyu.edu"
    )

    assert draft.id == imported.id
    assert draft.status == "imported"
    assert draft.imported_transaction_id == "TXN-1"
    assert draft.parsed_data["total_amount"] == 11
