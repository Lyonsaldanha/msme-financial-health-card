"""Hardcoded system prompt and the dynamic user prompt template (Augmentation step).

The system prompt is scoped to narrative-only output: chart configs are built
deterministically in ai/charts.py rather than asked of the model, so the
prompt doesn't ask for (or promise) chart JSON -- see ai_engine.py's module
docstring for why.
"""

from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You are a financial analyst assistant. Your job is to write clear, factual narratives about MSME financial health based ONLY on data provided.

CRITICAL RULES:
1. NEVER invent data or ratios not provided in the facts
2. NEVER make assumptions about customer intent or behavior
3. EVERY statement MUST be backed by a number or fact in the input
4. Use conditional language: "shows", "indicates", "suggests" (avoid absolute claims)
5. Cite data source for each claim: "(per GST data)", "(per bank statements)", "(per UPI data)", "(per EPFO data)"
6. Be concise: 2-3 sentences per section max
7. If a fact is marked "NA", do not discuss it and do not guess a value for it
8. Respond with the narrative fields only -- do not include chart data or numeric arrays"""


def build_user_prompt(facts: dict[str, Any]) -> str:
    """Inject retrieved facts into the report-generation prompt template."""
    gst_section = (
        f"""GST ANALYSIS:
- Monthly Turnover Range: ₹{facts['gst_min']}L–₹{facts['gst_max']}L
- Growth Trend: {facts['gst_growth']}% YoY
- Revenue Stability (CV): {facts['gst_cv']}% → {facts['cv_interpretation']}
- Filing Timeliness: {facts['gst_filing_delays']} late filings (0 is excellent)"""
        if facts["is_gst_registered"]
        else "GST ANALYSIS:\n- Not GST-registered (New-to-Credit customer) -- no GST data available"
    )

    return f"""Generate a financial health report for this MSME. Use ONLY these facts:

Customer: {facts['customer_name']} | {facts['sector']} | GST: {facts['gst_number']}

FINANCIAL METRICS:
- Composite Score: {facts['composite_score']}/100 → {facts['score_interpretation']}
- Business Health: Based on {facts['months']} months of transaction history ending {facts['scorecard_date']}

{gst_section}

UPI ANALYSIS:
- Average Daily Collections: ₹{facts['upi_avg_daily']}
- Transaction Frequency: {facts['upi_transactions_count']} total transactions
- Active Days: {facts['upi_active_days']}/365 days
- Transaction Pattern: {facts['upi_pattern_interpretation']}

BANK STATEMENT ANALYSIS:
- Average Monthly Credits: ₹{facts['aa_avg_credits']}L
- Average Daily Balance: ₹{facts['aa_adb']}L
- DSCR: {facts['dscr']} → {facts['dscr_interpretation']}
- Cheque Returns: {facts['cheque_returns']} (0 is excellent)
- Cash Withdrawal %: {facts['cash_withdrawal_pct']}% of inflows

PAYROLL ANALYSIS:
- Employee Count Growth: {facts['employee_growth']}% YoY
- Average Monthly Payroll: ₹{facts['payroll_avg']}
- Contribution Timeliness: {facts['epfo_delays']} late payments (0 is excellent)

CROSS-VALIDATION:
- GST vs Bank Credits Ratio: {facts['gst_aa_ratio']}
- GST vs UPI Ratio: {facts['gst_upi_ratio']}
{facts['cross_validation_flags']}

RISK INDICATORS:
{facts['red_flags_list']}

STRENGTH INDICATORS:
{facts['green_flags_list']}

Generate:
1. Executive summary (2 sentences)
2. Financial health assessment (2 sentences)
3. Key strengths (2-3 bullet points)
4. Key risks (2-3 bullet points)
5. Recommended next steps (1-2 sentences)

Remember: Only use facts provided above. Cite data source for each claim."""
