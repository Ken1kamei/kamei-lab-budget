import streamlit as st
import pandas as pd
from utils.sheets import (
    get_transactions,
    get_teams,
    get_currency_rates_to_usd,
    update_transaction,
    approve_transaction,
)
from utils.auth import require_role, can_edit, can_manage_all_budgets, current_teams
from utils.budget import BUDGET_STATUSES, SUPPORTED_CURRENCIES, round_currency, to_usd_equivalent
from utils.categories import CATEGORIES, SUBCATEGORIES
from utils.theme import apply_theme

require_role("pi", "budget_manager", "lead", "member")
apply_theme()

st.title("Requests / Transactions")

txns     = get_transactions()
teams_df = get_teams()
teams = current_teams()
rates = get_currency_rates_to_usd()

def _as_float(value) -> float:
    try:
        return float(str(value or "0").replace(",", ""))
    except ValueError:
        return 0.0

def _option_index(options: list[str], value: str, default: int = 0) -> int:
    return options.index(value) if value in options else default

def _subcategory_options(category: str) -> list[str]:
    return SUBCATEGORIES.get(category, ["Other"])

def _team_options(current_value: str) -> list[str]:
    if can_manage_all_budgets():
        team_values = teams_df["Team Name"].dropna().astype(str).str.strip().tolist() if not teams_df.empty else []
        options = ["(Lab-wide)"] + sorted({team for team in team_values if team})
    else:
        options = sorted({team for team in teams if team})
    if current_value and current_value not in options:
        options.append(current_value)
    return options or [current_value or ""]

if not can_manage_all_budgets() and "Team" in txns.columns:
    txns = txns[txns["Team"].isin(teams)]

col1, col2, col3, col4 = st.columns(4)
with col1:
    cats = ["All"] + sorted(txns["Category"].dropna().unique().tolist()) if "Category" in txns.columns else ["All"]
    cat_filter = st.selectbox("Category", cats)
with col2:
    statuses = ["All"] + sorted(txns["Status"].dropna().unique().tolist()) if "Status" in txns.columns else ["All"]
    status_filter = st.selectbox("Status", statuses)
with col3:
    if can_manage_all_budgets() and "Team" in txns.columns:
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
             "Currency", "Amount", "Amount (USD equiv)", "Status", "Entry Method",
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

        st.caption("Manually correct any field, then save. Currency changes recalculate the USD equivalent.")
        with st.form("edit_form"):
            col_a, col_b = st.columns(2)
            with col_a:
                new_date = st.text_input("Date", value=str(row.get("Date", "")))
                new_category = st.selectbox(
                    "Category",
                    CATEGORIES,
                    index=_option_index(CATEGORIES, str(row.get("Category", ""))),
                )
                subcategory_options = _subcategory_options(new_category)
                new_subcategory = st.selectbox(
                    "Sub-category",
                    subcategory_options,
                    index=_option_index(subcategory_options, str(row.get("Sub-category", ""))),
                )
                new_vendor = st.text_input("Vendor / Payee", value=str(row.get("Vendor / Payee", "")))
                new_description = st.text_area("Description", value=str(row.get("Description", "")), height=110)
            with col_b:
                current_team = str(row.get("Team", "")).strip()
                team_options = _team_options(current_team)
                team_label = current_team if current_team else "(Lab-wide)"
                new_team_selection = st.selectbox(
                    "Team",
                    team_options,
                    index=_option_index(team_options, team_label),
                )
                new_team = "" if new_team_selection == "(Lab-wide)" else new_team_selection
                new_po = st.text_input("PO Number", value=str(row.get("PO Number", "")))
                new_invoice = st.text_input("Invoice Number", value=str(row.get("Invoice Number", "")))
                new_status = st.selectbox(
                    "Status",
                    BUDGET_STATUSES,
                    index=BUDGET_STATUSES.index(str(row.get("Status", "Allocated")))
                    if str(row.get("Status", "Allocated")) in BUDGET_STATUSES
                    else 0,
                )

            current_currency = str(row.get("Currency", "USD")).upper()
            if current_currency not in SUPPORTED_CURRENCIES:
                current_currency = "AED" if _as_float(row.get("Amount (AED)", 0)) else "USD"
            current_amount = _as_float(row.get("Amount", 0))
            if current_amount == 0:
                current_amount = (
                    _as_float(row.get("Amount (AED)", 0))
                    if current_currency == "AED"
                    else _as_float(row.get("Amount (USD)", 0))
                )

            col_c, col_d, col_e = st.columns(3)
            with col_c:
                new_currency = st.selectbox(
                    "Currency",
                    SUPPORTED_CURRENCIES,
                    index=SUPPORTED_CURRENCIES.index(current_currency),
                )
            with col_d:
                new_amount = st.number_input("Amount", value=current_amount, min_value=0.0)
            new_usd_equiv = round_currency(to_usd_equivalent(new_currency, new_amount, rates))
            with col_e:
                st.metric("Amount (USD equiv)", f"${new_usd_equiv:,.2f}")

            new_notes  = st.text_area("Notes", value=str(row.get("Notes", "")), height=140)
            new_pdf    = st.text_input("PDF Link", value=str(row.get("PDF Link", "")))
            submitted  = st.form_submit_button("Save Changes", type="primary")

        if submitted:
            updates = {
                "Date":     new_date,
                "Category": new_category,
                "Sub-category": new_subcategory,
                "Team":     new_team,
                "Vendor / Payee": new_vendor,
                "Description": new_description,
                "PO Number": new_po,
                "Invoice Number": new_invoice,
                "Currency": new_currency,
                "Amount":   new_amount,
                "Status":   new_status,
                "Notes":    new_notes,
                "PDF Link": new_pdf,
            }
            old_status = str(row.get("Status", "Allocated"))
            if old_status != "Allocated" and new_status == "Allocated":
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
