import csv
import hashlib
import io
import json
import logging
import secrets
from datetime import date, timedelta

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponse
from django.db import transaction as db_transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from budget.access import lab_access
from budget.forms import ReceiptAttachmentForm, TransactionForm
from budget.models import FiscalYear, SheetOperation, Transaction, TransactionAudit
from budget.services.calculations import (
    DEFAULT_RATES_TO_USD,
    fiscal_year_for_date,
)
from budget.services.sheets import SheetsGateway, SheetsSourceError
from budget.services.sync import sync_fiscal_year
from budget.views import (
    _error_response,
    _can_attach_receipt,
    _can_full_edit_transaction,
    _lead_team_names,
    _scoped_transactions,
    _selected_fiscal_year,
    _visible_team_names,
)


logger = logging.getLogger(__name__)


def _transaction_snapshot(row):
    if row is None:
        return {}
    return {
        "fiscal_year": row.fiscal_year.label,
        "transaction_id": row.transaction_id,
        "date": str(row.date or ""),
        "category": row.category,
        "subcategory": row.subcategory,
        "vendor": row.vendor,
        "description": row.description,
        "po_number": row.po_number,
        "invoice_number": row.invoice_number,
        "currency": row.currency,
        "amount": str(row.amount),
        "amount_usd_equiv": str(row.amount_usd_equiv),
        "status": row.status,
        "team": row.team,
        "receipt_confirmed": row.receipt_confirmed,
        "pdf_link": row.pdf_link,
        "notes": row.notes,
    }


def _claim_operation(key, operation_type, actor, fiscal_year, request_payload):
    with db_transaction.atomic():
        operation, created = SheetOperation.objects.select_for_update().get_or_create(
            idempotency_key=key,
            defaults={
                "operation_type": operation_type,
                "actor": actor,
                "fiscal_year": fiscal_year,
                "request": request_payload,
            },
        )
        if not created and operation.status == "succeeded":
            return operation, False
        if not created and operation.status == "pending":
            from django.utils import timezone

            if operation.updated_at >= timezone.now() - timedelta(minutes=5):
                return operation, False
        operation.operation_type = operation_type
        operation.actor = actor
        operation.fiscal_year = fiscal_year
        operation.request = request_payload
        operation.status = "pending"
        operation.error = ""
        operation.save()
        return operation, True


def _finish_operation(operation, *, result=None, error=""):
    operation.result = json.loads(json.dumps(result or {}, default=str))
    operation.error = error
    operation.status = "failed" if error else "succeeded"
    from django.utils import timezone

    operation.completed_at = timezone.now()
    operation.save(update_fields=["result", "error", "status", "completed_at", "updated_at"])


def _csv_safe(value):
    text = str(value if value is not None else "")
    return f"'{text}" if text.startswith(("=", "+", "-", "@")) else text


def _sheet_write_allowed(request):
    allowed = settings.SHEET_WRITE_ALLOWED_EMAILS
    return settings.ENABLE_SHEET_WRITES and (
        "*" in allowed or request.user.email.strip().lower() in allowed
    )


def _entry_team_names(member, fiscal_year=None):
    names = set(_visible_team_names(member, fiscal_year))
    if fiscal_year is not None:
        names.intersection_update(
            fiscal_year.teams.filter(active=True).values_list("name", flat=True)
        )
    return sorted(names)


def _editable_transactions(member, fiscal_year):
    if member.highest_role in {"pi", "budget_manager"}:
        return fiscal_year.transactions.all()
    lead_teams = _lead_team_names(member, fiscal_year)
    return fiscal_year.transactions.filter(team__in=lead_teams)


def _receiptable_transactions(member, fiscal_year):
    visible_teams = _visible_team_names(member, fiscal_year)
    return fiscal_year.transactions.filter(
        team__in=visible_teams,
        entered_by__iexact=member.email,
    )


def _year_choices():
    return list(FiscalYear.objects.order_by("-label").values_list("label", flat=True))


def _initial_for_transaction(transaction):
    return {
        "date": transaction.date,
        "fiscal_year": transaction.fiscal_year.label,
        "category": transaction.category,
        "subcategory": transaction.subcategory,
        "vendor": transaction.vendor,
        "description": transaction.description,
        "po_number": transaction.po_number,
        "invoice_number": transaction.invoice_number,
        "currency": transaction.currency,
        "amount": transaction.amount,
        "status": transaction.status,
        "team": transaction.team,
        "receipt_confirmed": transaction.receipt_confirmed or bool(
            str(transaction.source_payload.get("Receipt Confirmed", "")).upper()
            in {"TRUE", "Y", "YES", "1"}
        ),
        "pdf_link": transaction.pdf_link,
        "notes": transaction.notes,
    }


