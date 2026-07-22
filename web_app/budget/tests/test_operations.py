from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from budget.models import (
    AdministrativeAudit,
    CategoryAllocation,
    FiscalYear,
    LabMember,
    SheetOperation,
    Team,
    Transaction,
    TransactionAudit,
)
from budget.forms import TeamForm
from budget.services.sheets import SheetsSourceError


def _login(client, email, role="member", teams=None):
    user = get_user_model().objects.create_user(username=email, email=email)
    LabMember.objects.create(
        email=email,
        highest_role=role,
        team_names=teams or [],
        active=True,
    )
    client.force_login(user)
    return user


def test_team_form_only_exposes_manager_assignment_to_pi():
    manager_form = TeamForm(year_choices=["FY2026-27"], allow_manager_assignment=False)
    pi_form = TeamForm(year_choices=["FY2026-27"], allow_manager_assignment=True)

    assert "manager_emails" not in manager_form.fields
    assert "manager_emails" in pi_form.fields


@pytest.mark.django_db
def test_member_add_expense_is_idempotent_and_audited(client, monkeypatch, settings):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"*"}
    _login(client, "member@nyu.edu", teams=["Diabetes"])
    fy = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(fiscal_year=fy, name="Diabetes", active=True)
    calls = []

    class Gateway:
        def write_transaction(
            self, fiscal_year, payload, transaction_id="", allow_existing=False
        ):
            calls.append((fiscal_year, payload, transaction_id, allow_existing))
            return {"transaction_id": transaction_id, "row": {}, "matched": False}

    def refresh(gateway, label, actor):
        Transaction.objects.update_or_create(
            fiscal_year=fy,
            transaction_id=calls[-1][2],
            defaults={
                "date": "2026-02-01",
                "category": "Consumables",
                "vendor": "Vendor",
                "description": "Reagent",
                "currency": "USD",
                "amount": Decimal("25"),
                "amount_usd_equiv": Decimal("25"),
                "status": "Allocated",
                "team": "Diabetes",
                "entered_by": actor,
            },
        )

    monkeypatch.setattr("budget.operation_views.SheetsGateway", Gateway)
    monkeypatch.setattr("budget.operation_views._refresh_mirror", refresh)
    data = {
        "idempotency_key": "create-once",
        "date": "2026-02-01",
        "fiscal_year": "FY2025-26",
        "category": "Consumables",
        "subcategory": "Reagents",
        "vendor": "Vendor",
        "description": "Reagent",
        "po_number": "PO-1",
        "invoice_number": "INV-1",
        "currency": "USD",
        "amount": "25.00",
        "status": "Allocated",
        "team": "Diabetes",
        "notes": "",
    }

    first = client.post(reverse("budget:add_transaction"), data)
    second = client.post(reverse("budget:add_transaction"), data)

    assert first.status_code == 302
    assert second.status_code == 302
    assert len(calls) == 1
    operation = SheetOperation.objects.get(idempotency_key="create-once")
    assert operation.status == "succeeded"
    assert operation.transaction.transaction_id.startswith("TXN-WEB-")
    assert calls[0][3] is True
    assert TransactionAudit.objects.get().action == "created"


