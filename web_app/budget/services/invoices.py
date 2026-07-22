import hashlib
import importlib.util
from pathlib import Path

from budget.models import InvoiceDraft
from budget.services.storage import save_invoice


def _load_parser():
    parser_path = Path(__file__).resolve().parents[3] / "streamlit_app" / "utils" / "parse_invoice.py"
    spec = importlib.util.spec_from_file_location("legacy_invoice_parser", parser_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The existing invoice parser could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse_pdf_bytes, module.parse_erb_excel_bytes


parse_pdf_bytes, parse_erb_excel_bytes = _load_parser()


def create_invoice_drafts(uploaded_files, uploader_email: str):
    drafts = []
    for uploaded_file in uploaded_files:
        payload = uploaded_file.read()
        if not payload.startswith(b"%PDF-"):
            raise ValueError(f"{uploaded_file.name} is not a valid PDF file.")
        digest = hashlib.sha256(payload).hexdigest()
        parsed = parse_pdf_bytes(payload, uploaded_file.name)
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
            },
        )
        if not created:
            draft.file_name = uploaded_file.name[:255]
            draft.parsed_data = parsed
            draft.object_key = stored.object_key
            draft.content_type = "application/pdf"
            draft.size = stored.size
            update_fields = ["file_name", "parsed_data", "object_key", "content_type", "size"]
            if draft.status != "imported":
                draft.status = status
                update_fields.append("status")
            draft.save(update_fields=update_fields)
        drafts.append(draft)
    return drafts
