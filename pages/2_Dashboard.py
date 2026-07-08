"""Dashboard: select a real, ETL-loaded customer and run the actual
Analytics + AI Engine pipeline in-process (no separate backend service --
see the design note in README.md's Streamlit Frontend section)."""

from __future__ import annotations

import streamlit as st

from ai_engine import AIEngine
from analytics_engine import run_analytics
from components.auth import render_header, require_login
from components.cards import render_health_card
from components.data_viewer import render_raw_data_viewer
from components.forms import customer_selector
from db import get_customer_financials, list_ai_reports

st.set_page_config(page_title="Dashboard", layout="wide")
require_login()
render_header("MSME Financial Health Card")

tab_generate, tab_reports = st.tabs(["Generate Card", "View Reports"])

with tab_generate:
    st.subheader("Select Customer")
    customer_id = customer_selector()

    if customer_id:
        render_raw_data_viewer(customer_id)

    generate_btn = st.button("Generate Health Card", type="primary", disabled=customer_id is None)

    if generate_btn and customer_id:
        with st.status("Generating health card...", expanded=True) as status:
            st.write("Computing GST / UPI / AA / EPFO ratios and cross-validation...")
            scorecard = run_analytics(customer_ids=[customer_id])[0]
            st.write("Scoring dimensions and composite health score...")
            st.write("Generating narrative report (Gemini, with deterministic fallback)...")
            engine = AIEngine()
            report = engine.generate_report(scorecard)
            status.update(label="Health card generated", state="complete")

        st.session_state["last_customer_id"] = customer_id
        st.session_state["last_scorecard"] = scorecard
        st.session_state["last_report"] = report

    if (
        customer_id
        and st.session_state.get("last_customer_id") == customer_id
        and st.session_state.get("last_scorecard")
    ):
        st.divider()
        customer = get_customer_financials(customer_id)["customer"]
        render_health_card(customer, st.session_state["last_scorecard"], st.session_state["last_report"])

with tab_reports:
    st.subheader("Recently Generated Reports")
    recent = list_ai_reports(limit=10)
    if not recent:
        st.info("No reports generated yet. Use the 'Generate Card' tab to create one.")
    else:
        st.dataframe(
            [
                {
                    "Customer": f"{r['customer_id']} -- {r['business_name']}",
                    "Sector": r["sector"],
                    "Date": r["scorecard_date"],
                    "Composite Score": r["composite_score"],
                    "Source": r["generation_method"],
                }
                for r in recent
            ],
            width='stretch',
            hide_index=True,
        )
        st.caption("See the Reports page (sidebar) to open and compare any historical report in full.")
