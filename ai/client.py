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
import threading
import time

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
# Without this, a stalled network request hangs the underlying httpx client
# indefinitely -- observed directly: a call that hung for minutes with no
# error and no response, blocking generate_report() forever instead of
# degrading to the fallback narrative like every other failure mode here does.
REQUEST_TIMEOUT_MS = int(os.getenv("GEMINI_TIMEOUT_MS", "30000"))

# Minimum spacing between outbound Gemini calls, enforced process-wide. The
# free-tier quota is tied to the API key, not to any one caller -- a Dashboard
# user clicking Generate repeatedly, or run_analytics looping over all 6
# customers, would otherwise fire requests back-to-back with no gap between
# them, which is exactly what trips a per-minute rate limit. Throttling here,
# at the single chokepoint every caller goes through, protects all of them
# uniformly rather than each call site needing its own pacing logic.
MIN_SECONDS_BETWEEN_CALLS = float(os.getenv("GEMINI_MIN_SECONDS_BETWEEN_CALLS", "4"))

_rate_limit_lock = threading.Lock()
_last_call_at = 0.0


def _throttle() -> None:
    global _last_call_at
    with _rate_limit_lock:
        wait = MIN_SECONDS_BETWEEN_CALLS - (time.monotonic() - _last_call_at)
        if wait > 0:
            logger.info("Rate limiting Gemini call: waiting %.1fs", wait)
            time.sleep(wait)
        _last_call_at = time.monotonic()


def _get_client() -> genai.Client | None:
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
    return genai.Client(api_key=api_key, http_options=types.HttpOptions(timeout=REQUEST_TIMEOUT_MS))


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
        _throttle()
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
