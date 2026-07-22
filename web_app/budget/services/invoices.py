import hashlib
import importlib.util
from pathlib import Path

from budget.models import InvoiceDraft


def _load_parser():
    parser_path = Path(__file__).resolve().parents[3] / "streamlit_app" / "utils" / "parse_invoice.py"
    spec = importlib.util.spec_from_file_location("legacy_invoice_parser", parser_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("The existing invoice parser could not be loaded.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.parse_pdf_bytes


parse_pdf_bytes = _load_parser()


def create_invoice_drafts(uploaded_files, uploader_email: str):
    drafts = []
    for uploaded_file in uploaded_files:
        payload = uploaded_file.read()
        digest = hashlib.sha256(payload).hexdigest()
        parsed = parse_pdf_bytes(payload, uploaded_file.name)
        status = "ready" if not parsed.get("_error") and not parsed.get("missing_fields") else "review"
        draft, created = InvoiceDraft.objects.get_or_create(
            uploader_email=uploader_email.strip().lower(),
            file_sha256=digest,
            defaults={
                "file_name": uploaded_file.name[:255],
                "parsed_data": parsed,
                "status": status,
            },
        )
        if not created:
            draft.file_name = uploaded_file.name[:255]
            draft.parsed_data = parsed
            update_fields = ["file_name", "parsed_data"]
            if draft.status != "imported":
                draft.status = status
                update_fields.append("status")
            draft.save(update_fields=update_fields)
        drafts.append(draft)
    return drafts