@pytest.mark.django_db
def test_member_add_expense_recovers_after_sheet_write_when_first_sync_fails(
    client, monkeypatch, settings
):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"*"}
    _login(client, "member@nyu.edu", teams=["Diabetes"])
    fy = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(fiscal_year=fy, name="Diabetes", active=True)
    sheet_rows = {}
    sync_attempts = 0

    class Gateway:
        def write_transaction(
            self, fiscal_year, payload, transaction_id="", allow_existing=False
        ):
            matched = transaction_id in sheet_rows
            sheet_rows.setdefault(transaction_id, dict(payload))
            return {
                "transaction_id": transaction_id,
                "row": sheet_rows[transaction_id],
                "matched": matched,
            }

    def refresh(gateway, label, actor):
        nonlocal sync_attempts
        sync_attempts += 1
        if sync_attempts == 1:
            raise SheetsSourceError("temporary mirror failure")
        transaction_id = next(iter(sheet_rows))
        Transaction.objects.update_or_create(
            fiscal_year=fy,
            transaction_id=transaction_id,
            defaults={
                "date": "2026-02-01",
                "category": "Consumables",
                "vendor": "Vendor",
                "description": "Reagent",
                "currency": "USD",
                "amount": Decimal("25"),
                "amount_usd_equiv": Decimal("25"),
                "status": "Allocated",
                "team": "Diabetes",
                "entered_by": actor,
            },
        )

    monkeypatch.setattr("budget.operation_views.SheetsGateway", Gateway)
    monkeypatch.setattr("budget.operation_views._refresh_mirror", refresh)
    data = {
        "idempotency_key": "recover-create",
        "date": "2026-02-01",
        "fiscal_year": "FY2025-26",
        "category": "Consumables",
        "vendor": "Vendor",
        "description": "Reagent",
        "currency": "USD",
        "amount": "25.00",
        "status": "Allocated",
        "team": "Diabetes",
    }

    first = client.post(reverse("budget:add_transaction"), data)
    second = client.post(reverse("budget:add_transaction"), data)

    assert first.status_code == 503
    assert second.status_code == 302
    assert len(sheet_rows) == 1
    assert sync_attempts == 2
    assert SheetOperation.objects.get(idempotency_key="recover-create").status == "succeeded"


@pytest.mark.django_db
def test_member_cannot_edit_another_members_transaction(client):
    _login(client, "member@nyu.edu", teams=["Diabetes"])
    fy = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(fiscal_year=fy, name="Diabetes", active=True)
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-OTHER",
        team="Diabetes",
        entered_by="other@nyu.edu",
    )

    response = client.get(
        reverse("budget:edit_transaction", args=["FY2025-26", "TXN-OTHER"])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_lead_cannot_edit_a_transaction_outside_own_team(client):
    _login(client, "lead@nyu.edu", role="lead", teams=["Diabetes"])
    fy = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(
        fiscal_year=fy,
        name="Diabetes",
        lead_emails=["lead@nyu.edu"],
        active=True,
    )
    Team.objects.create(fiscal_year=fy, name="IoC", active=True)
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-IOC",
        team="IoC",
        entered_by="member@nyu.edu",
    )

    response = client.get(
        reverse("budget:edit_transaction", args=["FY2025-26", "TXN-IOC"])
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_mixed_team_roles_only_allow_lead_edits_in_led_team(client):
    user = _login(client, "mixed@nyu.edu", role="lead", teams=["Diabetes", "IoC"])
    member = LabMember.objects.get(email=user.email)
    member.team_roles = {
        "FY2025-26": {"Diabetes": "lead", "IoC": "member"}
    }
    member.save(update_fields=["team_roles"])
    fy = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(fiscal_year=fy, name="Diabetes", active=True)
    Team.objects.create(fiscal_year=fy, name="IoC", active=True)
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-D-OTHER",
        team="Diabetes",
        entered_by="other@nyu.edu",
    )
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-I-OTHER",
        team="IoC",
        entered_by="other@nyu.edu",
    )
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-I-OWN",
        team="IoC",
        entered_by="mixed@nyu.edu",
    )

    assert client.get(
        reverse("budget:edit_transaction", args=[fy.label, "TXN-D-OTHER"])
    ).status_code == 200
    assert client.get(
        reverse("budget:edit_transaction", args=[fy.label, "TXN-I-OTHER"])
    ).status_code == 404
    assert client.get(
        reverse("budget:edit_transaction", args=[fy.label, "TXN-I-OWN"])
    ).status_code == 200


