import hashlib

from budget.models import InvoiceDraft, Transaction
from budget.services.invoice_parser import parse_erb_excel_bytes, parse_pdf_bytes
from budget.services.storage import save_invoice


MAX_PDF_BYTES = 20 * 1024 * 1024


def _history_key(value):
    return "".join(character for character in str(value or "").casefold() if character.isalnum())


def _enrich_with_history(parsed, team):
    if parsed.get("_error"):
        return parsed
    transactions = Transaction.objects.exclude(status="Cancelled")
    if team:
        transactions = transactions.filter(team=team)
    transactions = list(transactions.order_by("-updated_at")[:500])
    match = None
    for field, attribute in (("po_number", "po_number"), ("invoice_number", "invoice_number")):
        target = _history_key(parsed.get(field))
        if target:
            match = next(
                (
                    transaction
                    for transaction in transactions
                    if _history_key(getattr(transaction, attribute)) == target
                ),
                None,
            )
        if match:
            break
    if match is None:
        vendor = _history_key(parsed.get("vendor"))
        if vendor:
            match = next(
                (
                    transaction
                    for transaction in transactions
                    if _history_key(transaction.vendor)
                    and (
                        vendor == _history_key(transaction.vendor)
                        or vendor in _history_key(transaction.vendor)
                        or _history_key(transaction.vendor) in vendor
                    )
                ),
                None,
            )
    if match is None:
        return parsed
    updated = dict(parsed)
    hints = list(updated.get("history_hints") or [])
    for value, target_key in (
        (match.category, "suggested_category"),
        (match.subcategory, "suggested_subcategory"),
        (match.team, "suggested_team"),
        (match.vendor, "vendor"),
    ):
        if str(value or "").strip():
            updated[target_key] = value
            hints.append(f"{target_key.replace('_', ' ')} from prior ledger row")
    updated["history_hints"] = sorted(set(hints))
    confidence = dict(updated.get("confidence") or {})
    if updated.get("suggested_category"):
        confidence["suggested_category"] = "high"
    updated["confidence"] = confidence
    updated["missing_fields"] = [
        field for field, level in confidence.items() if level == "low"
    ]
    return updated


def create_invoice_drafts(uploaded_files, uploader_email: str, team=""):
    drafts = []
    for uploaded_file in uploaded_files:
        if getattr(uploaded_file, "size", 0) > MAX_PDF_BYTES:
            raise ValueError(f"{uploaded_file.name} exceeds the 20 MB PDF limit.")
        payload = uploaded_file.read()
        if len(payload) > MAX_PDF_BYTES:
            raise ValueError(f"{uploaded_file.name} exceeds the 20 MB PDF limit.")
        if not payload.startswith(b"%PDF-"):
            raise ValueError(f"{uploaded_file.name} is not a valid PDF file.")
        digest = hashlib.sha256(payload).hexdigest()
        parsed = _enrich_with_history(
            parse_pdf_bytes(payload, uploaded_file.name),
            team,
        )
        status = "ready" if not parsed.get("_error") and not parsed.get("missing_fields") else "review"
        object_key = f"invoices/{digest[:2]}/{digest}.pdf"
        stored = save_invoice(
            payload,
            filename=uploaded_file.name,
            content_type="application/pdf",
            object_key=object_key,
        )
        draft, created = InvoiceDraft.objects.get_or_create(
            uploader_email=uploader_email.strip().lower(),
            file_sha256=digest,
            defaults={
                "file_name": uploaded_file.name[:255],
                "parsed_data": parsed,
                "status": status,
                "object_key": stored.object_key,
                "content_type": "application/pdf",
                "size": stored.size,
                "team": team,
            },
        )
        if not created:
            draft.file_name = uploaded_file.name[:255]
            draft.parsed_data = parsed
            draft.object_key = stored.object_key
            draft.content_type = "application/pdf"
            draft.size = stored.size
            draft.team = team
            update_fields = [
                "file_name",
                "parsed_data",
                "object_key",
                "content_type",
                "size",
                "team",
            ]
            if draft.status != "imported":
                draft.status = status
                update_fields.append("status")
            draft.save(update_fields=update_fields)
        drafts.append(draft)
    return drafts
