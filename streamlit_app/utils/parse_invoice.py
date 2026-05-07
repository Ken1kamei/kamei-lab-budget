"""
Parse invoice PDFs and NYUAD ERB Excel files.
No AI / no Claude API — uses pdfplumber + openpyxl + regex.
"""
import re
from datetime import datetime


def parse_pdf_bytes(pdf_bytes: bytes, filename: str = "") -> dict:
    """Parse PDF from bytes (for Streamlit file_uploader). Returns field dict."""
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)
            tables = [tbl for page in pdf.pages for tbl in page.extract_tables()]
    except Exception as e:
        return {"_error": str(e)}
    return _extract_invoice_fields(text, tables, filename)


def _extract_invoice_fields(text: str, tables: list, filename: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return {
        "vendor": _find_vendor(lines),
        "invoice_number": _find_pattern(
            text,
            [
                r"(?:Invoice\s*(?:#|No\.?|Number)[:\s]+)([A-Z0-9\-/]+)",
                r"(?:INV|Invoice)[- ]([A-Z0-9\-/]+)",
            ],
        ),
        "invoice_date": _find_date(text),
        "total_amount": _find_total(text, tables),
        "currency": _detect_currency(text),
        "po_number": _find_pattern(
            text,
            [
                r"(?:P\.?O\.?\s*(?:#|No\.?|Number|Order)[:\s]+)([A-Z0-9\-/]+)",
            ],
        ),
        "suggested_category": _guess_category(text),
        "line_items": _extract_line_items(tables),
    }


def _find_vendor(lines):
    skip = {
        "invoice",
        "receipt",
        "tax invoice",
        "bill",
        "statement",
        "page",
        "date:",
        "to:",
        "from:",
        "ship",
        "bill to",
        "sold to",
    }
    for line in lines[:10]:
        if line.lower() not in skip and len(line) > 3 and not line[0].isdigit():
            return line
    return ""


def _find_pattern(text, patterns):
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _find_date(text):
    patterns = [
        r"(?:Invoice|Date)[:\s]+(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})",
        r"(\d{4}-\d{2}-\d{2})",
        r"(\d{1,2}/\d{1,2}/\d{4})",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return _normalise_date(m.group(1))
    return datetime.today().strftime("%Y-%m-%d")


def _normalise_date(s):
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.today().strftime("%Y-%m-%d")


def _find_total(text, tables):
    for pat in [
        r"(?:Grand\s+)?Total[:\s]+(?:AED|USD|\$)?\s*([\d,]+\.?\d*)",
        r"Amount\s+(?:Due|Payable)[:\s]+(?:AED|USD|\$)?\s*([\d,]+\.?\d*)",
    ]:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass
    for table in tables:
        for row in table or []:
            cells = [str(c or "").strip() for c in row]
            if any(re.search(r"total", c, re.IGNORECASE) for c in cells):
                for cell in reversed(cells):
                    try:
                        v = float(re.sub(r"[^\d.]", "", cell))
                        if v > 0:
                            return v
                    except ValueError:
                        pass
    return 0.0


def _detect_currency(text):
    if re.search(r"AED|د\.إ|Dhs\.?|Dirham", text, re.IGNORECASE):
        return "AED"
    if re.search(r"\$|USD|US Dollar", text):
        return "USD"
    return "AED"


def _guess_category(text):
    t = text.lower()
    if re.search(
        r"publication|article processing|open access|page charge|color charge|apc",
        t,
    ):
        return "Publications"
    if re.search(r"membership|member dues|society dues|annual dues", t):
        return "Memberships"
    if re.search(
        r"reagent|chemical|pipette|assay|antibod|enzyme|kit|consumable|plasticware",
        t,
    ):
        return "Consumables"
    if re.search(r"centrifug|instrument|software|license|equipment", t):
        return "Equipment"
    if re.search(r"salary|stipend|postdoc|research assistant|technician", t):
        return "Personnel"
    if re.search(
        r"flight|hotel|conference|registration|airfare|per diem|travel", t
    ):
        return "Travel"
    return "Other"


def _find_col(headers, keywords):
    for kw in keywords:
        for i, h in enumerate(headers):
            if kw in h.lower():
                return i
    return None


def _to_float(val):
    try:
        return float(re.sub(r"[^\d.]", "", str(val or "")))
    except ValueError:
        return 0.0


def _extract_line_items(tables):
    items = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        header = [str(c or "").strip().lower() for c in table[0]]
        desc_col = _find_col(header, ["description", "item", "product"])
        total_col = _find_col(header, ["total", "amount"])
        qty_col = _find_col(header, ["qty", "quantity"])
        price_col = _find_col(header, ["unit price", "unit cost", "price"])
        if desc_col is None:
            continue
        for row in table[1:]:
            try:
                desc = str(row[desc_col] or "").strip()
                total = (
                    _to_float(row[total_col])
                    if total_col is not None and len(row) > total_col
                    else 0
                )
                qty = (
                    _to_float(row[qty_col])
                    if qty_col is not None and len(row) > qty_col
                    else 1
                )
                price = (
                    _to_float(row[price_col])
                    if price_col is not None and len(row) > price_col
                    else 0
                )
                if desc and total > 0:
                    items.append(
                        {
                            "description": desc,
                            "quantity": qty,
                            "unit_price": price,
                            "total": total,
                        }
                    )
            except (IndexError, TypeError):
                pass
    return items


def parse_erb_excel_bytes(excel_bytes: bytes) -> list[dict]:
    """Parse NYUAD ERB cross-charge Excel from bytes. Returns list of transaction dicts."""
    import openpyxl
    import io

    wb = openpyxl.load_workbook(io.BytesIO(excel_bytes), data_only=True)
    ws = wb.active
    rows = list(ws.values)

    header_row = None
    for i, row in enumerate(rows):
        strs = [str(c or "").strip() for c in row]
        if "Long Descr" in strs or "Business Unit" in strs:
            header_row = i
            break
    if header_row is None:
        return []

    headers = [str(c or "").strip() for c in rows[header_row]]
    col = {h: i for i, h in enumerate(headers)}
    result = []

    for row in rows[header_row + 1 :]:
        if not any(row):
            continue
        descr = str(row[col.get("Long Descr", -1)] or "").strip()
        if not descr:
            continue
        acctg = row[col.get("Acctg Date", -1)]
        date_str = (
            acctg.strftime("%Y-%m-%d")
            if hasattr(acctg, "strftime")
            else str(acctg or "")[:10]
        )
        aed = float(row[col.get("Total Amount (AED)", -1)] or 0)
        order = str(row[col.get("Order No.", -1)] or "").split(".")[0]
        sku = str(row[col.get("Item (SKU #)", -1)] or "").strip()
        proj = str(row[col.get("Project", -1)] or "").strip()
        dept = str(row[col.get("Department", -1)] or "").split(".")[0]
        fund = str(row[col.get("Fund Code", -1)] or "").split(".")[0]
        req = str(row[col.get("Requestor Name", -1)] or "").strip()
        result.append(
            {
                "Date": date_str,
                "Category": "Consumables",
                "Sub-category": "NYUAD Stores",
                "Vendor / Payee": "NYUAD ERB (Stores)",
                "Description": descr,
                "Amount (AED)": aed,
                "Amount (USD)": 0,
                "Status": "Paid",
                "Invoice Number": order,
                "PO Number": order,
                "Entry Method": "Excel Import",
                "Notes": f"SKU: {sku} | Project: {proj} | Dept: {dept} | Fund: {fund} | Req: {req}",
            }
        )
    return result
