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
    line_items = _extract_line_items(tables)
    invoice_number = _find_invoice_number(text)
    invoice_date = _find_invoice_date(text)
    due_date = _find_due_date(text)
    po_number = _find_po_number(text)
    total_amount = _find_total(text, tables)
    currency = _detect_currency(text)
    suggested_category = _guess_category(text)
    suggested_description = _guess_description(line_items, lines, filename)
    confidence = _confidence_scores(
        {
            "vendor": _find_vendor(lines),
            "invoice_number": invoice_number,
            "invoice_date": invoice_date,
            "total_amount": total_amount,
            "currency": currency,
            "po_number": po_number,
            "suggested_category": suggested_category,
            "suggested_description": suggested_description,
            "line_items": line_items,
        }
    )
    return {
        "vendor": _find_vendor(lines),
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "total_amount": total_amount,
        "currency": currency,
        "po_number": po_number,
        "suggested_category": suggested_category,
        "suggested_description": suggested_description,
        "line_items": line_items,
        "confidence": confidence,
        "missing_fields": [field for field, score in confidence.items() if score == "low"],
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


def _find_invoice_number(text):
    return _find_pattern(
        text,
        [
            r"(?:Invoice\s*(?:#|No\.?|Number|Num)[:\s]+)([A-Z0-9][A-Z0-9\-/_.]+)",
            r"(?:Inv\s*(?:#|No\.?)[:\s]+)([A-Z0-9][A-Z0-9\-/_.]+)",
            r"(?:INV|Invoice)[- ]([A-Z0-9][A-Z0-9\-/_.]+)",
        ],
    )


def _find_po_number(text):
    return _find_pattern(
        text,
        [
            r"(?:P\.?O\.?\s*(?:#|No\.?|Number|Order)[:\s]+)([A-Z0-9][A-Z0-9\-/_.]+)",
            r"(?:Purchase\s+Order\s*(?:#|No\.?|Number)?[:\s]+)([A-Z0-9][A-Z0-9\-/_.]+)",
            r"(?:Customer\s+PO[:\s]+)([A-Z0-9][A-Z0-9\-/_.]+)",
        ],
    )


def _find_invoice_date(text):
    return _find_date(
        text,
        [
            r"(?:Invoice\s+Date|Inv\.?\s+Date)[:\s]+({date})",
            r"(?:Date\s+of\s+Invoice)[:\s]+({date})",
            r"(?:Date)[:\s]+({date})",
        ],
        default="",
        include_generic=True,
    )


def _find_due_date(text):
    return _find_date(
        text,
        [
            r"(?:Due\s+Date|Payment\s+Due|Pay\s+By)[:\s]+({date})",
        ],
        default="",
        include_generic=False,
    )


def _find_date(text, patterns, default: str | None = None, include_generic: bool = True):
    date_pattern = r"\d{4}-\d{2}-\d{2}|\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}"
    expanded_patterns = [pat.format(date=date_pattern) for pat in patterns]
    if include_generic:
        expanded_patterns.extend(
            [
                r"(\d{4}-\d{2}-\d{2})",
                r"(\d{1,2}/\d{1,2}/\d{4})",
            ]
        )
    for pat in expanded_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return _normalise_date(m.group(1))
    if default is not None:
        return default
    return datetime.today().strftime("%Y-%m-%d")


def _normalise_date(s):
    for fmt in (
        "%Y-%m-%d",
        "%d/%m/%Y",
        "%m/%d/%Y",
        "%d-%m-%Y",
        "%m-%d-%Y",
        "%d.%m.%Y",
        "%m.%d.%Y",
        "%d/%m/%y",
        "%m/%d/%y",
    ):
        try:
            return datetime.strptime(s.strip(), fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.today().strftime("%Y-%m-%d")


def _money_to_float(value: str) -> float:
    cleaned = re.sub(r"[^\d.\-]", "", value or "")
    if not cleaned or cleaned in {"-", "."}:
        return 0.0
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _find_total(text, tables):
    money = r"(?:AED|USD|EUR|JPY|GBP|€|¥|£|\$)?\s*([\d,]+(?:\.\d{1,2})?)"
    labeled_patterns = [
        rf"(?:Grand\s+Total|Invoice\s+Total|Total\s+Due|Amount\s+Due|Amount\s+Payable|Balance\s+Due)[:\s]+{money}",
        rf"(?:Total)[:\s]+{money}",
    ]
    for pat in labeled_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            amount = _money_to_float(m.group(1))
            if amount > 0:
                return amount
    for table in tables:
        for row in table or []:
            cells = [str(c or "").strip() for c in row]
            if any(re.search(r"total", c, re.IGNORECASE) for c in cells):
                for cell in reversed(cells):
                    v = _money_to_float(cell)
                    if v > 0:
                        return v
    return 0.0


def _detect_currency(text):
    if re.search(r"AED|د\.إ|Dhs\.?|Dirham", text, re.IGNORECASE):
        return "AED"
    if re.search(r"EUR|Euro|€", text, re.IGNORECASE):
        return "EUR"
    if re.search(r"JPY|Japanese Yen|¥", text, re.IGNORECASE):
        return "JPY"
    if re.search(r"GBP|Pound Sterling|£", text, re.IGNORECASE):
        return "GBP"
    if re.search(r"\$|USD|US Dollar", text):
        return "USD"
    return "USD"


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


def _guess_description(line_items: list[dict], lines: list[str], filename: str) -> str:
    item_names = [
        str(item.get("description", "")).strip()
        for item in line_items
        if str(item.get("description", "")).strip()
    ]
    if item_names:
        if len(item_names) == 1:
            return item_names[0][:180]
        joined = "; ".join(item_names[:3])
        suffix = "" if len(item_names) <= 3 else f"; +{len(item_names) - 3} more"
        return f"{joined}{suffix}"[:180]
    for line in lines:
        if re.search(r"reagent|kit|assay|service|membership|publication|software|license", line, re.IGNORECASE):
            return line[:180]
    return filename


def _confidence_scores(fields: dict) -> dict[str, str]:
    return {
        "vendor": "high" if fields.get("vendor") else "low",
        "invoice_number": "high" if fields.get("invoice_number") else "low",
        "invoice_date": "high" if fields.get("invoice_date") else "low",
        "total_amount": "high" if float(fields.get("total_amount") or 0) > 0 else "low",
        "currency": "high" if fields.get("currency") else "low",
        "po_number": "high" if fields.get("po_number") else "low",
        "suggested_category": "medium" if fields.get("suggested_category") != "Other" else "low",
        "suggested_description": "high" if fields.get("line_items") else "medium",
    }


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