@pytest.mark.django_db
def test_mixed_team_roles_include_all_visible_teams_in_dashboard_totals(client):
    user = _login(client, "mixed@nyu.edu", role="lead", teams=["Diabetes", "IoC"])
    member = LabMember.objects.get(email=user.email)
    member.team_roles = {
        "FY2025-26": {"Diabetes": "lead", "IoC": "member"},
        "FY2026-27": {"Other Year Team": "lead"},
    }
    member.save(update_fields=["team_roles"])
    fy = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(
        fiscal_year=fy, name="Diabetes", allocation_usd=Decimal("1000"), active=True
    )
    Team.objects.create(
        fiscal_year=fy, name="IoC", allocation_usd=Decimal("2000"), active=True
    )
    Team.objects.create(
        fiscal_year=fy, name="Other Year Team", allocation_usd=Decimal("9000"), active=True
    )
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-D",
        team="Diabetes",
        amount_usd_equiv=Decimal("100"),
        status="Allocated",
    )
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-I",
        team="IoC",
        amount_usd_equiv=Decimal("200"),
        status="Allocated",
    )

    response = client.get(reverse("budget:dashboard"), {"fy": fy.label})

    assert response.status_code == 200
    assert response.context["totals"]["total_budget"] == Decimal("3000.00")
    assert response.context["totals"]["total_allocated"] == Decimal("300.00")
    assert set(response.context["totals"]["teams"]) == {"Diabetes", "IoC"}


@pytest.mark.django_db
def test_member_dashboard_is_scoped_to_own_team(client):
    _login(client, "member@nyu.edu", teams=["Diabetes"])
    fy = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(
        fiscal_year=fy, name="Diabetes", allocation_usd=Decimal("1000"), active=True
    )
    Team.objects.create(
        fiscal_year=fy, name="IoC", allocation_usd=Decimal("9000"), active=True
    )
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-D",
        team="Diabetes",
        category="Consumables",
        amount_usd_equiv=Decimal("100"),
        status="Allocated",
    )
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-I",
        team="IoC",
        category="Consumables",
        amount_usd_equiv=Decimal("8000"),
        status="Allocated",
    )

    response = client.get(reverse("budget:dashboard"), {"fy": "FY2025-26"})

    assert response.status_code == 200
    assert b"$1,000.00" in response.content
    assert b"$100.00" in response.content
    assert b"$8,000.00" not in response.content


@pytest.mark.django_db
def test_lead_can_cancel_own_team_transaction(client, monkeypatch, settings):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"*"}
    _login(client, "lead@nyu.edu", role="lead", teams=["Diabetes"])
    fy = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(
        fiscal_year=fy,
        name="Diabetes",
        lead_emails=["lead@nyu.edu"],
        active=True,
    )
    txn = Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-1",
        date="2026-02-01",
        category="Consumables",
        vendor="Vendor",
        description="Item",
        currency="USD",
        amount=Decimal("100"),
        amount_usd_equiv=Decimal("100"),
        status="Allocated",
        team="Diabetes",
        entered_by="member@nyu.edu",
    )

    class Gateway:
        def update_transaction(self, source, transaction_id, payload, target_fiscal_year=None):
            assert payload["status"] == "Cancelled"
            return {"transaction_id": transaction_id, "row": {}, "moved": False}

    def refresh(gateway, label, actor):
        txn.status = "Cancelled"
        txn.save(update_fields=["status"])

    monkeypatch.setattr("budget.operation_views.SheetsGateway", Gateway)
    monkeypatch.setattr("budget.operation_views._refresh_mirror", refresh)
    response = client.post(
        reverse("budget:edit_transaction", args=["FY2025-26", "TXN-1"]),
        {
            "idempotency_key": "cancel-once",
            "date": "2026-02-01",
            "fiscal_year": "FY2025-26",
            "category": "Consumables",
            "vendor": "Vendor",
            "description": "Item",
            "currency": "USD",
            "amount": "100.00",
            "status": "Cancelled",
            "team": "Diabetes",
        },
    )

    assert response.status_code == 302
    txn.refresh_from_db()
    assert txn.status == "Cancelled"
    assert TransactionAudit.objects.get().action == "cancelled"


