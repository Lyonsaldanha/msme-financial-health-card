"""Analytics Engine: computes financial ratios from normalized MSME data and
generates a multi-dimensional scorecard per customer.

Public API:
    compute_gst_ratios(customer_id) -> dict
    compute_upi_ratios(customer_id) -> dict
    compute_aa_ratios(customer_id) -> dict
    compute_epfo_ratios(customer_id) -> dict
    compute_cross_validation(customer_id) -> dict
    compute_dimension_scores(customer_id) -> dict
    compute_composite_score(customer_id) -> int
    generate_scorecard(customer_id) -> dict
    run_analytics(customer_ids=None) -> list[dict]
"""

from __future__ import annotations

import json
import logging
from datetime import date

import pandas as pd
from sqlalchemy import text

from analytics.scoring import build_composite_score, build_dimension_scores, build_flags, interpret_score
from analytics.stats_utils import cagr, coefficient_of_variation, linregress_slope, mom_growth
from db.connection import get_engine
from db.schema import create_tables

logger = logging.getLogger(__name__)

# Table names here are fixed literals controlled by this module only, never user input.
_ORDER_BY = {
    "gst_filings": "year, month",
    "upi_transactions": "txn_date",
    "bank_statements": "year, month",
    "epfo_payroll": "year, month",
}


def _fetch_df(table: str, customer_id: str) -> pd.DataFrame:
    query = text(f"SELECT * FROM {table} WHERE customer_id = :cid ORDER BY {_ORDER_BY[table]}")
    return pd.read_sql_query(query, get_engine(), params={"cid": customer_id})


def compute_gst_ratios(customer_id: str) -> dict:
    df = _fetch_df("gst_filings", customer_id)

    if df.empty:
        return {
            "is_gst_registered": False,
            "cagr_percent": None,
            "mom_growth_percent": None,
            "cv_percent": None,
            "filing_delays": None,
            "tax_payment_status": "NA",
            "itc_utilization_percent": "NA",
            "customer_concentration": "NA",
        }

    sales = df["gstr_sales_paise"] / 100
    growth = cagr(sales.iloc[0], sales.iloc[-1])
    mom = mom_growth(sales.iloc[-2], sales.iloc[-1]) if len(sales) >= 2 else None
    cv = coefficient_of_variation(sales)

    return {
        "is_gst_registered": True,
        "cagr_percent": round(growth * 100, 1) if growth is not None else None,
        "mom_growth_percent": round(mom * 100, 1) if mom is not None else None,
        "cv_percent": round(cv * 100, 1) if cv is not None else None,
        "filing_delays": int(df["is_delayed"].sum()),
        "tax_payment_status": "NA",
        "itc_utilization_percent": "NA",
        "customer_concentration": "NA",
    }


def compute_upi_ratios(customer_id: str) -> dict:
    df = _fetch_df("upi_transactions", customer_id)

    if df.empty:
        return {
            "avg_daily_collections": 0,
            "total_transactions": 0,
            "avg_ticket_size": 0,
            "active_days": 0,
            "active_days_percent": 0.0,
            "ticket_size_cv_percent": None,
            "repeat_customer_rate": "NA",
            "weekend_weekday_ratio": None,
        }

    collections = df["collections_paise"] / 100
    tickets = df["avg_ticket_size_paise"] / 100
    is_weekend = df["day_of_week"].isin(["Saturday", "Sunday"])

    weekend_avg = collections[is_weekend].mean() if is_weekend.any() else None
    weekday_avg = collections[~is_weekend].mean() if (~is_weekend).any() else None
    ratio = round(weekend_avg / weekday_avg, 2) if weekend_avg is not None and weekday_avg else None

    active_days = int((collections > 0).sum())
    ticket_cv = coefficient_of_variation(tickets)

    return {
        "avg_daily_collections": round(collections.mean()),
        "total_transactions": int(df["num_transactions"].sum()),
        "avg_ticket_size": round(tickets.mean()),
        "active_days": active_days,
        "active_days_percent": round(active_days / 365 * 100, 1),
        "ticket_size_cv_percent": round(ticket_cv * 100, 1) if ticket_cv is not None else None,
        "repeat_customer_rate": "NA",
        "weekend_weekday_ratio": ratio,
    }


