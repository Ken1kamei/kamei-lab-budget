import json

from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from budget.access import lab_access
from budget.forms import AllocationForm, ExchangeRateForm, MemberForm, TeamForm
from budget.models import AdministrativeAudit, FiscalYear, LabMember, Team
from budget.operation_views import _sheet_write_allowed
from budget.services.calculations import CATEGORIES, DEFAULT_RATES_TO_USD
from budget.services.sheets import SheetsGateway, SheetsSourceError
from budget.services.sync import sync_fiscal_year
from budget.views import _error_response, _selected_fiscal_year


def _choices():
    return list(FiscalYear.objects.order_by("-label").values_list("label", flat=True))


def _sync(gateway, fiscal_year, actor):
    snapshot = gateway.read_fiscal_year(fiscal_year)
    run = sync_fiscal_year(snapshot, actor=actor)
    if run.status != "matched":
        raise SheetsSourceError("Saved values did not match the web mirror.")
    return snapshot


def _audit(request, action, target, before=None, after=None):
    AdministrativeAudit.objects.create(
        actor=request.user.email,
        action=action,
        target=target,
        before=json.loads(json.dumps(before or {}, default=str)),
        after=json.loads(json.dumps(after or {}, default=str)),
    )


def _settings_context(request, fiscal_year, **overrides):
    years = list(FiscalYear.objects.order_by("-label"))
    labels = [row.label for row in years]
    allocations = {
        row.category: row.budget_usd for row in fiscal_year.allocations.all()
    } if fiscal_year else {}
    team_names = sorted(
        set(Team.objects.filter(active=True).values_list("name", flat=True))
    )
    rates = {code: DEFAULT_RATES_TO_USD[code] for code in DEFAULT_RATES_TO_USD}
    aed_per_usd = "3.6725"
    if fiscal_year:
        rates.update(fiscal_year.exchange_rates or {})
        aed_per_usd = str(fiscal_year.aed_per_usd)
    context = {
        "years": years,
        "fiscal_year": fiscal_year,
        "allocation_form": AllocationForm(
            initial={"fiscal_year": fiscal_year.label if fiscal_year else ""},
            year_choices=labels,
            allocations=allocations,
            prefix="alloc",
        ),
        "team_form": TeamForm(
            initial={"fiscal_year": fiscal_year.label if fiscal_year else "", "active": True},
            year_choices=labels,
            allow_manager_assignment=request.lab_member.highest_role == "pi",
            prefix="team",
        ),
        "rate_form": ExchangeRateForm(
            initial={
                "fiscal_year": fiscal_year.label if fiscal_year else "",
                "aed_per_usd": aed_per_usd,
                "eur_to_usd": rates.get("EUR"),
                "jpy_to_usd": rates.get("JPY"),
                "gbp_to_usd": rates.get("GBP"),
            },
            year_choices=labels,
            prefix="rate",
        ),
        "member_form": MemberForm(team_choices=team_names, prefix="member"),
        "teams": fiscal_year.teams.all() if fiscal_year else [],
        "members": LabMember.objects.order_by("display_name", "email"),
        "sheet_write_allowed": _sheet_write_allowed(request),
    }
    context.update(overrides)
    return context


