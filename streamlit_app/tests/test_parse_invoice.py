import pandas as pd

from utils.parse_invoice import _extract_invoice_fields, enrich_with_history


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


def test_extract_inventory_pdf_reads_spaced_total_and_item_description():
    text = """
    Chartfields for Order Id : 0000073888
    DS SrcBU Order No. Line Sched Location Item ID Item Price (USD) Released Total Price (USD)
    1 BASEMENT_Level 2_TBC PROPIDIUM IODIDE, 94.0% (HPLC) P4170-1G 1G
    Net Total (USD) : 2 ,096.66
    """

    parsed = _extract_invoice_fields(text, [], "INS6000_9216771.PDF")

    assert parsed["vendor"] == "PeopleSoft Inventory"
    assert parsed["invoice_number"] == "INS6000_9216771"
    assert parsed["currency"] == "USD"
    assert parsed["total_amount"] == 2096.66
    assert parsed["suggested_category"] == "Consumables"
    assert "PROPIDIUM IODIDE" in parsed["suggested_description"]


def test_extract_ibuy_summary_reads_supplier_po_total_and_product():
    text = """
    Summary - PO iB00990633
    Supplier ABCAM LTD
    PO/Reference No. iB00990633 Ship To Bill To
    Purchase Order Date 1/26/2026
    Total 1,650.00 USD 10012-1402 Code
    Product Description Catalog No Unit Price Quantity Ext. Price
    Packaging
    1 Human Albumin ELISA Kit ab179887- 1x96Tests 855.00 USD 1 EA 855.00 USD
    Account Code values have been overridden for this line
    Subtotal 1,650.00
    Total 1,650.00 USD
    """

    parsed = _extract_invoice_fields(text, [], "Summary - PO iB00990633.pdf")

    assert parsed["vendor"] == "ABCAM LTD"
    assert parsed["po_number"] == "iB00990633"
    assert parsed["currency"] == "USD"
    assert parsed["total_amount"] == 1650.0
    assert parsed["suggested_category"] == "Consumables"
    assert parsed["suggested_description"] == "Human Albumin ELISA Kit ab179887- 1x96Tests"


def test_extract_ibuy_status_reads_supplier_po_and_multiple_products():
    text = """
    Status - PO iB00993845
    Supplier ABCAM LTD
    PO/Reference No. iB00993845 Workflow Completed
    Purchase Order Date 2/4/2026
    Total 3,980.00 USD
    Product Description Catalog No Unit Price Quantity Ext. Price Supplier Receiving Invoicing Matching
    Packaging
    1 Human Albumin ELISA Kit ab179887- 1x384Tests 2,020.00 USD 1 EA 2,020.00 USD Sent To none Fully No
    2 Human ALT ELISA Kit ab234578- 1x384Tests 1,960.00 USD 1 EA 1,960.00 USD Sent To none Fully No
    Subtotal 3,980.00
    Total 3,980.00 USD
    """

    parsed = _extract_invoice_fields(text, [], "Status - PO iB00993845.pdf")

    assert parsed["vendor"] == "ABCAM LTD"
    assert parsed["po_number"] == "iB00993845"
    assert parsed["currency"] == "USD"
    assert parsed["total_amount"] == 3980.0
    assert parsed["suggested_description"] == (
        "Human Albumin ELISA Kit ab179887- 1x384Tests; "
        "Human ALT ELISA Kit ab234578- 1x384Tests"
    )


def test_enrich_with_history_reuses_corrected_category_team_and_vendor():
    parsed = {
        "vendor": "ABCAM LTD",
        "po_number": "iB00993845",
        "invoice_number": "",
        "suggested_category": "Other",
        "suggested_subcategory": "",
        "suggested_team": "",
        "confidence": {"suggested_category": "low"},
        "history_hints": [],
    }
    txns = pd.DataFrame(
        [
            {
                "PO Number": "iB00993845",
                "Invoice Number": "",
                "Vendor / Payee": "Abcam Ltd",
                "Category": "Consumables",
                "Sub-category": "Assay kits",
                "Team": "Diabetes",
                "Status": "Allocated",
            }
        ]
    )

    enriched = enrich_with_history(parsed, txns)

    assert enriched["vendor"] == "Abcam Ltd"
    assert enriched["suggested_category"] == "Consumables"
    assert enriched["suggested_subcategory"] == "Assay kits"
    assert enriched["suggested_team"] == "Diabetes"
    assert enriched["confidence"]["suggested_category"] == "high"
