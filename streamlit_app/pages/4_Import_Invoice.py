import streamlit as st
import pandas as pd
from utils.runtime import refresh_runtime_modules

refresh_runtime_modules()

from utils.sheets import get_teams, get_exchange_rate, upsert_imported_transaction
from utils.parse_invoice import parse_pdf_bytes, parse_erb_excel_bytes
from utils.auth import require_role, is_pi, current_team
from utils.budget import to_aed_equivalent
from utils.categories import CATEGORIES

require_role("pi", "lead")

st.title("📥 Import Invoice / Receipt")

teams_df = get_teams()
rate = get_exchange_rate()
my_team = current_team()

def _category_index(value: str) -> int:
    return CATEGORIES.index(value) if value in CATEGORIES else 0

tab1, tab2 = st.tabs(["📄 PDF Invoice", "📊 NYUAD ERB Excel"])

with tab1:
    st.markdown(
        "Upload a PDF invoice or receipt. Fields are extracted automatically using Python (no AI)."
    )
    pdf_file = st.file_uploader("Drop PDF here", type=["pdf"], key="pdf_upload")

    if pdf_file:
        with st.spinner("Parsing invoice..."):
            parsed = parse_pdf_bytes(pdf_file.read(), pdf_file.name)

        if "_error" in parsed:
            st.error(f"Parse error: {parsed['_error']}")
        else:
            st.success("Parsed successfully. Review fields below before importing.")

            col1, col2 = st.columns(2)
            with col1:
                vendor = st.text_input(
                    "Vendor *", value=parsed.get("vendor", "")
                )
                inv_num = st.text_input(
                    "Invoice #", value=parsed.get("invoice_number", "")
                )
                inv_date = st.text_input(
                    "Date", value=parsed.get("invoice_date", "")
                )
            with col2:
                category = st.selectbox(
                    "Category",
                    CATEGORIES,
                    index=_category_index(parsed.get("suggested_category", "Equipment")),
                )
                po_num = st.text_input("PO Number", value=parsed.get("po_number", ""))

            currency = parsed.get("currency", "AED")
            total = float(parsed.get("total_amount", 0.0))
            col3, col4 = st.columns(2)
            with col3:
                aed = st.number_input(
                    "Amount (AED)",
                    value=total if currency == "AED" else 0.0,
                    min_value=0.0,
                )
            with col4:
                usd = st.number_input(
                    "Amount (USD)",
                    value=total if currency == "USD" else 0.0,
                    min_value=0.0,
                )

            if aed + usd > 0:
                equiv = to_aed_equivalent(aed, usd, rate)
                st.caption(f"AED equivalent: **AED {equiv:,.2f}** (rate: {rate})")

            description = st.text_input("Description", value=pdf_file.name)
            notes = st.text_area("Notes", value=f"Parsed by Python from {pdf_file.name}")

            if is_pi():
                team_names = ["(Lab-wide)"] + (
                    teams_df["Team Name"].tolist() if not teams_df.empty else []
                )
                team_sel = st.selectbox("Team", team_names)
                team_value = "" if team_sel == "(Lab-wide)" else team_sel
            else:
                team_value = my_team
                st.info(f"Team: **{my_team}**")

            status = st.selectbox(
                "Status", ["Pending Review"], disabled=True
            )
            submitted = st.button("Import Transaction", type="primary")

            if submitted:
                if not vendor.strip():
                    st.error("Vendor is required.")
                else:
                    result = upsert_imported_transaction({
                        "Date": inv_date,
                        "Category": category,
                        "Vendor / Payee": vendor.strip(),
                        "Description": description,
                        "Invoice Number": inv_num,
                        "PO Number": po_num,
                        "Amount (AED)": aed,
                        "Amount (USD)": usd,
                        "Status": status,
                        "Notes": notes,
                        "Entry Method": "Auto-PDF",
                        "Entered By": st.session_state.email,
                        "Team": team_value,
                    })
                    verb = "updated" if result["matched"] else "imported"
                    st.success(f"Invoice {verb} as **{result['transaction_id']}**")

with tab2:
    st.markdown(
        "Upload a `ADH_COST_ACCT_CRS_CHRG_ERB_DTL_*.xlsx` file from the NYUAD cost accounting system."
    )
    excel_file = st.file_uploader(
        "Drop Excel here", type=["xlsx", "xls"], key="excel_upload"
    )

    if excel_file:
        with st.spinner("Parsing Excel..."):
            rows = parse_erb_excel_bytes(excel_file.read())

        if not rows:
            st.error("No transactions found. Is this a valid ERB report?")
        else:
            st.success(f"Found **{len(rows)} row(s)**. Review below.")
            preview_df = pd.DataFrame(rows)[
                ["Date", "Description", "Amount (AED)", "Notes"]
            ]
            st.dataframe(preview_df, use_container_width=True, hide_index=True)
            total_aed = sum(r["Amount (AED)"] for r in rows)
            st.metric("Total", f"AED {total_aed:,.2f}")

            if is_pi():
                team_names = ["(Lab-wide)"] + (
                    teams_df["Team Name"].tolist() if not teams_df.empty else []
                )
                team_sel = st.selectbox("Assign all rows to team", team_names, key="excel_team")
                team_value = "" if team_sel == "(Lab-wide)" else team_sel
            else:
                team_value = my_team
                st.info(f"Team: **{my_team}**")

            if st.button(f"Import all {len(rows)} transactions", type="primary"):
                prog = st.progress(0)
                for i, row in enumerate(rows):
                    row["Team"] = team_value
                    row["Entered By"] = st.session_state.email
                    row["Status"] = "Pending Review"
                    upsert_imported_transaction(row)
                    prog.progress((i + 1) / len(rows))
                st.success(f"Imported or updated {len(rows)} transaction(s) for review.")
                st.balloons()
