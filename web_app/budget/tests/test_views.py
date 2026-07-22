from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from budget.models import CategoryAllocation, FiscalYear, InvoiceDraft, LabMember, Team, Transaction


@pytest.fixture
def pi_client(client):
    user = get_user_model().objects.create_user(username="kk4801", email="kk4801@nyu.edu")
    LabMember.objects.create(email="kk4801@nyu.edu", display_name="Ken Kamei", highest_role="pi", active=True)
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_dashboard_renders_selected_fiscal_year_totals(pi_client):
    fy = FiscalYear.objects.create(label="FY2026-27", spreadsheet_id="sheet")
    CategoryAllocation.objects.create(fiscal_year=fy, category="Consumables", budget_usd=Decimal("10000"))
    Transaction.objects.create(
        fiscal_year=fy,
        transaction_id="TXN-1",
        category="Consumables",
        currency="USD",
        amount=Decimal("2500"),
        amount_usd_equiv=Decimal("2500"),
        status="Allocated",
    )

    response = pi_client.get(reverse("budget:dashboard"), {"fy": "FY2026-27"})

    assert response.status_code == 200
    assert b"FY2026-27" in response.content
    assert b"$10,000.00" in response.content
    assert b"$2,500.00" in response.content
    assert b"$7,500.00" in response.content
    assert b"budget/favicon.svg" in response.content


@pytest.mark.django_db
def test_unknown_member_is_denied_even_with_valid_google_session(client):
    user = get_user_model().objects.create_user(username="unknown", email="unknown@nyu.edu")
    client.force_login(user)

    response = client.get(reverse("budget:dashboard"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_comparison_page_is_restricted_to_pi_and_budget_manager(client):
    user = get_user_model().objects.create_user(username="member", email="member@nyu.edu")
    LabMember.objects.create(email="member@nyu.edu", highest_role="member", active=True)
    client.force_login(user)

    response = client.get(reverse("budget:comparison"))

    assert response.status_code == 403


@pytest.mark.django_db
def test_lead_can_review_and_commit_invoice_to_own_team(client, monkeypatch, settings):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"lead@nyu.edu"}
    user = get_user_model().objects.create_user(username="lead", email="lead@nyu.edu")
    LabMember.objects.create(
        email="lead@nyu.edu",
        highest_role="lead",
        team_names=["Diabetes"],
        active=True,
    )
    LabMember.objects.create(
        email="member@nyu.edu",
        highest_role="member",
        team_names=["Diabetes"],
        active=True,
    )
    fiscal_year = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(
        fiscal_year=fiscal_year,
        name="Diabetes",
        lead_emails=["lead@nyu.edu"],
        active=True,
    )
    draft = InvoiceDraft.objects.create(
        uploader_email="member@nyu.edu",
        file_name="invoice.pdf",
        file_sha256="abc123",
        parsed_data={},
    )
    captured = {}

    class Gateway:
        def write_invoice_transaction(self, fiscal_year_label, payload):
            captured.update({"fiscal_year": fiscal_year_label, "payload": payload})
            return {"transaction_id": "TXN-TEST", "matched": False}

        def read_fiscal_year(self, fiscal_year_label):
            return {
                "fiscal_year": fiscal_year_label,
                "transactions": [
                    {"Transaction ID": "TXN-TEST", "Notes": "[PDF SHA256:abc123]"}
                ],
            }

    class Run:
        status = "matched"

    monkeypatch.setattr("budget.views.SheetsGateway", Gateway)
    monkeypatch.setattr("budget.views.sync_fiscal_year", lambda snapshot, actor: Run())
    client.force_login(user)

    response = client.post(
        reverse("budget:commit_invoice_draft", args=[draft.id]),
        {
            f"draft-{draft.id}-date": "2026-03-26",
            f"draft-{draft.id}-fiscal_year": "FY2025-26",
            f"draft-{draft.id}-category": "Consumables",
            f"draft-{draft.id}-subcategory": "Assay kits",
            f"draft-{draft.id}-vendor": "PeopleSoft Inventory",
            f"draft-{draft.id}-description": "QUBIT RNA BR ASSAY KIT",
            f"draft-{draft.id}-po_number": "",
            f"draft-{draft.id}-invoice_number": "INS6000_9216658",
            f"draft-{draft.id}-currency": "USD",
            f"draft-{draft.id}-amount": "151.95",
            f"draft-{draft.id}-team": "Diabetes",
            f"draft-{draft.id}-notes": "Reviewed",
        },
    )

    assert response.status_code == 302
    assert response.url == f"{reverse('budget:transactions')}?fy=FY2025-26"
    draft.refresh_from_db()
    assert draft.status == "imported"
    assert draft.imported_transaction_id == "TXN-TEST"
    assert captured["fiscal_year"] == "FY2025-26"
    assert captured["payload"]["team"] == "Diabetes"
    assert captured["payload"]["file_sha256"] == "abc123"
    assert "Uploaded by member@nyu.edu" in captured["payload"]["notes"]


@pytest.mark.django_db
def test_verified_sheet_import_stays_imported_when_mirror_sync_fails(
    client, monkeypatch, settings
):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"kk4801@nyu.edu"}
    user = get_user_model().objects.create_user(
        username="kk4801", email="kk4801@nyu.edu"
    )
    LabMember.objects.create(
        email="kk4801@nyu.edu", highest_role="pi", active=True
    )
    fiscal_year = FiscalYear.objects.create(
        label="FY2025-26", spreadsheet_id="sheet"
    )
    Team.objects.create(fiscal_year=fiscal_year, name="Core Lab", active=True)
    draft = InvoiceDraft.objects.create(
        uploader_email="kk4801@nyu.edu",
        file_name="verified.pdf",
        file_sha256="verified-hash",
        parsed_data={},
    )

    class Gateway:
        def write_invoice_transaction(self, fiscal_year_label, payload):
            return {"transaction_id": "TXN-VERIFIED", "matched": False}

        def read_fiscal_year(self, fiscal_year_label):
            return {
                "fiscal_year": fiscal_year_label,
                "transactions": [
                    {
                        "Transaction ID": "TXN-VERIFIED",
                        "Notes": "[PDF SHA256:verified-hash]",
                    }
                ],
            }

    monkeypatch.setattr("budget.views.SheetsGateway", Gateway)

    def fail_sync(snapshot, actor):
        raise RuntimeError("mirror down")

    monkeypatch.setattr("budget.views.sync_fiscal_year", fail_sync)
    client.force_login(user)

    response = client.post(
        reverse("budget:commit_invoice_draft", args=[draft.id]),
        {
            f"draft-{draft.id}-date": "2026-03-26",
            f"draft-{draft.id}-fiscal_year": "FY2025-26",
            f"draft-{draft.id}-category": "Consumables",
            f"draft-{draft.id}-vendor": "Vendor",
            f"draft-{draft.id}-description": "Description",
            f"draft-{draft.id}-invoice_number": "INV-VERIFIED",
            f"draft-{draft.id}-currency": "USD",
            f"draft-{draft.id}-amount": "10.00",
            f"draft-{draft.id}-team": "Core Lab",
        },
        follow=True,
    )

    assert response.status_code == 200
    assert b"Google Sheet registration is complete" in response.content
    draft.refresh_from_db()
    assert draft.status == "imported"
    assert draft.imported_transaction_id == "TXN-VERIFIED"


