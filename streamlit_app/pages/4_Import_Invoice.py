import streamlit as st
import pandas as pd
from utils.runtime import refresh_runtime_modules

refresh_runtime_modules()

from utils.sheets import get_teams, get_currency_rates_to_usd, upsert_imported_transaction
from utils.parse_invoice import parse_pdf_bytes, parse_erb_excel_bytes
from utils.auth import require_role, can_manage_all_budgets, current_team, current_teams
from utils.budget import SUPPORTED_CURRENCIES, round_currency, to_usd_equivalent
from utils.categories import CATEGORIES, SUBCATEGORIES
from utils.theme import apply_theme

require_role("pi", "budget_manager", "lead", "member")
apply_theme()

st.title("📥 Import Invoice / Receipt")

teams_df = get_teams()
rates = get_currency_rates_to_usd()
my_team = current_team()
my_teams = current_teams()

def _category_index(value: str) -> int:
    return CATEGORIES.index(value) if value in CATEGORIES else 0

def _subcategory_options(category: str) -> list[str]:
    return SUBCATEGORIES.get(category, ["Other"])

def _confidence_badge(score: str) -> str:
    return {"high": "🟢 high", "medium": "🟡 medium", "low": "🔴 needs review"}.get(score, "⚪ unknown")

def _render_pdf_import(pdf_file, parsed: dict, index: int):
    prefix = f"pdf_{index}_{pdf_file.name}"
    confidence = parsed.get("confidence", {})
    missing_fields = parsed.get("missing_fields", [])
    if missing_fields:
        st.warning(
            "Needs review: "
            + ", ".join(field.replace("_", " ") for field in missing_fields)
        )
    else:
        st.success("High-confidence extraction. Review before importing.")

    confidence_rows = [
        {"Field": field.replace("_", " ").title(), "Confidence": _confidence_badge(score)}
        for field, score in confidence.items()
    ]
    with st.expander("Auto-extracted details", expanded=bool(missing_fields)):
        if parsed.get("amount_source"):
            st.caption(f"Amount source: {parsed['amount_source']}")
        if confidence_rows:
            st.dataframe(pd.DataFrame(confidence_rows), use_container_width=True, hide_index=True)
        line_items = parsed.get("line_items", [])
        if line_items:
            st.caption("Detected line items")
            st.dataframe(pd.DataFrame(line_items), use_container_width=True, hide_index=True)
        if parsed.get("due_date"):
            st.caption(f"Detected due date: {parsed['due_date']}")

    col1, col2 = st.columns(2)
    with col1:
        vendor = st.text_input("Vendor *", value=parsed.get("vendor", ""), key=f"{prefix}_vendor")
        inv_num = st.text_input("Invoice #", value=parsed.get("invoice_number", ""), key=f"{prefix}_invoice")
        inv_date = st.text_input("Date", value=parsed.get("invoice_date", ""), key=f"{prefix}_date")
    with col2:
        category = st.selectbox(
            "Category to import as",
            CATEGORIES,
            index=_category_index(parsed.get("suggested_category", "Equipment")),
            key=f"{prefix}_category",
        )
        subcategory = st.selectbox(
            "Sub-category",
            _subcategory_options(category),
            index=0,
            key=f"{prefix}_subcategory",
        )
        po_num = st.text_input("PO Number", value=parsed.get("po_number", ""), key=f"{prefix}_po")

    parsed_currency = str(parsed.get("currency", "USD")).upper()
    if parsed_currency not in SUPPORTED_CURRENCIES:
        parsed_currency = "USD"
    total = float(parsed.get("total_amount", 0.0))
    col3, col4, col5 = st.columns(3)
    with col3:
        currency = st.selectbox(
            "Currency",
            SUPPORTED_CURRENCIES,
            index=SUPPORTED_CURRENCIES.index(parsed_currency),
            key=f"{prefix}_currency",
        )
    with col4:
        amount = st.number_input("Amount", value=total, min_value=0.0, key=f"{prefix}_amount")
    usd_equiv = round_currency(to_usd_equivalent(currency, amount, rates))
    with col5:
        st.metric("Amount (USD equiv)", f"${usd_equiv:,.2f}")

    if amount > 0:
        st.caption(f"{currency} {amount:,.2f} -> USD ${usd_equiv:,.2f}")

    description = st.text_input(
        "Description",
        value=parsed.get("suggested_description") or pdf_file.name,
        key=f"{prefix}_description",
    )
    extracted_notes = [
        f"Parsed by Python from {pdf_file.name}",
        f"Extraction confidence: {confidence}",
    ]
    if parsed.get("amount_source"):
        extracted_notes.append(f"Amount source: {parsed['amount_source']}")
    if parsed.get("due_date"):
        extracted_notes.append(f"Detected due date: {parsed['due_date']}")
    if parsed.get("line_items"):
        extracted_notes.append(f"Detected {len(parsed['line_items'])} line item(s)")
    notes = st.text_area("Notes", value="\n".join(extracted_notes), key=f"{prefix}_notes")

    if can_manage_all_budgets():
        team_names = ["(Lab-wide)"] + (
            teams_df["Team Name"].tolist() if not teams_df.empty else []
        )
        team_sel = st.selectbox("Team", team_names, key=f"{prefix}_team")
        team_value = "" if team_sel == "(Lab-wide)" else team_sel
    elif len(my_teams) > 1:
        team_value = st.selectbox("Team", my_teams, key=f"{prefix}_team_member")
    else:
        team_value = my_team
        st.info(f"Team: **{my_team}**")

    status = st.selectbox("Status", ["Pending Review"], disabled=True, key=f"{prefix}_status")
    submitted = st.button("Import Transaction", type="primary", key=f"{prefix}_submit")

    if submitted:
        if not vendor.strip():
            st.error("Vendor is required.")
            return
        result = upsert_imported_transaction({
            "Date": inv_date,
            "Category": category,
            "Sub-category": subcategory,
            "Vendor / Payee": vendor.strip(),
            "Description": description,
            "Invoice Number": inv_num,
            "PO Number": po_num,
            "Currency": currency,
            "Amount": amount,
            "Amount (USD equiv)": usd_equiv,
            "Status": status,
            "Notes": notes,
            "Entry Method": "Auto-PDF",
            "Entered By": st.session_state.email,
            "Team": team_value,
        })
        verb = "updated" if result["matched"] else "imported"
        st.success(f"Invoice {verb} as **{result['transaction_id']}**")


