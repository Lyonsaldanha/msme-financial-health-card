"""Read-only raw source data viewer -- lets a user inspect the GST/UPI/AA/EPFO
rows behind a customer's health card without editing them. Collapsed by
default so it doesn't clutter the generate/report flow; the user opts in by
clicking to expand it.
"""

from __future__ import annotations

import streamlit as st

from db import get_customer_financials

_TABS = (
    ("gst_filings", "GST Filings"),
    ("upi_transactions", "UPI Transactions"),
    ("bank_statements", "Bank Statements (AA)"),
    ("epfo_payroll", "EPFO Payroll"),
)


def render_raw_data_viewer(customer_id: str) -> None:
    """Collapsed-by-default expander with one read-only tab per data source.

    Uses st.dataframe (not st.data_editor) throughout -- viewing only, no
    editing is possible by construction, not just by convention.
    """
    with st.expander("View Raw Source Data", expanded=False):
        financials = get_customer_financials(customer_id)
        tabs = st.tabs([title for _, title in _TABS])
        for tab, (table, title) in zip(tabs, _TABS):
            with tab:
                rows = financials[table]
                if not rows:
                    st.caption(f"No {title.lower()} records for this customer.")
                    continue
                st.dataframe(rows, hide_index=True, width="stretch")
                st.caption(f"{len(rows)} record(s)")
