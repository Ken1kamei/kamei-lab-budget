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


def _split_emails(value: str) -> list[str]:
    seen = set()
    emails = []
    for raw in str(value or "").replace(";", ",").split(","):
        email = raw.strip().lower()
        if email and email not in seen:
            seen.add(email)
            emails.append(email)
    return emails


def _join_emails(emails: list[str]) -> str:
    return ", ".join(sorted(dict.fromkeys(e.strip().lower() for e in emails if e.strip())))


def _valid_nyu_email(email: str) -> bool:
    return email.strip().lower().endswith("@nyu.edu")


def _team_payload(row: pd.Series) -> dict:
    return {
        "Team Name": str(row.get("Team Name", "")).strip(),
        "Allocation (AED)": row.get("Allocation (AED)", 0),
        "Allocation (USD)": row.get("Allocation (USD)", 0),
        "Lead Emails": row.get("Lead Emails", ""),
        "Member Emails": row.get("Member Emails", ""),
        "Description": row.get("Description", ""),
        "Active": row.get("Active", "Y"),
    }


def _member_roster(teams_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    if teams_df.empty:
        return pd.DataFrame(columns=["Email", "Team", "Access"])
    for _, row in teams_df.iterrows():
        team = str(row.get("Team Name", "")).strip()
        for email in _split_emails(row.get("Lead Emails", "")):
            rows.append({"Email": email, "Team": team, "Access": "Team Lead"})
        for email in _split_emails(row.get("Member Emails", "")):
            rows.append({"Email": email, "Team": team, "Access": "Member"})
    return pd.DataFrame(rows).sort_values(["Team", "Access", "Email"]) if rows else pd.DataFrame(columns=["Email", "Team", "Access"])


def _set_member_access(teams_df: pd.DataFrame, email: str, target_team: str, access: str) -> None:
    normalized_email = email.strip().lower()
    for _, row in teams_df.iterrows():
        payload = _team_payload(row)
        leads = [e for e in _split_emails(payload["Lead Emails"]) if e != normalized_email]
        members = [e for e in _split_emails(payload["Member Emails"]) if e != normalized_email]
        if payload["Team Name"] == target_team and access == "Team Lead":
            leads.append(normalized_email)
        elif payload["Team Name"] == target_team and access == "Member":
            members.append(normalized_email)
        payload["Lead Emails"] = _join_emails(leads)
        payload["Member Emails"] = _join_emails(members)
        upsert_team(payload)

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
    st.markdown("**Member access:**")
    roster_df = _member_roster(teams_df)
    if not roster_df.empty:
        st.dataframe(roster_df, use_container_width=True, hide_index=True)
    else:
        st.info("No team members registered yet.")

    existing_options = [""] + (roster_df["Email"].drop_duplicates().tolist() if not roster_df.empty else [])
    selected_email = st.selectbox(
        "Load existing member",
        existing_options,
        format_func=lambda value: "Add new member..." if not value else value,
    )
    selected_row = (
        roster_df[roster_df["Email"] == selected_email].iloc[0].to_dict()
        if selected_email and not roster_df.empty
        else {}
    )
    team_options = teams_df["Team Name"].dropna().astype(str).tolist() if not teams_df.empty else []

    with st.form("member_access_form"):
        member_email = st.text_input("NYU email *", value=selected_email, placeholder="member@nyu.edu")
        current_team_value = selected_row.get("Team", team_options[0] if team_options else "")
        default_team_idx = team_options.index(current_team_value) if current_team_value in team_options else 0
        team_select_options = team_options or [""]
        target_team = st.selectbox(
            "Team",
            team_select_options,
            index=default_team_idx,
            disabled=not team_options,
        )
        access_options = ["Member", "Team Lead", "No access / remove from teams"]
        current_access = selected_row.get("Access", "Member")
        default_access_idx = access_options.index(current_access) if current_access in access_options else 0
        access = st.selectbox("Access", access_options, index=default_access_idx)
        if st.form_submit_button("Save Member Access", type="primary"):
            email = member_email.strip().lower()
            if not email:
                st.error("NYU email is required.")
            elif not _valid_nyu_email(email):
                st.error("Email must end with @nyu.edu.")
            elif not team_options:
                st.error("Create at least one active team first.")
            else:
                final_access = "No access" if access.startswith("No access") else access
                _set_member_access(
                    teams_df,
                    email,
                    target_team,
                    final_access,
                )
                if final_access == "No access":
                    st.success(f"Removed {email} from all team access lists.")
                else:
                    st.success(f"Saved {email} as {final_access} for {target_team}.")
                st.rerun()

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
