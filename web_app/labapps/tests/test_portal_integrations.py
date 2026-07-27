from datetime import datetime
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import pytest
from cryptography.fernet import Fernet
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client, override_settings

from labapps.models import LabAppAudit, SheetRecord, SlackConnection
from labapps.services.calendar import lab_calendar_week
from labapps.services.slack import (
    SLACK_USER_SCOPES,
    SlackIntegrationError,
    decrypt_token,
    encrypt_token,
    exchange_code,
)


pytestmark = pytest.mark.django_db
FERNET_KEY = Fernet.generate_key().decode("ascii")
SLACK_SETTINGS = {
    "SLACK_CLIENT_ID": "client-123",
    "SLACK_CLIENT_SECRET": "secret-456",
    "SLACK_REDIRECT_URI": "https://portal.example/portal/slack/callback/",
    "SLACK_TEAM_ID": "T-KAMEI",
    "SLACK_TEAM_NAME": "KameiLab_NYUAD",
    "SLACK_TOKEN_ENCRYPTION_KEY": FERNET_KEY,
}


def add_member(email, member_id):
    SheetRecord.objects.create(
        source="registry",
        table_name="Members",
        record_id=member_id,
        payload={
            "member_id": member_id,
            "email": email,
            "display_name": email.split("@", 1)[0],
            "global_role": "member",
            "active": "TRUE",
        },
    )


def signed_in_client(email):
    add_member(email, f"M-{email.split('@', 1)[0]}")
    user = get_user_model().objects.create_user(username=email, email=email)
    client = Client()
    client.force_login(user)
    return client


def calendar_unavailable():
    return {
        "status": "unavailable",
        "message": "Calendar unavailable",
        "week_label": "Jul 27 - Aug 2, 2026",
        "days": [],
    }


@override_settings(
    LAB_CALENDAR_ID="nyuadkameilab@gmail.com",
    LAB_CALENDAR_TIME_ZONE="Asia/Dubai",
)
@patch("labapps.services.calendar.AuthorizedSession")
@patch("labapps.services.calendar.google.auth.default")
def test_calendar_groups_timed_and_all_day_events_for_current_week(
    mock_default, mock_authorized_session
):
    cache.clear()
    mock_default.return_value = (Mock(), "kamei-lab-budget")
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "items": [
            {
                "id": "timed",
                "summary": "Lab meeting",
                "start": {"dateTime": "2026-07-29T10:00:00+04:00"},
                "end": {"dateTime": "2026-07-29T11:00:00+04:00"},
                "htmlLink": "https://calendar.google.com/event?eid=timed",
            },
            {
                "id": "all-day",
                "summary": "Holiday",
                "start": {"date": "2026-07-31"},
                "end": {"date": "2026-08-01"},
            },
        ]
    }
    mock_authorized_session.return_value.get.return_value = response

    result = lab_calendar_week(datetime(2026, 7, 29, 12, tzinfo=ZoneInfo("Asia/Dubai")))

    assert result["status"] == "ready"
    assert result["days"][2]["events"][0]["title"] == "Lab meeting"
    assert result["days"][2]["events"][0]["time_label"] == "10:00"
    assert result["days"][4]["events"][0]["time_label"] == "All day"
    request_params = mock_authorized_session.return_value.get.call_args.kwargs["params"]
    assert request_params["singleEvents"] == "true"
    assert request_params["timeZone"] == "Asia/Dubai"


@override_settings(**SLACK_SETTINGS)
def test_slack_token_is_encrypted_at_rest():
    ciphertext = encrypt_token("xoxp-private-token")
    assert ciphertext != "xoxp-private-token"
    assert decrypt_token(ciphertext) == "xoxp-private-token"


@override_settings(**SLACK_SETTINGS)
@patch("labapps.views.lab_calendar_week", side_effect=calendar_unavailable)
def test_slack_connect_uses_user_scopes_and_workspace(mock_calendar):
    client = signed_in_client("member@nyu.edu")
    response = client.get("/portal/slack/connect/")

    assert response.status_code == 302
    query = parse_qs(urlparse(response.url).query)
    assert query["team"] == ["T-KAMEI"]
    assert set(query["user_scope"][0].split(",")) == set(SLACK_USER_SCOPES)
    assert client.session["slack_oauth_state"] == query["state"][0]


