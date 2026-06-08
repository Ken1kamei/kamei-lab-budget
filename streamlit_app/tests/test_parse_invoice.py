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


def test_extract_invoice_fields_reads_nyuad_purchase_order_total_and_currency():
    text = """
    Purchase Order
    New York University in Abu Dhabi Corporation - Abu Dhabi ADH01-0000070658 05/05/2026 1
    Buyer Phone/Email Currency
    Procurement Dept USD
    Supplier: 0000018935 Ship To: NEW YORK UNIVERSITY IN ABU DHABI
    CLEVERGENE BIOCORP PRIVATE LIMITED Saadiyat Island, Abu Dhabi
    Line Item/Description QuantityUOM PO Price Extended Amt Due Date
    1 RNA QC and Quantitation RNA QC by 37.00EA 5.00 185.00 05/08/2026
    Item Total 185.00
    2 Eukaryotic mRNA library 37.00EA 85.00 3,145.00 05/08/2026
    Item Total 3,145.00
    Total PO Amount 3,430.00
    """

    parsed = _extract_invoice_fields(text, [], "PO 70658 Clevergene - Maab 74295.PDF")

    assert parsed["vendor"] == "CLEVERGENE BIOCORP PRIVATE LIMITED"
    assert parsed["po_number"] == "ADH01-0000070658"
    assert parsed["currency"] == "USD"
    assert parsed["total_amount"] == 3430.0
    assert parsed["amount_source"] == "Total PO Amount 3,430.00"


def test_extract_invoice_fields_reads_aed_purchase_order():
    text = """
    Purchase Order
    New York University in Abu Dhabi Corporation - Abu Dhabi ADH01-0000070995 06/01/2026 1
    Buyer Phone/Email Currency
    Procurement Dept AED
    Supplier: 0000007731 Ship To: NEW YORK UNIVERSITY IN ABU DHABI
    Milab Scientific And Laboratory Saadiyat Island, Abu Dhabi
    Equipment Trading LLC Email: nyuad.deliveries@nyu.edu
    1 640912 1.00EA 1,128.00 1,128.00 07/17/2026
    Alexa Fluor 647 Annexin V, Biolegend, 100 tests
    Item Total 1,128.00
    Total PO Amount 1,128.00
    """

    parsed = _extract_invoice_fields(text, [], "0000070995_ADH01.PDF")

    assert parsed["vendor"] == "Milab Scientific And Laboratory"
    assert parsed["po_number"] == "ADH01-0000070995"
    assert parsed["currency"] == "AED"
    assert parsed["total_amount"] == 1128.0
    assert parsed["suggested_category"] == "Consumables"
    assert parsed["suggested_description"] == "Alexa Fluor 647 Annexin V, Biolegend, 100 tests"