tab1, tab2 = st.tabs(["📄 PDF Invoice", "📊 NYUAD ERB Excel"])

with tab1:
    st.markdown(
        "Upload one or more PDF invoices, receipts, or NYUAD purchase orders. "
        "Fields are extracted automatically using Python (no AI)."
    )
    pdf_files = st.file_uploader(
        "Drop PDF files here",
        type=["pdf"],
        key="pdf_upload",
        accept_multiple_files=True,
    )

    if pdf_files:
        st.caption(f"{len(pdf_files)} PDF file(s) selected.")
        parsed_results = []
        with st.spinner("Parsing PDF files..."):
            for pdf_file in pdf_files:
                parsed_results.append((pdf_file, parse_pdf_bytes(pdf_file.getvalue(), pdf_file.name)))

        for i, (pdf_file, parsed) in enumerate(parsed_results):
            title = f"{i + 1}. {pdf_file.name}"
            if "_error" in parsed:
                with st.expander(title, expanded=True):
                    st.error(f"Parse error: {parsed['_error']}")
                continue
            with st.expander(title, expanded=i == 0):
                _render_pdf_import(pdf_file, parsed, i)

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
            preview_df["Currency"] = "AED"
            preview_df["Amount"] = preview_df["Amount (AED)"]
            preview_df["Amount (USD equiv)"] = preview_df["Amount"].map(
                lambda value: round_currency(to_usd_equivalent("AED", value, rates))
            )
            st.dataframe(
                preview_df[["Date", "Description", "Currency", "Amount", "Amount (USD equiv)", "Notes"]],
                use_container_width=True,
                hide_index=True,
            )
            total_usd = float(preview_df["Amount (USD equiv)"].sum())
            st.metric("Total", f"${total_usd:,.2f}")

            excel_category = st.selectbox(
                "Assign category to imported rows",
                CATEGORIES,
                index=_category_index(rows[0].get("Category", "Consumables")),
                key="excel_category",
            )
            excel_subcategory = st.selectbox(
                "Assign sub-category to imported rows",
                _subcategory_options(excel_category),
                index=0,
                key="excel_subcategory",
            )

            if can_manage_all_budgets():
                team_names = ["(Lab-wide)"] + (
                    teams_df["Team Name"].tolist() if not teams_df.empty else []
                )
                team_sel = st.selectbox("Assign all rows to team", team_names, key="excel_team")
                team_value = "" if team_sel == "(Lab-wide)" else team_sel
            elif len(my_teams) > 1:
                team_value = st.selectbox("Assign all rows to team", my_teams, key="excel_team_member")
            else:
                team_value = my_team
                st.info(f"Team: **{my_team}**")

            if st.button(f"Import all {len(rows)} transactions", type="primary"):
                prog = st.progress(0)
                for i, row in enumerate(rows):
                    row["Category"] = excel_category
                    row["Sub-category"] = excel_subcategory
                    row["Team"] = team_value
                    row["Entered By"] = st.session_state.email
                    row["Status"] = "Pending Review"
                    row["Currency"] = "AED"
                    row["Amount"] = row.get("Amount (AED)", 0)
                    row["Amount (USD equiv)"] = round_currency(
                        to_usd_equivalent("AED", row["Amount"], rates)
                    )
                    upsert_imported_transaction(row)
                    prog.progress((i + 1) / len(rows))
                st.success(f"Imported or updated {len(rows)} transaction(s) for review.")
                st.balloons()
