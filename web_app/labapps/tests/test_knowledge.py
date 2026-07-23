from io import BytesIO
import zipfile

from django.core.files.uploadedfile import SimpleUploadedFile
from openpyxl import Workbook

from labapps.forms import KnowledgeUploadForm
from labapps.services.knowledge import extract_knowledge_metadata
from labapps.services.knowledge import MAX_KNOWLEDGE_FILE_BYTES


def protocol_docx_bytes():
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>MEF preparation protocol</w:t></w:r></w:p>
    <w:p><w:r><w:t>Primary mouse embryonic fibroblast workflow.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Purpose / overview</w:t></w:r></w:p>
    <w:p><w:r><w:t>Prepare primary MEFs from individual embryos.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Materials</w:t></w:r></w:p>
    <w:tbl>
      <w:tr><w:tc><w:p><w:r><w:t>Reagent</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Use</w:t></w:r></w:p></w:tc></w:tr>
      <w:tr><w:tc><w:p><w:r><w:t>DMEM</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Culture medium</w:t></w:r></w:p></w:tc></w:tr>
    </w:tbl>
    <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Procedure</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="ListNumber"/></w:pPr><w:r><w:t>Collect each embryo separately.</w:t></w:r></w:p>
    <w:p><w:pPr><w:pStyle w:val="ListNumber"/></w:pPr><w:r><w:t>Plate cells in complete medium.</w:t></w:r></w:p>
    <w:sectPr/>
  </w:body>
</w:document>"""
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
</Types>"""
    output = BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("word/document.xml", document_xml)
    return output.getvalue()


def test_docx_protocol_sections_are_extracted_in_document_order():
    parsed = extract_knowledge_metadata(
        "MEF_protocol.docx",
        protocol_docx_bytes(),
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert parsed["parse_status"] == "parsed"
    assert parsed["document_title"] == "MEF preparation protocol"
    assert parsed["summary"] == ["Primary mouse embryonic fibroblast workflow."]
    assert [section["heading"] for section in parsed["sections"]] == [
        "Purpose / overview",
        "Materials",
        "Procedure",
    ]
    assert parsed["overview"] == ["Prepare primary MEFs from individual embryos."]
    assert "DMEM | Culture medium" in parsed["materials"]
    assert parsed["procedure"] == [
        "Collect each embryo separately.",
        "Plate cells in complete medium.",
    ]


def test_invalid_docx_returns_visible_parse_failure():
    parsed = extract_knowledge_metadata("broken.docx", b"not-a-docx")

    assert parsed["parse_status"] == "failed"
    assert parsed["parser"] == "docx-v1"
    assert "valid Word document" in parsed["parse_message"]


def test_unsupported_file_remains_downloadable_without_fake_content():
    parsed = extract_knowledge_metadata("image.tiff", b"pixels", "image/tiff")

    assert parsed["parse_status"] == "unsupported"
    assert "DOCX, PDF, MD, TXT, CSV, XLSX, and PPTX" in parsed["parse_message"]


def test_excel_content_is_extracted_for_knowledge_search():
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Differentiation"
    worksheet.append(["Stage", "Reagent"])
    worksheet.append(["Definitive endoderm", "Activin A"])
    payload = BytesIO()
    workbook.save(payload)

    parsed = extract_knowledge_metadata("protocol.xlsx", payload.getvalue())

    assert parsed["parse_status"] == "parsed"
    assert parsed["parser"] == "xlsx-v1"
    assert "Activin A" in str(parsed["sections"])


def test_powerpoint_content_is_extracted_for_knowledge_search():
    payload = BytesIO()
    slide_xml = """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
       xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody>
    <a:p><a:r><a:t>MEF preparation</a:t></a:r></a:p>
    <a:p><a:r><a:t>Digest embryos with trypsin.</a:t></a:r></a:p>
  </p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>"""
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("ppt/slides/slide1.xml", slide_xml)

    parsed = extract_knowledge_metadata("protocol.pptx", payload.getvalue())

    assert parsed["parse_status"] == "parsed"
    assert parsed["parser"] == "pptx-v1"
    assert "trypsin" in str(parsed["sections"]).lower()


def test_upload_form_rejects_unsupported_and_oversized_files():
    base = {
        "record_type": "protocol",
        "title": "Protocol",
        "team": "Common",
        "owner": "Ken",
        "category": "",
        "notes": "",
    }
    unsupported = KnowledgeUploadForm(
        data=base,
        files={"files": SimpleUploadedFile("protocol.exe", b"binary")},
    )
    assert unsupported.is_valid() is False
    assert "supported document" in unsupported.errors["files"][0]

    too_large_file = SimpleUploadedFile("protocol.docx", b"tiny")
    too_large_file.size = MAX_KNOWLEDGE_FILE_BYTES + 1
    oversized = KnowledgeUploadForm(
        data=base,
        files={"files": too_large_file},
    )
    assert oversized.is_valid() is False
    assert "25 MB or smaller" in oversized.errors["files"][0]
