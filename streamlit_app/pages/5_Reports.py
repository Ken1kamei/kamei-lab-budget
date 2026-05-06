import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from utils.sheets import get_transactions, get_summary, get_exchange_rate, get_teams
from utils.budget import get_category_summary, get_team_summary, get_lab_totals, monthly_spending
from utils.auth import require_role, is_pi, current_team

require_role("pi", "lead", "member")

st.title("📈 Reports")

txns     = get_transactions()
summary  = get_summary()
teams_df = get_teams()
rate     = get_exchange_rate()
team     = current_team()

team_txns = txns if is_pi() else txns[txns["Team"] == team] if "Team" in txns.columns else txns

st.subheader("Budget Summary")
cat_summary = get_category_summary(txns, summary, rate)
totals      = get_lab_totals(txns, summary, rate)

summary_rows = []
for cat, data in cat_summary.items():
    summary_rows.append({
        "Category":           cat,
        "Budget (AED equiv)": f"AED {data['budget_equiv']:,.0f}",
        "Committed":          f"AED {data['committed_equiv']:,.0f}",
        "Paid":               f"AED {data['paid_equiv']:,.0f}",
        "Remaining":          f"AED {data['remaining']:,.0f}",
        "% Used":             f"{data['pct_used']*100:.1f}%",
    })
summary_rows.append({
    "Category":           "TOTAL",
    "Budget (AED equiv)": f"AED {totals['total_budget']:,.0f}",
    "Committed":          f"AED {totals['total_committed']:,.0f}",
    "Paid":               f"AED {totals['total_paid']:,.0f}",
    "Remaining":          f"AED {totals['remaining']:,.0f}",
    "% Used":             f"{totals['pct_used']*100:.1f}%",
})
st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)

col1, col2 = st.columns(2)

with col1:
    st.subheader("Spending by Category")
    pie_data = {cat: data["committed_equiv"] for cat, data in cat_summary.items() if data["committed_equiv"] > 0}
    if pie_data:
        fig = px.pie(values=list(pie_data.values()), names=list(pie_data.keys()),
                     color_discrete_sequence=["#57068C","#9c27b0","#ce93d8","#e1bee7"],
                     hole=0.35)
        fig.update_layout(height=300, margin=dict(t=10,b=10))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No spending data yet.")

with col2:
    if is_pi():
        st.subheader("Team Spending vs Allocation")
        team_summary = get_team_summary(txns, teams_df)
        if team_summary:
            names  = list(team_summary.keys())
            committed = [v["committed"] for v in team_summary.values()]
            paid = [v["paid"] for v in team_summary.values()]
            alloc  = [v["allocated"] for v in team_summary.values()]
            fig2 = go.Figure(data=[
                go.Bar(name="Committed", x=names, y=committed, marker_color="#57068C"),
                go.Bar(name="Paid",      x=names, y=paid, marker_color="#2e7d32"),
                go.Bar(name="Allocated", x=names, y=alloc, marker_color="#e1bee7"),
            ])
            fig2.update_layout(barmode="group", height=300, margin=dict(t=10,b=10))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("No teams defined yet.")
    else:
        st.subheader(f"{team} — Spending Trend")
        monthly_df = monthly_spending(team_txns)
        if not monthly_df.empty:
            fig3 = px.line(monthly_df, x="month", y="amount_equiv", color="category",
                           color_discrete_sequence=["#57068C","#9c27b0","#ce93d8","#e1bee7"])
            fig3.update_layout(height=300, margin=dict(t=10,b=10))
            st.plotly_chart(fig3, use_container_width=True)
        else:
            st.info("No data yet.")

st.subheader("Monthly Spending Trend")
monthly_df = monthly_spending(team_txns)
if not monthly_df.empty:
    fig4 = px.bar(monthly_df, x="month", y="amount_equiv", color="category",
                  color_discrete_sequence=["#57068C","#9c27b0","#ce93d8","#e1bee7"],
                  labels={"amount_equiv":"Amount (AED)","month":"Month"})
    fig4.update_layout(height=320, margin=dict(t=10,b=20))
    st.plotly_chart(fig4, use_container_width=True)
else:
    st.info("No transaction data yet.")

st.divider()
csv = team_txns.to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Download all transactions (CSV)", csv, "report.csv", "text/csv")
