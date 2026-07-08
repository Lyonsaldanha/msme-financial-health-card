"""AI Engine: generates audit-safe financial narratives and chart configs from
Analytics Engine scorecards, using Gemini for the prose only.

Design deviations from the original prompt, and why:

1. **Chart configs (including all numeric data) are built deterministically in
   ai/charts.py, never asked of the LLM.** Reproducing a numeric array
   faithfully is the highest-hallucination-risk thing you can ask a model to
   do, and the scorecard doesn't even carry the raw monthly series a trend
   chart needs (only aggregates like CAGR/CV) -- so it isn't derivable from
   the stated "Scorecard JSON" input regardless of model behaviour. The LLM's
   role here is narrowed to exactly what benefits from natural language: the
   narrative prose.
2. **The prompt needs customer_name/sector/gst_number, which aren't in the
   scorecard.** These are read directly from the `customers` table via the
   scorecard's own customer_id -- still 100% real, unmodified data, just
   acknowledging the scorecard alone can't label a report.
3. **Uses the current `google-genai` SDK**, not the legacy
   `google.generativeai` shown in the original prompt's sample code (Google is
   sunsetting the legacy package). `response_schema=NarrativeReport` lets the
   SDK validate and parse the model's JSON itself.
4. **`audit_trail` counts (ratios_cited, total_claims) are computed by this
   code from what was actually handed to/returned by the model**, not
   self-reported by the LLM -- an LLM counting its own citations is itself an
   unverifiable claim.

Public API:
    AIEngine.retrieve_facts(scorecard) -> dict
    AIEngine.augment_prompt(facts) -> str
    AIEngine.generate_report(scorecard) -> dict
    AIEngine.generate_all_reports(scorecards) -> list[dict]
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from ai.charts import build_chart_configs
from ai.client import call_gemini
from ai.facts import count_cited_ratios, retrieve_facts as _retrieve_facts
from ai.fallback import build_fallback_narrative
from ai.prompts import SYSTEM_PROMPT, build_user_prompt
from db.connection import get_engine, parse_json_field
from db.schema import create_tables

logger = logging.getLogger(__name__)

_REQUIRED_SCORECARD_FIELDS = (
    "customer_id", "scorecard_date", "gst_ratios", "upi_ratios", "aa_ratios",
    "epfo_ratios", "cross_validation", "dimension_scores", "composite_score",
    "score_interpretation", "red_flags", "green_flags",
)


def _validate_scorecard(scorecard: dict[str, Any]) -> None:
    missing = [f for f in _REQUIRED_SCORECARD_FIELDS if f not in scorecard]
    if missing:
        raise ValueError(f"Scorecard is missing required field(s): {missing}")


class AIEngine:
    """AI Engine for financial report generation."""

    def __init__(self) -> None:
        self.system_prompt = SYSTEM_PROMPT

    def _fetch_customer(self, customer_id: str) -> dict[str, Any]:
        with get_engine().connect() as conn:
            row = conn.execute(
                text("SELECT business_name, sector, gst_number FROM customers WHERE customer_id = :cid"),
                {"cid": customer_id},
            ).mappings().first()
        if row is None:
            raise ValueError(f"Unknown customer_id: {customer_id}")
        return dict(row)

    def _fetch_monthly_rows(self, table: str, order_by: str, customer_id: str) -> list[dict]:
        with get_engine().connect() as conn:
            rows = conn.execute(
                text(f"SELECT * FROM {table} WHERE customer_id = :cid ORDER BY {order_by}"),
                {"cid": customer_id},
            ).mappings().all()
        return [dict(r) for r in rows]

    def retrieve_facts(self, scorecard: dict[str, Any]) -> dict[str, Any]:
        """Extract and format the facts the model (and fallback) may cite from a scorecard."""
        _validate_scorecard(scorecard)
        customer_id = scorecard["customer_id"]
        customer = self._fetch_customer(customer_id)
        gst_rows = self._fetch_monthly_rows("gst_filings", "year, month", customer_id)
        return _retrieve_facts(scorecard, customer, gst_rows)

    def augment_prompt(self, facts: dict[str, Any]) -> str:
        """Inject retrieved facts into the report-generation prompt template."""
        return build_user_prompt(facts)

    def generate_report(self, scorecard: dict[str, Any]) -> dict[str, Any]:
        """Full pipeline: scorecard -> facts -> prompt -> LLM (or fallback) -> report."""
        _validate_scorecard(scorecard)
        customer_id = scorecard["customer_id"]
        customer = self._fetch_customer(customer_id)

        gst_rows = self._fetch_monthly_rows("gst_filings", "year, month", customer_id)
        upi_rows = self._fetch_monthly_rows("upi_transactions", "txn_date", customer_id)
        epfo_rows = self._fetch_monthly_rows("epfo_payroll", "year, month", customer_id)

        facts = _retrieve_facts(scorecard, customer, gst_rows)
        user_prompt = self.augment_prompt(facts)

        narrative = call_gemini(self.system_prompt, user_prompt)
        generation_method = "gemini"
        if narrative is None:
            narrative = build_fallback_narrative(facts)
            generation_method = "fallback"

        chart_configs = build_chart_configs(scorecard, gst_rows, upi_rows, epfo_rows)

        total_claims = 2 + len(narrative.strengths) + len(narrative.risks) + 1  # summary + health + bullets + recommendations

        report = {
            "customer_id": customer_id,
            "business_name": customer["business_name"],
            "sector": customer["sector"],
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "generation_method": generation_method,
            "narrative": narrative.model_dump(),
            "chart_configs": chart_configs,
            "audit_trail": {
                "scorecard_date": scorecard["scorecard_date"],
                "data_sources_used": [
                    src for src, available in [
                        ("GST", facts["is_gst_registered"]),
                        ("UPI", True),
                        ("AA", facts["is_aa_available"]),
                        ("EPFO", facts["is_epfo_available"]),
                    ] if available
                ],
                "ratios_cited": count_cited_ratios(facts),
                "total_claims": total_claims,
            },
        }

        self._save_report(report)
        return report

    def _save_report(self, report: dict[str, Any]) -> None:
        engine = get_engine()
        is_sqlite = engine.dialect.name == "sqlite"
        # report_json is JSONB on Postgres (needs a cast from the bound text
        # parameter) but plain TEXT on SQLite; now() is Postgres-only, SQLite
        # uses CURRENT_TIMESTAMP for the same "right now" value.
        json_expr = ":report_json" if is_sqlite else "CAST(:report_json AS JSONB)"
        now_expr = "CURRENT_TIMESTAMP" if is_sqlite else "now()"
        with engine.begin() as conn:
            conn.execute(
                text(
                    f"""
                    INSERT INTO ai_reports (customer_id, scorecard_date, report_json, generation_method)
                    VALUES (:customer_id, :scorecard_date, {json_expr}, :generation_method)
                    ON CONFLICT (customer_id, scorecard_date) DO UPDATE SET
                        report_json = EXCLUDED.report_json,
                        generation_method = EXCLUDED.generation_method,
                        generated_at = {now_expr}
                    """
                ),
                {
                    "customer_id": report["customer_id"],
                    "scorecard_date": report["audit_trail"]["scorecard_date"],
                    "report_json": json.dumps(report),
                    "generation_method": report["generation_method"],
                },
            )

    def generate_all_reports(self, scorecards: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Generate reports for all given scorecards."""
        reports = []
        for scorecard in scorecards:
            report = self.generate_report(scorecard)
            reports.append(report)
            logger.info(
                "Report for %s: %s (%s)",
                report["customer_id"], report["generation_method"], report["narrative"]["summary"][:60],
            )
        return reports


def _latest_scorecards() -> list[dict[str, Any]]:
    """Load each customer's most recent scorecard from the scorecards table."""
    # ROW_NUMBER() rather than Postgres's DISTINCT ON (customer_id, ...) idiom --
    # SQLite doesn't support DISTINCT ON at all; window functions work identically
    # on both, so one query serves both dialects instead of branching.
    with get_engine().connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT customer_id, scorecard_json FROM (
                    SELECT customer_id, scorecard_json,
                           ROW_NUMBER() OVER (PARTITION BY customer_id ORDER BY scorecard_date DESC) AS rn
                    FROM scorecards
                ) ranked
                WHERE rn = 1
                """
            )
        ).all()
    return [parse_json_field(row.scorecard_json) for row in rows]


def main() -> None:
    create_tables()
    engine = AIEngine()
    scorecards = _latest_scorecards()
    reports = engine.generate_all_reports(scorecards)
    for report in reports:
        print(f"{report['customer_id']}: {report['generation_method']} -> {report['narrative']['summary']}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    main()
