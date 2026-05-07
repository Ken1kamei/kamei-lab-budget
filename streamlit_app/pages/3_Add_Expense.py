import streamlit as st
from datetime import date
from utils.sheets import get_teams, get_exchange_rate, append_transaction
from utils.auth import require_role, is_pi, can_edit, current_team
from utils.categories import CATEGORIES, SUBCATEGORIES

require_role("pi", "lead", "member")

st.title("Add Request")

teams_df  = get_teams()
rate      = get_exchange_rate()
my_team   = current_team()

with st.form("add_expense_form", clear_on_submit=True):
    col1, col2 = st.columns(2)
    with col1:
        exp_date = st.date_input("Date *", value=date.today())
        category = st.selectbox("Category *", CATEGORIES)
    with col2:
        subcat   = st.selectbox("Sub-category", SUBCATEGORIES.get(category, ["Other"]))
        if can_edit():
            status = st.selectbox("Status", ["Requested", "Approved", "Ordered", "Pending Review", "Delivered", "Paid"])
        else:
            status = "Requested"
            st.info("Status: Requested")

    vendor      = st.text_input("Vendor / Payee *")
    description = st.text_input("Description *")

    col3, col4 = st.columns(2)
    with col3:
        po_num  = st.text_input("PO Number (optional)")
        inv_num = st.text_input("Invoice Number (optional)")
    with col4:
        aed_amt = st.number_input("Amount (AED) — 0 if paid in USD", min_value=0.0, step=0.01)
        usd_amt = st.number_input("Amount (USD) — 0 if paid in AED", min_value=0.0, step=0.01)

    if aed_amt + usd_amt > 0:
        equiv = aed_amt + usd_amt * rate
        st.caption(f"AED equivalent: **AED {equiv:,.2f}** (rate: {rate})")

    pdf_link = st.text_input("PDF Link (Google Drive URL, optional)")
    notes    = st.text_area("Notes", height=80)

    if is_pi():
        team_names = ["(Lab-wide / unassigned)"] + (teams_df["Team Name"].tolist() if not teams_df.empty else [])
        team_sel   = st.selectbox("Team", team_names)
        team_value = "" if team_sel == "(Lab-wide / unassigned)" else team_sel
    else:
        st.info(f"Team: **{my_team}** (pre-assigned)")
        team_value = my_team

    submitted = st.form_submit_button("Add Transaction", type="primary", use_container_width=True)

if submitted:
    if not vendor.strip() or not description.strip():
        st.error("Vendor and Description are required.")
    else:
        approved_fields = {}
        if status in ("Approved", "Ordered", "Pending Review", "Delivered", "Paid"):
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
            "Amount (AED)":  aed_amt,
            "Amount (USD)":  usd_amt,
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
