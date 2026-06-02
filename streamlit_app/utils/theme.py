import html

import streamlit as st


THEME_MODES = ("Day", "Night")


def _mode_from_query() -> str | None:
    raw = st.query_params.get("theme")
    if isinstance(raw, list):
        raw = raw[0] if raw else None
    value = str(raw or "").strip().lower()
    if value == "night":
        return "Night"
    if value == "day":
        return "Day"
    return None


def apply_theme() -> str:
    """Apply the shared app styling and return the selected visual mode."""
    query_mode = _mode_from_query()
    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = query_mode or "Day"
    elif query_mode and query_mode != st.session_state.theme_mode:
        st.session_state.theme_mode = query_mode
    if (
        "_theme_mode_widget" not in st.session_state
        or st.session_state._theme_mode_widget != st.session_state.theme_mode
    ):
        st.session_state._theme_mode_widget = st.session_state.theme_mode

    with st.sidebar:
        selected = st.radio(
            "Mode",
            THEME_MODES,
            horizontal=True,
            key="_theme_mode_widget",
        )
    st.session_state.theme_mode = selected
    st.query_params["theme"] = selected.lower()

    dark = selected == "Night"
    colors = {
        "bg": "#f6f5f2" if not dark else "#101214",
        "surface": "#ffffff" if not dark else "#191d22",
        "surface_alt": "#f0efec" if not dark else "#222832",
        "text": "#202124" if not dark else "#f6f3ee",
        "muted": "#72716d" if not dark else "#d0cbc4",
        "subtle": "#a09d96" if not dark else "#aaa49c",
        "line": "#e3e0da" if not dark else "#39414b",
        "grid": "#dedbd4" if not dark else "#414954",
        "cyan": "#29b8c8",
        "green": "#69c83d",
        "amber": "#ffb000",
        "violet": "#bd65d8",
        "danger": "#e53935",
        "shadow": "0 22px 55px rgba(36, 38, 42, .08)"
        if not dark
        else "0 24px 55px rgba(0, 0, 0, .34)",
    }
    st.session_state["_theme_colors"] = colors

    st.markdown(
        f"""
        <style>
        :root {{
          --lab-bg: {colors["bg"]};
          --lab-surface: {colors["surface"]};
          --lab-surface-alt: {colors["surface_alt"]};
          --lab-text: {colors["text"]};
          --lab-muted: {colors["muted"]};
          --lab-subtle: {colors["subtle"]};
          --lab-line: {colors["line"]};
          --lab-grid: {colors["grid"]};
          --lab-cyan: {colors["cyan"]};
          --lab-green: {colors["green"]};
          --lab-amber: {colors["amber"]};
          --lab-violet: {colors["violet"]};
          --lab-danger: {colors["danger"]};
          --lab-shadow: {colors["shadow"]};
        }}
        .stApp {{
          background:
            radial-gradient(circle at 16% 0%, rgba(41, 184, 200, .08), transparent 28rem),
            linear-gradient(180deg, var(--lab-bg), var(--lab-bg));
          color: var(--lab-text);
        }}
        section[data-testid="stSidebar"] {{
          background: var(--lab-surface-alt);
          border-right: 1px solid var(--lab-line);
        }}
        section[data-testid="stSidebar"] * {{
          color: var(--lab-text);
        }}
        div[data-testid="stSidebarNav"] li a {{
          border-radius: 8px;
          margin: 4px 8px;
        }}
        div[data-testid="stSidebarNav"] li a[aria-current="page"] {{
          background: var(--lab-surface);
          box-shadow: inset 0 0 0 1px var(--lab-line);
        }}
        .main .block-container {{
          padding-top: 2.1rem;
          max-width: 1280px;
        }}
        h1, h2, h3, p, label {{
          color: var(--lab-text);
        }}
        [data-testid="stMetric"],
        div[data-testid="stForm"],
        div[data-testid="stDataFrame"] {{
          border-radius: 8px;
        }}
        .stButton > button,
        .stDownloadButton > button {{
          border-radius: 8px;
          border: 1px solid var(--lab-line);
          background: var(--lab-surface);
          color: var(--lab-text);
          box-shadow: 0 8px 22px rgba(0,0,0,.04);
        }}
        .stButton > button[kind="primary"],
        .stFormSubmitButton > button[kind="primary"] {{
          background: var(--lab-text);
          color: var(--lab-bg);
          border-color: var(--lab-text);
        }}
        .lab-hero {{
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 24px;
          margin-bottom: 24px;
        }}
        .lab-eyebrow {{
          color: var(--lab-subtle, var(--lab-muted));
          font-size: 0.92rem;
          margin-bottom: 6px;
        }}
        .lab-title {{
          color: var(--lab-text);
          font-size: clamp(1.9rem, 3.2vw, 3rem);
          line-height: .98;
          font-weight: 500;
          letter-spacing: 0;
          margin: 0;
        }}
        .lab-subtitle {{
          color: var(--lab-muted);
          font-size: 1rem;
          margin-top: 12px;
        }}
        .lab-pill {{
          display: inline-flex;
          align-items: center;
          gap: 8px;
          padding: 10px 14px;
          border-radius: 8px;
          background: var(--lab-surface);
          border: 1px solid var(--lab-line);
          box-shadow: var(--lab-shadow);
          color: var(--lab-muted);
          font-size: .95rem;
          white-space: nowrap;
        }}
        .lab-card {{
          background: var(--lab-surface);
          border: 1px solid var(--lab-line);
          border-radius: 8px;
          padding: 22px;
          min-height: 160px;
          box-shadow: var(--lab-shadow);
          overflow: hidden;
        }}
        .lab-card-title {{
          display: flex;
          gap: 12px;
          align-items: center;
          color: var(--lab-text);
          font-size: 1rem;
          margin-bottom: 20px;
        }}
        .lab-handle {{
          color: var(--lab-muted);
          line-height: .75;
          font-weight: 700;
        }}
        .lab-kpi {{
          color: var(--lab-text);
          font-size: clamp(1.8rem, 2.45vw, 2.75rem);
          line-height: 1.05;
          font-weight: 500;
          letter-spacing: 0;
          white-space: nowrap;
          max-width: 100%;
          overflow: hidden;
          text-overflow: clip;
        }}
        .lab-dollar {{
          color: color-mix(in srgb, var(--lab-muted) 65%, transparent);
          margin-right: 4px;
        }}
        .lab-caption {{
          color: var(--lab-muted);
          margin-top: 10px;
          font-size: .9rem;
          line-height: 1.35;
        }}
        .lab-positive {{
          color: var(--lab-green);
          font-weight: 600;
        }}
        .lab-warning {{
          color: var(--lab-danger);
          font-weight: 600;
        }}
        .lab-progress-track {{
          height: 10px;
          background: var(--lab-surface-alt);
          border-radius: 999px;
          overflow: hidden;
          margin-top: 18px;
        }}
        .lab-progress-fill {{
          height: 100%;
          border-radius: 999px;
          background: linear-gradient(90deg, var(--lab-cyan), var(--lab-green));
        }}
        .lab-mini-grid {{
          display: grid;
          grid-template-columns: repeat(3, minmax(0, 1fr));
          gap: 10px;
          margin-top: 18px;
        }}
        .lab-mini {{
          background: var(--lab-surface-alt);
          border-radius: 8px;
          padding: 12px;
          border: 1px solid var(--lab-line);
        }}
        .lab-mini-label {{
          color: var(--lab-muted);
          font-size: .78rem;
          margin-bottom: 4px;
        }}
        .lab-mini-value {{
          color: var(--lab-text);
          font-size: 1.02rem;
          font-weight: 600;
          white-space: nowrap;
        }}
        @media (max-width: 900px) {{
          .lab-hero {{
            flex-direction: column;
          }}
          .lab-kpi {{
            font-size: clamp(1.7rem, 8vw, 2.35rem);
          }}
          .lab-mini-grid {{
            grid-template-columns: 1fr;
          }}
        }}
        div[data-testid="stDataFrame"] {{
          border: 1px solid var(--lab-line);
          box-shadow: var(--lab-shadow);
        }}
        div[data-testid="stVerticalBlockBorderWrapper"] {{
          background: var(--lab-surface);
          border-color: var(--lab-line);
          border-radius: 8px;
          box-shadow: var(--lab-shadow);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    return selected


def chart_theme() -> dict[str, str]:
    colors = st.session_state.get("_theme_colors", {})
    return {
        "text": colors.get("text", "#202124"),
        "muted": colors.get("muted", "#72716d"),
        "grid": colors.get("grid", "#dedbd4"),
        "surface": colors.get("surface", "#ffffff"),
    }


def metric_card(
    title: str,
    value: str,
    caption: str = "",
    progress: float | None = None,
    accent: str = "cyan",
) -> None:
    accent_var = {
        "cyan": "var(--lab-cyan)",
        "green": "var(--lab-green)",
        "amber": "var(--lab-amber)",
        "violet": "var(--lab-violet)",
        "danger": "var(--lab-danger)",
    }.get(accent, "var(--lab-cyan)")
    progress_html = ""
    if progress is not None:
        pct = max(0, min(float(progress), 1)) * 100
        progress_html = (
            '<div class="lab-progress-track">'
            f'<div class="lab-progress-fill" style="width:{pct:.1f}%; background:{accent_var};"></div>'
            "</div>"
        )
    st.markdown(
        f"""
        <div class="lab-card">
          <div class="lab-card-title"><span class="lab-handle">⠿</span>{html.escape(title)}</div>
          <div class="lab-kpi"><span class="lab-dollar">$</span>{html.escape(value)}</div>
          <div class="lab-caption">{caption}</div>
          {progress_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_card(title: str, body_html: str) -> None:
    st.markdown(
        f"""
        <div class="lab-card">
          <div class="lab-card-title"><span class="lab-handle">⠿</span>{html.escape(title)}</div>
          {body_html}
        </div>
        """,
        unsafe_allow_html=True,
    )
