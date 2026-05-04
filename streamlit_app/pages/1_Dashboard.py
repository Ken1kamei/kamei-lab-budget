import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from utils.sheets import get_transactions, get_summary, get_exchange_rate, get_teams
from utils.budget import get_category_summary, get_team_summary, get_lab_totals, monthly_spending
from utils.auth import require_role, is_pi, current_team

require_role("pi", "lead", "member")

st.title("📊 Budget Dashboard")

# Load data
txns      = get_transactions()
summary   = get_summary()
teams_df  = get_teams()
rate      = get_exchange_rate()

# ── Currency toggle ───────────────────────────────────────────────────────────
currency = st.radio("Display in", ["AED", "USD"], horizontal=True)
divisor  = rate if currency == "USD" else 1.0
sym      = "$" if currency == "USD" else "AED "

# ── Role-specific view ────────────────────────────────────────────────────────
if is_pi():
    # PI: lab-wide category summary + team comparison
    cat_summary = get_category_summary(txns, summary, rate)
    totals      = get_lab_totals(txns, summary, rate)

    # Summary cards
    cols = st.columns(4)
    for i, (cat, data) in enumerate(cat_summary.items()):
        with cols[i]:
            spent  = data["spent_equiv"]  / divisor
            budget = data["budget_equiv"] / divisor
            pct    = data["pct_used"]
            color  = "🔴" if pct > 0.9 else "🟡" if pct > 0.7 else "🟢"
            st.metric(
                label=f"{color} {cat}",
                value=f"{sym}{spent:,.0f}",
                delta=f"{sym}{(budget - spent) / divisor:,.0f} remaining",
                delta_color="normal",
            )
            st.progress(min(pct, 1.0))

    st.divider()

    # Team comparison bar chart
    team_summary = get_team_summary(txns, teams_df)
    if team_summary:
        team_names  = list(team_summary.keys())
        spent_vals  = [v["spent"] / divisor for v in team_summary.values()]
        alloc_vals  = [v["allocated"] / divisor for v in team_summary.values()]
        fig = go.Figure(data=[
            go.Bar(name="Spent",     x=team_names, y=spent_vals,  marker_color="#57068C"),
            go.Bar(name="Allocated", x=team_names, y=alloc_vals,  marker_color="#e1bee7"),
        ])
        fig.update_layout(barmode="overlay", title="Team Spending vs Allocation",
                          yaxis_title=f"Amount ({currency})", height=300,
                          margin=dict(t=40, b=20))
        st.plotly_chart(fig, use_container_width=True)

else:
    # Team Lead / Member: own team card + lab totals
    team_name    = current_team()
    team_summary = get_team_summary(txns, teams_df)
    team_data    = team_summary.get(team_name, {})
    totals       = get_lab_totals(txns, summary, rate)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric(f"🏷️ {team_name} — Allocated",
                  f"{sym}{team_data.get('allocated', 0) / divisor:,.0f}")
    with col2:
        st.metric(f"💸 {team_name} — Spent",
                  f"{sym}{team_data.get('spent', 0) / divisor:,.0f}")
    with col3:
        rem = team_data.get("remaining", 0)
        st.metric(f"✅ {team_name} — Remaining",
                  f"{sym}{rem / divisor:,.0f}",
                  delta_color="normal")

    st.divider()
    st.subheader("🔬 Lab-Wide Summary")
    c1, c2, c3 = st.columns(3)
    c1.metric("Total Budget",  f"AED {totals['total_budget']:,.0f}")
    c2.metric("Total Spent",   f"AED {totals['total_spent']:,.0f}")
    c3.metric("Total Remaining", f"AED {totals['remaining']:,.0f}")

# ── Monthly spending chart (all roles) ───────────────────────────────────────
st.subheader("📈 Monthly Spending Trend")
team_filter = None if is_pi() else current_team()
filtered    = txns if is_pi() else txns[txns["Team"] == team_filter] if "Team" in txns.columns else txns
monthly_df  = monthly_spending(filtered)

if not monthly_df.empty:
    fig2 = px.bar(monthly_df, x="month", y="amount_equiv", color="category",
                  color_discrete_sequence=["#57068C","#9c27b0","#ce93d8","#e1bee7"],
                  labels={"amount_equiv": f"Amount (AED)", "month": "Month"},
                  title="")
    fig2.update_layout(height=280, margin=dict(t=10, b=20))
    st.plotly_chart(fig2, use_container_width=True)
else:
    st.info("No transaction data yet for the current fiscal year.")

# ── Recent transactions ───────────────────────────────────────────────────────
st.subheader("🕐 Recent Transactions")
display_txns = txns if is_pi() else txns[txns["Team"] == current_team()] if "Team" in txns.columns else txns
recent = display_txns.tail(10).iloc[::-1]  # newest first
if not recent.empty:
    show_cols = ["Date", "Vendor / Payee", "Description",
                 "Category", "Team", "Amount (AED)", "Amount (USD)", "Status"]
    show_cols = [c for c in show_cols if c in recent.columns]
    st.dataframe(recent[show_cols], use_container_width=True, hide_index=True)
else:
    st.info("No transactions yet.")
