import hashlib
import json
from collections import Counter
from decimal import Decimal

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from budget.access import lab_access
from budget.forms import ErbImportForm
from budget.models import FiscalYear, Transaction, TransactionAudit
from budget.operation_views import (
    _claim_operation,
    _entry_team_names,
    _finish_operation,
    _refresh_mirror,
    _sheet_write_allowed,
    _transaction_snapshot,
)
from budget.services.calculations import fiscal_year_for_date
from budget.services.invoices import parse_erb_excel_bytes
from budget.services.sheets import SheetsGateway, SheetsSourceError
from budget.views import _error_response


SESSION_KEY = "erb_import_preview"


def _transaction_id(row, source_row=0):
    identity = {
        key: row.get(key)
        for key in (
            "Date",
            "Vendor / Payee",
            "Description",
            "PO Number",
            "Invoice Number",
            "Amount (AED)",
            "Notes",
        )
    }
    identity["Source Row"] = int(source_row or row.get("Source Row") or 0)
    identity = json.dumps(identity, sort_keys=True, default=str).encode("utf-8")
    return f"TXN-ERB-{hashlib.sha256(identity).hexdigest()[:16].upper()}"


def _line_signature(row):
    return tuple(
        str(row.get(key) or "").strip().casefold()
        for key in (
            "Date",
            "Team",
            "Vendor / Payee",
            "PO Number",
            "Invoice Number",
            "Description",
            "Amount (AED)",
        )
    )


