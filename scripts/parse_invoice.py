#!/usr/bin/env python3
"""
parse_invoice.py — Parse a PDF invoice or NYUAD ERB Excel file and import it
into the Kamei Lab Budget system without using the Claude API.

Usage:
    python3 scripts/parse_invoice.py path/to/invoice.pdf
    python3 scripts/parse_invoice.py path/to/ERB_report.xlsx
    python3 scripts/parse_invoice.py path/to/invoice.pdf --dry-run   # preview only
"""

import sys, re, json, argparse, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path

WEB_APP_URL = "https://script.google.com/macros/s/AKfycbx36yl34Z4CtCfc4IfCPhD1DNU0Zarat9yyRErqODQkjGt3i9ggmJXkTHZoGhASDdM/exec"


# ── PDF parsing ────────────────────────────────────────────────────────────────

def parse_pdf(path: Path) -> dict:
    try:
        import pdfplumber
    except ImportError:
        sys.exit("pdfplumber not installed. Run: pip3 install pdfplumber")

    text = ""
    tables = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text += (page.extract_text() or "") + "\n"
            for tbl in page.extract_tables():
                tables.append(tbl)

    return extract_invoice_fields(text, tables, path.name)


def extract_invoice_fields(text: str, tables: list, filename: str) -> dict:
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    result = {
        "vendor":        _find_vendor(lines),
        "invoice_number": _find_pattern(text, [
            r'(?:Invoice\s*(?:#|No\.?|Number)[:\s]+)([A-Z0-9\-/]+)',
            r'(?:INV|Invoice)[- ]([A-Z0-9\-/]+)',
        ]),
        "invoice_date":  _find_date(text),
        "total_amount":  _find_total(text, tables),
        "currency":      _detect_currency(text),
        "po_number":     _find_pattern(text, [
            r'(?:P\.?O\.?\s*(?:#|No\.?|Number|Order)[:\s]+)([A-Z0-9\-/]+)',
        ]),
        "suggested_category": _guess_category(text),
        "line_items":    _extract_line_items(tables),
        "raw_text":      text[:500],
    }
    return result


def _find_vendor(lines: list) -> str:
    skip = {"invoice", "receipt", "tax invoice", "bill", "statement",
            "page", "date:", "to:", "from:", "ship", "bill to", "sold to"}
    for line in lines[:10]:
        if line.lower() not in skip and len(line) > 3 and not line[0].isdigit():
            return line
    return ""


