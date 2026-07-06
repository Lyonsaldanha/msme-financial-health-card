"""Deterministic chart config assembly.

Every number in every chart config comes straight from the database via
plain aggregation -- the LLM never sees or produces this. Asking a model to
faithfully reproduce a numeric array is the single highest hallucination-risk
operation you could hand it, and the scorecard doesn't even carry the raw
monthly series a trend chart needs (only aggregates like CAGR/CV) -- so it
couldn't come from the LLM's stated input regardless. See ai_engine.py's
module docstring for the fuller rationale.

No pie chart: the two natural pie candidates (revenue concentration, debt
composition) both require data this dataset doesn't have at instrument/payer
granularity (customer_concentration is explicitly "NA"; existing_emi is a
single aggregate, not itemized facilities) -- fabricating slices to fill a
pie would violate the "no synthetic data" rule as surely as an invented
narrative claim would.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd


def _month_label(year: int, month: int) -> str:
    return date(year, month, 1).strftime("%b %Y")


def _paise_to_rupees(paise: int) -> float:
    return round(paise / 100, 2)


def _composite_score_gauge(scorecard: dict) -> dict:
    return {
        "type": "gauge",
        "title": "Composite Financial Health Score",
        "data_value": scorecard["composite_score"],
        "min": 0,
        "max": 100,
        "thresholds": {"red": [0, 40], "yellow": [40, 70], "green": [70, 100]},
        "source": "Analytics Engine - Composite Score",
    }


def _dimension_scores_bar(scorecard: dict) -> dict:
    dims = scorecard["dimension_scores"]
    return {
        "type": "bar",
        "title": "Dimension Scores",
        "categories": list(dims.keys()),
        "data": list(dims.values()),
        "source": "Analytics Engine - Dimension Scores",
    }


def _revenue_trend_line(gst_rows: list[dict], upi_rows: list[dict]) -> dict | None:
    if gst_rows:
        rows = sorted(gst_rows, key=lambda r: (r["year"], r["month"]))
        return {
            "type": "line",
            "title": "GST Monthly Revenue Trend (₹)",
            "x_key": "month",
            "y_key": "gst_sales",
            "data": [
                {"month": _month_label(r["year"], r["month"]), "value": _paise_to_rupees(r["gstr_sales_paise"])}
                for r in rows
            ],
            "source": "GST Analytics Engine",
        }

    if not upi_rows:
        return None

    upi_df = pd.DataFrame(upi_rows)
    upi_df["txn_date"] = pd.to_datetime(upi_df["txn_date"])
    monthly = upi_df.groupby(upi_df["txn_date"].dt.to_period("M"))["collections_paise"].sum()
    return {
        "type": "line",
        "title": "UPI Monthly Collections Trend (₹)",
        "x_key": "month",
        "y_key": "upi_collections",
        "data": [
            {"month": period.strftime("%b %Y"), "value": _paise_to_rupees(int(total))}
            for period, total in monthly.items()
        ],
        "source": "UPI Analytics Engine (no GST data available for this customer)",
    }


def _employee_count_line(epfo_rows: list[dict]) -> dict | None:
    if not epfo_rows:
        return None
    rows = sorted(epfo_rows, key=lambda r: (r["year"], r["month"]))
    return {
        "type": "line",
        "title": "Employee Count Trend",
        "x_key": "month",
        "y_key": "employee_count",
        "data": [{"month": _month_label(r["year"], r["month"]), "value": r["employee_count"]} for r in rows],
        "source": "EPFO Analytics Engine",
    }


def _cross_validation_table(cross_validation: dict) -> dict:
    def flag_text(mismatch: bool | None) -> str:
        if mismatch is None:
            return "NA"
        return "⚠️ Mismatch" if mismatch else "✅ Aligned"

    rows = [
        ["GST vs Bank Credits", cross_validation["gst_vs_aa_ratio"], flag_text(cross_validation["gst_vs_aa_mismatch"])],
        ["GST vs UPI Collections", cross_validation["gst_vs_upi_ratio"], flag_text(cross_validation["gst_vs_upi_mismatch"])],
        [
            "AA Payroll vs EPFO Payroll",
            cross_validation["aa_payroll_vs_epfo_payroll_ratio"],
            flag_text(cross_validation["aa_payroll_vs_epfo_payroll_mismatch"]),
        ],
        ["UPI vs AA Credits", cross_validation["upi_vs_aa_credits_ratio"], flag_text(cross_validation["upi_vs_aa_credits_mismatch"])],
    ]
    return {
        "type": "table",
        "title": "Cross-Validation: Data Source Reconciliation",
        "columns": ["Metric", "Ratio", "Status"],
        "rows": [[label, ratio if ratio is not None else "NA", status] for label, ratio, status in rows],
        "source": "Cross-Validation Analytics",
    }


def build_chart_configs(
    scorecard: dict[str, Any],
    gst_rows: list[dict],
    upi_rows: list[dict],
    epfo_rows: list[dict],
) -> list[dict]:
    charts = [
        _composite_score_gauge(scorecard),
        _dimension_scores_bar(scorecard),
        _cross_validation_table(scorecard["cross_validation"]),
    ]

    revenue_chart = _revenue_trend_line(gst_rows, upi_rows)
    if revenue_chart:
        charts.append(revenue_chart)

    employee_chart = _employee_count_line(epfo_rows)
    if employee_chart:
        charts.append(employee_chart)

    return charts
