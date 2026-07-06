import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from utils.sheets import (
    fiscal_year_spreadsheet_ready,
    get_active_fiscal_year,
    get_transactions,
    get_summary,
    get_exchange_rate,
    get_teams,
)
from utils.budget import get_category_summary, get_team_summary, get_lab_totals, monthly_spending
from utils.auth import require_role, can_manage_all_budgets, current_team, current_teams
from utils.categories import CATEGORY_COLOR_SEQUENCE
from utils.theme import apply_theme, chart_theme

require_role("pi", "budget_manager", "lead", "member")
apply_theme()
chart_colors = chart_theme()
axis_line_color = chart_colors.get("line", chart_colors.get("grid", "#3d4652"))


def _night_chart(fig, height: int):
    fig.update_layout(
        height=height,
        margin=dict(t=10, b=24, l=10, r=10),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=chart_colors["muted"], size=13),
        legend=dict(
            font=dict(color=chart_colors["muted"]),
            bgcolor="rgba(0,0,0,0)",
        ),
    )
    fig.update_xaxes(
        tickfont=dict(color=chart_colors["muted"]),
        title_font=dict(color=chart_colors["muted"]),
        gridcolor=chart_colors["grid"],
        zerolinecolor=chart_colors["grid"],
        linecolor=axis_line_color,
    )
    fig.update_yaxes(
        tickfont=dict(color=chart_colors["muted"]),
        title_font=dict(color=chart_colors["muted"]),
        gridcolor=chart_colors["grid"],
        zerolinecolor=chart_colors["grid"],
        linecolor=axis_line_color,
    )
    return fig

st.title("📈 Reports")

selected_fy = get_active_fiscal_year()
if not fiscal_year_spreadsheet_ready(selected_fy):
    st.info(
        f"{selected_fy} ledger has not been created yet. Showing an empty report. "
        "Use Settings > Fiscal Year to prepare the Google Sheet when you are ready."
    )

txns     = get_transactions(selected_fy)
summary  = get_summary(selected_fy)
teams_df = get_teams(selected_fy)
rate     = get_exchange_rate()
team     = current_team()
teams    = current_teams()

team_txns = txns
if not can_manage_all_budgets() and "Team" in txns.columns:
    team_txns = txns[txns["Team"].isin(teams)]

st.subheader("Budget Summary")
cat_summary = get_category_summary(txns, summary, rate)
totals      = get_lab_totals(txns, summary, rate)

summary_rows = []
for cat, data in cat_summary.items():
    summary_rows.append({
        "Category":           cat,
        "Budget (USD)":       f"${data['budget_equiv']:,.0f}",
        "Allocated":          f"${data['committed_equiv']:,.0f}",
        "Available":          f"${data['remaining']:,.0f}",
        "% Used":             f"{data['pct_used']*100:.1f}%",
    })
summary_rows.append({
    "Category":           "TOTAL",
    "Budget (USD)":       f"${totals['total_budget']:,.0f}",
    "Allocated":          f"${totals['total_committed']:,.0f}",
    "Available":          f"${totals['remaining']:,.0f}",
    "% Used":             f"{totals['pct_used']*100:.1f}%",
})
st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Spending by Category")
    pie_data = {cat: data["committed_equiv"] for cat, data in cat_summary.items() if data["committed_equiv"] > 0}
    if pie_data:
        fig = px.pie(values=list(pie_data.values()), names=list(pie_data.keys()),
                     color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
                     hole=0.35)
        _night_chart(fig, 300)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No spending data yet.")

with col2:
    if can_manage_all_budgets():
        st.subheader("Team Spending vs Allocation")
        team_summary = get_team_summary(txns, teams_df)
        if team_summary:
            names  = list(team_summary.keys())
            committed = [v["committed"] for v in team_summary.values()]
            remaining = [v["remaining"] for v in team_summary.values()]
            alloc  = [v["allocated"] for v in team_summary.values()]
            fig2 = go.Figure(data=[
                go.Bar(name="Allocated", x=names, y=committed, marker_color="#35c4d5"),
                go.Bar(name="Available", x=names, y=remaining, marker_color="#76d04a"),
                go.Bar(name="Budget", x=names, y=alloc, marker_color="#ffb51c"),
            ])
            _night_chart(fig2, 300)
            fig2.update_layout(barmode="group")
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No teams defined yet.")
    else:
        st.subheader(f"{team} — Spending Trend")
        monthly_df = monthly_spending(team_txns)
        if not monthly_df.empty:
            fig3 = px.line(monthly_df, x="month", y="amount_equiv", color="category",
                           color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
                           line_shape="linear")
            fig3.update_traces(mode="lines+markers", line=dict(width=2.5))
            _night_chart(fig3, 300)
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No data yet.")

st.subheader("Monthly Spending Trend")
monthly_df = monthly_spending(team_txns)
if not monthly_df.empty:
    fig4 = px.line(monthly_df, x="month", y="amount_equiv", color="category",
                  color_discrete_sequence=CATEGORY_COLOR_SEQUENCE,
                  line_shape="linear",
                  labels={"amount_equiv":"Amount (USD)","month":"Month"})
    fig4.update_traces(mode="lines+markers", line=dict(width=2.8))
    _night_chart(fig4, 320)
    st.plotly_chart(fig4, use_container_width=True)
else:
    st.info("No transaction data yet.")

st.divider()
csv = team_txns.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download all transactions (CSV)", csv, "report.csv", "text/csv")
