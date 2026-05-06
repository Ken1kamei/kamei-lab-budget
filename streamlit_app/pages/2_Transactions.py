import streamlit as st
import pandas as pd
from utils.sheets import get_transactions, get_teams, update_transaction, approve_transaction
from utils.auth import require_role, is_pi, can_edit, current_team
from utils.budget import LIFECYCLE_STATUSES

require_role("pi", "lead", "member")

st.title("Requests / Transactions")

txns     = get_transactions()
teams_df = get_teams()
team     = current_team()

if not is_pi() and "Team" in txns.columns:
    txns = txns[txns["Team"] == team]

col1, col2, col3, col4 = st.columns(4)
with col1:
    cats = ["All"] + sorted(txns["Category"].dropna().unique().tolist()) if "Category" in txns.columns else ["All"]
    cat_filter = st.selectbox("Category", cats)
with col2:
    statuses = ["All"] + sorted(txns["Status"].dropna().unique().tolist()) if "Status" in txns.columns else ["All"]
    status_filter = st.selectbox("Status", statuses)
with col3:
    if is_pi() and "Team" in txns.columns:
        team_opts = ["All"] + sorted(txns["Team"].dropna().unique().tolist())
        team_filter = st.selectbox("Team", team_opts)
    else:
        team_filter = "All"
with col4:
    search = st.text_input("Search vendor / description", "")

filtered = txns.copy()
if cat_filter    != "All": filtered = filtered[filtered["Category"] == cat_filter]
if status_filter != "All": filtered = filtered[filtered["Status"]   == status_filter]
if team_filter   != "All": filtered = filtered[filtered["Team"]     == team_filter]
if search:
    mask = (
        filtered.get("Vendor / Payee", pd.Series(dtype=str)).str.contains(search, case=False, na=False) |
        filtered.get("Description",    pd.Series(dtype=str)).str.contains(search, case=False, na=False)
    )
    filtered = filtered[mask]

if "Date" in filtered.columns:
    filtered = filtered.sort_values("Date", ascending=False)

st.caption(f"Showing {len(filtered)} of {len(txns)} transactions")

SHOW_COLS = ["Transaction ID", "Date", "Category", "Team",
             "Vendor / Payee", "Description",
             "Amount (AED)", "Amount (USD)", "Status", "Entry Method",
             "Approved By", "Approved At"]
show_cols = [c for c in SHOW_COLS if c in filtered.columns]
st.dataframe(filtered[show_cols], use_container_width=True, hide_index=True)

csv = filtered[show_cols].to_csv(index=False).encode("utf-8")
st.download_button("⬇️ Export CSV", csv, "transactions.csv", "text/csv")

if can_edit():
    st.divider()
    st.subheader("✏️ Edit Transaction")
    txn_ids = filtered["Transaction ID"].tolist() if "Transaction ID" in filtered.columns else []
    if txn_ids:
        selected_id = st.selectbox("Select Transaction ID to edit", txn_ids)
        row = filtered[filtered["Transaction ID"] == selected_id].iloc[0]

        with st.form("edit_form"):
            new_status = st.selectbox("Status",
                LIFECYCLE_STATUSES,
                index=LIFECYCLE_STATUSES.index(str(row.get("Status", "Requested")))
                    if str(row.get("Status", "Requested")) in LIFECYCLE_STATUSES else 0)
            new_notes  = st.text_area("Notes", value=str(row.get("Notes", "")))
            new_pdf    = st.text_input("PDF Link", value=str(row.get("PDF Link", "")))
            submitted  = st.form_submit_button("Save Changes", type="primary")

        if submitted:
            updates = {
                "Status":   new_status,
                "Notes":    new_notes,
                "PDF Link": new_pdf,
            }
            old_status = str(row.get("Status", "Requested"))
            if old_status == "Requested" and new_status in ("Approved", "Ordered", "Pending Review", "Delivered", "Paid"):
                approve_transaction(selected_id, st.session_state.email, new_status)
                updates.pop("Status")
            if updates:
                update_transaction(selected_id, updates)
            st.success(f"✓ Updated {selected_id}")
            st.rerun()
    else:
        st.info("No transactions match the current filters.")
else:
    st.divider()
    st.subheader("Attach Receipt")
    txn_ids = filtered["Transaction ID"].tolist() if "Transaction ID" in filtered.columns else []
    if txn_ids:
        selected_id = st.selectbox("Select your request", txn_ids)
        row = filtered[filtered["Transaction ID"] == selected_id].iloc[0]
        with st.form("member_receipt_form"):
            new_notes = st.text_area("Notes", value=str(row.get("Notes", "")))
            new_pdf = st.text_input("Receipt / PDF Link", value=str(row.get("PDF Link", "")))
            submitted = st.form_submit_button("Save Receipt Link", type="primary")
        if submitted:
            update_transaction(selected_id, {
                "Notes": new_notes,
                "PDF Link": new_pdf,
            })
            st.success(f"Receipt information saved for {selected_id}")
            st.rerun()
