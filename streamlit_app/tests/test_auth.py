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