def _refresh_mirror(gateway, fiscal_year_label, actor):
    snapshot = gateway.read_fiscal_year(fiscal_year_label)
    run = sync_fiscal_year(snapshot, actor=actor)
    if run.status != "matched":
        raise SheetsSourceError("Google Sheet saved, but the web mirror did not match it.")
    return run


def _year_details():
    details = {}
    for fiscal_year in FiscalYear.objects.order_by("-label"):
        rates = {
            code: str(value)
            for code, value in DEFAULT_RATES_TO_USD.items()
        }
        rates.update(
            {
                str(code).upper(): str(value)
                for code, value in (fiscal_year.exchange_rates or {}).items()
            }
        )
        if fiscal_year.aed_per_usd:
            rates["AED"] = str(1 / fiscal_year.aed_per_usd)
        details[fiscal_year.label] = {
            "ready": bool(fiscal_year.spreadsheet_id),
            "rates": rates,
        }
    return details


@lab_access("member")
@require_http_methods(["GET", "POST"])
def add_transaction(request):
    year_labels = _year_choices()
    selected_year = request.POST.get("fiscal_year") or request.GET.get("fy")
    if selected_year not in year_labels:
        selected_year = fiscal_year_for_date(date.today())
    selected_fy = FiscalYear.objects.filter(label=selected_year).first()
    team_names = _entry_team_names(request.lab_member, selected_fy)
    initial = {
        "idempotency_key": secrets.token_urlsafe(24),
        "date": date.today(),
        "fiscal_year": selected_year,
        "currency": "USD",
        "status": "Allocated",
        "team": team_names[0] if len(team_names) == 1 else "",
    }
    form = TransactionForm(
        request.POST or None,
        initial=initial,
        year_choices=year_labels,
        team_choices=team_names,
    )
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        target_fy = get_object_or_404(FiscalYear, label=cleaned["fiscal_year"])
        allowed_teams = _entry_team_names(request.lab_member, target_fy)
        if cleaned["team"] not in allowed_teams:
            form.add_error("team", "Select a team you can access for this fiscal year.")
        elif not _sheet_write_allowed(request):
            form.add_error(None, "Google Sheet writes are not enabled for this account yet.")
        else:
            payload = {
                **cleaned,
                "entered_by": request.user.email,
                "entry_method": "Manual",
            }
            operation, claimed = _claim_operation(
                cleaned["idempotency_key"],
                "create_transaction",
                request.user.email,
                target_fy,
                {key: str(value) for key, value in payload.items()},
            )
            if not claimed:
                if operation.status == "succeeded":
                    messages.info(request, "This expense was already saved.")
                    return redirect(f"{reverse('budget:transactions')}?fy={target_fy.label}")
                messages.warning(request, "This expense is already being processed.")
                return redirect("budget:add_transaction")
            try:
                gateway = SheetsGateway()
                stable_transaction_id = (
                    "TXN-WEB-"
                    + hashlib.sha256(cleaned["idempotency_key"].encode("utf-8"))
                    .hexdigest()[:16]
                    .upper()
                )
                result = gateway.write_transaction(
                    target_fy.label,
                    payload,
                    transaction_id=stable_transaction_id,
                    allow_existing=True,
                )
                _refresh_mirror(gateway, target_fy.label, request.user.email)
                created = Transaction.objects.get(
                    fiscal_year=target_fy, transaction_id=result["transaction_id"]
                )
                TransactionAudit.objects.create(
                    transaction=created,
                    actor=request.user.email,
                    action="created",
                    after=_transaction_snapshot(created),
                )
                operation.transaction = created
                operation.save(update_fields=["transaction"])
                _finish_operation(operation, result=result)
            except (SheetsSourceError, ValueError) as error:
                _finish_operation(operation, error=str(error))
                return _error_response(
                    request,
                    "The expense was not confirmed in Google Sheets. Retrying is safe.",
                )
            messages.success(
                request,
                f"Saved {result['transaction_id']} in {target_fy.label} and verified the Google Sheet row.",
            )
            return redirect(f"{reverse('budget:transactions')}?fy={target_fy.label}")
    return render(
        request,
        "budget/transaction_form.html",
        {
            "form": form,
            "mode": "add",
            "sheet_write_allowed": _sheet_write_allowed(request),
            "year_details": _year_details(),
        },
    )