@lab_access("budget_manager")
@require_http_methods(["GET", "POST"])
def settings_page(request):
    years, fiscal_year = _selected_fiscal_year(request)
    if request.method == "GET":
        return render(request, "budget/settings.html", _settings_context(request, fiscal_year))
    if not _sheet_write_allowed(request):
        return _error_response(request, "Google Sheet writes are not enabled for this account.", 403)
    action = request.POST.get("action", "")
    labels = [row.label for row in years]
    gateway = SheetsGateway()
    try:
        if action == "allocations":
            form = AllocationForm(
                request.POST,
                year_choices=labels,
                prefix="alloc",
            )
            if not form.is_valid():
                return render(
                    request,
                    "budget/settings.html",
                    _settings_context(request, fiscal_year, allocation_form=form),
                    status=400,
                )
            target = form.cleaned_data["fiscal_year"]
            before = {
                row.category: row.budget_usd
                for row in FiscalYear.objects.get(label=target).allocations.all()
            }
            gateway.write_category_allocations(target, form.allocation_values())
            _sync(gateway, target, request.user.email)
            _audit(request, "allocations_updated", target, before, form.allocation_values())
            messages.success(request, f"Saved and verified category budgets for {target}.")
            return redirect(f"{reverse('budget:settings')}?fy={target}")
        if action == "team":
            form = TeamForm(
                request.POST,
                year_choices=labels,
                allow_manager_assignment=request.lab_member.highest_role == "pi",
                prefix="team",
            )
            if not form.is_valid():
                return render(
                    request,
                    "budget/settings.html",
                    _settings_context(request, fiscal_year, team_form=form),
                    status=400,
                )
            target = form.cleaned_data["fiscal_year"]
            payload = dict(form.cleaned_data)
            current_team = Team.objects.filter(
                fiscal_year__label=target, name=payload["name"]
            ).first()
            before = {
                "name": current_team.name,
                "allocation_usd": current_team.allocation_usd,
                "manager_emails": current_team.manager_emails,
                "lead_emails": current_team.lead_emails,
                "member_emails": current_team.member_emails,
                "active": current_team.active,
            } if current_team else {}
            if "manager_emails" not in payload:
                payload["manager_emails"] = ",".join(
                    current_team.manager_emails if current_team else []
                )
            gateway.upsert_registry_team(payload)
            gateway.upsert_team(target, payload)
            _sync(gateway, target, request.user.email)
            _audit(request, "team_updated", f"{target}:{payload['name']}", before, payload)
            messages.success(request, f"Saved and verified {form.cleaned_data['name']} in {target}.")
            return redirect(f"{reverse('budget:settings')}?fy={target}#teams")
        if action == "rates":
            form = ExchangeRateForm(request.POST, year_choices=labels, prefix="rate")
            if not form.is_valid():
                return render(
                    request,
                    "budget/settings.html",
                    _settings_context(request, fiscal_year, rate_form=form),
                    status=400,
                )
            target = form.cleaned_data["fiscal_year"]
            year = FiscalYear.objects.get(label=target)
            before = {
                "aed_per_usd": year.aed_per_usd,
                "exchange_rates": year.exchange_rates,
            }
            for key, value in {
                "AED/USD Exchange Rate": form.cleaned_data["aed_per_usd"],
                "EUR/USD Exchange Rate": form.cleaned_data["eur_to_usd"],
                "JPY/USD Exchange Rate": form.cleaned_data["jpy_to_usd"],
                "GBP/USD Exchange Rate": form.cleaned_data["gbp_to_usd"],
            }.items():
                gateway.set_config(target, key, value)
            _sync(gateway, target, request.user.email)
            _audit(request, "exchange_rates_updated", target, before, form.cleaned_data)
            messages.success(request, f"Saved and verified exchange rates for {target}.")
            return redirect(f"{reverse('budget:settings')}?fy={target}#rates")
        if action == "member":
            if request.lab_member.highest_role != "pi":
                return _error_response(request, "Only the PI can change the lab roster.", 403)
            team_names = sorted(set(Team.objects.values_list("name", flat=True)))
            form = MemberForm(request.POST, team_choices=team_names, prefix="member")
            if not form.is_valid():
                return render(
                    request,
                    "budget/settings.html",
                    _settings_context(request, fiscal_year, member_form=form),
                    status=400,
                )
            gateway.upsert_registry_member(form.cleaned_data)
            for target in labels:
                _sync(gateway, target, request.user.email)
            _audit(
                request,
                "member_updated",
                form.cleaned_data["email"],
                {},
                form.cleaned_data,
            )
            messages.success(request, f"Saved and verified access for {form.cleaned_data['email']}.")
            return redirect(f"{reverse('budget:settings')}?fy={fiscal_year.label}#members")
        if action == "fiscal_year":
            if request.lab_member.highest_role != "pi":
                return _error_response(request, "Only the PI can create a fiscal year.", 403)
            target = request.POST.get("new_fiscal_year", "").strip()
            result = gateway.queue_fiscal_year_creation(target)
            _audit(request, "fiscal_year_queued", target, {}, result)
            messages.success(
                request,
                f"Queued {target}. The PI-owned Google Sheet creator will register it shortly.",
            )
            return redirect(f"{reverse('budget:settings')}?fy={fiscal_year.label}#fiscal-year")
    except (SheetsSourceError, ValueError):
        return _error_response(
            request,
            "The settings change was not confirmed in Google Sheets. No success was recorded.",
        )
    return _error_response(request, "Unknown settings action.", 400)
