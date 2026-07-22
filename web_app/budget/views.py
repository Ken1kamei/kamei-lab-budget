import logging
import secrets
from collections import defaultdict
from decimal import Decimal

from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login, logout
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from budget.access import current_member, lab_access
from budget.forms import InvoiceCommitForm
from budget.models import FiscalYear, InvoiceDraft, LabMember, SyncRun, Team, Transaction
from budget.services.calculations import CATEGORIES, compare_totals, fiscal_year_for_date, money
from budget.services.invoices import create_invoice_drafts
from budget.services.sheets import SheetsGateway, SheetsSourceError
from budget.services.sync import database_totals, sync_fiscal_year


logger = logging.getLogger(__name__)
oauth = OAuth()
if settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=settings.GOOGLE_OAUTH_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def _error_response(request, message, status=503):
    request_id = secrets.token_hex(6)
    logger.exception("Budget web request failed [%s]", request_id)
    return render(
        request,
        "budget/error.html",
        {"friendly_message": message, "request_id": request_id},
        status=status,
    )


def login_view(request):
    if request.user.is_authenticated and current_member(request):
        return redirect("budget:dashboard")
    return render(
        request,
        "budget/login.html",
        {
            "google_enabled": bool(
                settings.GOOGLE_OAUTH_CLIENT_ID and settings.GOOGLE_OAUTH_CLIENT_SECRET
            ),
            "dev_enabled": settings.ALLOW_DEV_LOGIN,
        },
    )


def google_login(request):
    if "google" not in oauth._registry:
        return HttpResponseBadRequest("Google OIDC is not configured.")
    redirect_uri = settings.GOOGLE_OAUTH_REDIRECT_URI or request.build_absolute_uri(
        reverse("budget:google_callback")
    )
    return oauth.google.authorize_redirect(request, redirect_uri)


def google_callback(request):
    try:
        token = oauth.google.authorize_access_token(request)
        userinfo = token.get("userinfo") or oauth.google.userinfo(token=token)
        email = str(userinfo.get("email", "")).strip().lower()
        if not email or not userinfo.get("email_verified"):
            return HttpResponseBadRequest("Google did not return a verified email address.")
        if not LabMember.objects.filter(email=email, active=True).exists():
            return render(request, "budget/not_allowed.html", {"email": email}, status=403)
        user, _ = get_user_model().objects.update_or_create(
            username=email,
            defaults={
                "email": email,
                "first_name": str(userinfo.get("given_name", ""))[:150],
                "last_name": str(userinfo.get("family_name", ""))[:150],
            },
        )
        user.set_unusable_password()
        user.save(update_fields=["password"])
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        return redirect("budget:dashboard")
    except Exception:
        return _error_response(request, "Google sign-in could not be completed.", status=400)


def logout_view(request):
    logout(request)
    return redirect("budget:login")


@require_POST
def dev_login(request):
    if not settings.ALLOW_DEV_LOGIN:
        return HttpResponse(status=404)
    email = settings.DEV_AUTH_EMAIL
    member, _ = LabMember.objects.update_or_create(
        email=email,
        defaults={
            "display_name": "Local PI",
            "highest_role": "pi" if email == settings.PI_EMAIL else "member",
            "active": True,
        },
    )
    user, _ = get_user_model().objects.get_or_create(username=email, defaults={"email": email})
    if user.email != email:
        user.email = email
        user.save(update_fields=["email"])
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.lab_member = member
    return redirect("budget:dashboard")


def _selected_fiscal_year(request):
    years = list(FiscalYear.objects.order_by("-label"))
    selected_label = request.GET.get("fy") or request.session.get("selected_fy")
    selected = next((item for item in years if item.label == selected_label), None)
    if selected is None and years:
        selected = years[0]
    if selected:
        request.session["selected_fy"] = selected.label
    return years, selected


def _scoped_transactions(member, fiscal_year):
    transactions = fiscal_year.transactions.all()
    if member.highest_role not in {"pi", "budget_manager"}:
        transactions = transactions.filter(team__in=member.team_names)
    return transactions


def _allowed_team_names(member, fiscal_year=None):
    teams = Team.objects.filter(active=True)
    if fiscal_year is not None:
        teams = teams.filter(fiscal_year=fiscal_year)
    if member.highest_role in {"pi", "budget_manager"}:
        return list(teams.order_by("name").values_list("name", flat=True).distinct())
    if member.highest_role == "lead":
        email = member.email.strip().lower()
        return sorted(
            {
                team.name
                for team in teams
                if email in {str(value).strip().lower() for value in team.lead_emails}
            }
        )
    return []


def _visible_invoice_drafts(request):
    member = request.lab_member
    if member.highest_role in {"pi", "budget_manager"}:
        return InvoiceDraft.objects.all()
    if member.highest_role == "lead":
        lead_teams = set(_allowed_team_names(member))
        visible_emails = [
            lab_member.email
            for lab_member in LabMember.objects.filter(active=True)
            if lead_teams.intersection(lab_member.team_names)
        ]
        return InvoiceDraft.objects.filter(uploader_email__in=visible_emails)
    return InvoiceDraft.objects.filter(uploader_email=request.user.email)


