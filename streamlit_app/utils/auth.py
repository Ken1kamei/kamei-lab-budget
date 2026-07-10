import base64
import hashlib
import hmac
import time
from urllib.parse import urlencode

import streamlit as st
from utils.sheets import get_teams

SESSION_EMAIL_KEY = "portal_authenticated_email"
HANDOFF_QUERY_PARAM = "portal_token"
HANDOFF_TTL_SECONDS = 600


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


def _handoff_secret() -> str:
    explicit = str(_secret("PORTAL_SESSION_SECRET", "") or "").strip()
    if explicit:
        return explicit
    auth = _secret("auth", {}) or {}
    return str(auth.get("cookie_secret", "") or "").strip()


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


def handoff_configured() -> bool:
    return bool(_handoff_secret())


def make_handoff_token(email: str, ttl_seconds: int = HANDOFF_TTL_SECONDS) -> str:
    secret = _handoff_secret()
    normalized_email = str(email or "").strip().lower()
    if not secret or not normalized_email:
        return ""
    expires = int(time.time()) + ttl_seconds
    payload = f"{normalized_email}|{expires}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return _b64encode(f"{payload}|{signature}".encode("utf-8"))


def app_url_with_handoff(url: str, email: str) -> str:
    url = str(url or "").strip()
    email = str(email or "").strip().lower()
    if not url or not email or not handoff_configured():
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode({HANDOFF_QUERY_PARAM: make_handoff_token(email)})}"


def verify_handoff_token(token: str) -> str | None:
    secret = _handoff_secret()
    if not secret or not token:
        return None
    try:
        email, expires_raw, signature = _b64decode(token).decode("utf-8").split("|", 2)
        expires = int(expires_raw)
    except Exception:
        return None
    if expires < int(time.time()):
        return None
    payload = f"{email}|{expires}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    normalized = email.strip().lower()
    if not normalized.endswith("@nyu.edu"):
        return None
    return normalized


def consume_handoff_token_from_query() -> str | None:
    try:
        token = st.query_params.get(HANDOFF_QUERY_PARAM)
    except Exception:
        return None
    if isinstance(token, list):
        token = token[0] if token else ""
    email = verify_handoff_token(str(token or ""))
    if not email:
        return None
    st.session_state[SESSION_EMAIL_KEY] = email
    try:
        del st.query_params[HANDOFF_QUERY_PARAM]
    except Exception:
        pass
    return email


def get_session_email() -> str | None:
    email = str(st.session_state.get(SESSION_EMAIL_KEY, "") or "").strip().lower()
    if email.endswith("@nyu.edu"):
        return email
    return None


def get_authenticated_email() -> str | None:
    return get_oidc_email() or consume_handoff_token_from_query() or get_session_email() or get_local_dev_email()


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

    role, teams = get_user_access(email, teams_df)
    return role, teams[0] if teams else None


def _split_emails(value: str) -> list[str]:
    return [e.strip().lower() for e in str(value or "").replace(";", ",").split(",") if e.strip()]


def get_user_access(email: str, teams_df=None) -> tuple[str, list[str]]:
    """Return highest role and all active teams for an email."""
    normalized = email.strip().lower()
    pi_email = _secret("PI_EMAIL", "ken1kamei@nyu.edu").strip().lower()
    # The PI has lab-wide administrative authority even when the shared
    # registry also lists the account as a budget manager on one or more teams.
    if normalized == pi_email:
        return "pi", []

    if teams_df is None:
        teams_df = get_teams()
    if teams_df.empty:
        return "unknown", []

    budget_manager_teams = []
    lead_teams = []
    member_teams = []
    for _, row in teams_df.iterrows():
        if str(row.get("Active", "Y")).strip().upper() != "Y":
            continue
        team = str(row.get("Team Name", "")).strip()
        if not team:
            continue
        budget_managers = _split_emails(row.get("Budget Manager Emails", ""))
        leads = _split_emails(row.get("Lead Emails", ""))
        members = _split_emails(row.get("Member Emails", ""))
        if normalized in budget_managers:
            budget_manager_teams.append(team)
        if normalized in leads:
            lead_teams.append(team)
        if normalized in members:
            member_teams.append(team)

    if budget_manager_teams:
        return "budget_manager", sorted(dict.fromkeys(budget_manager_teams))
    if lead_teams:
        return "lead", sorted(dict.fromkeys(lead_teams))
    if member_teams:
        return "member", sorted(dict.fromkeys(member_teams))
    return "unknown", []


def get_current_user_role() -> tuple[str, str | None]:
    email = get_authenticated_email()
    if not email:
        return "unknown", None
    return get_user_role(email)


def sync_session_from_oidc_user() -> tuple[str, str | None]:
    """Copy trusted OIDC or explicit local-dev identity into Streamlit session state."""
    email = get_authenticated_email()
    role, teams = get_user_access(email) if email else ("unknown", [])
    team = teams[0] if teams else None
    st.session_state["email"] = email
    st.session_state["role"] = role
    st.session_state["team"] = team
    st.session_state["teams"] = teams
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

def is_budget_manager() -> bool:
    return st.session_state.get("role") == "budget_manager"

def is_lead() -> bool:
    return st.session_state.get("role") == "lead"

def can_manage_all_budgets() -> bool:
    return st.session_state.get("role") in ("pi", "budget_manager")

def can_edit() -> bool:
    return st.session_state.get("role") in ("pi", "budget_manager", "lead")

def current_team() -> str | None:
    return st.session_state.get("team")

def current_teams() -> list[str]:
    teams = st.session_state.get("teams")
    if isinstance(teams, list):
        return teams
    team = current_team()
    return [team] if team else []
