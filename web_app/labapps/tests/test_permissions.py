import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory

from labapps.models import SheetRecord
from labapps.permissions import app_role, can_write, current_registry_member


pytestmark = pytest.mark.django_db


def record(table, record_id, payload):
    return SheetRecord.objects.create(
        source="registry", table_name=table, record_id=record_id, payload=payload
    )


def test_registry_member_and_scoped_app_role_are_resolved():
    record(
        "Members",
        "M009",
        {"member_id": "M009", "email": "maab@nyu.edu", "active": "TRUE", "global_role": "member"},
    )
    record(
        "App_Roles",
        "AR009",
        {
            "member_id": "M009", "app_id": "project_tracker", "app_role": "lead",
            "scope_team_id": "T002", "active": "TRUE",
        },
    )
    request = RequestFactory().get("/tracker/")
    request.user = get_user_model().objects.create_user(
        username="maab@nyu.edu", email="maab@nyu.edu"
    )
    member = current_registry_member(request)
    assert member["member_id"] == "M009"
    assert app_role(member, "project_tracker") == {"role": "lead", "scope_team_id": "T002"}
    assert can_write(member, "project_tracker") is True


def test_inactive_registry_member_is_rejected():
    record(
        "Members",
        "M010",
        {"member_id": "M010", "email": "inactive@nyu.edu", "active": "FALSE"},
    )
    request = RequestFactory().get("/portal/")
    request.user = get_user_model().objects.create_user(
        username="inactive@nyu.edu", email="inactive@nyu.edu"
    )
    assert current_registry_member(request) is None