@override_settings(**SLACK_SETTINGS)
@patch("labapps.views.exchange_code")
def test_slack_callback_requires_one_time_account_confirmation(mock_exchange):
    client = signed_in_client("member@nyu.edu")
    session = client.session
    session["slack_oauth_state"] = "state-123"
    session.save()
    mock_exchange.return_value = {
        "token": "xoxp-private-token",
        "team_id": "T-KAMEI",
        "team_name": "KameiLab_NYUAD",
        "user_id": "U123",
        "user_name": "Satoshi",
        "email": "member@nyu.edu",
        "scopes": SLACK_USER_SCOPES,
    }

    response = client.get(
        "/portal/slack/callback/?state=state-123&code=oauth-code"
    )

    assert response.status_code == 302
    connection = SlackConnection.objects.get(portal_email="member@nyu.edu")
    assert connection.confirmed is False
    assert connection.access_token_ciphertext != "xoxp-private-token"
    audit = LabAppAudit.objects.get(action="slack_identity_pending")
    assert "xoxp-private-token" not in str(audit.after)

    with patch("labapps.views.lab_calendar_week", side_effect=calendar_unavailable):
        confirmation = client.get("/portal/")
    assert confirmation.status_code == 200
    assert b"Use this Slack account?" in confirmation.content
    assert b"Satoshi" in confirmation.content
    assert b"xoxp-private-token" not in confirmation.content

    confirmed = client.post(
        "/portal/slack/confirm/", {"decision": "confirm"}
    )
    assert confirmed.status_code == 302
    connection.refresh_from_db()
    assert connection.confirmed is True


@override_settings(**SLACK_SETTINGS)
@patch("labapps.views.lab_calendar_week", side_effect=calendar_unavailable)
def test_slack_connections_are_isolated_by_portal_account(mock_calendar):
    first = signed_in_client("first@nyu.edu")
    second = signed_in_client("second@nyu.edu")
    SlackConnection.objects.create(
        portal_email="first@nyu.edu",
        slack_team_id="T-KAMEI",
        slack_team_name="KameiLab_NYUAD",
        slack_user_id="U-FIRST",
        slack_user_name="First User",
        access_token_ciphertext=encrypt_token("xoxp-first"),
        confirmed=False,
    )

    first_response = first.get("/portal/")
    second_response = second.get("/portal/")

    assert b"First User" in first_response.content
    assert b"Connect your Slack account" in second_response.content
    assert b"First User" not in second_response.content


@override_settings(**SLACK_SETTINGS)
@patch("labapps.services.slack._api")
@patch("labapps.services.slack.requests.post")
def test_slack_oauth_rejects_a_different_workspace(mock_post, mock_api):
    response = Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {
        "ok": True,
        "authed_user": {"access_token": "xoxp-other", "scope": "users:read"},
    }
    mock_post.return_value = response
    mock_api.return_value = {"team_id": "T-OTHER", "user_id": "U1"}

    with pytest.raises(SlackIntegrationError, match="KameiLab_NYUAD"):
        exchange_code("oauth-code")


@override_settings(**SLACK_SETTINGS)
@patch("labapps.views.slack_workspace_context")
@patch("labapps.views.lab_calendar_week", side_effect=calendar_unavailable)
def test_slack_api_failure_does_not_break_portal(mock_calendar, mock_workspace):
    client = signed_in_client("member@nyu.edu")
    SlackConnection.objects.create(
        portal_email="member@nyu.edu",
        slack_team_id="T-KAMEI",
        slack_team_name="KameiLab_NYUAD",
        slack_user_id="U123",
        slack_user_name="Member",
        access_token_ciphertext=encrypt_token("xoxp-private"),
        confirmed=True,
    )
    mock_workspace.side_effect = SlackIntegrationError("Slack unavailable")

    response = client.get("/portal/")

    assert response.status_code == 200
    assert b"Slack needs attention" in response.content
    assert b"Slack unavailable" in response.content


@override_settings(**SLACK_SETTINGS)
def test_invalid_slack_oauth_state_is_rejected_without_writing_connection():
    client = signed_in_client("member@nyu.edu")
    session = client.session
    session["slack_oauth_state"] = "expected"
    session.save()

    response = client.get("/portal/slack/callback/?state=wrong&code=oauth-code")

    assert response.status_code == 302
    assert not SlackConnection.objects.exists()