def compute_aa_ratios(customer_id: str) -> dict:
    df = _fetch_df("bank_statements", customer_id)
    if df.empty:
        return {}

    credits = df["total_credits_paise"] / 100
    surplus = df["operating_surplus_paise"] / 100
    adb = df["avg_daily_balance_paise"] / 100
    emi = df["existing_emi_paise"] / 100
    withdrawals = df["cash_withdrawals_paise"] / 100
    operating_expenses = df["operating_expenses_paise"] / 100

    avg_credits = credits.mean()
    credits_cv = coefficient_of_variation(credits)

    return {
        "avg_monthly_credits": round(avg_credits),
        "monthly_credits_trend_slope": round(linregress_slope(credits), 2),
        "monthly_credits_volatility_percent": round(credits_cv * 100, 1) if credits_cv is not None else None,
        "avg_daily_balance": round(adb.mean()),
        "avg_monthly_operating_expenses": round(operating_expenses.mean()),
        "cash_conversion_ratio": round(surplus.mean() / avg_credits, 2) if avg_credits else None,
        # DSCR arrives pre-computed per the AA feed; we validate/aggregate it, not recompute it,
        # since the proposed-EMI component it depends on isn't available at record level.
        "dscr": round(df["dscr"].mean(), 2),
        "existing_debt_total_annual": round(emi.sum()),
        "existing_debt_avg_monthly": round(emi.mean()),
        "existing_debt_instrument_count": "NA",
        "cheque_return_count": int(df["cheque_returns"].sum()),
        "cash_withdrawal_percent": round(withdrawals.mean() / avg_credits * 100, 1) if avg_credits else None,
        "days_sales_outstanding": "NA",
    }


def compute_epfo_ratios(customer_id: str) -> dict:
    df = _fetch_df("epfo_payroll", customer_id)
    if df.empty:
        return {}

    employee_counts = df["employee_count"]
    payroll = df["monthly_payroll_paise"] / 100
    wages = df["avg_wage_paise"] / 100

    start_count = int(employee_counts.iloc[0])
    end_count = int(employee_counts.iloc[-1])
    growth_percent = round((end_count - start_count) / start_count * 100, 1) if start_count else None
    wage_inflation = (
        round((wages.iloc[-1] - wages.iloc[0]) / wages.iloc[0] * 100, 1) if wages.iloc[0] else None
    )
    avg_employee_count = employee_counts.mean()
    churn_rate = (
        round(df["employee_churn"].sum() / (12 * avg_employee_count), 4) if avg_employee_count else None
    )

    return {
        "starting_employee_count": start_count,
        "ending_employee_count": end_count,
        "employee_growth_percent": growth_percent,
        "avg_employee_count": round(avg_employee_count, 1),
        "employee_count_trend_slope": round(linregress_slope(employee_counts), 3),
        "avg_monthly_payroll": round(payroll.mean()),
        "monthly_payroll_variance": round(payroll.std(ddof=1), 2) if len(payroll) > 1 else 0.0,
        "avg_wage": round(wages.mean()),
        "wage_inflation_percent": wage_inflation,
        "contribution_timeliness_late_count": int(df["is_late_contribution"].sum()),
        "employee_churn_rate": churn_rate,
    }


def compute_cross_validation(customer_id: str) -> dict:
    gst_df = _fetch_df("gst_filings", customer_id)
    aa_df = _fetch_df("bank_statements", customer_id)
    upi_df = _fetch_df("upi_transactions", customer_id)
    epfo_df = _fetch_df("epfo_payroll", customer_id)

    avg_gst_sales = (gst_df["gstr_sales_paise"] / 100).mean() if not gst_df.empty else None
    avg_aa_credits = (aa_df["total_credits_paise"] / 100).mean() if not aa_df.empty else None
    avg_upi_monthly = (upi_df["collections_paise"] / 100).mean() * 30 if not upi_df.empty else None
    avg_aa_payroll = (aa_df["payroll_paid_paise"] / 100).mean() if not aa_df.empty else None
    avg_epfo_payroll = (epfo_df["monthly_payroll_paise"] / 100).mean() if not epfo_df.empty else None

    def ratio_and_flag(numerator: float | None, denominator: float | None) -> tuple[float | None, bool | None]:
        if not numerator or not denominator:
            return None, None
        r = round(numerator / denominator, 2)
        return r, bool(r > 1.5 or r < 0.5)

    gst_vs_aa_ratio, gst_vs_aa_mismatch = ratio_and_flag(avg_gst_sales, avg_aa_credits)
    gst_vs_upi_ratio, gst_vs_upi_mismatch = ratio_and_flag(avg_gst_sales, avg_upi_monthly)
    aa_payroll_vs_epfo_ratio, aa_payroll_vs_epfo_mismatch = ratio_and_flag(avg_aa_payroll, avg_epfo_payroll)
    upi_vs_aa_ratio, upi_vs_aa_mismatch = ratio_and_flag(avg_upi_monthly, avg_aa_credits)

    gst_growth = cagr(gst_df["gstr_sales_paise"].iloc[0], gst_df["gstr_sales_paise"].iloc[-1]) if len(gst_df) >= 2 else None
    employee_growth = (
        (epfo_df["employee_count"].iloc[-1] - epfo_df["employee_count"].iloc[0]) / epfo_df["employee_count"].iloc[0]
        if not epfo_df.empty and epfo_df["employee_count"].iloc[0]
        else None
    )
    if gst_growth is None or employee_growth is None:
        growth_alignment = "NA"
    elif (gst_growth >= 0) == (employee_growth >= 0):
        growth_alignment = "aligned"
    else:
        growth_alignment = "misaligned"

    return {
        "gst_vs_aa_ratio": gst_vs_aa_ratio,
        "gst_vs_aa_mismatch": gst_vs_aa_mismatch,
        "gst_vs_upi_ratio": gst_vs_upi_ratio,
        "gst_vs_upi_mismatch": gst_vs_upi_mismatch,
        "aa_payroll_vs_epfo_payroll_ratio": aa_payroll_vs_epfo_ratio,
        "aa_payroll_vs_epfo_payroll_mismatch": aa_payroll_vs_epfo_mismatch,
        "upi_vs_aa_credits_ratio": upi_vs_aa_ratio,
        "upi_vs_aa_credits_mismatch": upi_vs_aa_mismatch,
        "gst_growth_vs_employee_growth": growth_alignment,
    }