@pytest.mark.django_db
def test_member_cannot_commit_an_invoice(client, monkeypatch, settings):
    settings.ENABLE_SHEET_WRITES = True
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"kk4801@nyu.edu"}
    user = get_user_model().objects.create_user(username="member", email="member@nyu.edu")
    LabMember.objects.create(
        email="member@nyu.edu",
        highest_role="member",
        team_names=["Diabetes"],
        active=True,
    )
    fiscal_year = FiscalYear.objects.create(label="FY2025-26", spreadsheet_id="sheet")
    Team.objects.create(fiscal_year=fiscal_year, name="Diabetes", active=True)
    draft = InvoiceDraft.objects.create(
        uploader_email="member@nyu.edu",
        file_name="invoice.pdf",
        file_sha256="abc123",
        parsed_data={},
    )
    client.force_login(user)

    response = client.post(
        reverse("budget:commit_invoice_draft", args=[draft.id]),
        {
            f"draft-{draft.id}-date": "2026-03-26",
            f"draft-{draft.id}-fiscal_year": "FY2025-26",
            f"draft-{draft.id}-category": "Consumables",
            f"draft-{draft.id}-vendor": "Vendor",
            f"draft-{draft.id}-description": "Description",
            f"draft-{draft.id}-invoice_number": "INV-1",
            f"draft-{draft.id}-currency": "USD",
            f"draft-{draft.id}-amount": "10.00",
            f"draft-{draft.id}-team": "Diabetes",
        },
    )

    assert response.status_code == 403
    draft.refresh_from_db()
    assert draft.status != "imported"


@pytest.mark.django_db
def test_invoice_commit_endpoint_is_closed_when_sheet_writes_are_disabled(client, settings):
    settings.ENABLE_SHEET_WRITES = False
    settings.SHEET_WRITE_ALLOWED_EMAILS = {"lead@nyu.edu"}
    user = get_user_model().objects.create_user(username="lead", email="lead@nyu.edu")
    LabMember.objects.create(email="lead@nyu.edu", highest_role="lead", active=True)
    draft = InvoiceDraft.objects.create(
        uploader_email="lead@nyu.edu",
        file_name="invoice.pdf",
        file_sha256="abc123",
        parsed_data={},
    )
    client.force_login(user)

    response = client.post(reverse("budget:commit_invoice_draft", args=[draft.id]))

    assert response.status_code == 404
