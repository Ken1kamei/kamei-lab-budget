import html

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
from utils.runtime import refresh_runtime_modules

refresh_runtime_modules()

from utils.auth import can_manage_all_budgets, current_team, current_teams, require_role
from utils.budget import get_category_summary, get_lab_totals, get_team_summary, monthly_spending
from utils.categories import CATEGORY_COLOR_SEQUENCE
from utils.sheets import (
    fiscal_year_options,
    fiscal_year_spreadsheet_ready,
    get_active_fiscal_year,
    get_exchange_rate,
    get_summary,
    get_teams,
    get_transactions,
)
from utils.theme import apply_theme, chart_theme, metric_card

require_role("pi", "budget_manager", "lead", "member")
theme_mode = apply_theme()
chart_colors = chart_theme()
axis_line_color = chart_colors.get("line", chart_colors.get("grid", "#3d4652"))

fy_options = fiscal_year_options()
active_fy = get_active_fiscal_year()
if active_fy not in fy_options:
    fy_options.insert(0, active_fy)
selected_fy = st.selectbox(
    "Academic year",
    fy_options,
    index=fy_options.index(active_fy),
    key="selected_fiscal_year",
    help="Budget years run from September 1 to August 31.",
)

if not fiscal_year_spreadsheet_ready(selected_fy):
    st.info(
        f"{selected_fy} ledger has not been created yet. Showing an empty view. "
        "Use Settings > Fiscal Year to prepare the Google Sheet when you are ready."
    )

txns = get_transactions(selected_fy)
summary = get_summary(selected_fy)
teams_df = get_teams(selected_fy)
rate = get_exchange_rate()

cat_summary = get_category_summary(txns, summary, rate)
totals = get_lab_totals(txns, summary, rate)
user_teams = current_teams()
display_txns = txns
if not can_manage_all_budgets() and "Team" in txns.columns:
    display_txns = txns[txns["Team"].isin(user_teams)]
monthly_df = monthly_spending(display_txns)
team_summary = get_team_summary(display_txns if not can_manage_all_budgets() else txns, teams_df)

user_email = st.session_state.get("email", "")
display_name = str(user_email).split("@")[0] if user_email else "Kamei Lab"
scope = "Lab-wide overview" if can_manage_all_budgets() else f"{', '.join(user_teams) or current_team()} overview"
fy_caption = f"{selected_fy} · Sep 1 - Aug 31"

total_budget = totals["total_budget"]
total_committed = totals["total_committed"]
total_remaining = totals["remaining"]
overall_pct = totals["pct_used"]
avg_monthly = float(monthly_df["amount_equiv"].sum() / max(monthly_df["month"].nunique(), 1)) if not monthly_df.empty else 0.0

st.html(
    f"""
    <div class="lab-dashboard-top">
      <div>
        <h1 class="lab-title">Kamei Lab Budget<br>Manager</h1>
        <div class="lab-subtitle">{html.escape(scope)} · {html.escape(fy_caption)} · Hello, {html.escape(display_name)} · USD base</div>
      </div>
      <div class="lab-top-tabs">
        <a class="lab-top-tab lab-top-tab-active" href="/Dashboard">Overview</a>
        <a class="lab-top-tab" href="/Transactions">Requests</a>
        <a class="lab-top-tab" href="/Import_Invoice">Import</a>
        <a class="lab-top-tab" href="/Reports">Reports</a>
        <a class="lab-top-tab" href="/Settings">Teams</a>
        <a class="lab-top-tab" href="/Settings">Settings</a>
      </div>
    </div>
    """
)

cancelled_count = int((display_txns["Status"].astype(str) == "Cancelled").sum()) if "Status" in display_txns.columns else 0
team_count = len(team_summary)
active_months = monthly_df["month"].nunique() if not monthly_df.empty else 0

