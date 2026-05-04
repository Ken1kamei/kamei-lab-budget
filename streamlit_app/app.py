import streamlit as st
from utils.auth import get_user_role

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

# ── Login screen ──────────────────────────────────────────────────────────────
if not st.session_state.email:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("## 🔬 Kamei Lab Budget")
        st.markdown("*Kamei Reverse Bioengineering Lab · NYUAD*")
        st.divider()
        email = st.text_input("Enter your nyu.edu email", placeholder="yourname@nyu.edu")
        if st.button("Sign in", type="primary", use_container_width=True):
            if not email.strip().endswith("@nyu.edu"):
                st.error("Please use your nyu.edu email address.")
            else:
                role, team = get_user_role(email.strip().lower())
                if role == "unknown":
                    st.error("Email not registered. Ask the PI to add you to the lab roster (Settings → Team Management).")
                else:
                    st.session_state.email = email.strip().lower()
                    st.session_state.role  = role
                    st.session_state.team  = team
                    st.rerun()
    st.stop()

# ── Sidebar (shown after login) ───────────────────────────────────────────────
with st.sidebar:
    st.markdown(f"**🔬 Kamei Lab Budget**")
    st.caption(f"Logged in as: `{st.session_state.email}`")
    st.caption(f"Role: **{st.session_state.role.upper()}**"
               + (f" · {st.session_state.team}" if st.session_state.team else ""))
    st.divider()
    if st.button("Sign out", use_container_width=True):
        for key in ("email", "role", "team"):
            st.session_state[key] = None
        st.rerun()

# ── Default landing page ───────────────────────────────────────────────────────
st.markdown("## Budget Dashboard")
st.info("Select a page from the sidebar to get started.")
