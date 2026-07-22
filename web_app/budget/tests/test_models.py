from datetime import timedelta

import pytest
from django.db import IntegrityError
from django.db.models.deletion import ProtectedError
from django.utils import timezone

from budget.models import (
    FiscalYear,
    InvoiceDraft,
    SheetOperation,
    Transaction,
    TransactionAudit,
)


@pytest.mark.django_db
def test_transaction_operational_fields_and_audit_are_durable():
    fiscal_year = FiscalYear.objects.create(label="FY2026-27")
    transaction = Transaction.objects.create(
        fiscal_year=fiscal_year,
        transaction_id="TXN-1",
        receipt_confirmed=True,
        email_thread_id="thread-123",
        approved_by="lead@nyu.edu",
        approved_at=timezone.now(),
        sheet_last_modified_at=timezone.now() - timedelta(minutes=1),
        version=3,
    )
    audit = TransactionAudit.objects.create(
        transaction=transaction,
        actor="manager@nyu.edu",
        action="update",
        before={"status": "Allocated"},
        after={"status": "Cancelled"},
    )

    transaction.refresh_from_db()
    assert transaction.version == 3
    assert transaction.updated_at is not None
    assert transaction.receipt_confirmed is True
    assert audit.transaction == transaction
    assert audit.before["status"] == "Allocated"
    assert audit.after["status"] == "Cancelled"
    assert audit.timestamp is not None
    with pytest.raises(ProtectedError):
        transaction.delete()


@pytest.mark.django_db
def test_sheet_operation_has_unique_idempotency_key_and_status_lifecycle():
    operation = SheetOperation.objects.create(
        idempotency_key="invoice:sha256:abc",
        operation_type="invoice_import",
        actor="member@nyu.edu",
        request={"invoice_number": "INV-1"},
    )
    assert operation.status == "pending"

    operation.status = "succeeded"
    operation.result = {"transaction_id": "TXN-1"}
    operation.completed_at = timezone.now()
    operation.save()
    operation.refresh_from_db()
    assert operation.status == "succeeded"
    assert operation.result["transaction_id"] == "TXN-1"

    with pytest.raises(IntegrityError):
        SheetOperation.objects.create(
            idempotency_key="invoice:sha256:abc",
            operation_type="invoice_import",
        )


@pytest.mark.django_db
def test_invoice_draft_tracks_private_object_and_processing_context():
    fiscal_year = FiscalYear.objects.create(label="FY2026-27")
    draft = InvoiceDraft.objects.create(
        uploader_email="member@nyu.edu",
        file_name="invoice.pdf",
        file_sha256="a" * 64,
        object_key="invoices/2026/07/private-invoice.pdf",
        content_type="application/pdf",
        size=321,
        team="Diabetes",
        fiscal_year=fiscal_year,
        parsed_data={},
        status="processing",
    )

    draft.refresh_from_db()
    assert draft.status == "processing"
    assert draft.fiscal_year == fiscal_year
    assert draft.team == "Diabetes"
    assert draft.object_key.startswith("invoices/")
