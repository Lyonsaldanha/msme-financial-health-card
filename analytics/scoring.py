"""Dimension scoring, composite score, and red/green flag rules.

Pure functions: everything here operates on already-computed ratio dicts
(from analytics_engine's compute_*_ratios), with no database access, so the
scoring rules can be reasoned about and tested in isolation.
"""

from __future__ import annotations

WEIGHTS = {
    "aa_bank_cashflow": 0.35,
    "gst_quality": 0.25,
    "upi_behaviour": 0.20,
    "epfo_stability": 0.10,
    "compliance_bureau": 0.10,
}

# Fixed for this prototype: no credit bureau / regulatory data source exists yet.
COMPLIANCE_BUREAU_SCORE = 80

# Neutral score for GST quality when the customer is NTC (no GST data at all),
# rather than penalizing NTC status itself within a dimension meant to score filing behaviour.
GST_QUALITY_NTC_DEFAULT = 50

_INTERPRETATION_BANDS = [(85, "Excellent"), (70, "Good"), (50, "Fair"), (30, "Weak")]


def _score_high_is_good(value: float | None, tiers: list[tuple[float, int]]) -> int:
    """tiers: [(min_value, score), ...] sorted descending by min_value."""
    if value is None:
        return 0
    for min_value, score in tiers:
        if value >= min_value:
            return score
    return 0


def _score_low_is_good(value: float | None, tiers: list[tuple[float, int]]) -> int:
    """tiers: [(max_value, score), ...] sorted ascending by max_value."""
    if value is None:
        return 0
    for max_value, score in tiers:
        if value <= max_value:
            return score
    return 0


def score_dscr(dscr: float | None) -> int:
    return _score_high_is_good(dscr, [(1.75, 100), (1.25, 70), (1.0, 40)])


def score_adb_sufficiency(adb: float, avg_monthly_operating_expenses: float) -> int:
    if avg_monthly_operating_expenses <= 0:
        return 100
    expense_45_days = (avg_monthly_operating_expenses / 30) * 45
    return _score_high_is_good(adb / expense_45_days, [(1.5, 100), (1.0, 70), (0.5, 40)])


def score_cheque_returns(count: int) -> int:
    if count == 0:
        return 100
    if count == 1:
        return 60
    return 0


def score_cash_withdrawal_percent(pct: float | None) -> int:
    return _score_low_is_good(pct, [(5, 100), (15, 70)])


def score_filing_delays(delays: int | None) -> int:
    if delays is None:  # NTC customer: no GST filings to be delayed
        return 100
    if delays == 0:
        return 100
    if delays <= 2:
        return 70
    return 0


def score_revenue_cv(cv_percent: float | None) -> int:
    return _score_low_is_good(cv_percent, [(15, 100), (30, 70), (40, 40)])


def score_growth_trend(cagr_percent: float | None) -> int:
    if cagr_percent is None:
        return 70
    if cagr_percent > 1:
        return 100
    if cagr_percent < -1:
        return 0
    return 70


def score_active_days_percent(pct: float) -> int:
    return _score_high_is_good(pct, [(90, 100), (70, 70)])


def score_ticket_size_cv(cv_percent: float | None) -> int:
    return _score_low_is_good(cv_percent, [(30, 100), (50, 70)])


def score_transaction_frequency(avg_daily_transactions: float) -> int:
    """Absolute daily-transaction-count banding, standing in for a true
    sector-benchmarked frequency score (this dataset has no peer/sector table)."""
    if avg_daily_transactions >= 80:
        return 100
    if avg_daily_transactions >= 40:
        return 70
    return 0


def score_employee_growth(growth_percent: float | None) -> int:
    if growth_percent is None:
        return 70
    if growth_percent > 0:
        return 100
    if growth_percent == 0:
        return 70
    return 0


def score_contribution_timeliness(late_count: int) -> int:
    if late_count == 0:
        return 100
    if late_count <= 2:
        return 70
    return 0


def build_dimension_scores(gst_ratios: dict, upi_ratios: dict, aa_ratios: dict, epfo_ratios: dict) -> dict:
    aa_score = round(
        score_dscr(aa_ratios.get("dscr")) * 0.40
        + score_adb_sufficiency(
            aa_ratios.get("avg_daily_balance", 0), aa_ratios.get("avg_monthly_operating_expenses", 0)
        )
        * 0.30
        + score_cheque_returns(aa_ratios.get("cheque_return_count", 0)) * 0.20
        + score_cash_withdrawal_percent(aa_ratios.get("cash_withdrawal_percent")) * 0.10
    )

    if gst_ratios.get("is_gst_registered"):
        gst_score = round(
            score_filing_delays(gst_ratios.get("filing_delays")) * 0.50
            + score_revenue_cv(gst_ratios.get("cv_percent")) * 0.30
            + score_growth_trend(gst_ratios.get("cagr_percent")) * 0.20
        )
    else:
        gst_score = GST_QUALITY_NTC_DEFAULT

    avg_daily_transactions = upi_ratios.get("total_transactions", 0) / 365
    upi_score = round(
        score_active_days_percent(upi_ratios.get("active_days_percent", 0)) * 0.50
        + score_ticket_size_cv(upi_ratios.get("ticket_size_cv_percent")) * 0.30
        + score_transaction_frequency(avg_daily_transactions) * 0.20
    )

    epfo_score = round(
        score_employee_growth(epfo_ratios.get("employee_growth_percent")) * 0.50
        + score_contribution_timeliness(epfo_ratios.get("contribution_timeliness_late_count", 0)) * 0.50
    )

    return {
        "aa_bank_cashflow": aa_score,
        "gst_quality": gst_score,
        "upi_behaviour": upi_score,
        "epfo_stability": epfo_score,
        "compliance_bureau": COMPLIANCE_BUREAU_SCORE,
    }