@pytest.mark.django_db
def test_budget_manager_saves_fiscal_year_allocations(client, monkeypatch, settings):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"*"}
    _login(client, "manager@nyu.edu", role="budget_manager")
    fy = FiscalYear.objects.create(label="FY2026-27", spreadsheet_id="sheet")
    captured = {}

    class Gateway:
        def read_fiscal_year(self, label):
            return {"exchange_rates": {}, "aed_per_usd": "3.6725"}

        def write_category_allocations(self, label, values):
            captured.update(values)
            return {"fiscal_year": label}

    def sync(gateway, label, actor):
        for category, amount in captured.items():
            CategoryAllocation.objects.update_or_create(
                fiscal_year=fy, category=category, defaults={"budget_usd": amount}
            )

    monkeypatch.setattr("budget.settings_views.SheetsGateway", Gateway)
    monkeypatch.setattr("budget.settings_views._sync", sync)
    data = {"action": "allocations", "alloc-fiscal_year": "FY2026-27"}
    for category in (
        "equipment",
        "consumables",
        "personnel",
        "travel",
        "publications",
        "memberships",
        "other",
    ):
        data[f"alloc-budget_{category}"] = "10000" if category == "consumables" else "0"

    response = client.post(reverse("budget:settings"), data)

    assert response.status_code == 302
    assert CategoryAllocation.objects.get(
        fiscal_year=fy, category="Consumables"
    ).budget_usd == Decimal("10000")
    audit = AdministrativeAudit.objects.get(action="allocations_updated")
    assert audit.actor == "manager@nyu.edu"
    assert audit.target == "FY2026-27"


@pytest.mark.django_db
def test_erb_preview_and_commit_use_stable_ids(client, monkeypatch, settings):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"*"}
    _login(client, "lead@nyu.edu", role="lead", teams=["Diabetes"])
    fy = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(
        fiscal_year=fy,
        name="Diabetes",
        lead_emails=["lead@nyu.edu"],
        active=True,
    )
    monkeypatch.setattr(
        "budget.erb_views.parse_erb_excel_bytes",
        lambda payload: [
            {
                "Date": "2026-02-01",
                "Category": "Consumables",
                "Sub-category": "NYUAD Stores",
                "Vendor / Payee": "NYUAD ERB (Stores)",
                "Description": "Tube",
                "Amount (AED)": 36.725,
                "Invoice Number": "1001",
                "PO Number": "1001",
                "Notes": "SKU: TUBE",
            }
        ],
    )
    saved_ids = []

    class Gateway:
        def write_transaction(
            self, label, payload, transaction_id="", allow_existing=False
        ):
            saved_ids.append(transaction_id)
            return {"transaction_id": transaction_id, "row": {}}

    monkeypatch.setattr("budget.erb_views.SheetsGateway", Gateway)

    def refresh(*args):
        for transaction_id in saved_ids:
            Transaction.objects.update_or_create(
                fiscal_year=fy,
                transaction_id=transaction_id,
                defaults={
                    "date": "2026-02-01",
                    "category": "Consumables",
                    "currency": "AED",
                    "amount": Decimal("36.725"),
                    "amount_usd_equiv": Decimal("10"),
                    "status": "Allocated",
                    "team": "Diabetes",
                },
            )

    monkeypatch.setattr("budget.erb_views._refresh_mirror", refresh)
    parsed = client.post(
        reverse("budget:erb_import"),
        {
            "action": "parse",
            "category": "Consumables",
            "subcategory": "NYUAD Stores",
            "team": "Diabetes",
            "excel_file": SimpleUploadedFile(
                "erb.xlsx",
                b"fake",
                content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    committed = client.post(reverse("budget:erb_import"), {"action": "commit"})

    assert parsed.status_code == 302
    assert committed.status_code == 302
    assert len(saved_ids) == 1
    assert saved_ids[0].startswith("TXN-ERB-")
