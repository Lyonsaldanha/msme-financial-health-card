"""Thin wrapper around google-genai: structured output, retry, and graceful
degradation to the fallback narrative on quota/timeout/invalid-output errors.

Uses the current `google-genai` SDK rather than the legacy
`google.generativeai` package (which Google is sunsetting), so the report can
request `response_schema=NarrativeReport` directly -- the SDK validates and
parses the model's JSON into that Pydantic model itself, rather than us
hand-parsing `response.text` and hoping it's well-formed.
"""

from __future__ import annotations

import logging
import os

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from ai.schemas import NarrativeReport

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-flash-latest"
TEMPERATURE = 0.3  # low temperature = factual mode, per spec
# gemini-flash-latest is a "thinking" model that spends part of this budget on
# internal reasoning tokens before emitting visible output (confirmed empirically:
# a 10-token budget produced 0 visible chars, all spent on ~45 thinking tokens) --
# sized generously so structured JSON generation doesn't get truncated by that.
MAX_OUTPUT_TOKENS = 4096
MAX_ATTEMPTS = 2


def _get_client() -> genai.Client | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def _describe_quota_error(exc: "genai_errors.APIError") -> str:
    """Distinguish "no quota provisioned" (limit: 0 -- a project/billing config
    issue, retrying won't help) from a genuine transient rate limit (quota > 0,
    temporarily used up -- retrying later will help)."""
    message = exc.message or ""
    if "limit: 0" in message:
        return (
            "Gemini free-tier quota is 0 for this project/model (not merely exhausted) -- "
            "this is a Google Cloud project/billing provisioning issue, not a rate limit. "
            "See https://ai.google.dev/gemini-api/docs/rate-limits. Retrying will not help."
        )
    return f"Gemini quota exceeded (transient rate limit): {message or exc}"


def call_gemini(system_prompt: str, user_prompt: str) -> NarrativeReport | None:
    """Call Gemini for a structured NarrativeReport.

    Returns None (the caller falls back to the deterministic template) on a
    missing API key, quota exhaustion, or output that fails schema validation
    after retrying once -- this function deliberately never raises for those
    cases, since a missing narrative is worse than a template one.
    """
    client = _get_client()
    if client is None:
        logger.warning("GEMINI_API_KEY not configured; using fallback narrative")
        return None

    model = os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
    config = types.GenerateContentConfig(
        system_instruction=system_prompt,
        temperature=TEMPERATURE,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        response_mime_type="application/json",
        response_schema=NarrativeReport,
    )

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = client.models.generate_content(model=model, contents=user_prompt, config=config)
        except genai_errors.APIError as exc:
            if exc.code == 429 or exc.status == "RESOURCE_EXHAUSTED":
                logger.warning("%s Using fallback narrative.", _describe_quota_error(exc))
                return None
            last_error = exc
            logger.warning("Gemini call failed (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, exc)
            continue
        except Exception as exc:  # noqa: BLE001 -- any failure here must degrade to fallback, not crash the report pipeline
            last_error = exc
            logger.warning("Gemini call failed (attempt %d/%d): %s", attempt, MAX_ATTEMPTS, exc)
            continue

        parsed = response.parsed
        if isinstance(parsed, NarrativeReport):
            return parsed
        last_error = ValueError(f"Gemini response did not match NarrativeReport schema: {response.text!r}")
        logger.warning("Gemini response failed schema validation (attempt %d/%d)", attempt, MAX_ATTEMPTS)

    logger.warning("Gemini call exhausted retries (%s); using fallback narrative", last_error)
    return None
