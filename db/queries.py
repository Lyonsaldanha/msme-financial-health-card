"""Read-side helpers for querying a customer's normalized financial footprint."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text

from db.connection import get_engine, parse_json_field

# Table names here are fixed literals controlled by this module only, never user input.
_CHILD_TABLES = (
    ("gst_filings", "year, month"),
    ("upi_transactions", "txn_date"),
    ("bank_statements", "year, month"),
    ("epfo_payroll", "year, month"),
)


def get_customer_financials(customer_id: str) -> dict[str, Any]:
    """Fetch a customer record plus all linked GST/UPI/AA/EPFO rows."""
    with get_engine().connect() as conn:
        customer = conn.execute(
            text("SELECT * FROM customers WHERE customer_id = :cid"),
            {"cid": customer_id},
        ).mappings().first()
        if customer is None:
            raise ValueError(f"Unknown customer_id: {customer_id}")

        financials: dict[str, Any] = {"customer": dict(customer)}
        for table, order_by in _CHILD_TABLES:
            rows = conn.execute(
                text(f"SELECT * FROM {table} WHERE customer_id = :cid ORDER BY {order_by}"),
                {"cid": customer_id},
            ).mappings().all()
            financials[table] = [dict(r) for r in rows]

        return financials


def list_ai_reports(limit: int | None = None) -> list[dict[str, Any]]:
    """List generated reports (newest first) joined with customer master fields,
    for the Streamlit 'view reports' pages."""
    # composite_score lives on scorecards, not ai_reports -- join both.
    query = """
        SELECT r.customer_id, c.business_name, c.sector, r.scorecard_date,
               s.composite_score, r.generation_method, r.generated_at
        FROM ai_reports r
        JOIN customers c ON c.customer_id = r.customer_id
        JOIN scorecards s ON s.customer_id = r.customer_id AND s.scorecard_date = r.scorecard_date
        ORDER BY r.generated_at DESC
    """
    if limit is not None:
        query += " LIMIT :limit"

    with get_engine().connect() as conn:
        rows = conn.execute(text(query), {"limit": limit} if limit is not None else {}).mappings().all()
    return [dict(r) for r in rows]


def get_ai_report(customer_id: str, scorecard_date: Any) -> dict[str, Any] | None:
    """Fetch one full report_json + its paired scorecard_json for a customer/date."""
    with get_engine().connect() as conn:
        row = conn.execute(
            text(
                """
                SELECT r.report_json, s.scorecard_json
                FROM ai_reports r
                JOIN scorecards s ON s.customer_id = r.customer_id AND s.scorecard_date = r.scorecard_date
                WHERE r.customer_id = :cid AND r.scorecard_date = :sdate
                """
            ),
            {"cid": customer_id, "sdate": scorecard_date},
        ).first()
    if row is None:
        return None
    return {"report": parse_json_field(row.report_json), "scorecard": parse_json_field(row.scorecard_json)}
