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
