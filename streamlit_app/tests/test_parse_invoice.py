from utils.parse_invoice import _extract_invoice_fields


def test_extract_invoice_fields_prefills_review_values():
    text = """
    Bio-Rad Laboratories
    Invoice Number INV-2048
    Invoice Date 05/31/2026
    Due Date 06/30/2026
    Purchase Order PO-777
    Qubit RNA BR Assay Kit
    Grand Total USD 2,506.00
    """
    tables = [
        [
            ["Description", "Qty", "Unit Price", "Total"],
            ["Qubit RNA BR Assay Kit", "2", "1,253.00", "2,506.00"],
        ]
    ]

    parsed = _extract_invoice_fields(text, tables, "approval_receipt.pdf")

    assert parsed["vendor"] == "Bio-Rad Laboratories"
    assert parsed["invoice_number"] == "INV-2048"
    assert parsed["invoice_date"] == "2026-05-31"
    assert parsed["due_date"] == "2026-06-30"
    assert parsed["po_number"] == "PO-777"
    assert parsed["currency"] == "USD"
    assert parsed["total_amount"] == 2506.0
    assert parsed["suggested_category"] == "Consumables"
    assert parsed["suggested_description"] == "Qubit RNA BR Assay Kit"
    assert parsed["confidence"]["total_amount"] == "high"
    assert parsed["line_items"][0]["description"] == "Qubit RNA BR Assay Kit"


def test_extract_invoice_fields_flags_missing_values_for_review():
    parsed = _extract_invoice_fields("Invoice\nTotal 0", [], "unknown.pdf")

    assert "invoice_number" in parsed["missing_fields"]
    assert "total_amount" in parsed["missing_fields"]
    assert parsed["suggested_description"] == "unknown.pdf"
