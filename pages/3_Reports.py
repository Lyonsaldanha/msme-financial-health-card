"""Historical reports across all customers: comparison chart + full card view."""

from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from components.auth import render_header, require_login
from components.cards import render_health_card
from db import get_ai_report, get_customer_financials, list_ai_reports

st.set_page_config(page_title="Reports", layout="wide")
require_login()
render_header("Financial Health Reports")

reports = list_ai_reports()

if not reports:
    st.info("No reports generated yet. Use the Dashboard's 'Generate Card' tab to create one.")
else:
    st.subheader("Composite Score Comparison (latest report per customer)")
    latest_by_customer: dict[str, dict] = {}
    for r in reports:
        latest_by_customer.setdefault(r["customer_id"], r)
    comparison = sorted(latest_by_customer.values(), key=lambda r: r["customer_id"])

    fig = go.Figure(
        go.Bar(
            x=[f"{r['customer_id']} ({r['business_name']})" for r in comparison],
            y=[r["composite_score"] for r in comparison],
            marker_color="#4a90d9",
        )
    )
    fig.update_layout(title="Latest Composite Score by Customer", height=350, yaxis_range=[0, 100])
    st.plotly_chart(fig, width='stretch')

    st.divider()
    st.subheader("All Reports")
    st.dataframe(
        [
            {
                "Customer": f"{r['customer_id']} -- {r['business_name']}",
                "Sector": r["sector"],
                "Date": r["scorecard_date"],
                "Composite Score": r["composite_score"],
                "Source": r["generation_method"],
                "Generated At": r["generated_at"],
            }
            for r in reports
        ],
        width='stretch',
        hide_index=True,
    )

    st.divider()
    st.subheader("View a Report")
    options = [f"{r['customer_id']} -- {r['scorecard_date']} (score {r['composite_score']})" for r in reports]
    selected_idx = st.selectbox("Select a report to view", range(len(options)), format_func=lambda i: options[i])

    chosen = reports[selected_idx]
    data = get_ai_report(chosen["customer_id"], chosen["scorecard_date"])
    if data:
        st.divider()
        customer = get_customer_financials(chosen["customer_id"])["customer"]
        render_health_card(customer, data["scorecard"], data["report"])
