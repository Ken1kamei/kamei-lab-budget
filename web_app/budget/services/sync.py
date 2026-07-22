import json
import re
from datetime import date
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
        "exchange_rates": {"USD": "1"},
        "aed_per_usd": "3.6725",
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


def _sync_members(team_rows: list[dict], synced_at):
    aggregate = {}
    for team_row in team_rows:
        team_name = str(team_row.get("Team Name", "")).strip()
        for role, email, name in _role_members(team_row):
            current = aggregate.setdefault(email, {"role": role, "teams": set(), "name": name})
            if ROLE_PRIORITY[role] > ROLE_PRIORITY[current["role"]]:
                current["role"] = role
            if team_name:
                current["teams"].add(team_name)
            if name and name != email:
                current["name"] = name
    pi_email = settings.PI_EMAIL
    if pi_email:
        pi = aggregate.setdefault(pi_email, {"role": "pi", "teams": set(), "name": pi_email})
        pi["role"] = "pi"
    for email, data in aggregate.items():
        LabMember.objects.update_or_create(
            email=email,
            defaults={
                "display_name": data["name"],
                "highest_role": data["role"],
                "team_names": sorted(data["teams"]),
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
        fiscal_year.sync_state = "running"
        fiscal_year.sync_error = ""
        fiscal_year.save(update_fields=["spreadsheet_id", "sync_state", "sync_error"])
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
        _sync_members(team_rows, synced_at)

        incoming_ids = []
        rates = snapshot.get("exchange_rates", {})
        for row in snapshot.get("transactions", []):
            transaction_id = str(row.get("Transaction ID", "")).strip()
            if not transaction_id:
                continue
            incoming_ids.append(transaction_id)
            currency = str(row.get("Currency", "") or "USD").strip().upper()
            amount = decimal_value(row.get("Amount"))
            if amount == 0:
                amount = decimal_value(row.get("Amount (USD)")) or decimal_value(row.get("Amount (AED)"))
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
