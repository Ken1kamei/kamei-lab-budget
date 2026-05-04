import streamlit as st
import pandas as pd
from utils.sheets import (get_teams, get_exchange_rate, get_summary,
                           set_budget_allocation, upsert_team, set_config,
                           get_transactions, append_transaction, update_transaction)
from utils.auth import require_role

require_role("pi")

st.title("⚙️ Settings")

tab1, tab2, tab3, tab4 = st.tabs([
    "💰 Budget Allocations", "👥 Teams", "🔧 Exchange Rate", "🧪 Test Mode"
])

with tab1:
    st.markdown("Set the lab budget per category for the current fiscal year.")
    summary_df = get_summary()
    CATEGORIES = ["Equipment", "Personnel", "Travel", "Other"]

    with st.form("budget_alloc_form"):
        st.markdown("**Enter amounts in AED, USD, or both:**")
        alloc_data = {}
        for cat in CATEGORIES:
            row = summary_df[summary_df["Category"] == cat] if "Category" in summary_df.columns else pd.DataFrame()
            curr_aed = float(row["Budgeted (AED)"].iloc[0]) if not row.empty else 0.0
            curr_usd = float(row["Budgeted (USD)"].iloc[0]) if not row.empty else 0.0
            c1, c2, c3 = st.columns([2, 1, 1])
            c1.markdown(f"**{cat}**")
            aed = c2.number_input(f"AED##{cat}", value=curr_aed, min_value=0.0, step=1000.0, label_visibility="collapsed")
            usd = c3.number_input(f"USD##{cat}", value=curr_usd, min_value=0.0, step=1000.0, label_visibility="collapsed")
            alloc_data[cat] = (aed, usd)
        if st.form_submit_button("Save Allocations", type="primary"):
            for cat, (aed, usd) in alloc_data.items():
                set_budget_allocation(cat, aed, usd)
            st.success("✓ Budget allocations saved.")

with tab2:
    st.markdown("Manage lab teams. Team leads can add/edit transactions for their team.")
    teams_df = get_teams()

    if not teams_df.empty:
        st.dataframe(teams_df, use_container_width=True, hide_index=True)
    else:
        st.info("No teams defined yet.")

    st.divider()
    st.markdown("**Add / Update Team:**")
    with st.form("team_form"):
        team_name     = st.text_input("Team Name *")
        allocation    = st.number_input("Total Allocation (AED)", min_value=0.0, step=1000.0)
        lead_emails   = st.text_input("Lead Emails (comma-separated nyu.edu)", placeholder="lead@nyu.edu")
        member_emails = st.text_input("Member Emails (comma-separated nyu.edu)", placeholder="ra@nyu.edu")
        description   = st.text_input("Description (optional)")
        active        = st.selectbox("Active", ["Y", "N"])
        if st.form_submit_button("Save Team", type="primary"):
            if not team_name.strip():
                st.error("Team Name is required.")
            else:
                upsert_team({
                    "Team Name":       team_name.strip(),
                    "Allocation (AED)":allocation,
                    "Lead Emails":     lead_emails.strip(),
                    "Member Emails":   member_emails.strip(),
                    "Description":     description.strip(),
                    "Active":          active,
                })
                st.success(f"✓ Team '{team_name}' saved.")
                st.rerun()

with tab3:
    current_rate = get_exchange_rate()
    st.metric("Current AED/USD Rate", f"1 USD = {current_rate} AED")
    with st.form("rate_form"):
        new_rate = st.number_input("New Rate (1 USD = ? AED)",
                                   value=float(current_rate), min_value=0.001,
                                   step=0.0001, format="%.4f")
        if st.form_submit_button("Update Rate", type="primary"):
            set_config("AED/USD Exchange Rate", new_rate)
            st.success(f"✓ Rate updated to {new_rate}")

with tab4:
    st.warning("⚠️ Test mode loads sample data tagged with `[TEST]`. Remove it cleanly when done.")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🧪 Load Dummy Data", use_container_width=True):
            from datetime import date, timedelta
            samples = [
                {"Date": (date.today() - timedelta(days=80)).isoformat(), "Category":"Equipment",
                 "Vendor / Payee":"Fisher Scientific","Description":"Pipette tips 1000uL",
                 "Amount (AED)":3450,"Amount (USD)":0,"Status":"Delivered","Team":"",
                 "Entry Method":"Manual","Notes":"[TEST] Auto-generated"},
                {"Date": (date.today() - timedelta(days=60)).isoformat(), "Category":"Travel",
                 "Vendor / Payee":"Emirates Airlines","Description":"AUH-BOS-AUH conference",
                 "Amount (AED)":0,"Amount (USD)":1850,"Status":"Paid","Team":"",
                 "Entry Method":"Manual","Notes":"[TEST] Auto-generated"},
                {"Date": (date.today() - timedelta(days=30)).isoformat(), "Category":"Personnel",
                 "Vendor / Payee":"Postdoc — October","Description":"Monthly stipend",
                 "Amount (AED)":18000,"Amount (USD)":0,"Status":"Paid","Team":"",
                 "Entry Method":"Manual","Notes":"[TEST] Auto-generated"},
            ]
            set_budget_allocation("Equipment", 500000, 0)
            set_budget_allocation("Personnel", 300000, 0)
            set_budget_allocation("Travel",     50000, 10000)
            set_budget_allocation("Other",      30000,  5000)
            for s in samples:
                s["Entered By"] = st.session_state.email
                append_transaction(s)
            st.success(f"✓ Loaded {len(samples)} test transactions and budget allocations.")

    with col2:
        if st.button("🗑️ Clear All Test Data", type="secondary", use_container_width=True):
            txns = get_transactions()
            if "Notes" in txns.columns:
                test_ids = txns[txns["Notes"].str.contains(r"\[TEST\]", na=False)]["Transaction ID"].tolist()
                for txn_id in test_ids:
                    update_transaction(txn_id, {"Status": "Cancelled"})
                for cat in ["Equipment","Personnel","Travel","Other"]:
                    set_budget_allocation(cat, 0, 0)
                st.success(f"✓ Cancelled {len(test_ids)} test transactions and reset allocations.")
            else:
                st.info("No transactions found.")