def _can_commit_invoices(request):
    return (
        settings.ENABLE_SHEET_WRITES
        and request.lab_member.highest_role in {"pi", "budget_manager", "lead"}
        and request.user.email.strip().lower() in settings.SHEET_WRITE_ALLOWED_EMAILS
    )


def _draft_initial(draft, year_labels, team_names):
    parsed = dict(draft.parsed_data or {})
    invoice_date = str(parsed.get("invoice_date") or timezone.localdate().isoformat())[:10]
    try:
        suggested_year = fiscal_year_for_date(invoice_date)
    except ValueError:
        invoice_date = timezone.localdate().isoformat()
        suggested_year = fiscal_year_for_date(invoice_date)
    if suggested_year not in year_labels and year_labels:
        suggested_year = year_labels[0]
    category = str(parsed.get("suggested_category") or "Consumables")
    if category not in CATEGORIES:
        category = "Consumables"
    suggested_team = str(parsed.get("suggested_team") or "")
    return {
        "date": invoice_date,
        "fiscal_year": suggested_year,
        "category": category,
        "subcategory": str(parsed.get("suggested_subcategory") or ""),
        "vendor": str(parsed.get("vendor") or ""),
        "description": str(
            parsed.get("suggested_description") or draft.file_name
        ),
        "po_number": str(parsed.get("po_number") or ""),
        "invoice_number": str(parsed.get("invoice_number") or ""),
        "currency": str(parsed.get("currency") or "USD").upper(),
        "amount": parsed.get("total_amount") or "",
        "team": suggested_team if suggested_team in team_names else (team_names[0] if len(team_names) == 1 else ""),
        "notes": "",
    }


def _imports_context(request, active_draft=None, active_form=None, form_error=None):
    member = request.lab_member
    year_labels = list(FiscalYear.objects.order_by("-label").values_list("label", flat=True))
    team_names = _allowed_team_names(member)
    rows = []
    for draft in _visible_invoice_drafts(request):
        form = active_form if active_draft and draft.id == active_draft.id else None
        if form is None and draft.status != "imported":
            form = InvoiceCommitForm(
                initial=_draft_initial(draft, year_labels, team_names),
                year_choices=year_labels,
                team_choices=team_names,
                prefix=f"draft-{draft.id}",
            )
        rows.append({"draft": draft, "form": form})
    return {
        "draft_rows": rows,
        "form_error": form_error,
        "sheet_writes_enabled": settings.ENABLE_SHEET_WRITES,
        "can_commit_invoices": _can_commit_invoices(request),
    }


@lab_access("member")
def dashboard(request):
    years, fiscal_year = _selected_fiscal_year(request)
    if fiscal_year is None:
        return render(request, "budget/dashboard.html", {"years": [], "fiscal_year": None})
    member = request.lab_member
    totals = database_totals(fiscal_year)
    scoped = _scoped_transactions(member, fiscal_year)
    monthly = defaultdict(Decimal)
    for txn in scoped.exclude(status="Cancelled").exclude(date=None):
        monthly[txn.date.strftime("%Y-%m")] += txn.amount_usd_equiv
    max_month = max(monthly.values(), default=Decimal("1")) or Decimal("1")
    category_rows = [
        {"name": category, **totals["categories"][category]}
        for category in CATEGORIES
        if totals["categories"][category]["budget"] or totals["categories"][category]["allocated"]
    ]
    return render(
        request,
        "budget/dashboard.html",
        {
            "years": years,
            "fiscal_year": fiscal_year,
            "totals": totals,
            "category_rows": category_rows,
            "monthly_rows": [
                {"month": month, "amount": money(amount), "width": float(amount / max_month * 100)}
                for month, amount in sorted(monthly.items())
            ],
            "cancelled_count": scoped.filter(status="Cancelled").count(),
            "sync_run": fiscal_year.sync_runs.first(),
        },
    )


@lab_access("member")
def transactions_view(request):
    years, fiscal_year = _selected_fiscal_year(request)
    transactions = _scoped_transactions(request.lab_member, fiscal_year) if fiscal_year else []
    return render(
        request,
        "budget/transactions.html",
        {"years": years, "fiscal_year": fiscal_year, "transactions": transactions},
    )


@lab_access("member")
@require_http_methods(["GET", "POST"])
def imports_view(request):
    if request.method == "POST":
        uploads = request.FILES.getlist("pdfs")
        if not uploads:
            return render(
                request,
                "budget/imports.html",
                _imports_context(request, form_error="Select at least one PDF file."),
                status=400,
            )
        if len(uploads) > 20:
            return render(
                request,
                "budget/imports.html",
                _imports_context(request, form_error="Upload at most 20 PDFs at a time."),
                status=400,
            )
        try:
            create_invoice_drafts(uploads, request.user.email)
        except Exception:
            return _error_response(request, "One or more PDFs could not be parsed.", status=422)
        return redirect("budget:imports")
    return render(request, "budget/imports.html", _imports_context(request))


