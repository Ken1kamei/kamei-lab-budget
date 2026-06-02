import streamlit as st
import pandas as pd
from utils.runtime import refresh_runtime_modules

refresh_runtime_modules()

from utils.sheets import (get_teams, get_exchange_rate, get_currency_rates_to_usd, get_summary,
                           set_budget_allocation, upsert_team, set_config,
                           get_config, get_transactions, append_transaction,
                           update_transaction)
from utils.auth import require_role
from utils.categories import CATEGORIES
from utils.theme import apply_theme

require_role("pi")
apply_theme()

st.title("⚙️ Settings")

tab1, tab2, tab3, tab4, tab5 = st.tabs([
    "💰 Budget Allocations", "👥 Teams", "🔧 Exchange Rate", "Fiscal Year", "🧪 Test Mode"
])

with tab1:
    st.markdown("Set the lab budget per category for the current fiscal year.")
    summary_df = get_summary()

    with st.form("budget_alloc_form"):
        st.markdown("**Enter category budgets in USD:**")
        alloc_data = {}
        for cat in CATEGORIES:
            row = summary_df[summary_df["Category"] == cat] if "Category" in summary_df.columns else pd.DataFrame()
            curr_usd = float(row["Budgeted (USD)"].iloc[0]) if not row.empty else 0.0
            c1, c2 = st.columns([2, 1])
            c1.markdown(f"**{cat}**")
            usd = c2.number_input(f"USD##{cat}", value=curr_usd, min_value=0.0, step=1000.0, label_visibility="collapsed")
            alloc_data[cat] = usd
        if st.form_submit_button("Save Allocations", type="primary"):
            for cat, usd in alloc_data.items():
                set_budget_allocation(cat, 0, usd)
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
        allocation    = st.number_input("Total Allocation (USD)", min_value=0.0, step=1000.0)
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
                    "Allocation (USD)":allocation,
                    "Lead Emails":     lead_emails.strip(),
                    "Member Emails":   member_emails.strip(),
                    "Description":     description.strip(),
                    "Active":          active,
                })
                st.success(f"✓ Team '{team_name}' saved.")
                st.rerun()

with tab3:
    current_rate = get_exchange_rate()
    rates = get_currency_rates_to_usd()
    st.metric("Current AED Rate", f"1 AED = ${rates['AED']:.4f}")
    with st.form("rate_form"):
        new_rate = st.number_input("New Rate (1 USD = ? AED)",
                                   value=float(current_rate), min_value=0.001,
                                   step=0.0001, format="%.4f")
        eur = st.number_input("EUR/USD Exchange Rate (1 EUR = ? USD)",
                              value=float(rates["EUR"]), min_value=0.0001,
                              step=0.0001, format="%.4f")
        jpy = st.number_input("JPY/USD Exchange Rate (1 JPY = ? USD)",
                              value=float(rates["JPY"]), min_value=0.000001,
                              step=0.0001, format="%.6f")
        gbp = st.number_input("GBP/USD Exchange Rate (1 GBP = ? USD)",
                              value=float(rates["GBP"]), min_value=0.0001,
                              step=0.0001, format="%.4f")
        if st.form_submit_button("Update Rate", type="primary"):
            set_config("AED/USD Exchange Rate", new_rate)
            set_config("EUR/USD Exchange Rate", eur)
            set_config("JPY/USD Exchange Rate", jpy)
            set_config("GBP/USD Exchange Rate", gbp)
            st.success("✓ Currency rates updated.")

with tab4:
    st.markdown("Manage the fiscal-year label and automation settings for the current spreadsheet.")
    current_fy = get_config("Current Fiscal Year") or get_config("Fiscal Year") or "FY2025-26"
    threshold = get_config("Notification Threshold %") or "80"
    gmail_label = get_config("Gmail Label") or "Budget/Invoices"
    with st.form("fiscal_year_form"):
        fy = st.text_input("Current Fiscal Year", value=str(current_fy), placeholder="FY2026-27")
        notify = st.number_input("Notification Threshold %", value=float(threshold), min_value=1.0, max_value=100.0, step=1.0)
        label = st.text_input("Gmail Label", value=str(gmail_label))
        if st.form_submit_button("Save Fiscal Year Settings", type="primary"):
            if not fy.strip().startswith("FY"):
                st.error("Fiscal year must look like FY2026-27.")
            else:
                set_config("Current Fiscal Year", fy.strip())
                set_config("Fiscal Year", fy.strip())
                set_config("Notification Threshold %", notify)
                set_config("Gmail Label", label.strip() or "Budget/Invoices")
                st.success("Fiscal year settings saved.")

with tab5:
    st.warning("⚠️ Test mode loads sample data tagged with `[TEST]`. Remove it cleanly when done.")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("🧪 Load Dummy Data", use_container_width=True):
            from datetime import date, timedelta
            samples = [
                {"Date": (date.today() - timedelta(days=80)).isoformat(), "Category":"Equipment",
                 "Vendor / Payee":"Fisher Scientific","Description":"Pipette tips 1000uL",
                 "Currency":"AED","Amount":3450,"Status":"Delivered","Team":"",
                 "Entry Method":"Manual","Notes":"[TEST] Auto-generated"},
                {"Date": (date.today() - timedelta(days=60)).isoformat(), "Category":"Travel",
                 "Vendor / Payee":"Emirates Airlines","Description":"AUH-BOS-AUH conference",
                 "Currency":"USD","Amount":1850,"Status":"Paid","Team":"",
                 "Entry Method":"Manual","Notes":"[TEST] Auto-generated"},
                {"Date": (date.today() - timedelta(days=30)).isoformat(), "Category":"Personnel",
                 "Vendor / Payee":"Postdoc — October","Description":"Monthly stipend",
                 "Currency":"AED","Amount":18000,"Status":"Paid","Team":"",
                 "Entry Method":"Manual","Notes":"[TEST] Auto-generated"},
            ]
            set_budget_allocation("Equipment", 0, 135000)
            set_budget_allocation("Consumables", 0, 14000)
            set_budget_allocation("Personnel", 0, 82000)
            set_budget_allocation("Travel", 0, 24000)
            set_budget_allocation("Publications", 0, 12000)
            set_budget_allocation("Memberships", 0, 4000)
            set_budget_allocation("Other", 0, 13000)
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
                for cat in CATEGORIES:
                    set_budget_allocation(cat, 0, 0)
                st.success(f"✓ Cancelled {len(test_ids)} test transactions and reset allocations.")
            else:
                st.info("No transactions found.")