st.html(
    f"""
    <div class="lab-stat-grid">
      <div class="lab-stat-card">
        <div class="lab-stat-title">Total Budget</div>
        <div class="lab-stat-value">${total_budget:,.0f}</div>
        <div class="lab-stat-caption">allocated lab budget<br>for {html.escape(selected_fy)}</div>
        <a class="lab-stat-button" href="/Transactions">Open ledger</a>
      </div>
      <div class="lab-stat-card lab-stat-card-magenta">
        <div class="lab-stat-title">Allocated</div>
        <div class="lab-stat-value lab-stat-value-cyan">${total_committed:,.0f}</div>
        <div class="lab-stat-caption">reserved from<br>lab budget</div>
        <a class="lab-stat-button" href="/Transactions">Open ledger</a>
      </div>
      <div class="lab-stat-card">
        <div class="lab-stat-title">Available</div>
        <div class="lab-stat-value lab-stat-value-amber">${total_remaining:,.0f}</div>
        <div class="lab-stat-caption">unreserved budget<br>still available</div>
        <a class="lab-stat-button" href="/Reports">Open report</a>
      </div>
      <div class="lab-stat-card lab-stat-card-magenta">
        <div class="lab-stat-title">Cancelled</div>
        <div class="lab-stat-value">{cancelled_count}</div>
        <div class="lab-stat-caption">excluded from<br>budget usage</div>
        <a class="lab-stat-button" href="/Transactions">Review</a>
      </div>
      <div class="lab-stat-card">
        <div class="lab-stat-title">Teams</div>
        <div class="lab-stat-value lab-stat-value-cyan">{team_count}</div>
        <div class="lab-stat-caption">{active_months} active month(s)<br>${avg_monthly:,.0f} monthly average</div>
        <a class="lab-stat-button" href="/Settings">Open teams</a>
      </div>
    </div>
    """
)

top_chart_col, status_col = st.columns([3.2, 1.05], gap="small")
with top_chart_col:
    with st.container(border=True):
        st.markdown('<div class="lab-chart-title"><span class="lab-handle">⠿</span>Budget velocity</div>', unsafe_allow_html=True)
        if not monthly_df.empty:
            fig_trend = px.line(
                monthly_df,
                x="month",
                y="amount_equiv",
                color="category",
                color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
                labels={"amount_equiv": "USD", "month": "Month"},
                line_shape="linear",
            )
            fig_trend.update_traces(
                mode="lines+markers",
                line=dict(width=2.8),
                marker=dict(size=6, line=dict(width=1.2, color=chart_colors["surface"])),
            )
            fig_trend.update_layout(
                height=285,
                margin=dict(t=6, b=18, l=4, r=4),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                hovermode="x unified",
                font=dict(color=chart_colors["muted"], size=13),
                legend=dict(
                    orientation="h",
                    yanchor="bottom",
                    y=1.02,
                    xanchor="left",
                    x=0,
                    font=dict(color=chart_colors["muted"]),
                    bgcolor="rgba(0,0,0,0)",
                ),
                xaxis=dict(
                    tickfont=dict(color=chart_colors["muted"]),
                    title_font=dict(color=chart_colors["muted"]),
                    gridcolor=chart_colors["grid"],
                    zerolinecolor=chart_colors["grid"],
                    linecolor=axis_line_color,
                ),
                yaxis=dict(
                    tickfont=dict(color=chart_colors["muted"]),
                    title_font=dict(color=chart_colors["muted"]),
                    gridcolor=chart_colors["grid"],
                    zerolinecolor=chart_colors["grid"],
                    linecolor=axis_line_color,
                ),
            )
            st.plotly_chart(fig_trend, use_container_width=True)
        else:
            st.info("No transaction data yet for the current fiscal year.")

with status_col:
    with st.container(border=True):
        fig_gauge = go.Figure(
            go.Indicator(
                mode="gauge+number",
                value=min(overall_pct * 100, 100),
                number={"suffix": "%", "font": {"size": 34, "color": chart_colors["text"]}},
                gauge={
                    "axis": {"range": [0, 100], "visible": False},
                    "bar": {"color": "#2f8cff", "thickness": 0.24},
                    "bgcolor": "rgba(0,0,0,0)",
                    "borderwidth": 0,
                    "steps": [{"range": [0, 100], "color": "#343b5c"}],
                },
                title={"text": "PERCENT USED", "font": {"size": 10, "color": chart_colors["muted"]}},
            )
        )
        fig_gauge.update_layout(
            height=205,
            margin=dict(t=12, b=0, l=10, r=10),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
        )
        st.markdown('<div class="lab-chart-title"><span class="lab-handle">⠿</span>Fiscal pulse</div>', unsafe_allow_html=True)
        st.plotly_chart(fig_gauge, use_container_width=True)
        st.html(
            f"""
            <div class="lab-mini">
              <div class="lab-mini-label">Remaining</div>
              <div class="lab-mini-value">${total_remaining:,.0f}</div>
            </div>
            """
        )

category_rows = []
for cat, data in cat_summary.items():
    if data["committed_equiv"] > 0 or data["budget_equiv"] > 0:
        category_rows.append(
            {
                "Category": cat,
                "Committed": data["committed_equiv"],
                "Budget": data["budget_equiv"],
                "Usage": min(data["pct_used"], 1),
            }
        )
