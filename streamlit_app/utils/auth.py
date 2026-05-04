import streamlit as st
from utils.sheets import get_teams


def get_user_role(email: str) -> tuple[str, str | None]:
    """
    Determine role from email.
    Returns (role, team_name) where role is 'pi' | 'lead' | 'member' | 'unknown'
    and team_name is None for pi/unknown.
    """
    pi_email = st.secrets.get("PI_EMAIL", "ken1kamei@nyu.edu")
    if email.strip().lower() == pi_email.strip().lower():
        return "pi", None

    teams_df = get_teams()
    if teams_df.empty:
        return "unknown", None

    for _, row in teams_df.iterrows():
        if str(row.get("Active", "Y")).strip().upper() != "Y":
            continue
        leads   = [e.strip().lower() for e in str(row.get("Lead Emails", "")).split(",") if e.strip()]
        members = [e.strip().lower() for e in str(row.get("Member Emails", "")).split(",") if e.strip()]
        if email.strip().lower() in leads:
            return "lead", str(row["Team Name"])
        if email.strip().lower() in members:
            return "member", str(row["Team Name"])

    return "unknown", None


def require_role(*allowed_roles: str):
    """Call at top of page to block access. Shows error and stops if role not allowed."""
    role = st.session_state.get("role")
    if role not in allowed_roles:
        st.error("You don't have permission to view this page.")
        st.stop()


def is_pi() -> bool:
    return st.session_state.get("role") == "pi"

def is_lead() -> bool:
    return st.session_state.get("role") == "lead"

def can_edit() -> bool:
    return st.session_state.get("role") in ("pi", "lead")

def current_team() -> str | None:
    return st.session_state.get("team")
