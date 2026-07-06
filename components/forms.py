"""Customer selection for health card generation.

The original spec's form lets a user type in a brand-new business (name,
GST, UPI ID, EPFO ID, bank ref) and generate a card for it. This POC has no
live GST/UPI/AA/EPFO data connectors -- only the customers already loaded by
the ETL Engine have real financial history in Postgres. Rather than fabricate
numbers for an arbitrary typed-in name (which the original spec's own sample
code does, via a hardcoded static scorecard), this selects among real,
already-ingested customers so "Generate Health Card" always produces genuine,
traceable output.
"""

from __future__ import annotations

from typing import Any

import streamlit as st
from sqlalchemy import text

from db.connection import get_engine


@st.cache_data(ttl=60)
def _list_customers() -> list[dict[str, Any]]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                "SELECT customer_id, business_name, sector, persona, gst_number "
                "FROM customers ORDER BY customer_id"
            )
        ).mappings().all()
    return [dict(r) for r in rows]


def customer_selector() -> str | None:
    """Render a dropdown of real, ETL-loaded customers. Returns the selected customer_id."""
    customers = _list_customers()
    if not customers:
        st.warning("No customers found. Run the ETL Engine first: `uv run python etl_engine.py`")
        return None

    def _label(customer_id: str) -> str:
        row = next(c for c in customers if c["customer_id"] == customer_id)
        return f"{customer_id} -- {row['business_name']} ({row['sector']})"

    selected = st.selectbox(
        "Select customer *",
        options=[c["customer_id"] for c in customers],
        format_func=_label,
    )

    if selected:
        row = next(c for c in customers if c["customer_id"] == selected)
        with st.expander("Customer details", expanded=False):
            st.write(f"**Business Name:** {row['business_name']}")
            st.write(f"**Sector:** {row['sector']}")
            st.write(f"**GST Number:** {row['gst_number']}")
            st.write(f"**Persona:** {row['persona']}")

    return selected
