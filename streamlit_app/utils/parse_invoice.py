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
    line_items = _dedupe_line_items(_extract_line_items(tables) + _extract_text_line_items(lines))
    vendor = _find_vendor(lines, text)
    invoice_number = _find_invoice_number(text) or _find_invoice_number(filename)
    if not invoice_number:
        invoice_number = _find_inventory_invoice_number(text, filename)
    invoice_date = _find_invoice_date(text)
    due_date = _find_due_date(text)
    po_number = _find_po_number(text) or _find_po_number(filename)
    total_candidate = _find_total_candidate(text, tables)
    total_amount = total_candidate["amount"]
    currency = total_candidate.get("currency") or _detect_currency(text)
    suggested_category = _guess_category(text)
    suggested_description = _guess_description(line_items, lines, filename)
    confidence = _confidence_scores(
        {
            "vendor": vendor,
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
        "vendor": vendor,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "due_date": due_date,
        "total_amount": total_amount,
        "currency": currency,
        "amount_source": total_candidate.get("source", ""),
        "po_number": po_number,
        "suggested_category": suggested_category,
        "suggested_subcategory": "",
        "suggested_team": "",
        "suggested_description": suggested_description,
        "line_items": line_items,
        "history_hints": [],
        "confidence": confidence,
        "missing_fields": [field for field, score in confidence.items() if score == "low"],
    }


def _find_vendor(lines, text=""):
    if re.search(r"Chartfields\s+for\s+Order\s+Id|PeopleSoft\s+Inventory", str(text or ""), re.IGNORECASE):
        return "PeopleSoft Inventory"
    supplier = _find_supplier_vendor(text)
    if supplier:
        return supplier
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
        "purchase order",
    }
    for line in lines[:10]:
        if line.lower() not in skip and len(line) > 3 and not line[0].isdigit():
            return line
    return ""


def _find_supplier_vendor(text: str) -> str:
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    for i, line in enumerate(lines):
        supplier_line = re.match(r"^Supplier\s+(?!Name\b)(.+)$", line, flags=re.IGNORECASE)
        if supplier_line:
            cleaned = _clean_vendor_name(supplier_line.group(1))
            if cleaned:
                return cleaned[:120]
        if "supplier:" not in line.casefold():
            continue
        after_supplier = re.split(r"supplier:\s*", line, flags=re.IGNORECASE, maxsplit=1)[-1]
        before_ship_to = re.split(r"\s+ship\s+to:", after_supplier, flags=re.IGNORECASE, maxsplit=1)[0]
        code_match = re.search(r"\b\d{5,}\b", before_ship_to)
        if code_match:
            remainder = before_ship_to[code_match.end() :].strip(" :-")
            if remainder and not re.fullmatch(r"\d+", remainder):
                return remainder[:120]
        for candidate in lines[i + 1 : i + 5]:
            cleaned = re.split(r"\s+Saadiyat\s+Island\b|\s+Email:|\s+T:", candidate, flags=re.IGNORECASE)[0].strip()
            if (
                cleaned
                and len(cleaned) > 3
                and not cleaned.casefold().startswith(("auto dispatch", "ship to", "bill to"))
                and not re.fullmatch(r"[\d\s:/.-]+", cleaned)
            ):
                continuation = ""
                next_index = lines.index(candidate) + 1 if candidate in lines else -1
                if next_index > 0 and next_index + 1 < len(lines):
                    next_cleaned = re.split(
                        r"\s+Email:|\s+T:",
                        lines[next_index + 1],
                        flags=re.IGNORECASE,
                    )[0].strip()
                    if re.search(r"\b(LLC|LTD|LIMITED|TRADING|CORPORATION|INC\.?)\b", next_cleaned, re.IGNORECASE):
                        continuation = f" {next_cleaned}"
                if continuation and not re.search(r"\b(LLC|LTD|LIMITED|TRADING|CORPORATION|INC\.?)\b", cleaned, re.IGNORECASE):
                    cleaned = f"{cleaned}{continuation}"
                return _clean_vendor_name(cleaned)[:120]
    return ""


def _clean_vendor_name(value: str) -> str:
    cleaned = str(value or "").strip(" :-")
    cleaned = re.split(
        r"\s+Ship\s+To\b|\s+Bill\s+To\b|\s+Workflow\b|\s+Accepted\b|\s+Sent\s+To\b|\s+Product\s+Description\b",
        cleaned,
        flags=re.IGNORECASE,
    )[0].strip(" :-")
    if not cleaned or cleaned.casefold() in {"name", "supplier name"}:
        return ""
    if re.fullmatch(r"[\d\s:/.-]+", cleaned):
        return ""
    return cleaned


def _find_pattern(text, patterns):
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m and _looks_like_identifier(m.group(1)):
            return m.group(1).strip()
    return ""