def _find_pattern(text: str, patterns: list) -> str:
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def _find_date(text: str) -> str:
    patterns = [
        r'(?:Invoice|Inv\.?|Bill|Date)[:\s]+(\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4})',
        r'(?:Invoice|Inv\.?|Bill|Date)[:\s]+(\d{4}[\/\-\.]\d{1,2}[\/\-\.]\d{1,2})',
        r'(?:Invoice|Inv\.?|Bill|Date)[:\s]+(\d{1,2}\s+\w+\s+\d{4})',
        r'(\d{4}-\d{2}-\d{2})',
        r'(\d{1,2}/\d{1,2}/\d{4})',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            return _normalise_date(m.group(1))
    return datetime.today().strftime("%Y-%m-%d")


def _normalise_date(s: str) -> str:
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y",
                "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    return datetime.today().strftime("%Y-%m-%d")


def _find_total(text: str, tables: list) -> float:
    # Look for "Total" line with amount
    patterns = [
        r'(?:Grand\s+)?Total\s*(?:Amount|Due|AED|USD|:)?\s*[:\s]?\s*(?:AED|USD|د\.إ|\$)?\s*([\d,]+\.?\d*)',
        r'(?:Total|TOTAL)\s*[:\s]\s*([\d,]+\.?\d*)',
        r'Amount\s+(?:Due|Payable)\s*[:\s]\s*(?:AED|USD|\$)?\s*([\d,]+\.?\d*)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass

    # Try scanning tables for a "Total" row
    for table in tables:
        for row in (table or []):
            row_flat = [str(c or "").strip() for c in row]
            if any(re.search(r'total', c, re.IGNORECASE) for c in row_flat):
                for cell in reversed(row_flat):
                    try:
                        val = float(re.sub(r"[^\d.]", "", cell))
                        if val > 0:
                            return val
                    except ValueError:
                        pass
    return 0.0


def _detect_currency(text: str) -> str:
    if re.search(r'AED|د\.إ|Dhs\.?|Dirham', text, re.IGNORECASE):
        return "AED"
    if re.search(r'\$|USD|US Dollar', text):
        return "USD"
    return "AED"  # default for NYUAD context


def _guess_category(text: str) -> str:
    t = text.lower()
    if re.search(r'reagent|chemical|pipette|centrifug|assay|antibod|primer|enzyme|kit|consumable|instrument|microscop|software|license', t):
        return "Equipment"
    if re.search(r'salary|stipend|postdoc|research assistant|technician|honorarium|payroll|personnel', t):
        return "Personnel"
    if re.search(r'flight|hotel|conference|registration|airfare|per diem|travel|visa', t):
        return "Travel"
    if re.search(r'publication|open access|office|printing|maintenance|subscription', t):
        return "Other"
    return "Equipment"


def _extract_line_items(tables: list) -> list:
    items = []
    for table in tables:
        if not table or len(table) < 2:
            continue
        header = [str(c or "").strip().lower() for c in table[0]]
        # Find description, quantity, unit price, total columns
        desc_col  = _find_col(header, ["description", "item", "product", "details"])
        qty_col   = _find_col(header, ["qty", "quantity", "units"])
        price_col = _find_col(header, ["unit price", "unit cost", "price", "rate"])
        total_col = _find_col(header, ["total", "amount", "subtotal"])
        if desc_col is None:
            continue
        for row in table[1:]:
            try:
                desc  = str(row[desc_col] or "").strip() if desc_col is not None else ""
                qty   = _to_float(row[qty_col])   if qty_col   is not None and len(row) > qty_col   else 1
                price = _to_float(row[price_col]) if price_col is not None and len(row) > price_col else 0
                total = _to_float(row[total_col]) if total_col is not None and len(row) > total_col else price
                if desc and total > 0:
                    items.append({"description": desc, "quantity": qty,
                                  "unit_price": price, "total": total})
            except (IndexError, TypeError):
                pass
    return items


def _find_col(headers: list, keywords: list) -> int | None:
    for kw in keywords:
        for i, h in enumerate(headers):
            if kw in h:
                return i
    return None


def _to_float(val) -> float:
    try:
        return float(re.sub(r"[^\d.]", "", str(val or "")))
    except ValueError:
        return 0.0


# ── Excel (NYUAD ERB) parsing ──────────────────────────────────────────────────

def parse_excel(path: Path) -> list[dict]:
    try:
        import openpyxl
    except ImportError:
        sys.exit("openpyxl not installed. Run: pip3 install openpyxl")

    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.values)

    # Find header row
    header_row = None
    for i, row in enumerate(rows):
        row_strs = [str(c or "").strip() for c in row]
        if "Long Descr" in row_strs or "Business Unit" in row_strs:
            header_row = i
            break

    if header_row is None:
        sys.exit("Could not find header row in Excel file. Is this an ERB cross-charge report?")

    headers = [str(c or "").strip() for c in rows[header_row]]
    col = {h: i for i, h in enumerate(headers)}

    transactions = []
    for row in rows[header_row + 1:]:
        if not any(row):
            continue
        descr = str(row[col.get("Long Descr", -1)] or "").strip()
        if not descr:
            continue

        acctg_date = row[col.get("Acctg Date", -1)]
        if hasattr(acctg_date, "strftime"):
            date_str = acctg_date.strftime("%Y-%m-%d")
        else:
            date_str = str(acctg_date or "")[:10]

        aed   = float(row[col.get("Total Amount (AED)", -1)] or 0)
        order = str(row[col.get("Order No.", -1)] or "").split(".")[0]
        sku   = str(row[col.get("Item (SKU #)", -1)] or "").strip()
        proj  = str(row[col.get("Project", -1)] or "").strip()
        dept  = str(row[col.get("Department", -1)] or "").split(".")[0]
        fund  = str(row[col.get("Fund Code", -1)] or "").split(".")[0]
        req   = str(row[col.get("Requestor Name", -1)] or "").strip()

        transactions.append({
            "date":          date_str,
            "category":      "Equipment",
            "subCategory":   "Consumables",
            "vendor":        "NYUAD ERB (Stores)",
            "description":   descr,
            "amountAed":     aed,
            "amountUsd":     0,
            "status":        "Paid",
            "invoiceNumber": order,
            "poNumber":      order,
            "entryMethod":   "Excel Import",
            "notes":         f"SKU: {sku} | Project: {proj} | Dept: {dept} | Fund: {fund} | Req: {req}"
        })
    return transactions


# ── Budget API ─────────────────────────────────────────────────────────────────

def post_transaction(data: dict) -> dict:
    payload = json.dumps({"action": "addTransaction", "data": data}).encode()
    req = urllib.request.Request(WEB_APP_URL, data=payload,
                                  headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as e:
        return {"success": False, "error": str(e)}


# ── Interactive confirmation ───────────────────────────────────────────────────

def confirm_and_import_pdf(parsed: dict, filename: str, dry_run: bool):
    print("\n" + "─" * 60)
    print(f"  Parsed Invoice: {filename}")
    print("─" * 60)
    print(f"  Vendor:         {parsed['vendor'] or '(not found)'}")
    print(f"  Invoice #:      {parsed['invoice_number'] or '(not found)'}")
    print(f"  Date:           {parsed['invoice_date']}")
    print(f"  Total:          {parsed['currency']} {parsed['total_amount']:,.2f}")
    print(f"  Category:       {parsed['suggested_category']}  (suggested)")
    if parsed['line_items']:
        print(f"  Line items:     {len(parsed['line_items'])} found")
        for item in parsed['line_items'][:3]:
            print(f"    • {item['description'][:50]}  {parsed['currency']} {item['total']:,.2f}")
    print("─" * 60)

    if dry_run:
        print("  [DRY RUN] Not importing. Remove --dry-run to import.")
        return

    # Allow editing before import
    print("\nEdit fields (press Enter to keep current value):")
    vendor = input(f"  Vendor [{parsed['vendor']}]: ").strip() or parsed['vendor']
    description = input(f"  Description [{filename}]: ").strip() or filename
    category = input(f"  Category [{parsed['suggested_category']}]: ").strip() or parsed['suggested_category']
    status_opts = "Ordered/Delivered/Paid/Pending Review"
    status = input(f"  Status [Pending Review] ({status_opts}): ").strip() or "Pending Review"

    aed = parsed['total_amount'] if parsed['currency'] == 'AED' else 0
    usd = parsed['total_amount'] if parsed['currency'] == 'USD' else 0

    data = {
        "date":          parsed['invoice_date'],
        "category":      category,
        "vendor":        vendor,
        "description":   description,
        "invoiceNumber": parsed['invoice_number'] or "",
        "poNumber":      parsed['po_number'] or "",
        "amountAed":     aed,
        "amountUsd":     usd,
        "status":        status,
        "entryMethod":   "Python Import",
        "notes":         f"Parsed by parse_invoice.py from {filename}"
    }

    confirm = input("\nImport this transaction? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    print("  Sending to budget system…", end="", flush=True)
    result = post_transaction(data)
    if result.get("success"):
        print(f" ✓  Transaction ID: {result.get('transactionId')}")
    else:
        print(f" ✗  Error: {result.get('error') or result}")


def confirm_and_import_excel(transactions: list, filename: str, dry_run: bool):
    print("\n" + "─" * 60)
    print(f"  ERB Excel: {filename}")
    print(f"  Rows found: {len(transactions)}")
    print("─" * 60)
    for t in transactions:
        print(f"  • {t['description'][:55]:<55} AED {t['amountAed']:>10,.2f}")
    total = sum(t['amountAed'] for t in transactions)
    print(f"  {'TOTAL':<55} AED {total:>10,.2f}")
    print("─" * 60)

    if dry_run:
        print("  [DRY RUN] Not importing. Remove --dry-run to import.")
        return

    confirm = input(f"\nImport all {len(transactions)} transaction(s)? [y/N]: ").strip().lower()
    if confirm != "y":
        print("Aborted.")
        return

    for i, txn in enumerate(transactions, 1):
        print(f"  [{i}/{len(transactions)}] {txn['description'][:50]}…", end="", flush=True)
        result = post_transaction(txn)
        if result.get("success"):
            print(f" ✓  {result.get('transactionId')}")
        else:
            print(f" ✗  {result.get('error') or result}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Import an invoice PDF or ERB Excel into the Kamei Lab Budget.")
    parser.add_argument("file", help="Path to PDF invoice or NYUAD ERB Excel file")
    parser.add_argument("--dry-run", action="store_true", help="Parse and preview only, do not import")
    args = parser.parse_args()

    path = Path(args.file)
    if not path.exists():
        sys.exit(f"File not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".pdf":
        print(f"Parsing PDF: {path.name}")
        parsed = parse_pdf(path)
        confirm_and_import_pdf(parsed, path.name, args.dry_run)

    elif suffix in (".xlsx", ".xls"):
        print(f"Parsing Excel: {path.name}")
        transactions = parse_excel(path)
        if not transactions:
            sys.exit("No transactions found in Excel file.")
        confirm_and_import_excel(transactions, path.name, args.dry_run)

    else:
        sys.exit(f"Unsupported file type: {suffix}  (use .pdf, .xlsx, or .xls)")


if __name__ == "__main__":
    main()