@lab_access("member")
@require_http_methods(["GET", "POST"])
def edit_transaction(request, fiscal_year, transaction_id):
    source_fy = get_object_or_404(FiscalYear, label=fiscal_year)
    transaction = get_object_or_404(
        _editable_transactions(request.lab_member, source_fy),
        transaction_id=transaction_id,
    )
    year_labels = _year_choices()
    submitted_year = request.POST.get("fiscal_year") or source_fy.label
    target_fy = FiscalYear.objects.filter(label=submitted_year).first() or source_fy
    team_names = _entry_team_names(request.lab_member, target_fy)
    form = TransactionForm(
        request.POST or None,
        initial={**_initial_for_transaction(transaction), "idempotency_key": secrets.token_urlsafe(24)},
        year_choices=year_labels,
        team_choices=team_names,
    )
    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        target_fy = get_object_or_404(FiscalYear, label=cleaned["fiscal_year"])
        if cleaned["team"] not in _entry_team_names(request.lab_member, target_fy):
            form.add_error("team", "Select a team you can access for this fiscal year.")
        elif not _sheet_write_allowed(request):
            form.add_error(None, "Google Sheet writes are not enabled for this account yet.")
        else:
            before = _transaction_snapshot(transaction)
            payload = {
                **cleaned,
                "entered_by": transaction.entered_by or request.user.email,
                "entry_method": transaction.entry_method or "Manual",
                "last_known_payload": transaction.source_payload,
            }
            operation, claimed = _claim_operation(
                cleaned["idempotency_key"],
                "update_transaction",
                request.user.email,
                target_fy,
                {key: str(value) for key, value in payload.items()},
            )
            if not claimed:
                if operation.status == "succeeded":
                    messages.info(request, "These changes were already saved.")
                    return redirect(f"{reverse('budget:transactions')}?fy={target_fy.label}")
                messages.warning(request, "This update is already being processed.")
                return redirect(
                    "budget:edit_transaction", source_fy.label, transaction.transaction_id
                )
            try:
                gateway = SheetsGateway()
                result = gateway.update_transaction(
                    source_fy.label,
                    transaction.transaction_id,
                    payload,
                    target_fiscal_year=target_fy.label,
                )
                _refresh_mirror(gateway, target_fy.label, request.user.email)
                if target_fy.label != source_fy.label:
                    _refresh_mirror(gateway, source_fy.label, request.user.email)
                updated = Transaction.objects.get(
                    fiscal_year=target_fy, transaction_id=result["transaction_id"]
                )
                TransactionAudit.objects.create(
                    transaction=updated,
                    actor=request.user.email,
                    action="cancelled" if updated.status == "Cancelled" else "updated",
                    before=before,
                    after=_transaction_snapshot(updated),
                )
                operation.transaction = updated
                operation.save(update_fields=["transaction"])
                _finish_operation(operation, result=result)
            except (SheetsSourceError, ValueError) as error:
                _finish_operation(operation, error=str(error))
                return _error_response(
                    request,
                    "The transaction update was not confirmed in Google Sheets. No success was recorded.",
                )
            messages.success(
                request,
                f"Updated {result['transaction_id']} and verified the Google Sheet row.",
            )
            return redirect(f"{reverse('budget:transactions')}?fy={target_fy.label}")
    return render(
        request,
        "budget/transaction_form.html",
        {
            "form": form,
            "mode": "edit",
            "transaction": transaction,
            "sheet_write_allowed": _sheet_write_allowed(request),
            "year_details": _year_details(),
        },
    )


