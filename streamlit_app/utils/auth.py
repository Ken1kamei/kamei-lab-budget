import streamlit as st
from utils.sheets import get_teams


def _secret(key: str, default=None):
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


def _user_value(key: str, default=None):
    try:
        if hasattr(st.user, key):
            return getattr(st.user, key)
        return st.user.get(key, default)
    except Exception:
        return default


def oidc_configured() -> bool:
    auth = _secret("auth", {}) or {}
    required = [
        "redirect_uri",
        "cookie_secret",
        "client_id",
        "client_secret",
        "server_metadata_url",
    ]
    return all(str(auth.get(k, "") or "").strip() for k in required)


def get_oidc_email() -> str | None:
    """Return the logged-in verified nyu.edu email from Streamlit OIDC state."""
    if not bool(_user_value("is_logged_in", False)):
        return None
    email = str(_user_value("email", "") or "").strip().lower()
    if not email.endswith("@nyu.edu"):
        return None
    verified = _user_value("email_verified", True)
    if verified is False:
        return None
    return email


def get_local_dev_email() -> str | None:
    """Return a local-only dev identity when OIDC has not been configured yet."""
    enabled = str(_secret("ALLOW_LOCAL_DEV_LOGIN", "")).strip().lower() in {"1", "true", "yes", "y"}
    if not enabled or oidc_configured():
        return None
    email = str(_secret("DEV_AUTH_EMAIL", "") or "").strip().lower()
    if email.endswith("@nyu.edu"):
        return email
    return None


def get_authenticated_email() -> str | None:
    return get_oidc_email() or get_local_dev_email()


def get_user_role(email: str) -> tuple[str, str | None]:
    """
    Determine role from email.
    Returns (role, team_name) where role is 'pi' | 'lead' | 'member' | 'unknown'
    and team_name is None for pi/unknown.
    """
    pi_email = _secret("PI_EMAIL", "ken1kamei@nyu.edu")
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


def get_current_user_role() -> tuple[str, str | None]:
    email = get_authenticated_email()
    if not email:
        return "unknown", None
    return get_user_role(email)


def sync_session_from_oidc_user() -> tuple[str, str | None]:
    """Copy trusted OIDC or explicit local-dev identity into Streamlit session state."""
    email = get_authenticated_email()
    role, team = get_user_role(email) if email else ("unknown", None)
    st.session_state["email"] = email
    st.session_state["role"] = role
    st.session_state["team"] = team
    return role, team


def require_role(*allowed_roles: str):
    """Call at top of page to block access. Shows error and stops if role not allowed."""
    role = st.session_state.get("role")
    if role not in allowed_roles and get_authenticated_email():
        role, _ = sync_session_from_oidc_user()
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
