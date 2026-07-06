"""Structured-output schema for the LLM call.

This is the only thing the model is allowed to produce: prose fields keyed to
the facts we hand it. Numeric data (ratios, chart values) never round-trips
through the LLM -- see ai/charts.py.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class NarrativeReport(BaseModel):
    summary: str = Field(description="Executive summary, 2 sentences.")
    financial_health: str = Field(description="Financial health assessment, 2 sentences.")
    strengths: list[str] = Field(description="2-3 bullet points, each citing a data source.")
    risks: list[str] = Field(description="2-3 bullet points, each citing a data source.")
    recommendations: str = Field(description="Recommended next steps, 1-2 sentences.")
