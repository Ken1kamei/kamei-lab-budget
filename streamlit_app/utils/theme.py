import html

import streamlit as st


THEME_MODES = ("Day", "Night")


def apply_theme() -> str:
    """Apply the shared app styling and return the selected visual mode."""
    if "theme_mode" not in st.session_state:
        st.session_state.theme_mode = "Day"

    with st.sidebar:
        selected = st.radio(
            "Mode",
            THEME_MODES,
            index=THEME_MODES.index(st.session_state.theme_mode),
            horizontal=True,
            key="theme_mode",
        )

    dark = selected == "Night"
    colors = {
        "bg": "#f6f5f2" if not dark else "#111315",
        "surface": "#ffffff" if not dark else "#181b1f",
        "surface_alt": "#f0efec" if not dark else "#20242a",
        "text": "#202124" if not dark else "#f2f0ec",
        "muted": "#72716d" if not dark else "#a3a09a",
        "line": "#e3e0da" if not dark else "#2d3238",
        "cyan": "#29b8c8",
        "green": "#69c83d",
        "amber": "#ffb000",
        "violet": "#bd65d8",
        "danger": "#e53935",
        "shadow": "0 22px 55px rgba(36, 38, 42, .08)"
        if not dark
        else "0 24px 55px rgba(0, 0, 0, .34)",
    }

    st.markdown(
        f"""
        <style>
        :root {{
          --lab-bg: {colors["bg"]};
          --lab-surface: {colors["surface"]};
          --lab-surface-alt: {colors["surface_alt"]};
          --lab-text: {colors["text"]};
          --lab-muted: {colors["muted"]};
          --lab-line: {colors["line"]};
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
        h1, h2, h3, p, label, span {{
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
          color: var(--lab-muted);
          font-size: 0.92rem;
          margin-bottom: 6px;
        }}
        .lab-title {{
          color: var(--lab-text);
          font-size: clamp(2.1rem, 4vw, 4.25rem);
          line-height: .98;
          font-weight: 500;
          letter-spacing: 0;
          margin: 0;
        }}
        .lab-subtitle {{
          color: var(--lab-muted);
          font-size: 1.08rem;
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
          white-space: nowrap;
        }}
        .lab-card {{
          background: var(--lab-surface);
          border: 1px solid var(--lab-line);
          border-radius: 8px;
          padding: 24px;
          min-height: 178px;
          box-shadow: var(--lab-shadow);
        }}
        .lab-card-title {{
          display: flex;
          gap: 12px;
          align-items: center;
          color: var(--lab-text);
          font-size: 1.06rem;
          margin-bottom: 24px;
        }}
        .lab-handle {{
          color: var(--lab-muted);
          line-height: .75;
          font-weight: 700;
        }}
        .lab-kpi {{
          color: var(--lab-text);
          font-size: clamp(2.15rem, 5vw, 4.1rem);
          line-height: 1;
          font-weight: 500;
          letter-spacing: 0;
        }}
        .lab-dollar {{
          color: color-mix(in srgb, var(--lab-muted) 65%, transparent);
          margin-right: 4px;
        }}
        .lab-caption {{
          color: var(--lab-muted);
          margin-top: 10px;
          font-size: .95rem;
        }}
        .lab-positive {{
          color: #2f9b57;
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
          grid-template-columns: repeat(3, 1fr);
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
