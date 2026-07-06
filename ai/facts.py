"""Retrieval step: pull and format the facts the LLM (and the deterministic
fallback) are allowed to talk about.

Every value here traces to either the scorecard (Analytics Engine output) or
a direct, unmodified read of the customer's master/raw records -- never a
model-invented number. The scorecard alone doesn't carry the customer's
business_name/sector/gst_number, or raw monthly GST figures needed for a
turnover range, so those are passed in separately from a light DB read; see
ai_engine.py for where they come from.
"""

from __future__ import annotations

from typing import Any

from analytics.scoring import interpret_active_days, interpret_cv, interpret_dscr

_PAISE_PER_LAKH = 100 * 100_000  # rupees-per-lakh * paise-per-rupee


def _paise_to_lakhs(paise: int) -> float:
    return round(paise / _PAISE_PER_LAKH, 2)


def _rupees_to_lakhs(rupees: float) -> float:
    return round(rupees / 100_000, 2)


def _format_flags(flags: list[str]) -> str:
    return "\n".join(f"- {flag}" for flag in flags) if flags else "None recorded"


def _format_cross_validation_flags(cross_validation: dict) -> str:
    mismatches = []
    if cross_validation.get("gst_vs_aa_mismatch"):
        mismatches.append(f"GST vs AA credits mismatch (ratio {cross_validation.get('gst_vs_aa_ratio')})")
    if cross_validation.get("gst_vs_upi_mismatch"):
        mismatches.append(f"GST vs UPI mismatch (ratio {cross_validation.get('gst_vs_upi_ratio')})")
    if cross_validation.get("aa_payroll_vs_epfo_payroll_mismatch"):
        mismatches.append(
            f"AA payroll vs EPFO payroll mismatch (ratio {cross_validation.get('aa_payroll_vs_epfo_payroll_ratio')})"
        )
    if cross_validation.get("upi_vs_aa_credits_mismatch"):
        mismatches.append(f"UPI vs AA credits mismatch (ratio {cross_validation.get('upi_vs_aa_credits_ratio')})")
    if not mismatches:
        return "- No cross-validation mismatches detected"
    return "\n".join(f"- {m}" for m in mismatches)


def retrieve_facts(scorecard: dict[str, Any], customer: dict[str, Any], gst_rows: list[dict]) -> dict[str, Any]:
    """Extract and format every fact the prompt template / fallback narrative may cite."""
    gst = scorecard["gst_ratios"]
    upi = scorecard["upi_ratios"]
    aa = scorecard["aa_ratios"]
    epfo = scorecard["epfo_ratios"]
    cross = scorecard["cross_validation"]

    if gst["is_gst_registered"] and gst_rows:
        monthly_sales_lakhs = [_paise_to_lakhs(row["gstr_sales_paise"]) for row in gst_rows]
        gst_min, gst_max = min(monthly_sales_lakhs), max(monthly_sales_lakhs)
    else:
        gst_min = gst_max = "NA"

    months = len({(row["year"], row["month"]) for row in gst_rows}) or 12

    return {
        "customer_id": scorecard["customer_id"],
        "customer_name": customer["business_name"],
        "sector": customer["sector"],
        "gst_number": customer["gst_number"],
        "scorecard_date": scorecard["scorecard_date"],
        "months": months,
        "composite_score": scorecard["composite_score"],
        "score_interpretation": scorecard["score_interpretation"],
        # GST
        "is_gst_registered": gst["is_gst_registered"],
        "gst_min": gst_min,
        "gst_max": gst_max,
        "gst_growth": gst["cagr_percent"] if gst["cagr_percent"] is not None else "NA",
        "gst_cv": gst["cv_percent"] if gst["cv_percent"] is not None else "NA",
        "cv_interpretation": interpret_cv(gst["cv_percent"]),
        "gst_filing_delays": gst["filing_delays"] if gst["filing_delays"] is not None else "NA",
        # UPI
        "upi_avg_daily": upi["avg_daily_collections"],
        "upi_transactions_count": upi["total_transactions"],
        "upi_active_days": upi["active_days"],
        "upi_pattern_interpretation": interpret_active_days(upi["active_days_percent"]),
        # AA / bank
        "aa_avg_credits": _rupees_to_lakhs(aa["avg_monthly_credits"]),
        "aa_adb": _rupees_to_lakhs(aa["avg_daily_balance"]),
        "dscr": aa["dscr"],
        "dscr_interpretation": interpret_dscr(aa["dscr"]),
        "cheque_returns": aa["cheque_return_count"],
        "cash_withdrawal_pct": aa["cash_withdrawal_percent"],
        # EPFO
        "employee_growth": epfo["employee_growth_percent"] if epfo["employee_growth_percent"] is not None else "NA",
        "payroll_avg": epfo["avg_monthly_payroll"],
        "epfo_delays": epfo["contribution_timeliness_late_count"],
        # Cross-validation
        "gst_aa_ratio": cross["gst_vs_aa_ratio"] if cross["gst_vs_aa_ratio"] is not None else "NA",
        "gst_upi_ratio": cross["gst_vs_upi_ratio"] if cross["gst_vs_upi_ratio"] is not None else "NA",
        "cross_validation_flags": _format_cross_validation_flags(cross),
        # Flags
        "red_flags": scorecard["red_flags"],
        "green_flags": scorecard["green_flags"],
        "red_flags_list": _format_flags(scorecard["red_flags"]),
        "green_flags_list": _format_flags(scorecard["green_flags"]),
    }


def count_cited_ratios(facts: dict[str, Any]) -> int:
    """How many distinct numeric/NA facts were made available to the model -- computed
    from what we handed it, not something the model self-reports (which would itself
    be an unverifiable claim)."""
    ratio_keys = [
        "gst_growth", "gst_cv", "gst_filing_delays", "upi_avg_daily", "upi_transactions_count",
        "upi_active_days", "aa_avg_credits", "aa_adb", "dscr", "cheque_returns",
        "cash_withdrawal_pct", "employee_growth", "payroll_avg", "epfo_delays",
        "gst_aa_ratio", "gst_upi_ratio",
    ]
    return sum(1 for key in ratio_keys if facts.get(key) not in (None, "NA"))
