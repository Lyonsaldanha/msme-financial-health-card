"""Deterministic, non-LLM narrative built directly from facts.

Used when Gemini is unavailable, over quota, times out, or returns something
that fails schema validation -- the report pipeline always produces a usable
narrative, never a hard failure, per the spec's error-handling requirements.
Every sentence here follows the same source-citation rule the LLM is asked to
follow, just assembled with plain string formatting instead of a model.
"""

from __future__ import annotations

from typing import Any

from ai.schemas import NarrativeReport


def build_fallback_narrative(facts: dict[str, Any]) -> NarrativeReport:
    summary = (
        f"{facts['customer_name']} ({facts['sector']}) has a composite financial health score of "
        f"{facts['composite_score']}/100, rated {facts['score_interpretation']} (per Analytics Engine)."
    )

    if facts["dscr"] != "NA":
        financial_health = (
            f"Based on {facts['months']} months of transaction history, DSCR is {facts['dscr']}, indicating "
            f"{facts['dscr_interpretation']} (per bank statements)."
        )
    else:
        financial_health = (
            f"Based on {facts['months']} months of transaction history, bank statement (AA) data is not "
            "available for this customer."
        )
    if facts["is_gst_registered"] and facts["gst_cv"] != "NA":
        financial_health += (
            f" GST revenue volatility (CV={facts['gst_cv']}%) shows {facts['cv_interpretation']} (per GST data)."
        )

    strengths = [f"{flag} (per Analytics Engine flags)" for flag in facts["green_flags"]]
    if not strengths:
        strengths = ["No specific strengths flagged by Analytics Engine for this period"]

    risks = [f"{flag} (per Analytics Engine flags)" for flag in facts["red_flags"]]
    if not risks:
        risks = ["No specific risks flagged by Analytics Engine for this period"]

    if facts["red_flags"]:
        recommendations = (
            "Recommend reviewing the flagged risk indicators above with the customer before proceeding "
            "(per Analytics Engine risk flags)."
        )
    else:
        recommendations = (
            "No red flags recorded; standard periodic monitoring is sufficient (per Analytics Engine)."
        )

    return NarrativeReport(
        summary=summary,
        financial_health=financial_health,
        strengths=strengths,
        risks=risks,
        recommendations=recommendations,
    )