category_df = pd.DataFrame(category_rows).sort_values("Committed", ascending=False) if category_rows else pd.DataFrame()

funnel_col, team_col = st.columns([1.25, 1], gap="small")
with funnel_col:
    with st.container(border=True):
        st.markdown('<div class="lab-chart-title"><span class="lab-handle">⠿</span>Spending funnel</div>', unsafe_allow_html=True)
        if not category_df.empty:
            funnel_df = category_df.sort_values("Committed", ascending=True)
            fig_funnel = go.Figure(
                go.Bar(
                    x=funnel_df["Committed"],
                    y=funnel_df["Category"],
                    orientation="h",
                    marker=dict(color="#ffd335"),
                    text=[f"${v:,.0f}" for v in funnel_df["Committed"]],
                    textposition="inside",
                )
            )
            fig_funnel.update_layout(
                height=300,
                margin=dict(t=4, b=12, l=4, r=4),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                font=dict(color=chart_colors["muted"], size=12),
                xaxis=dict(visible=False),
                yaxis=dict(gridcolor="rgba(0,0,0,0)", tickfont=dict(color=chart_colors["muted"])),
            )
            st.plotly_chart(fig_funnel, use_container_width=True)
        else:
            st.info("No category spending yet.")

with team_col:
    if can_manage_all_budgets() and team_summary:
        names = list(team_summary.keys())
        fig = go.Figure(
            data=[
                go.Bar(name="Allocated", x=names, y=[v["committed"] for v in team_summary.values()], marker_color="#2ee6cf"),
                go.Bar(name="Available", x=names, y=[v["remaining"] for v in team_summary.values()], marker_color="#7cff6b"),
                go.Bar(name="Budget", x=names, y=[v["allocated"] for v in team_summary.values()], marker_color="#2f8cff"),
            ]
        )
        fig.update_layout(
            barmode="group",
            height=300,
            margin=dict(t=4, b=12, l=4, r=4),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=chart_colors["muted"]),
            yaxis_title="USD",
            xaxis_title="",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0,
                font=dict(color=chart_colors["muted"]),
            ),
            xaxis=dict(
                tickfont=dict(color=chart_colors["muted"]),
                title_font=dict(color=chart_colors["muted"]),
                gridcolor=chart_colors["grid"],
                zerolinecolor=chart_colors["grid"],
            ),
            yaxis=dict(
                tickfont=dict(color=chart_colors["muted"]),
                title_font=dict(color=chart_colors["muted"]),
                gridcolor=chart_colors["grid"],
                zerolinecolor=chart_colors["grid"],
            ),
        )
        with st.container(border=True):
            st.markdown('<div class="lab-chart-title"><span class="lab-handle">⠿</span>Team budget</div>', unsafe_allow_html=True)
            st.plotly_chart(fig, use_container_width=True)
    else:
        team_name = current_team()
        data = team_summary.get(team_name, {})
        metric_card(
            f"{team_name} budget",
            f"{data.get('allocated', 0):,.2f}",
            f"${data.get('remaining', 0):,.0f} available · ${data.get('committed', 0):,.0f} allocated",
            progress=data.get("pct_used", 0),
            accent="cyan",
            class_name="lab-card-chart",
        )

breakdown_col, recent_col = st.columns([1, 1.25], gap="small")
with breakdown_col:
    with st.container(border=True):
        st.markdown('<div class="lab-chart-title"><span class="lab-handle">⠿</span>Expenses breakdown</div>', unsafe_allow_html=True)
        if not category_df.empty:
            fig_pie = px.pie(
                category_df,
                values="Committed",
                names="Category",
                hole=0.58,
                color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
            )
            fig_pie.update_layout(
                height=310,
                margin=dict(t=4, b=4, l=4, r=4),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                font=dict(color=chart_colors["muted"]),
                legend=dict(font=dict(color=chart_colors["muted"])),
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No category spending yet.")

with recent_col:
    with st.container(border=True):
        st.markdown('<div class="lab-chart-title"><span class="lab-handle">⠿</span>Recent transactions</div>', unsafe_allow_html=True)
        recent = display_txns.tail(7).iloc[::-1]
        if not recent.empty:
            show_cols = ["Date", "Vendor / Payee", "Category", "Team", "Currency", "Amount", "Status"]
            show_cols = [c for c in show_cols if c in recent.columns]
            st.dataframe(recent[show_cols], use_container_width=True, hide_index=True)
        else:
            st.info("No transactions yet.")