@lab_access("member")
@require_http_methods(["GET", "POST"])
def attach_receipt(request, fiscal_year, transaction_id):
    source_fy = get_object_or_404(FiscalYear, label=fiscal_year)
    transaction = get_object_or_404(
        _receiptable_transactions(request.lab_member, source_fy),
        transaction_id=transaction_id,
    )
    if not _can_attach_receipt(request.lab_member, source_fy, transaction):
        return HttpResponse(status=403)
    initial = {
        "idempotency_key": secrets.token_urlsafe(24),
        "receipt_confirmed": transaction.receipt_confirmed or bool(
            str(transaction.source_payload.get("Receipt Confirmed", "")).upper()
            in {"TRUE", "Y", "YES", "1"}
        ),
        "pdf_link": transaction.pdf_link,
        "notes": transaction.notes,
    }
    form = ReceiptAttachmentForm(request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        if not _sheet_write_allowed(request):
            form.add_error(None, "Google Sheet writes are not enabled for this account yet.")
        else:
            cleaned = form.cleaned_data
            before = _transaction_snapshot(transaction)
            payload = {
                **_initial_for_transaction(transaction),
                **cleaned,
                "entered_by": transaction.entered_by or request.user.email,
                "entry_method": transaction.entry_method or "Manual",
                "last_known_payload": transaction.source_payload,
            }
            operation, claimed = _claim_operation(
                cleaned["idempotency_key"],
                "attach_receipt",
                request.user.email,
                source_fy,
                {key: str(value) for key, value in payload.items()},
            )
            if not claimed:
                if operation.status == "succeeded":
                    messages.info(request, "This receipt update was already saved.")
                    return redirect(
                        f"{reverse('budget:transactions')}?fy={source_fy.label}"
                    )
                messages.warning(request, "This receipt update is already being processed.")
                return redirect(
                    "budget:attach_receipt", source_fy.label, transaction.transaction_id
                )
            try:
                gateway = SheetsGateway()
                result = gateway.update_transaction(
                    source_fy.label,
                    transaction.transaction_id,
                    payload,
                    target_fiscal_year=source_fy.label,
                )
                _refresh_mirror(gateway, source_fy.label, request.user.email)
                updated = Transaction.objects.get(
                    fiscal_year=source_fy,
                    transaction_id=result["transaction_id"],
                )
                TransactionAudit.objects.create(
                    transaction=updated,
                    actor=request.user.email,
                    action="receipt_attached",
                    before=before,
                    after=_transaction_snapshot(updated),
                )
                operation.transaction = updated
                operation.save(update_fields=["transaction"])
                _finish_operation(operation, result=result)
            except (SheetsSourceError, ValueError) as error:
                _finish_operation(operation, error=str(error))
                return _error_response(
                    request,
                    "The receipt update was not confirmed in Google Sheets. Retrying is safe.",
                )
            messages.success(
                request,
                f"Updated the receipt details for {result['transaction_id']} and verified the Google Sheet row.",
            )
            return redirect(f"{reverse('budget:transactions')}?fy={source_fy.label}")
    return render(
        request,
        "budget/receipt_form.html",
        {
            "form": form,
            "transaction": transaction,
            "sheet_write_allowed": _sheet_write_allowed(request),
        },
    )


@lab_access("member")
def export_transactions(request):
    years, fiscal_year = _selected_fiscal_year(request)
    if fiscal_year is None:
        return HttpResponse(status=404)
    rows = _scoped_transactions(request.lab_member, fiscal_year)
    category = request.GET.get("category", "").strip()
    status = request.GET.get("status", "").strip()
    team = request.GET.get("team", "").strip()
    query = request.GET.get("q", "").strip()
    if category:
        rows = rows.filter(category=category)
    if status:
        rows = rows.filter(status=status)
    if team:
        rows = rows.filter(team=team)
    if query:
        rows = rows.filter(
            Q(transaction_id__icontains=query)
            | Q(vendor__icontains=query)
            | Q(description__icontains=query)
            | Q(po_number__icontains=query)
            | Q(invoice_number__icontains=query)
        )
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "Transaction ID",
            "Date",
            "Fiscal Year",
            "Team",
            "Category",
            "Sub-category",
            "Vendor / Payee",
            "Description",
            "PO Number",
            "Invoice Number",
            "Currency",
            "Amount",
            "Amount (USD equiv)",
            "Status",
            "Entered By",
            "Notes",
        ]
    )
    for row in rows:
        writer.writerow(
            [_csv_safe(value) for value in [
                row.transaction_id,
                row.date,
                fiscal_year.label,
                row.team,
                row.category,
                row.subcategory,
                row.vendor,
                row.description,
                row.po_number,
                row.invoice_number,
                row.currency,
                row.amount,
                row.amount_usd_equiv,
                row.status,
                row.entered_by,
                row.notes,
            ]]
        )
    response = HttpResponse(output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="transactions-{fiscal_year.label}.csv"'
    return response