@lab_access("lead")
@require_POST
def commit_invoice_draft(request, draft_id):
    if not settings.ENABLE_SHEET_WRITES:
        return HttpResponse(status=404)
    if not _can_commit_invoices(request):
        return HttpResponse(status=403)
    draft = get_object_or_404(_visible_invoice_drafts(request), id=draft_id)
    if draft.status == "imported":
        messages.info(request, f"{draft.file_name} has already been imported.")
        return redirect("budget:imports")
    year_labels = list(FiscalYear.objects.order_by("-label").values_list("label", flat=True))
    team_names = _allowed_team_names(request.lab_member)
    form = InvoiceCommitForm(
        request.POST,
        year_choices=year_labels,
        team_choices=team_names,
        prefix=f"draft-{draft.id}",
    )
    if not form.is_valid():
        return render(
            request,
            "budget/imports.html",
            _imports_context(
                request,
                active_draft=draft,
                active_form=form,
                form_error="Review the highlighted invoice fields.",
            ),
            status=400,
        )
    cleaned = form.cleaned_data
    fiscal_year = get_object_or_404(FiscalYear, label=cleaned["fiscal_year"])
    allowed_for_year = _allowed_team_names(request.lab_member, fiscal_year)
    if cleaned["team"] not in allowed_for_year:
        form.add_error("team", "You cannot import transactions for this team and fiscal year.")
        return render(
            request,
            "budget/imports.html",
            _imports_context(
                request,
                active_draft=draft,
                active_form=form,
                form_error="Select a team you can access for this fiscal year.",
            ),
            status=403,
        )
    payload = {
        **cleaned,
        "file_name": draft.file_name,
        "file_sha256": draft.file_sha256,
        "entered_by": request.user.email,
        "notes": "\n".join(
            part
            for part in (
                str(cleaned.get("notes") or "").strip(),
                f"Uploaded by {draft.uploader_email}",
            )
            if part
        ),
    }
    try:
        gateway = SheetsGateway()
        result = gateway.write_invoice_transaction(fiscal_year.label, payload)
        snapshot = gateway.read_fiscal_year(fiscal_year.label)
        matches = [
            row
            for row in snapshot.get("transactions", [])
            if str(row.get("Transaction ID") or "").strip() == result["transaction_id"]
        ]
        if len(matches) != 1 or draft.file_sha256 not in str(matches[0].get("Notes") or ""):
            raise SheetsSourceError(
                "The imported transaction was not read back exactly once."
            )
    except (SheetsSourceError, ValueError):
        return _error_response(
            request,
            "The invoice could not be verified in Google Sheets. Retrying is safe because PDF imports are idempotent.",
        )
    draft.status = "imported"
    draft.imported_fiscal_year = fiscal_year.label
    draft.imported_transaction_id = result["transaction_id"]
    draft.imported_at = timezone.now()
    draft.save(
        update_fields=[
            "status",
            "imported_fiscal_year",
            "imported_transaction_id",
            "imported_at",
        ]
    )
    mirror_warning = ""
    try:
        run = sync_fiscal_year(snapshot, actor=request.user.email)
        if run.status != "matched":
            mirror_warning = (
                "The Google Sheet registration is complete, but the web dashboard "
                "mirror needs to be synchronized again."
            )
    except Exception:
        logger.exception(
            "Invoice %s was verified in Google Sheets but mirror sync failed.",
            result["transaction_id"],
        )
        mirror_warning = (
            "The Google Sheet registration is complete, but the web dashboard "
            "mirror needs to be synchronized again."
        )
    verb = "Updated" if result["matched"] else "Imported"
    messages.success(
        request,
        f"{verb} {draft.file_name} as {result['transaction_id']} in {fiscal_year.label}.",
    )
    if mirror_warning:
        messages.warning(request, mirror_warning)
    return redirect(f"{reverse('budget:transactions')}?fy={fiscal_year.label}")


@lab_access("budget_manager")
def comparison_view(request):
    years, fiscal_year = _selected_fiscal_year(request)
    runs = fiscal_year.sync_runs.all()[:20] if fiscal_year else []
    return render(
        request,
        "budget/comparison.html",
        {"years": years, "fiscal_year": fiscal_year, "runs": runs},
    )


@lab_access("budget_manager")
@require_POST
def sync_view(request):
    fiscal_year = request.POST.get("fy", "").strip()
    try:
        gateway = SheetsGateway()
        snapshot = gateway.read_fiscal_year(fiscal_year)
        run = sync_fiscal_year(snapshot, actor=request.user.email)
    except (SheetsSourceError, ValueError):
        return _error_response(request, "The Google Sheet mirror could not be refreshed.")
    if run.status != "matched":
        return redirect(f"{reverse('budget:comparison')}?fy={fiscal_year}")
    return redirect(f"{reverse('budget:dashboard')}?fy={fiscal_year}")


def health(request):
    return HttpResponse("ok", content_type="text/plain")
