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
        .lab-sidebar-brand {{
          padding: 12px 8px 22px;
        }}
        .lab-sidebar-title {{
          color: var(--lab-text);
          font-size: 1.55rem;
          font-weight: 900;
          margin-bottom: 22px;
        }}
        .lab-sidebar-muted {{
          color: var(--lab-subtle);
          font-size: .96rem;
          font-weight: 700;
          margin-bottom: 22px;
        }}
        .lab-sidebar-card {{
          background: linear-gradient(135deg, rgba(47,140,255,.24), rgba(46,230,207,.08));
          border: 1px solid rgba(47,140,255,.24);
          border-radius: 10px;
          padding: 18px 18px;
          color: var(--lab-text);
          font-size: 1.08rem;
          font-weight: 800;
          margin-bottom: 28px;
        }}
        .lab-sidebar-rule {{
          height: 1px;
          background: var(--lab-line);
          margin: 8px 0 24px;
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
          margin: 20px 0 22px;
        }}
        .lab-eyebrow {{
          color: var(--lab-subtle, var(--lab-muted));
          font-size: 0.92rem;
          margin-bottom: 6px;
        }}
        .lab-title {{
          color: var(--lab-text);
          font-size: clamp(2.4rem, 4vw, 4.1rem);
          line-height: 1.05;
          font-weight: 800;
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
        .lab-dashboard-top {{
          display: grid;
          grid-template-columns: minmax(320px, 1fr) minmax(480px, 1.1fr);
          gap: 34px;
          align-items: end;
          padding-bottom: 26px;
          border-bottom: 1px solid var(--lab-line);
          margin-bottom: 28px;
        }}
        .lab-top-tabs {{
          display: flex;
          gap: 26px;
          flex-wrap: wrap;
          align-items: center;
          justify-content: flex-end;
        }}
        .lab-top-tab {{
          color: var(--lab-subtle);
          font-size: .82rem;
          font-weight: 800;
          text-transform: uppercase;
          letter-spacing: .04em;
          padding: 8px 0;
        }}
        .lab-top-tab-active {{
          color: var(--lab-cyan);
          border-bottom: 3px solid var(--lab-cyan);
          text-shadow: 0 0 18px rgba(46, 230, 207, .38);
        }}
        .lab-stat-grid {{
          display: grid;
          grid-template-columns: repeat(5, minmax(150px, 1fr));
          gap: 18px;
          margin-bottom: 18px;
        }}
        .lab-stat-card {{
          min-height: 250px;
          padding: 28px 24px 22px;
          border-radius: 8px;
          border: 1px solid #425074;
          background: linear-gradient(145deg, #303851, #202842);
          box-shadow: 0 18px 46px rgba(4, 7, 18, .35);
          border-top: 4px solid var(--lab-cyan);
        }}
        .lab-stat-card-magenta {{
          border-top-color: #ff2fcf;
        }}
        .lab-stat-title {{
          color: var(--lab-text);
          font-size: .88rem;
          font-weight: 900;
          text-transform: uppercase;
          letter-spacing: .04em;
          margin-bottom: 28px;
        }}
        .lab-stat-value {{
          color: var(--lab-text);
          font-size: clamp(2.35rem, 4vw, 4.25rem);
          line-height: .95;
          font-weight: 900;
          letter-spacing: 0;
          margin-bottom: 22px;
        }}
        .lab-stat-value-cyan {{
          color: var(--lab-cyan);
        }}
        .lab-stat-value-amber {{
          color: var(--lab-amber);
        }}
        .lab-stat-caption {{
          color: var(--lab-muted);
          font-size: 1rem;
          line-height: 1.28;
        }}
        .lab-stat-button {{
          display: inline-flex;
          color: var(--lab-text);
          border: 1px solid #5c6b9a;
          border-radius: 6px;
          padding: 10px 18px;
          font-size: .86rem;
          font-weight: 800;
          margin-top: 24px;
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
          .lab-dashboard-top {{
            grid-template-columns: 1fr;
          }}
          .lab-top-tabs {{
            justify-content: flex-start;
          }}
          .lab-stat-grid {{
            grid-template-columns: 1fr;
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
