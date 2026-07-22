import logging
import secrets
from collections import defaultdict
from decimal import Decimal

from authlib.integrations.django_client import OAuth
from django.conf import settings
from django.contrib.auth import get_user_model, login, logout
from django.http import HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from budget.access import current_member, lab_access
from budget.models import FiscalYear, InvoiceDraft, LabMember, SyncRun, Transaction
from budget.services.calculations import CATEGORIES, compare_totals, money
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
    drafts = InvoiceDraft.objects.filter(uploader_email=request.user.email)
    if request.method == "POST":
        uploads = request.FILES.getlist("pdfs")
        if not uploads:
            return render(
                request,
                "budget/imports.html",
                {"drafts": drafts, "form_error": "Select at least one PDF file."},
                status=400,
            )
        if len(uploads) > 20:
            return render(
                request,
                "budget/imports.html",
                {"drafts": drafts, "form_error": "Upload at most 20 PDFs at a time."},
                status=400,
            )
        try:
            create_invoice_drafts(uploads, request.user.email)
        except Exception:
            return _error_response(request, "One or more PDFs could not be parsed.", status=422)
        return redirect("budget:imports")
    return render(request, "budget/imports.html", {"drafts": drafts})


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
