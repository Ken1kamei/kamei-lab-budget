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
from utils.sheets import get_exchange_rate, get_summary, get_teams, get_transactions
from utils.theme import apply_theme, chart_theme, metric_card, section_card

require_role("pi", "budget_manager", "lead", "member")
theme_mode = apply_theme()
chart_colors = chart_theme()

txns = get_transactions()
summary = get_summary()
teams_df = get_teams()
rate = get_exchange_rate()

cat_summary = get_category_summary(txns, summary, rate)
totals = get_lab_totals(txns, summary, rate)
team_summary = get_team_summary(txns, teams_df)

user_teams = current_teams()
display_txns = txns
if not can_manage_all_budgets() and "Team" in txns.columns:
    display_txns = txns[txns["Team"].isin(user_teams)]
monthly_df = monthly_spending(display_txns)

user_email = st.session_state.get("email", "")
display_name = str(user_email).split("@")[0] if user_email else "Kamei Lab"
scope = "Lab-wide overview" if can_manage_all_budgets() else f"{', '.join(user_teams) or current_team()} overview"

st.markdown(
    f"""
    <div class="lab-hero">
      <div>
        <div class="lab-eyebrow">Kamei Reverse Bioengineering Lab</div>
        <h1 class="lab-title">Hello, {html.escape(display_name)}!</h1>
        <div class="lab-subtitle">Here is a brief overview of {html.escape(scope.lower())} in USD.</div>
      </div>
      <div class="lab-pill">{html.escape(theme_mode)} mode · USD base</div>
    </div>
    """,
    unsafe_allow_html=True,
)

total_budget = totals["total_budget"]
total_committed = totals["total_committed"]
total_paid = totals["total_paid"]
total_remaining = totals["remaining"]
overall_pct = totals["pct_used"]

budget_col, paid_col = st.columns(2, gap="large")
with budget_col:
    metric_card(
        "Budget",
        f"{total_budget:,.2f}",
        (
            f'<span class="lab-positive">{overall_pct * 100:.1f}% committed</span>'
            f" · ${total_remaining:,.0f} remaining"
        ),
        progress=overall_pct,
        accent="cyan",
    )
with paid_col:
    metric_card(
        "Paid",
        f"{total_paid:,.2f}",
        f"${total_committed:,.0f} committed total",
        progress=(total_paid / total_budget if total_budget else 0),
        accent="green",
    )

risk = "Low"
risk_class = "lab-positive"
if overall_pct > 0.9:
    risk = "High"
    risk_class = "lab-warning"
elif overall_pct > 0.7:
    risk = "Watch"
    risk_class = "lab-warning"
body = f"""
  <div class="lab-kpi lab-kpi-wide"><span class="lab-dollar">$</span>{total_remaining:,.2f}</div>
  <div class="lab-caption"><span class="{risk_class}">{risk}</span> budget pressure</div>
  <div class="lab-mini-grid lab-mini-grid-wide">
    <div class="lab-mini"><div class="lab-mini-label">Committed</div><div class="lab-mini-value">${total_committed:,.0f}</div></div>
    <div class="lab-mini"><div class="lab-mini-label">Paid</div><div class="lab-mini-value">${total_paid:,.0f}</div></div>
    <div class="lab-mini"><div class="lab-mini-label">Open</div><div class="lab-mini-value">${max(total_committed - total_paid, 0):,.0f}</div></div>
  </div>
"""
section_card("Outcome", body, class_name="lab-card-wide")

with st.container(border=True):
    st.markdown('<div class="lab-chart-title"><span class="lab-handle">⠿</span>Monthly spending</div>', unsafe_allow_html=True)
    if not monthly_df.empty:
        fig_trend = px.area(
            monthly_df,
            x="month",
            y="amount_equiv",
            color="category",
            color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
            labels={"amount_equiv": "USD", "month": "Month"},
            line_shape="spline",
        )
        fig_trend.update_traces(fill="tozeroy", opacity=0.5, line=dict(width=2.5))
        fig_trend.update_layout(
            height=360,
            margin=dict(t=8, b=8, l=8, r=8),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            font=dict(color=chart_colors["muted"]),
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
        st.plotly_chart(fig_trend, use_container_width=True)
    else:
        st.info("No transaction data yet for the current fiscal year.")

team_col, breakdown_col = st.columns(2, gap="large")
with team_col:
    if can_manage_all_budgets() and team_summary:
        names = list(team_summary.keys())
        fig = go.Figure(
            data=[
                go.Bar(name="Committed", x=names, y=[v["committed"] for v in team_summary.values()], marker_color="#29b8c8"),
                go.Bar(name="Paid", x=names, y=[v["paid"] for v in team_summary.values()], marker_color="#69c83d"),
                go.Bar(name="Allocated", x=names, y=[v["allocated"] for v in team_summary.values()], marker_color="#ffb000"),
            ]
        )
        fig.update_layout(
            barmode="group",
            height=330,
            margin=dict(t=8, b=8, l=8, r=8),
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
            f"${data.get('remaining', 0):,.0f} remaining · ${data.get('paid', 0):,.0f} paid",
            progress=data.get("pct_used", 0),
            accent="cyan",
            class_name="lab-card-chart",
        )

with breakdown_col:
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
                height=330,
                margin=dict(t=8, b=8, l=8, r=8),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                showlegend=True,
                font=dict(color=chart_colors["muted"]),
                legend=dict(font=dict(color=chart_colors["muted"])),
            )
            st.plotly_chart(fig_pie, use_container_width=True)
        else:
            st.info("No category spending yet.")

st.markdown("### Recent transactions")
recent = display_txns.tail(10).iloc[::-1]
if not recent.empty:
    show_cols = ["Date", "Vendor / Payee", "Description", "Category", "Team", "Currency", "Amount", "Amount (USD equiv)", "Status"]
    show_cols = [c for c in show_cols if c in recent.columns]
    st.dataframe(recent[show_cols], use_container_width=True, hide_index=True)
else:
    st.info("No transactions yet.")
