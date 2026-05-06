import pandas as pd
import pytest
from unittest.mock import patch

@pytest.fixture
def teams_df():
    return pd.DataFrame({
        "Team Name":    ["Synbio", "Imaging"],
        "Lead Emails":  ["lead1@nyu.edu, lead2@nyu.edu", "lead3@nyu.edu"],
        "Member Emails":["ra1@nyu.edu", "ra2@nyu.edu, ra3@nyu.edu"],
        "Active":       ["Y", "Y"],
    })

@patch("utils.auth.get_teams")
@patch("utils.auth.st")
def test_pi_role(mock_st, mock_get_teams, teams_df):
    mock_st.secrets = {"PI_EMAIL": "pi@nyu.edu"}
    mock_get_teams.return_value = teams_df
    from utils.auth import get_user_role
    role, team = get_user_role("pi@nyu.edu")
    assert role == "pi"
    assert team is None

@patch("utils.auth.get_teams")
@patch("utils.auth.st")
def test_lead_role(mock_st, mock_get_teams, teams_df):
    mock_st.secrets = {"PI_EMAIL": "pi@nyu.edu"}
    mock_get_teams.return_value = teams_df
    from utils.auth import get_user_role
    role, team = get_user_role("lead1@nyu.edu")
    assert role == "lead"
    assert team == "Synbio"

@patch("utils.auth.get_teams")
@patch("utils.auth.st")
def test_member_role(mock_st, mock_get_teams, teams_df):
    mock_st.secrets = {"PI_EMAIL": "pi@nyu.edu"}
    mock_get_teams.return_value = teams_df
    from utils.auth import get_user_role
    role, team = get_user_role("ra2@nyu.edu")
    assert role == "member"
    assert team == "Imaging"

@patch("utils.auth.get_teams")
@patch("utils.auth.st")
def test_unknown_role(mock_st, mock_get_teams, teams_df):
    mock_st.secrets = {"PI_EMAIL": "pi@nyu.edu"}
    mock_get_teams.return_value = teams_df
    from utils.auth import get_user_role
    role, team = get_user_role("stranger@nyu.edu")
    assert role == "unknown"
    assert team is None

@patch("utils.auth.get_teams")
@patch("utils.auth.st")
def test_role_from_oidc_user_uses_verified_nyu_email(mock_st, mock_get_teams, teams_df):
    mock_st.secrets = {"PI_EMAIL": "pi@nyu.edu"}
    mock_get_teams.return_value = teams_df
    mock_st.user = {
        "is_logged_in": True,
        "email": "RA1@nyu.edu",
        "email_verified": True,
    }
    from utils.auth import get_oidc_email, get_current_user_role
    assert get_oidc_email() == "ra1@nyu.edu"
    assert get_current_user_role() == ("member", "Synbio")

@patch("utils.auth.st")
def test_oidc_email_rejects_unverified_or_non_nyu_users(mock_st):
    mock_st.user = {
        "is_logged_in": True,
        "email": "person@example.com",
        "email_verified": True,
    }
    from utils.auth import get_oidc_email
    assert get_oidc_email() is None

@patch("utils.auth.st")
def test_local_dev_email_requires_explicit_opt_in_and_no_oidc_config(mock_st):
    mock_st.secrets = {
        "ALLOW_LOCAL_DEV_LOGIN": True,
        "DEV_AUTH_EMAIL": "PI@nyu.edu",
    }
    mock_st.user = {"is_logged_in": False}
    from utils.auth import get_authenticated_email
    assert get_authenticated_email() == "pi@nyu.edu"

@patch("utils.auth.st")
def test_local_dev_email_disabled_when_oidc_configured(mock_st):
    mock_st.secrets = {
        "ALLOW_LOCAL_DEV_LOGIN": True,
        "DEV_AUTH_EMAIL": "pi@nyu.edu",
        "auth": {
            "redirect_uri": "https://example.streamlit.app/oauth2callback",
            "cookie_secret": "secret",
            "client_id": "client",
            "client_secret": "secret",
            "server_metadata_url": "https://accounts.google.com/.well-known/openid-configuration",
        },
    }
    mock_st.user = {"is_logged_in": False}
    from utils.auth import get_authenticated_email
    assert get_authenticated_email() is None