@lab_access("member")
@require_http_methods(["GET", "POST"])
def erb_import(request):
    team_names = _entry_team_names(request.lab_member)
    form = ErbImportForm(request.POST or None, request.FILES or None, team_choices=team_names)
    preview = request.session.get(SESSION_KEY, [])
    if request.method == "POST" and request.POST.get("action") == "parse" and form.is_valid():
        try:
            rows = parse_erb_excel_bytes(form.cleaned_data["excel_file"].read())
        except Exception:
            return _error_response(request, "The ERB Excel file could not be parsed.", 422)
        if not rows:
            form.add_error("excel_file", "No ERB transaction rows were found.")
        else:
            preview = []
            for source_row, row in enumerate(rows, start=1):
                row["Source Row"] = source_row
                row["Transaction ID"] = _transaction_id(row, source_row)
                row["Category"] = form.cleaned_data["category"]
                row["Sub-category"] = form.cleaned_data["subcategory"]
                row["Team"] = form.cleaned_data["team"]
                row["Fiscal Year"] = fiscal_year_for_date(row.get("Date"))
                preview.append(row)
            request.session[SESSION_KEY] = preview
            request.session.modified = True
            messages.success(request, f"Parsed {len(preview)} ERB rows. Review before import.")
            return redirect("budget:erb_import")
    if request.method == "POST" and request.POST.get("action") == "commit":
        if request.lab_member.highest_role not in {"pi", "budget_manager", "lead"}:
            return _error_response(
                request,
                "An authorized budget reviewer must register ERB transactions.",
                403,
            )
        if not preview:
            messages.error(request, "Parse an ERB Excel file first.")
            return redirect("budget:erb_import")
        if not _sheet_write_allowed(request):
            return _error_response(request, "Google Sheet writes are not enabled for this account.", 403)
        missing_years = sorted(
            {
                row["Fiscal Year"]
                for row in preview
                if not FiscalYear.objects.filter(label=row["Fiscal Year"]).exists()
            }
        )
        if missing_years:
            messages.error(
                request,
                "Prepare these fiscal years before importing: " + ", ".join(missing_years),
            )
            return redirect("budget:erb_import")
        fiscal_years = {
            row["Fiscal Year"]: FiscalYear.objects.get(label=row["Fiscal Year"])
            for row in preview
        }
        unauthorized = sorted(
            {
                f"{row['Fiscal Year']} / {row.get('Team', '')}"
                for row in preview
                if row.get("Team")
                not in _entry_team_names(
                    request.lab_member, fiscal_years[row["Fiscal Year"]]
                )
            }
        )
        if unauthorized:
            return _error_response(
                request,
                "You cannot import to these fiscal-year teams: "
                + ", ".join(unauthorized),
                403,
            )
        gateway = SheetsGateway()
        touched = set()
        resolved_transaction_ids = {}
        line_counts = Counter(_line_signature(row) for row in preview)
        try:
            for row in preview:
                fy = row["Fiscal Year"]
                payload = {
                    "date": row.get("Date"),
                    "category": row.get("Category"),
                    "subcategory": row.get("Sub-category"),
                    "vendor": row.get("Vendor / Payee"),
                    "description": row.get("Description"),
                    "po_number": row.get("PO Number"),
                    "invoice_number": row.get("Invoice Number"),
                    "currency": "AED",
                    "amount": row.get("Amount (AED)"),
                    "status": "Allocated",
                    "team": row.get("Team"),
                    "entered_by": request.user.email,
                    "entry_method": "Excel Import",
                    "notes": row.get("Notes"),
                }
                operation, claimed = _claim_operation(
                    f"erb:{row['Transaction ID']}",
                    "erb_transaction",
                    request.user.email,
                    fiscal_years[fy],
                    {key: str(value) for key, value in payload.items()},
                )
                if not claimed and operation.status == "succeeded":
                    resolved_transaction_ids[row["Transaction ID"]] = str(
                        (operation.result or {}).get("transaction_id")
                        or row["Transaction ID"]
                    )
                    touched.add(fy)
                    continue
                result = gateway.write_transaction(
                    fy,
                    payload,
                    transaction_id=row["Transaction ID"],
                    allow_existing=True,
                    match_identity=(
                        "line"
                        if line_counts[_line_signature(row)] == 1
                        else False
                    ),
                )
                _finish_operation(operation, result=result)
                resolved_transaction_ids[row["Transaction ID"]] = str(
                    result.get("transaction_id") or row["Transaction ID"]
                )
                touched.add(fy)
            for fy in sorted(touched):
                _refresh_mirror(gateway, fy, request.user.email)
            for row in preview:
                transaction = Transaction.objects.get(
                    fiscal_year=fiscal_years[row["Fiscal Year"]],
                    transaction_id=resolved_transaction_ids.get(
                        row["Transaction ID"],
                        row["Transaction ID"],
                    ),
                )
                TransactionAudit.objects.get_or_create(
                    transaction=transaction,
                    action="imported_erb",
                    defaults={
                        "actor": request.user.email,
                        "after": _transaction_snapshot(transaction),
                    },
                )
        except (SheetsSourceError, ValueError) as error:
            if "operation" in locals() and operation.status == "pending":
                _finish_operation(operation, error=str(error))
            return _error_response(
                request,
                "ERB import stopped before complete verification. Retrying is safe because every row has a stable ID.",
            )
        request.session.pop(SESSION_KEY, None)
        messages.success(request, f"Imported and verified {len(preview)} ERB transactions.")
        return redirect(f"{reverse('budget:transactions')}?fy={sorted(touched)[-1]}")
    preview_rows = []
    preview_total_usd = Decimal("0")
    for row in preview:
        fiscal_year = FiscalYear.objects.filter(label=row.get("Fiscal Year")).first()
        aed_per_usd = fiscal_year.aed_per_usd if fiscal_year else Decimal("3.6725")
        amount_aed = Decimal(str(row.get("Amount (AED)") or "0"))
        amount_usd = amount_aed / aed_per_usd if aed_per_usd else Decimal("0")
        preview_total_usd += amount_usd
        preview_rows.append(
            {
                "date": row.get("Date"),
                "fiscal_year": row.get("Fiscal Year"),
                "description": row.get("Description"),
                "team": row.get("Team"),
                "invoice_number": row.get("Invoice Number"),
                "amount_aed": amount_aed,
                "amount_usd": amount_usd,
            }
        )
    return render(
        request,
        "budget/erb_import.html",
        {
            "form": form,
            "preview": preview,
            "preview_rows": preview_rows,
            "preview_total_usd": preview_total_usd,
            "sheet_write_allowed": _sheet_write_allowed(request),
            "can_commit": request.lab_member.highest_role
            in {"pi", "budget_manager", "lead"},
        },
    )
