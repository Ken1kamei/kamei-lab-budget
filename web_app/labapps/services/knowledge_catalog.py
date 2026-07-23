import json
import re

from labapps.models import KnowledgeRecord


AVAILABLE_STATUSES = ("", "active", "candidate", "indexed")
SEARCH_TEXT_LIMIT = 200_000
PREVIEW_CHARACTER_LIMIT = 40_000
PREVIEW_BLOCK_LIMIT = 120
PREVIEW_TABLE_ROW_LIMIT = 50


def public_status(value):
    normalized = str(value or "").strip().casefold()
    if normalized in AVAILABLE_STATUSES:
        return "Available"
    if normalized == "draft":
        return "Draft"
    if normalized == "archived":
        return "Archived"
    return "Needs review"


def build_search_text(
    *,
    record_id="",
    record_type="",
    title="",
    team="",
    owner="",
    category="",
    original_filename="",
    metadata=None,
):
    metadata_text = json.dumps(
        metadata or {},
        ensure_ascii=False,
        default=str,
        separators=(",", ":"),
    )
    combined = " ".join(
        str(value or "")
        for value in (
            record_id,
            record_type,
            title,
            team,
            owner,
            category,
            original_filename,
            metadata_text,
        )
    )
    return re.sub(r"\s+", " ", combined).strip().casefold()[:SEARCH_TEXT_LIMIT]


def refresh_knowledge_indexes(records=None):
    queryset = records if records is not None else KnowledgeRecord.objects.all()
    rows = list(queryset.order_by("created_at", "record_id"))
    canonical_by_digest = {}
    updates = []
    for row in rows:
        digest = str(
            row.content_sha256
            or row.metadata.get("sha256")
            or row.metadata.get("content_sha256")
            or ""
        ).strip().casefold()
        canonical_id = row.record_id
        if digest:
            canonical_id = canonical_by_digest.setdefault(
                (row.record_type, digest),
                row.record_id,
            )
        search_text = build_search_text(
            record_id=row.record_id,
            record_type=row.record_type,
            title=row.title,
            team=row.team,
            owner=row.owner,
            category=row.category,
            original_filename=row.original_filename,
            metadata=row.metadata,
        )
        if (
            row.content_sha256 != digest
            or row.canonical_record_id != canonical_id
            or row.search_text != search_text
        ):
            row.content_sha256 = digest
            row.canonical_record_id = canonical_id
            row.search_text = search_text
            updates.append(row)
    if updates:
        KnowledgeRecord.objects.bulk_update(
            updates,
            ["content_sha256", "canonical_record_id", "search_text"],
        )
    return {
        "records": len(rows),
        "canonical": sum(
            1 for row in rows if not row.content_sha256 or row.canonical_record_id == row.record_id
        ),
        "aliases": sum(
            1 for row in rows if row.content_sha256 and row.canonical_record_id != row.record_id
        ),
    }


def build_document_preview(metadata):
    metadata = metadata or {}
    preview = {
        key: metadata.get(key)
        for key in (
            "document_title",
            "parse_status",
            "parse_message",
            "last_reprocess_status",
            "last_reprocess_error",
            "notes",
            "project",
            "modified_time",
            "file_type",
            "size_bytes",
        )
    }
    remaining_characters = PREVIEW_CHARACTER_LIMIT
    remaining_blocks = PREVIEW_BLOCK_LIMIT
    truncated = False

    def limited_lines(values):
        nonlocal remaining_characters, remaining_blocks, truncated
        output = []
        for value in values or []:
            if remaining_blocks <= 0 or remaining_characters <= 0:
                truncated = True
                break
            text = str(value or "").strip()
            if not text:
                continue
            if len(text) > remaining_characters:
                text = text[:remaining_characters].rstrip()
                truncated = True
            output.append(text)
            remaining_characters -= len(text)
            remaining_blocks -= 1
        return output

    sections = []
    for section in metadata.get("sections") or []:
        if remaining_blocks <= 0 or remaining_characters <= 0:
            truncated = True
            break
        blocks = []
        for block in section.get("blocks") or []:
            if remaining_blocks <= 0 or remaining_characters <= 0:
                truncated = True
                break
            kind = block.get("kind")
            if kind == "table":
                rows = block.get("rows") or []
                if len(rows) > PREVIEW_TABLE_ROW_LIMIT:
                    truncated = True
                limited_rows = []
                for row in rows[:PREVIEW_TABLE_ROW_LIMIT]:
                    cells = limited_lines(row)
                    if cells:
                        limited_rows.append(cells)
                if limited_rows:
                    blocks.append({"kind": "table", "rows": limited_rows})
            elif kind in {"bullets", "numbered"}:
                items = limited_lines(block.get("items"))
                if items:
                    blocks.append({"kind": kind, "items": items})
            else:
                lines = limited_lines([block.get("text")])
                if lines:
                    blocks.append({"kind": "paragraph", "text": lines[0]})
        if blocks:
            sections.append(
                {
                    "heading": str(section.get("heading") or "Document"),
                    "blocks": blocks,
                }
            )
    preview["sections"] = sections
    if not sections:
        for key in ("summary", "overview", "materials", "procedure"):
            preview[key] = limited_lines(metadata.get(key))
    preview["truncated"] = truncated
    return preview
