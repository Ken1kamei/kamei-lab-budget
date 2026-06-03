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


def test_extract_invoice_fields_reads_symbol_amount_after_amount_paid_label():
    text = """
    Amount paid on Apr 10, 2026 ¥385,255
    Room rate AED 15662.00 /- per room FOR ENTIRE STAY
    USD 2872
    AED 10,547.42
    """

    parsed = _extract_invoice_fields(text, [], "travel_receipt.pdf")

    assert parsed["total_amount"] == 385255.0
    assert parsed["currency"] == "JPY"
    assert parsed["amount_source"] == "Amount paid on Apr 10, 2026 ¥385,255"


def test_extract_invoice_fields_reads_japanese_total_with_dollar_symbol():
    text = """
    Dropbox Plus - 2TB (2019-11-04 から 2020-11-04 まで) $119.88
    小計 $119.88
    + Consumption tax (10%) $11.99
    合計 $131.87
    金額はすべてUSDで表示されます。
    """

    parsed = _extract_invoice_fields(text, [], "請求書払い - Dropbox.pdf")

    assert parsed["total_amount"] == 131.87
    assert parsed["currency"] == "USD"
    assert parsed["amount_source"] == "合計 $131.87"
