import html

import streamlit as st


def apply_theme() -> str:
    """Apply the shared app styling and return the selected visual mode."""
    selected = "Night"
    st.session_state.theme_mode = selected
    st.session_state._theme_mode_widget = selected
    if st.query_params.get("theme") != "night":
        st.query_params["theme"] = "night"

    dark = True
    colors = {
        "bg": "#151b32",
        "surface": "#242a46",
        "surface_alt": "#1d233b",
        "text": "#f7f8ff",
        "muted": "#c1c8e4",
        "subtle": "#8892bb",
        "line": "#37405f",
        "grid": "#303858",
        "cyan": "#2ee6cf",
        "green": "#7cff6b",
        "amber": "#ffd335",
        "violet": "#a86cff",
        "danger": "#ff4f80",
        "shadow": "0 18px 44px rgba(5, 8, 20, .38)",
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
            radial-gradient(circle at 12% 0%, rgba(46, 230, 207, .12), transparent 24rem),
            radial-gradient(circle at 82% 8%, rgba(168, 108, 255, .12), transparent 22rem),
            linear-gradient(180deg, var(--lab-bg), var(--lab-bg));
          color: var(--lab-text);
        }}
        header[data-testid="stHeader"] {{
          background: var(--lab-bg);
          color: var(--lab-text);
        }}
        header[data-testid="stHeader"] * {{
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
          padding-top: 1rem;
          max-width: 1480px;
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
        button[data-testid="stBaseButton-primary"],
        button[data-testid="stBaseButton-primary"] * {{
          background: var(--lab-text);
          color: var(--lab-bg) !important;
          border-color: var(--lab-text);
        }}
        .lab-hero {{
          display: flex;
          align-items: flex-start;
          justify-content: space-between;
          gap: 24px;
          margin-bottom: 12px;
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
          border-radius: 4px;
          padding: 16px;
          min-height: 145px;
          height: 100%;
          box-shadow: var(--lab-shadow);
          overflow: hidden;
        }}
        .lab-card-wide {{
          min-height: 150px;
        }}
        .lab-card-chart {{
          min-height: 330px;
        }}
        .lab-card-title {{
          display: flex;
          gap: 12px;
          align-items: center;
          color: var(--lab-text);
          font-size: .86rem;
          text-transform: uppercase;
          letter-spacing: .04em;
          margin-bottom: 14px;
        }}
        .lab-handle {{
          color: var(--lab-muted);
          line-height: .75;
          font-weight: 700;
        }}
        .lab-kpi {{
          color: var(--lab-text);
          font-size: clamp(1.55rem, 2.2vw, 2.65rem);
          line-height: 1.05;
          font-weight: 500;
          letter-spacing: 0;
          white-space: nowrap;
          max-width: 100%;
          overflow: hidden;
          text-overflow: clip;
        }}
        .lab-kpi-wide {{
          font-size: clamp(1.9rem, 3vw, 3.6rem);
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
          gap: 8px;
          margin-top: 16px;
        }}
        .lab-mini-grid-wide {{
          grid-template-columns: repeat(3, minmax(150px, 1fr));
        }}
        .lab-mini {{
          background: var(--lab-surface-alt);
          border-radius: 4px;
          padding: 10px;
          border: 1px solid var(--lab-line);
        }}
        .lab-mini-label {{
          color: var(--lab-muted);
          font-size: .78rem;
          margin-bottom: 4px;
        }}
        .lab-mini-value {{
          color: var(--lab-text);
          font-size: 1rem;
          font-weight: 600;
          white-space: nowrap;
        }}
        .lab-chart-title {{
          display: flex;
          gap: 12px;
          align-items: center;
          color: var(--lab-text);
          font-size: 1rem;
          margin: 8px 8px 12px;
        }}
        .lab-chart-empty {{
          min-height: 330px;
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
          border-radius: 4px;
          box-shadow: var(--lab-shadow);
          min-height: 320px;
        }}
        .lab-panel-label {{
          color: var(--lab-subtle);
          font-size: .72rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: .08em;
        }}
        .lab-status-chip {{
          display: inline-flex;
          align-items: center;
          gap: 6px;
          color: var(--lab-green);
          font-size: .72rem;
          font-weight: 700;
          text-transform: uppercase;
          letter-spacing: .06em;
        }}
        .lab-status-chip::before {{
          content: "";
          width: 8px;
          height: 8px;
          border-radius: 999px;
          background: var(--lab-green);
          box-shadow: 0 0 14px var(--lab-green);
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    return selected


def chart_theme() -> dict[str, str]:
    colors = st.session_state.get("_theme_colors", {})
    return {
        "text": colors.get("text", "#f7f3ec"),
        "muted": colors.get("muted", "#d6d0c7"),
        "grid": colors.get("grid", "#3d4652"),
        "surface": colors.get("surface", "#171c21"),
        "bg": colors.get("bg", "#0d1114"),
        "line": colors.get("line", "#343d48"),
    }


def metric_card(
    title: str,
    value: str,
    caption: str = "",
    progress: float | None = None,
    accent: str = "cyan",
    class_name: str = "",
) -> None:
    extra_class = f" {html.escape(class_name)}" if class_name else ""
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
        <div class="lab-card{extra_class}">
          <div class="lab-card-title"><span class="lab-handle">⠿</span>{html.escape(title)}</div>
          <div class="lab-kpi"><span class="lab-dollar">$</span>{html.escape(value)}</div>
          <div class="lab-caption">{caption}</div>
          {progress_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_card(title: str, body_html: str, class_name: str = "") -> None:
    extra_class = f" {html.escape(class_name)}" if class_name else ""
    st.html(
        f"""
        <div class="lab-card{extra_class}">
          <div class="lab-card-title"><span class="lab-handle">⠿</span>{html.escape(title)}</div>
          {body_html}
        </div>
        """
    )
