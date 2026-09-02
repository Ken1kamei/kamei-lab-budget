from datetime import date
from decimal import Decimal

from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from budget.models import FiscalYear, InvoiceDraft, LabMember, Team, Transaction
from labapps.permissions import (
    app_roles,
    is_portal_admin,
    project_team_ids,
    scope_tracker_records,
    truthy,
)
from labapps.services.sheets import snapshot_rows


BUDGET_ALERT_THRESHOLD = Decimal("80")
COMPLETED_STATUSES = {"complete", "completed", "done", "cancelled", "canceled"}


def _parse_date(value):
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except (TypeError, ValueError):
        return None


def _tracker_rows(member):
    roles = app_roles(member, "project_tracker")
    if not roles and not is_portal_admin(member):
        return [], []
    unrestricted = is_portal_admin(member) or any(
        not role.get("scope_team_id") for role in roles
    )
    projects = snapshot_rows("Projects")
    milestones = snapshot_rows("Milestones")
    experiments = snapshot_rows("Experiments")
    memberships = [
        row
        for row in snapshot_rows("Member_Teams")
        if truthy(row.get("active", "TRUE"))
    ]
    projects, milestones, experiments = scope_tracker_records(
        member,
        projects,
        milestones,
        experiments,
        memberships,
    )
    if unrestricted:
        return milestones, experiments

    allowed_team_ids = {
        role.get("scope_team_id") for role in roles if role.get("scope_team_id")
    }
    member_ids = {
        row.get("member_id")
        for row in memberships
        if row.get("team_id") in allowed_team_ids
    }
    projects = [
        row
        for row in projects
        if project_team_ids(row, memberships) & allowed_team_ids
    ]
    project_ids = {row.get("project_id") for row in projects}
    milestones = [
        row
        for row in milestones
        if row.get("owner_member_id") in member_ids
        or row.get("project_id") in project_ids
    ]
    milestone_ids = {row.get("milestone_id") for row in milestones}
    experiments = [
        row
        for row in experiments
        if row.get("member_id") in member_ids
        or row.get("milestone_id") in milestone_ids
    ]
    return milestones, experiments


def _budget_member(email):
    return LabMember.objects.filter(email__iexact=email, active=True).first()


def _budget_team_names(member, fiscal_year):
    if member.highest_role in {"pi", "budget_manager"}:
        return list(
            fiscal_year.teams.filter(active=True).values_list("name", flat=True)
        )
    configured = member.team_roles or {}
    annual_roles = configured.get(fiscal_year.label, {})
    if annual_roles:
        return list(annual_roles)
    return list(member.team_names or [])


def _visible_invoice_drafts(member, email, team_names, fiscal_year):
    drafts = InvoiceDraft.objects.filter(status__in={"ready", "review", "processing"})
    if member.highest_role in {"pi", "budget_manager"}:
        return drafts
    lead_teams = {
        name
        for name, role in (member.team_roles or {}).get(fiscal_year.label, {}).items()
        if role == "lead"
    }
    if not member.team_roles and member.highest_role == "lead":
        lead_teams = set(team_names)
    return drafts.filter(Q(uploader_email__iexact=email) | Q(team__in=lead_teams))


def _budget_alerts(member, fiscal_year, team_names):
    alerts = []
    transactions = Transaction.objects.filter(fiscal_year=fiscal_year).exclude(
        status="Cancelled"
    )
    if member.highest_role not in {"pi", "budget_manager"}:
        transactions = transactions.filter(team__in=team_names)

    allocated_by_team = {
        row["team"]: row["allocated"] or Decimal("0")
        for row in transactions.values("team").annotate(allocated=Sum("amount_usd_equiv"))
    }
    for team in Team.objects.filter(
        fiscal_year=fiscal_year, active=True, name__in=team_names
    ):
        if team.allocation_usd <= 0:
            continue
        utilization = allocated_by_team.get(team.name, Decimal("0")) * 100 / team.allocation_usd
        if utilization >= BUDGET_ALERT_THRESHOLD:
            alerts.append((team.name, utilization))

    if member.highest_role in {"pi", "budget_manager"}:
        allocated_by_category = {
            row["category"]: row["allocated"] or Decimal("0")
            for row in transactions.values("category").annotate(
                allocated=Sum("amount_usd_equiv")
            )
        }
        for allocation in fiscal_year.allocations.all():
            if allocation.budget_usd <= 0:
                continue
            utilization = (
                allocated_by_category.get(allocation.category, Decimal("0"))
                * 100
                / allocation.budget_usd
            )
            if utilization >= BUDGET_ALERT_THRESHOLD:
                alerts.append((allocation.category, utilization))
    return alerts


def build_action_panel(member, email):
    today = timezone.localdate()
    milestones, experiments = _tracker_rows(member)
    tracker_rows = [*milestones, *experiments]
    overdue = []
    for row in tracker_rows:
        due_date = _parse_date(row.get("due_date"))
        status = str(row.get("status") or "").strip().lower()
        if due_date is not None and due_date < today and status not in COMPLETED_STATUSES:
            overdue.append(row)
    blocked = [
        row
        for row in tracker_rows
        if str(row.get("status") or "").strip().lower() == "blocked"
    ]
    tracker_pending = [
        row
        for row in tracker_rows
        if str(row.get("review_status") or "").strip().lower() == "pending"
    ]

    fiscal_year = FiscalYear.objects.order_by("-label").first()
    budget_member = _budget_member(email)
    invoice_count = 0
    budget_alerts = []
    if fiscal_year and budget_member:
        team_names = _budget_team_names(budget_member, fiscal_year)
        invoice_count = _visible_invoice_drafts(
            budget_member, email, team_names, fiscal_year
        ).count()
        budget_alerts = _budget_alerts(budget_member, fiscal_year, team_names)

    highest_alert = max((value for _, value in budget_alerts), default=Decimal("0"))
    critical = sum(value >= 100 for _, value in budget_alerts)
    return {
        "as_of": today,
        "fiscal_year": fiscal_year.label if fiscal_year and budget_member else "",
        "items": [
            {
                "label": "Overdue",
                "count": len(overdue),
                "detail": "Past-due milestones and experiments",
                "url": f"{reverse('labapps:tracker')}#milestones",
                "tone": "danger" if overdue else "clear",
                "visible": bool(milestones or experiments or app_roles(member, "project_tracker")),
            },
            {
                "label": "Blocked",
                "count": len(blocked),
                "detail": "Items waiting for intervention",
                "url": f"{reverse('labapps:tracker')}#review",
                "tone": "danger" if blocked else "clear",
                "visible": bool(milestones or experiments or app_roles(member, "project_tracker")),
            },
            {
                "label": "Pending approval",
                "count": len(tracker_pending) + invoice_count,
                "detail": f"Tracker {len(tracker_pending)} · invoices {invoice_count}",
                "url": f"{reverse('labapps:tracker')}#review" if tracker_pending else reverse("budget:imports"),
                "tone": "warning" if tracker_pending or invoice_count else "clear",
                "visible": bool(app_roles(member, "project_tracker") or budget_member),
            },
            {
                "label": "Budget alert",
                "count": len(budget_alerts),
                "detail": (
                    f"{critical} critical · highest {highest_alert:.0f}%"
                    if budget_alerts
                    else "No allocation at or above 80%"
                ),
                "url": reverse("budget:dashboard"),
                "tone": "danger" if critical else "warning" if budget_alerts else "clear",
                "visible": bool(fiscal_year and budget_member),
            },
        ],
    }
