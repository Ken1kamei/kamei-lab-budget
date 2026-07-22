import json
import re
from datetime import date, datetime
from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from budget.models import CategoryAllocation, FiscalYear, LabMember, SyncRun, Team, Transaction
from budget.services.calculations import (
    CATEGORIES,
    canonical_status,
    compare_totals,
    decimal_value,
    money,
    snapshot_totals,
    split_emails,
    summary_budget_usd,
    transaction_usd_equivalent,
)


ROLE_PRIORITY = {"member": 1, "lead": 2, "budget_manager": 3, "pi": 4}


def _safe_payload(value):
    return json.loads(json.dumps(value, default=str))


def _parse_date(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _parse_datetime(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _validate_snapshot(snapshot: dict) -> str:
    if not isinstance(snapshot, dict):
        raise ValueError("Sheet snapshot must be a dictionary.")
    fiscal_year = str(snapshot.get("fiscal_year", "")).strip()
    if not re.fullmatch(r"FY\d{4}-\d{2}", fiscal_year):
        raise ValueError("Fiscal year must look like FY2026-27.")
    for key in ("summary", "teams", "transactions"):
        if not isinstance(snapshot.get(key, []), list):
            raise ValueError(f"Sheet snapshot field {key} must be a list.")
    return fiscal_year


def _database_snapshot(fiscal_year: FiscalYear) -> dict:
    summary = [
        {"Category": row.category, "Budgeted (USD equiv)": str(row.budget_usd)}
        for row in fiscal_year.allocations.all()
    ]
    teams = [
        {
            "Team Name": row.name,
            "Allocation (USD)": str(row.allocation_usd),
            "Active": "Y" if row.active else "N",
        }
        for row in fiscal_year.teams.all()
    ]
    transactions = [
        {
            "Transaction ID": row.transaction_id,
            "Category": row.category,
            "Status": row.status,
            "Currency": row.currency,
            "Amount": str(row.amount),
            "Amount (USD equiv)": str(row.amount_usd_equiv),
            "Team": row.team,
        }
        for row in fiscal_year.transactions.all()
    ]
    return {
        "fiscal_year": fiscal_year.label,
        "summary": summary,
        "teams": teams,
        "transactions": transactions,
        "exchange_rates": fiscal_year.exchange_rates or {"USD": "1"},
        "aed_per_usd": str(fiscal_year.aed_per_usd),
    }


def database_totals(fiscal_year: FiscalYear) -> dict:
    return snapshot_totals(_database_snapshot(fiscal_year))


def _role_members(team_row: dict):
    def names(value):
        return [item.strip() for item in str(value or "").replace(";", ",").split(",") if item.strip()]

    manager_names = names(team_row.get("Budget Manager Names"))
    lead_names = names(team_row.get("Lead Names"))
    member_names = names(team_row.get("Member Names"))
    name_lists = {
        "budget_manager": manager_names,
        "lead": lead_names,
        "member": member_names,
    }
    for role, email_key in (
        ("budget_manager", "Budget Manager Emails"),
        ("lead", "Lead Emails"),
        ("member", "Member Emails"),
    ):
        emails = split_emails(team_row.get(email_key))
        names = name_lists[role]
        for index, email in enumerate(emails):
            yield role, email, names[index] if index < len(names) else email


def _sync_members(team_rows: list[dict], member_rows: list[dict], fiscal_year_label, synced_at):
    display_names = {}
    for team_row in team_rows:
        for _, email, name in _role_members(team_row):
            if name and name != email:
                display_names[email] = name
    aggregate = {}
    for row in member_rows:
        email = str(row.get("email", "")).strip().lower()
        if not email or not row.get("active", True):
            continue
        role = str(row.get("role", "member")).strip().lower()
        if role not in ROLE_PRIORITY:
            role = "member"
        raw_team_roles = row.get("team_roles") or {}
        team_roles = {
            str(name): "lead" if str(team_role).lower() == "lead" else "member"
            for name, team_role in raw_team_roles.items()
        }
        aggregate[email] = {
            "role": role,
            "teams": set(team_roles),
            "team_roles": {fiscal_year_label: team_roles},
            "name": str(row.get("display_name") or email),
        }
    for team in Team.objects.filter(active=True):
        role_emails = (
            ("lead", team.manager_emails),
            ("lead", team.lead_emails),
            ("member", team.member_emails),
        )
        for role, emails in role_emails:
            for email in emails:
                email = str(email or "").strip().lower()
                if not email:
                    continue
                current = aggregate.setdefault(
                    email,
                    {
                        "role": role,
                        "teams": set(),
                        "team_roles": {},
                        "name": display_names.get(email, email),
                    },
                )
                existing = LabMember.objects.filter(email=email).first()
                if existing and existing.highest_role in {"pi", "budget_manager"}:
                    current["role"] = existing.highest_role
                elif ROLE_PRIORITY[role] > ROLE_PRIORITY[current["role"]]:
                    current["role"] = role
                current["teams"].add(team.name)
                annual_roles = current["team_roles"].setdefault(team.fiscal_year.label, {})
                if role == "lead" or annual_roles.get(team.name) != "lead":
                    annual_roles[team.name] = role
                if email in display_names:
                    current["name"] = display_names[email]
    pi_email = settings.PI_EMAIL
    if pi_email:
        pi = aggregate.setdefault(
            pi_email,
            {"role": "pi", "teams": set(), "team_roles": {}, "name": pi_email},
        )
        pi["role"] = "pi"
    LabMember.objects.filter(last_synced_at__isnull=False).exclude(
        email__in=aggregate.keys()
    ).update(active=False, last_synced_at=synced_at)
    for email, data in aggregate.items():
        existing_name = (
            LabMember.objects.filter(email=email)
            .values_list("display_name", flat=True)
            .first()
        )
        LabMember.objects.update_or_create(
            email=email,
            defaults={
                "display_name": (
                    data["name"]
                    if data["name"] != email
                    else existing_name or email
                ),
                "highest_role": data["role"],
                "team_names": sorted(data["teams"]),
                "team_roles": data["team_roles"],
                "active": True,
                "last_synced_at": synced_at,
            },
        )


def sync_fiscal_year(snapshot: dict, actor="system") -> SyncRun:
    fiscal_year_label = _validate_snapshot(snapshot)
    source_totals = snapshot_totals(snapshot)
    synced_at = timezone.now()
    with transaction.atomic():
        fiscal_year, _ = FiscalYear.objects.select_for_update().get_or_create(label=fiscal_year_label)
        fiscal_year.spreadsheet_id = str(snapshot.get("spreadsheet_id", ""))
        fiscal_year.exchange_rates = _safe_payload(snapshot.get("exchange_rates", {}))
        fiscal_year.aed_per_usd = decimal_value(snapshot.get("aed_per_usd"), "3.6725")
        fiscal_year.sync_state = "running"
        fiscal_year.sync_error = ""
        fiscal_year.save(
            update_fields=[
                "spreadsheet_id",
                "exchange_rates",
                "aed_per_usd",
                "sync_state",
                "sync_error",
            ]
        )
        run = SyncRun.objects.create(
            fiscal_year=fiscal_year,
            actor=actor,
            source_transaction_count=len(snapshot.get("transactions", [])),
            source_totals=_safe_payload(source_totals),
        )

        summary_by_category = {
            str(row.get("Category", "")).strip(): row for row in snapshot.get("summary", [])
        }
        for category in CATEGORIES:
            CategoryAllocation.objects.update_or_create(
                fiscal_year=fiscal_year,
                category=category,
                defaults={
                    "budget_usd": summary_budget_usd(
                        summary_by_category.get(category, {}),
                        decimal_value(snapshot.get("aed_per_usd"), "3.6725"),
                    )
                },
            )

        fiscal_year.teams.all().delete()
        team_rows = snapshot.get("teams", [])
        for row in team_rows:
            name = str(row.get("Team Name", "")).strip()
            if not name:
                continue
            if str(row.get("Allocation (USD)", "")).strip() != "":
                allocation = decimal_value(row.get("Allocation (USD)"))
            else:
                allocation = decimal_value(row.get("Allocation (AED)")) / Decimal("3.6725")
            Team.objects.create(
                fiscal_year=fiscal_year,
                name=name,
                allocation_usd=money(allocation),
                manager_emails=split_emails(row.get("Budget Manager Emails")),
                lead_emails=split_emails(row.get("Lead Emails")),
                member_emails=split_emails(row.get("Member Emails")),
                description=str(row.get("Description", "")),
                active=str(row.get("Active", "Y")).strip().upper() in {"Y", "YES", "TRUE", "1"},
            )
        _sync_members(
            team_rows,
            snapshot.get("members", []),
            fiscal_year_label,
            synced_at,
        )

        incoming_ids = []
        rates = snapshot.get("exchange_rates", {})
        for row in snapshot.get("transactions", []):
            transaction_id = str(row.get("Transaction ID", "")).strip()
            if not transaction_id:
                continue
            incoming_ids.append(transaction_id)
            raw_currency = str(row.get("Currency", "") or "").strip().upper()
            amount = decimal_value(row.get("Amount"))
            legacy_usd = decimal_value(row.get("Amount (USD)"))
            legacy_aed = decimal_value(row.get("Amount (AED)"))
            currency = raw_currency or ("USD" if legacy_usd else "AED" if legacy_aed else "USD")
            if amount == 0:
                amount = legacy_usd or legacy_aed
            Transaction.objects.update_or_create(
                fiscal_year=fiscal_year,
                transaction_id=transaction_id,
                defaults={
                    "date": _parse_date(row.get("Date")),
                    "category": str(row.get("Category", "")),
                    "subcategory": str(row.get("Sub-category", "")),
                    "vendor": str(row.get("Vendor / Payee", "")),
                    "description": str(row.get("Description", "")),
                    "po_number": str(row.get("PO Number", "")),
                    "invoice_number": str(row.get("Invoice Number", "")),
                    "currency": currency[:3],
                    "amount": money(amount),
                    "amount_usd_equiv": transaction_usd_equivalent(row, rates),
                    "status": canonical_status(row.get("Status")),
                    "team": str(row.get("Team", "")),
                    "entered_by": str(row.get("Entered By", "")),
                    "entry_method": str(row.get("Entry Method", "")),
                    "notes": str(row.get("Notes", "")),
                    "pdf_link": str(row.get("PDF Link", "")),
                    "receipt_confirmed": str(row.get("Receipt Confirmed", "")).strip().upper()
                    in {"TRUE", "Y", "YES", "1"},
                    "email_thread_id": str(row.get("Email Thread ID", "")),
                    "approved_by": str(row.get("Approved By", "")),
                    "approved_at": _parse_datetime(row.get("Approved At")),
                    "sheet_last_modified_at": _parse_datetime(row.get("Last Modified")),
                    "source_payload": _safe_payload(row),
                },
            )
        stale = fiscal_year.transactions.all()
        if incoming_ids:
            stale = stale.exclude(transaction_id__in=incoming_ids)
        stale.delete()

        mirror_totals = database_totals(fiscal_year)
        comparison = compare_totals(source_totals, mirror_totals)
        run.status = "matched" if comparison["matches"] else "mismatch"
        run.finished_at = synced_at
        run.mirror_transaction_count = fiscal_year.transactions.count()
        run.mirror_totals = _safe_payload(mirror_totals)
        run.differences = comparison["differences"]
        run.save()
        fiscal_year.synced_at = synced_at
        fiscal_year.sync_state = run.status
        fiscal_year.save(update_fields=["synced_at", "sync_state"])
    return run