def build_composite_score(dimension_scores: dict) -> int:
    total = sum(dimension_scores[dim] * weight for dim, weight in WEIGHTS.items())
    return round(total)


def interpret_score(score: int) -> str:
    for min_score, label in _INTERPRETATION_BANDS:
        if score >= min_score:
            return label
    return "Poor"


def build_flags(
    gst_ratios: dict, upi_ratios: dict, aa_ratios: dict, epfo_ratios: dict, cross_validation: dict
) -> tuple[list[str], list[str]]:
    red: list[str] = []
    green: list[str] = []

    dscr = aa_ratios.get("dscr")
    if dscr is not None:
        if dscr < 1.0:
            red.append(f"Weak repayment capacity (DSCR {dscr})")
        elif dscr > 1.75:
            green.append(f"Strong repayment capacity (DSCR {dscr})")

    cheque_returns = aa_ratios.get("cheque_return_count", 0)
    if cheque_returns >= 2:
        red.append(f"Liquidity stress ({cheque_returns} cheque bounces)")
    elif cheque_returns == 0:
        green.append("Zero cheque bounces")

    filing_delays = gst_ratios.get("filing_delays")
    if filing_delays is not None:
        if filing_delays >= 3:
            red.append(f"Compliance risk ({filing_delays} late GST filings)")
        elif filing_delays == 0:
            green.append("All GST filings on time")

    late_contributions = epfo_ratios.get("contribution_timeliness_late_count", 0)
    if late_contributions >= 2:
        red.append(f"Payroll stress ({late_contributions} late EPFO contributions)")

    start = epfo_ratios.get("starting_employee_count")
    end = epfo_ratios.get("ending_employee_count")
    if start is not None and end is not None and end < start:
        red.append(f"Declining employee count ({start} -> {end})")

    growth_percent = epfo_ratios.get("employee_growth_percent")
    if growth_percent is not None and growth_percent > 10:
        green.append(f"Employee growth of {growth_percent}%")

    cagr_percent = gst_ratios.get("cagr_percent")
    if cagr_percent is not None:
        if cagr_percent < -5:
            red.append(f"Revenue decline ({cagr_percent}% YoY)")
        elif cagr_percent > 5:
            green.append(f"Revenue growth of {cagr_percent}% YoY")

    if cross_validation.get("gst_vs_aa_mismatch"):
        red.append(f"Unaccounted cash flow (GST vs AA ratio {cross_validation.get('gst_vs_aa_ratio')})")

    cash_withdrawal_percent = aa_ratios.get("cash_withdrawal_percent")
    if cash_withdrawal_percent is not None and cash_withdrawal_percent > 15:
        red.append(f"High cash withdrawals ({cash_withdrawal_percent}% of collections)")

    adb = aa_ratios.get("avg_daily_balance")
    opex = aa_ratios.get("avg_monthly_operating_expenses")
    if adb is not None and opex:
        expense_60_days = (opex / 30) * 60
        if adb > expense_60_days:
            green.append("Healthy cash buffer (ADB covers 60+ days of expenses)")

    return red, green


# --- Text interpretations for the AI Engine's narrative layer ---
# Reuse the exact cutpoints from the numeric scorers above (score_dscr,
# score_revenue_cv, score_active_days_percent) so narrative prose never
# contradicts the dimension scores computed from the same ratios.


def interpret_dscr(dscr: float | None) -> str:
    if dscr is None:
        return "not available"
    if dscr >= 1.75:
        return "strong repayment capacity"
    if dscr >= 1.25:
        return "acceptable repayment capacity"
    if dscr >= 1.0:
        return "modest, borderline repayment capacity"
    return "weak repayment capacity"


def interpret_cv(cv_percent: float | None) -> str:
    if cv_percent is None:
        return "not available"
    if cv_percent < 15:
        return "very stable"
    if cv_percent < 30:
        return "normal, moderate volatility"
    if cv_percent < 40:
        return "elevated volatility"
    return "highly volatile"


def interpret_active_days(active_days_percent: float | None) -> str:
    if active_days_percent is None:
        return "not available"
    if active_days_percent >= 90:
        return "consistent, near-daily activity"
    if active_days_percent >= 70:
        return "regular but uneven activity"
    return "sparse, irregular activity"
