import streamlit as st
from utils.auth import (
    SESSION_EMAIL_KEY,
    app_url_with_handoff,
    get_authenticated_email,
    oidc_configured,
    sync_session_from_oidc_user,
)
from utils.sheets import ensure_fiscal_year_spreadsheet, fiscal_year_options, get_active_fiscal_year
from utils.theme import apply_theme

st.set_page_config(
    page_title="Kamei Lab Budget",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Session state initialisation ──────────────────────────────────────────────
if "email" not in st.session_state:
    st.session_state.email = None
    st.session_state.role  = None
    st.session_state.team  = None

apply_theme()
DEFAULT_PORTAL_URL = "https://kamei-lab-tools.streamlit.app/"

# ── OIDC / local-dev login screen ─────────────────────────────────────────────
if not get_authenticated_email():
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🔬 Kamei Lab Budget")
        st.markdown("*Kamei Reverse Bioengineering Lab · NYUAD*")
        st.divider()
        if oidc_configured():
            st.write("Sign in with your NYU Google account to continue.")
            if st.button("Sign in with Google", type="primary", use_container_width=True):
                st.login()
        else:
            st.error("OIDC login is not configured yet. Add [auth] settings to secrets.toml or enable local dev login.")
    st.stop()

email = get_authenticated_email()
role, team = sync_session_from_oidc_user()

if not email:
    st.error("Please sign in with a verified nyu.edu Google account.")
    if st.button("Sign out", type="primary"):
        st.logout()
    st.stop()

if role == "unknown":
    st.error("This NYU Google account is not linked to Budget access in the shared lab registry.")
    st.caption(f"Signed in as: {email}")
    st.info("Ask a Portal admin to register this exact email in Members and grant Budget access.")
    if st.button("Sign out", type="primary"):
        st.session_state.pop(SESSION_EMAIL_KEY, None)
        st.logout()
    st.stop()

# ── Sidebar (shown after login) ───────────────────────────────────────────────
with st.sidebar:
    st.html(
        f"""
        <div class="lab-sidebar-brand">
          <div class="lab-sidebar-title">Kamei Lab</div>
          <div class="lab-sidebar-muted">Budget Manager</div>
          <div class="lab-sidebar-card">Private lab portal</div>
          <div class="lab-sidebar-rule"></div>
        </div>
        """
    )
    st.caption(f"Logged in as: `{st.session_state.email}`")
    st.caption(f"Role: **{st.session_state.role.upper()}**"
               + (f" · {st.session_state.team}" if st.session_state.team else ""))
    try:
        portal_url = str(st.secrets.get("PORTAL_APP_URL", DEFAULT_PORTAL_URL) or DEFAULT_PORTAL_URL).strip()
    except Exception:
        portal_url = DEFAULT_PORTAL_URL
    st.link_button("Back to Kamei Lab Portal", app_url_with_handoff(portal_url, email), use_container_width=True)
    year_options = fiscal_year_options()
    current_fy = get_active_fiscal_year()
    selected_fy = st.selectbox(
        "Academic year",
        year_options,
        index=year_options.index(current_fy) if current_fy in year_options else 0,
        key="selected_fiscal_year",
    )
    try:
        active_ss = ensure_fiscal_year_spreadsheet(selected_fy)
        st.caption(f"Ledger: `{active_ss.title}`")
    except Exception as e:
        st.error(f"Cannot prepare ledger for {selected_fy}: {e}")
    if st.button("Sign out", use_container_width=True):
        st.session_state.pop(SESSION_EMAIL_KEY, None)
        st.logout()

# ── Default landing page ───────────────────────────────────────────────────────
st.markdown("## Budget Dashboard")
st.info("Select a page from the sidebar to get started.")
