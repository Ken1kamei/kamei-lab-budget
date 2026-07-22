from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from budget.models import CategoryAllocation, FiscalYear, LabMember, Transaction


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
