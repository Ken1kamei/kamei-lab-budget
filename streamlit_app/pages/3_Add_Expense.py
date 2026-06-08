import streamlit as st
from datetime import date
from utils.runtime import refresh_runtime_modules

refresh_runtime_modules()

from utils.sheets import get_teams, get_currency_rates_to_usd, append_transaction
from utils.auth import require_role, can_edit, can_manage_all_budgets, current_team, current_teams
from utils.budget import BUDGET_STATUSES, SUPPORTED_CURRENCIES, round_currency, to_usd_equivalent
from utils.categories import CATEGORIES, SUBCATEGORIES
from utils.theme import apply_theme

require_role("pi", "budget_manager", "lead", "member")
apply_theme()

st.title("Add Request")

teams_df  = get_teams()
rates     = get_currency_rates_to_usd()
my_team   = current_team()
my_teams  = current_teams()

with st.form("add_expense_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        exp_date = st.date_input("Date *", value=date.today())
        category = st.selectbox("Category *", CATEGORIES)
    with col2:
        subcat   = st.selectbox("Sub-category", SUBCATEGORIES.get(category, ["Other"]))
        if can_edit():
            status = st.selectbox("Status", BUDGET_STATUSES)
        else:
            status = "Allocated"
            st.info("Status: Allocated")

    vendor      = st.text_input("Vendor / Payee *")
    description = st.text_input("Description *")

    col3, col4 = st.columns(2)
    with col3:
        po_num  = st.text_input("PO Number (optional)")
        inv_num = st.text_input("Invoice Number (optional)")
    with col4:
        currency = st.selectbox("Currency", SUPPORTED_CURRENCIES)
        amount = st.number_input("Amount", min_value=0.0, step=0.01)

    usd_equiv = round_currency(to_usd_equivalent(currency, amount, rates))
    if amount > 0:
        st.caption(f"USD equivalent: **${usd_equiv:,.2f}**")

    pdf_link = st.text_input("PDF Link (Google Drive URL, optional)")
    notes    = st.text_area("Notes", height=80)

    if can_manage_all_budgets():
        team_names = ["(Lab-wide / unassigned)"] + (teams_df["Team Name"].tolist() if not teams_df.empty else [])
        team_sel   = st.selectbox("Team", team_names)
        team_value = "" if team_sel == "(Lab-wide / unassigned)" else team_sel
    elif len(my_teams) > 1:
        team_value = st.selectbox("Team", my_teams)
    else:
        st.info(f"Team: **{my_team}** (pre-assigned)")
        team_value = my_team

    submitted = st.form_submit_button("Add Transaction", type="primary", use_container_width=True)

if submitted:
    if not vendor.strip() or not description.strip():
        st.error("Vendor and Description are required.")
    else:
        approved_fields = {}
        if status == "Allocated":
            from datetime import datetime
            approved_fields = {
                "Approved By": st.session_state.email,
                "Approved At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        txn_id = append_transaction({
            "Date":          exp_date.isoformat(),
            "Category":      category,
            "Sub-category":  subcat,
            "Vendor / Payee": vendor.strip(),
            "Description":   description.strip(),
            "PO Number":     po_num.strip(),
            "Invoice Number": inv_num.strip(),
            "Currency":      currency,
            "Amount":        amount,
            "Amount (USD equiv)": usd_equiv,
            "Status":        status,
            "PDF Link":      pdf_link.strip(),
            "Notes":         notes.strip(),
            "Entered By":    st.session_state.email,
            "Entry Method":  "Manual",
            "Team":          team_value,
            **approved_fields,
        })
        st.success(f"Request saved: **{txn_id}**")
        st.balloons()