def _looks_like_identifier(value: str) -> bool:
    value = str(value or "").strip()
    if not value:
        return False
    if re.fullmatch(r"\d{1,2}[\/\-\.]\d{1,2}[\/\-\.]\d{2,4}", value):
        return False
    return bool(re.search(r"\d|[-_/]", value))


def _find_invoice_number(text):
    return _find_pattern(
        text,
        [
            r"(?:Invoice\s*(?:#|No\.?|Number|Num)[:\s]+)([A-Z0-9][A-Z0-9\-/_.]+)",
            r"(?:Inv\s*(?:#|No\.?)[:\s]+)([A-Z0-9][A-Z0-9\-/_.]+)",
            r"(?:INV|Invoice)[- ]([A-Z0-9][A-Z0-9\-/_.]+)",
        ],
    )


def _find_inventory_invoice_number(text: str, filename: str) -> str:
    filename_match = re.search(r"\b(INS\d+[_-]\d+)\b", str(filename or ""), re.IGNORECASE)
    if filename_match:
        return filename_match.group(1)
    order_match = re.search(r"Chartfields\s+for\s+Order\s+Id\s*:\s*(\d{6,})", str(text or ""), re.IGNORECASE)
    if order_match:
        return order_match.group(1)
    return ""


def _find_po_number(text):
    return _find_pattern(
        text,
        [
            r"\b(iB\d{6,})\b",
            r"\b(ADH\d{2}-\d{6,})\b",
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


def _normalize_currency(value: str) -> str:
    value = str(value or "").strip().upper()
    symbols = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY", "￥": "JPY"}
    if value in symbols:
        return symbols[value]
    if value in {"US$", "USD"}:
        return "USD"
    if value in {"AED", "DHS", "DHS.", "DIRHAM"}:
        return "AED"
    if value in {"EUR", "JPY", "GBP"}:
        return value
    return ""


def _money_mentions(line: str) -> list[dict]:
    amount = r"\d[\d,\s]*(?:\.\d{1,2})?"
    currency = r"AED|USD|EUR|JPY|GBP|US\$|Dhs\.?|Dirham|[$€£¥￥]"
    mentions = []
    patterns = [
        rf"(?P<currency>{currency})\s*(?P<amount>{amount})",
        rf"(?P<amount>{amount})\s*(?P<currency>{currency})",
    ]
    for pat in patterns:
        for match in re.finditer(pat, line, re.IGNORECASE):
            if match.end() < len(line) and line[match.end()] == "-":
                continue
            parsed_amount = _money_to_float(match.group("amount"))
            parsed_currency = _normalize_currency(match.group("currency"))
            if parsed_amount > 0 and parsed_currency:
                mentions.append(
                    {
                        "amount": parsed_amount,
                        "currency": parsed_currency,
                        "text": match.group(0),
                        "start": match.start(),
                    }
                )
    return sorted(mentions, key=lambda item: item["start"])


def _bare_amount_mentions(line: str) -> list[dict]:
    mentions = []
    protected = str(line or "")
    for money in _money_mentions(protected):
        protected = protected.replace(money["text"], " ")
    amount = (
        r"(?<![\d/-])\d[\d,\s]*,\s*\d{3}(?:\.\d{1,2})?"
        r"|(?<![\d/-])\d+\.\d{2}(?![\d/-])"
    )
    for match in re.finditer(amount, protected):
        parsed_amount = _money_to_float(match.group(0))
        if parsed_amount > 0:
            mentions.append(
                {
                    "amount": parsed_amount,
                    "currency": "",
                    "text": match.group(0),
                    "start": match.start(),
                }
            )
    return sorted(mentions, key=lambda item: item["start"])


def _amount_label_score(line: str) -> int:
    label = line.casefold()
    if re.search(r"total\s+po\s+amount|po\s+total|purchase\s+order\s+total", label):
        return 98
    if re.search(r"amount\s+paid|paid\s+amount|payment\s+amount|支払|支払い", label):
        return 100
    if re.search(r"grand\s+total|invoice\s+total|total\s+due|amount\s+due|amount\s+payable|balance\s+due", label):
        return 95
    if re.search(r"合計|請求金額|請求額|総額|total", label):
        return 90
    if re.search(r"小計|subtotal", label):
        return 30
    return 0


def _find_total_candidate(text, tables):
    candidates = []
    for line in text.splitlines():
        mentions = _money_mentions(line)
        score = _amount_label_score(line)
        if score and mentions:
            # The rightmost/last amount on a labelled line is usually the row total.
            mention = mentions[-1]
            candidates.append({**mention, "score": score, "source": line.strip()[:180]})
        elif score >= 80:
            bare_mentions = _bare_amount_mentions(line)
            if bare_mentions:
                mention = bare_mentions[-1]
                candidates.append({**mention, "score": score - 2, "source": line.strip()[:180]})

    if candidates:
        candidates.sort(key=lambda item: (item["score"], item["amount"]), reverse=True)
        return candidates[0]

    for table in tables:
        for row in table or []:
            cells = [str(c or "").strip() for c in row]
            if any(re.search(r"total", c, re.IGNORECASE) for c in cells):
                for cell in reversed(cells):
                    mentions = _money_mentions(cell)
                    if mentions:
                        mention = mentions[-1]
                        return {**mention, "score": 80, "source": "table total row"}
                    value = _money_to_float(cell)
                    if value > 0:
                        return {"amount": value, "currency": "", "score": 50, "source": "table total row"}
    return {"amount": 0.0, "currency": "", "score": 0, "source": ""}


def _find_total(text, tables):
    return _find_total_candidate(text, tables)["amount"]


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
        r"reagent|chemical|pipet|dpbs|serum|fetal bovine|cell gm|rinsing sol|propidium|methyl cellulose|oligo|transwell|superscript|master mix|acetaminophen|assay|antibod|annexin|biolegend|fluor|enzyme|kit|consumable|plasticware",
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
        if re.search(
            r"agreement|terms|conditions|invalidated|signature|purchase order form|prior to",
            line,
            re.IGNORECASE,
        ):
            continue
        if re.search(
            r"reagent|kit|assay|annexin|biolegend|fluor|sequencing|library|service|membership|publication|software|license",
            line,
            re.IGNORECASE,
        ):
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


def _dedupe_line_items(items: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for item in items:
        desc = _clean_description(item.get("description", ""))
        if not desc:
            continue
        key = re.sub(r"\W+", "", desc.casefold())[:80]
        if key in seen:
            continue
        seen.add(key)
        row = dict(item)
        row["description"] = desc
        deduped.append(row)
    return deduped


def _clean_description(value: str) -> str:
    desc = " ".join(str(value or "").replace("\uf0c6", " ").split())
    desc = re.sub(r"^(\d+|\*\*)\s+BASEMENT_Level\s+\d+_TBC\s+", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+Sent\s+To\s+.*$", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+Accepted\s+.*$", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+Supplier\s+Invoiced\s+.*$", "", desc, flags=re.IGNORECASE)
    desc = re.sub(r"\s+Account\s+Code\s+.*$", "", desc, flags=re.IGNORECASE)
    desc = desc.strip(" :-")
    if not desc or _is_bad_description_line(desc):
        return ""
    return desc[:220]


def _is_bad_description_line(line: str) -> bool:
    value = str(line or "").strip()
    folded = value.casefold()
    if not value:
        return True
    if re.search(r"www\.|https?://|nyu\.edu|terms|conditions|invalidated|signature", folded):
        return True
    if folded in {"packaging", "supplier name", "line item/description quantityuom po price extended amt due date"}:
        return True
    if re.fullmatch(r"[\d\s:/.,$€£¥-]+", value):
        return True
    return False


def _extract_text_line_items(lines: list[str]) -> list[dict]:
    items = []
    items.extend(_extract_inventory_items(lines))
    items.extend(_extract_ibuy_items(lines))
    items.extend(_extract_nyuad_po_items(lines))
    return items


def _extract_inventory_items(lines: list[str]) -> list[dict]:
    items = []
    for line in lines:
        if not re.match(r"^(?:\d+|\*\*)\s+BASEMENT_Level\s+\d+_TBC\s+", line, re.IGNORECASE):
            continue
        desc = _clean_description(line)
        if desc:
            items.append({"description": desc, "quantity": 1, "unit_price": 0, "total": 0})
    return items


def _extract_ibuy_items(lines: list[str]) -> list[dict]:
    items = []
    in_items = False
    for line in lines:
        if re.search(
            r"Product\s+Description.*(?:Unit\s+Price|Ext\.\s+Price)|Unit\s+Price\s+Quantity\s+Ext\.\s+Price",
            line,
            re.IGNORECASE,
        ):
            in_items = True
            continue
        if not in_items:
            continue
        if re.search(r"Subtotal|Shipping|Handling|Total\uf0c6|Distribution|Supplier\s+Information", line, re.IGNORECASE):
            if re.search(r"Subtotal|Total\uf0c6", line, re.IGNORECASE):
                break
            continue
        if _is_bad_description_line(line):
            continue
        match = re.match(
            r"^\d+\s+(?P<desc>.+?)\s+\d[\d,\s]*\.\d{2}\s+(?:USD|AED|EUR|JPY|GBP)\s+\d+(?:\.\d+)?\s+EA\b",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue
        desc = _clean_description(match.group("desc"))
        if desc:
            items.append({"description": desc, "quantity": 1, "unit_price": 0, "total": 0})
    return items


def _extract_nyuad_po_items(lines: list[str]) -> list[dict]:
    items = []
    in_items = False
    current = []
    for line in lines:
        if re.search(r"Line\s+Item/Description\s+QuantityUOM\s+PO\s+Price", line, re.IGNORECASE):
            in_items = True
            continue
        if not in_items:
            continue
        if re.search(r"Total\s+PO\s+Amount|QUOTE\s+NO|PAYMENT\s+TERMS|CHARTFIELD", line, re.IGNORECASE):
            if current:
                _append_po_item(items, current)
                current = []
            if re.search(r"Total\s+PO\s+Amount", line, re.IGNORECASE):
                break
            continue
        if re.search(r"Item\s+Total", line, re.IGNORECASE):
            if current:
                _append_po_item(items, current)
                current = []
            continue
        start_match = re.match(
            r"^\d+\s+(?P<desc>.+?)\s+\d+(?:\.\d+)?\s*EA\b.*\d{1,2}/\d{1,2}/\d{4}",
            line,
            flags=re.IGNORECASE,
        )
        if start_match:
            if current:
                _append_po_item(items, current)
            current = [start_match.group("desc")]
            continue
        if current and not re.search(r"^<<|^Utech\s+#|^VAT|^Ship\s+To|^Bill\s+To", line, re.IGNORECASE):
            current.append(line)
    if current:
        _append_po_item(items, current)
    return items


def _append_po_item(items: list[dict], parts: list[str]) -> None:
    desc = _clean_description(" ".join(parts))
    desc = re.sub(r"\s+UOM\s*:.*$", "", desc, flags=re.IGNORECASE).strip(" :-")
    if desc:
        items.append({"description": desc, "quantity": 1, "unit_price": 0, "total": 0})


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


def enrich_with_history(parsed: dict, transactions) -> dict:
    """
    Lightweight adaptive learning from previously corrected/imported rows.

    This is intentionally not a trained ML model. It uses the Google Sheet ledger
    as feedback: once a user corrects vendor/category/sub-category/team for a PO,
    invoice, or vendor, future imports with the same signal get the same defaults.
    """
    if parsed.get("_error") or transactions is None:
        return parsed
    try:
        if transactions.empty:
            return parsed
    except AttributeError:
        return parsed

    txns = transactions.copy()
    if "Status" in txns.columns:
        txns = txns[txns["Status"].astype(str).str.strip().ne("Cancelled")]
    if txns.empty:
        return parsed

    match = _history_exact_match(parsed, txns)
    if match is None:
        match = _history_vendor_match(parsed, txns)
    if match is None:
        return parsed

    updated = dict(parsed)
    hints = list(updated.get("history_hints", []))
    for source_col, target_key in (
        ("Category", "suggested_category"),
        ("Sub-category", "suggested_subcategory"),
        ("Team", "suggested_team"),
        ("Vendor / Payee", "vendor"),
    ):
        value = str(match.get(source_col, "") or "").strip()
        if value:
            updated[target_key] = value
            hints.append(f"{target_key.replace('_', ' ')} from prior ledger row")
    updated["history_hints"] = sorted(set(hints))
    confidence = dict(updated.get("confidence", {}))
    if updated.get("suggested_category"):
        confidence["suggested_category"] = "high"
    updated["confidence"] = confidence
    updated["missing_fields"] = [
        field for field, score in confidence.items() if score == "low"
    ]
    return updated


def _history_exact_match(parsed: dict, txns):
    for col, key in (("PO Number", "po_number"), ("Invoice Number", "invoice_number")):
        value = _history_key(parsed.get(key))
        if not value or col not in txns.columns:
            continue
        matches = txns[txns[col].map(_history_key) == value]
        if not matches.empty:
            return matches.iloc[-1]
    return None


def _history_vendor_match(parsed: dict, txns):
    vendor = _history_key(parsed.get("vendor"))
    if not vendor or "Vendor / Payee" not in txns.columns:
        return None
    vendor_rows = txns[txns["Vendor / Payee"].map(_history_key) == vendor]
    if vendor_rows.empty:
        vendor_rows = txns[
            txns["Vendor / Payee"].map(lambda value: vendor in _history_key(value) or _history_key(value) in vendor)
        ]
    if vendor_rows.empty:
        return None
    return vendor_rows.iloc[-1]


def _history_key(value) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())


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
                "Status": "Allocated",
                "Invoice Number": order,
                "PO Number": order,
                "Entry Method": "Excel Import",
                "Notes": f"SKU: {sku} | Project: {proj} | Dept: {dept} | Fund: {fund} | Req: {req}",
            }
        )
    return result