def compute_dimension_scores(customer_id: str) -> dict:
    return build_dimension_scores(
        compute_gst_ratios(customer_id),
        compute_upi_ratios(customer_id),
        compute_aa_ratios(customer_id),
        compute_epfo_ratios(customer_id),
    )


def compute_composite_score(customer_id: str) -> int:
    return build_composite_score(compute_dimension_scores(customer_id))


def generate_scorecard(customer_id: str) -> dict:
    gst_ratios = compute_gst_ratios(customer_id)
    upi_ratios = compute_upi_ratios(customer_id)
    aa_ratios = compute_aa_ratios(customer_id)
    epfo_ratios = compute_epfo_ratios(customer_id)
    cross_validation = compute_cross_validation(customer_id)

    dimension_scores = build_dimension_scores(gst_ratios, upi_ratios, aa_ratios, epfo_ratios)
    composite_score = build_composite_score(dimension_scores)
    red_flags, green_flags = build_flags(gst_ratios, upi_ratios, aa_ratios, epfo_ratios, cross_validation)

    return {
        "customer_id": customer_id,
        "scorecard_date": date.today().isoformat(),
        "gst_ratios": gst_ratios,
        "upi_ratios": upi_ratios,
        "aa_ratios": aa_ratios,
        "epfo_ratios": epfo_ratios,
        "cross_validation": cross_validation,
        "dimension_scores": dimension_scores,
        "composite_score": composite_score,
        "score_interpretation": interpret_score(composite_score),
        "red_flags": red_flags,
        "green_flags": green_flags,
    }


def _save_scorecard(scorecard: dict) -> None:
    engine = get_engine()
    # scorecard_json is JSONB on Postgres (needs an explicit cast from the bound
    # text parameter) but plain TEXT on SQLite (no JSONB type there -- see
    # db/schema_sqlite.sql); the value itself is the same json.dumps() string either way.
    json_expr = ":scorecard_json" if engine.dialect.name == "sqlite" else "CAST(:scorecard_json AS JSONB)"
    with engine.begin() as conn:
        conn.execute(
            text(
                f"""
                INSERT INTO scorecards (customer_id, scorecard_date, scorecard_json, composite_score)
                VALUES (:customer_id, :scorecard_date, {json_expr}, :composite_score)
                ON CONFLICT (customer_id, scorecard_date) DO UPDATE SET
                    scorecard_json = EXCLUDED.scorecard_json,
                    composite_score = EXCLUDED.composite_score
                """
            ),
            {
                "customer_id": scorecard["customer_id"],
                "scorecard_date": scorecard["scorecard_date"],
                "scorecard_json": json.dumps(scorecard),
                "composite_score": scorecard["composite_score"],
            },
        )


def _all_customer_ids() -> list[str]:
    with get_engine().connect() as conn:
        rows = conn.execute(text("SELECT customer_id FROM customers ORDER BY customer_id")).all()
    return [r[0] for r in rows]


def run_analytics(customer_ids: list[str] | None = None) -> list[dict]:
    """Generate and persist scorecards for the given customers (or all customers)."""
    create_tables()
    ids = customer_ids if customer_ids else _all_customer_ids()

    scorecards = []
    for customer_id in ids:
        scorecard = generate_scorecard(customer_id)
        _save_scorecard(scorecard)
        scorecards.append(scorecard)
        logger.info(
            "Scorecard for %s: composite=%d (%s)",
            customer_id,
            scorecard["composite_score"],
            scorecard["score_interpretation"],
        )

    return scorecards


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for card in run_analytics():
        print(
            f"{card['customer_id']}: composite={card['composite_score']} "
            f"({card['score_interpretation']}) red_flags={len(card['red_flags'])} "
            f"green_flags={len(card['green_flags'])}"
        )
