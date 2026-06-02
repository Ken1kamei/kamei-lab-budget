import streamlit as st
from utils.auth import get_authenticated_email, oidc_configured, sync_session_from_oidc_user
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
apply_theme()

if not email:
    st.error("Please sign in with a verified nyu.edu Google account.")
    if st.button("Sign out", type="primary"):
        st.logout()
    st.stop()

if role == "unknown":
    st.error("Email not registered. Ask the PI to add you to the lab roster in Settings → Teams.")
    st.caption(f"Signed in as: {email}")
    if st.button("Sign out", type="primary"):
        st.logout()
    st.stop()

# ── Sidebar (shown after login) ───────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"**🔬 Kamei Lab Budget**")
    st.caption(f"Logged in as: `{st.session_state.email}`")
    st.caption(f"Role: **{st.session_state.role.upper()}**"
               + (f" · {st.session_state.team}" if st.session_state.team else ""))
    st.divider()
    if st.button("Sign out", use_container_width=True):
        st.logout()

# ── Default landing page ───────────────────────────────────────────────────────
st.markdown("## Budget Dashboard")
st.info("Select a page from the sidebar to get started.")
