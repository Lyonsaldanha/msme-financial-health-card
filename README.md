# MSME Financial Health Card (POC)

Loads synthetic MSME alternate-data (GST, UPI, AA/bank statements, EPFO) into
PostgreSQL with normalization, validation, and full audit lineage (**ETL
Engine**), computes per-customer financial ratios, cross-source
reconciliation, dimension scores, a composite health score, and risk flags
(**Analytics Engine**), generates an audit-safe narrative report and chart
configs per customer via Gemini (**AI Engine**), and presents it all through
a **Streamlit frontend** with login, customer selection, and report history.

See [context/msme_fhc_context.md](context/msme_fhc_context.md) for the full
3-layer architecture this POC implements end-to-end.

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management
- Docker Desktop (used to run PostgreSQL locally)

## Setup

1. Install dependencies:

   ```bash
   uv sync
   ```

2. Copy the environment template and adjust if needed:

   ```bash
   cp .env.example .env
   ```

3. Start PostgreSQL:

   ```bash
   docker compose up -d
   ```

   > **Note:** `docker-compose.yml` maps the container to **host port 5433**,
   > not 5432. If you already have a local/native PostgreSQL install, it will
   > typically claim 5432 first, and Docker's own port-forwarding can appear
   > to coexist with it in `netstat` without actually being reachable — your
   > app ends up talking to the wrong server with the wrong credentials. Using
   > 5433 sidesteps that entirely. If you change the port, update `DB_PORT` in
   > `.env` to match.

4. Verify Postgres is healthy:

   ```bash
   docker compose ps
   ```

## Running the ETL Engine

Loads `mock_data/*.json` into PostgreSQL, creating tables on first run:

```bash
uv run python etl_engine.py
```

Or from Python:

```python
from etl_engine import run_etl

results = run_etl(data_dir="mock_data")
for r in results:
    print(r.table_name, r.loaded, "/", r.attempted, "loaded, ", r.skipped, "skipped")
```

Expected output: 6 customers, 60 GST filings, 2190 UPI transactions, 72 bank
statements, 72 EPFO records — all `SUCCESS` in `data_lineage`.

Loads are **idempotent**: re-running upserts on each table's natural key
(`customer_id` for customers; `customer_id + year + month` for monthly
tables; `customer_id + date` for UPI) rather than duplicating rows.

To dry-run validation without touching the database:

```python
from etl_engine import validate_data

report = validate_data("mock_data")
```

Row-level validation failures (both blocking and warning-level) are logged
to the `validation_errors` table with the source file, table, record
identifier, and reason. See [Known data-quality quirks](#known-data-quality-quirks-in-the-mock-data)
below for the two warning types you'll actually see with the bundled data.

## Running the Analytics Engine

Computes ratios and scorecards for all customers (or a subset), reading from
the tables the ETL Engine populated, and persists each scorecard as JSONB in
the `scorecards` table:

```bash
uv run python analytics_engine.py
```

Or from Python:

```python
from analytics_engine import generate_scorecard, run_analytics

scorecard = generate_scorecard("CUST_001")
print(scorecard["composite_score"], scorecard["score_interpretation"])
print(scorecard["red_flags"])

# Generate + persist for every customer:
run_analytics()

# Or a specific subset:
run_analytics(customer_ids=["CUST_001", "CUST_003"])
```

## Running the AI Engine

Generates an audit-safe narrative report and chart configs per customer from
each scorecard, and persists each report as JSONB in the `ai_reports` table:

```bash
uv run python ai_engine.py
```

Or from Python:

```python
from ai_engine import AIEngine
from analytics_engine import generate_scorecard

engine = AIEngine()
scorecard = generate_scorecard("CUST_001")
report = engine.generate_report(scorecard)

print(report["generation_method"])   # "gemini" or "fallback"
print(report["narrative"]["summary"])
for chart in report["chart_configs"]:
    print(chart["type"], chart["title"])
```

Requires `GEMINI_API_KEY` in `.env` (get one at
[aistudio.google.com/apikey](https://aistudio.google.com/apikey)). Without a
key configured, or if Gemini errors/times out/exceeds quota, `generate_report`
transparently falls back to a deterministic, non-LLM template narrative built
from the same facts — `report["generation_method"]` tells you which path ran.

Default model is `gemini-flash-latest` (configurable via `GEMINI_MODEL`).
During development, `gemini-2.0-flash` and `gemini-2.0-flash-lite` both
returned `429 RESOURCE_EXHAUSTED` with `limit: 0` on the free-tier project
used to build this — that's zero quota provisioned for those two specific
model names, not a rate limit from overuse or an account-wide block: switching
to `gemini-flash-latest` on the *same* key/project worked immediately. If you
hit `limit: 0` on whatever model you configure, try `gemini-flash-latest` (or
another current alias) before assuming your project needs a billing account
linked. Note `gemini-flash-latest` is a "thinking" model that spends part of
`max_output_tokens` on internal reasoning before emitting visible text —
confirmed empirically (a 10-token budget produced zero visible characters, all
spent on ~45 thinking tokens) — so `ai/client.py` sizes the budget generously
(4096) rather than the smaller value you'd use for a non-thinking model.

**Design deviations from a literal reading of the AI Engine spec** (each
chosen for audit-safety, documented rather than silent):

- **Chart configs — including every number in them — are built
  deterministically in `ai/charts.py`, never generated by the LLM.** Asking a
  model to faithfully reproduce a numeric array is the highest
  hallucination-risk operation you could hand it, and the scorecard alone
  doesn't carry the raw monthly series a trend chart needs (only aggregates
  like CAGR/CV) — so it isn't derivable from the LLM's stated input anyway.
  The LLM's role is narrowed to exactly what benefits from natural language:
  the narrative prose.
- **Customer name/sector/GST number** (needed by the prompt template but not
  present in the scorecard JSON) are read directly from the `customers`
  table via the scorecard's own `customer_id` — still real, unmodified data.
- **Uses the current `google-genai` SDK**, not the legacy
  `google.generativeai` package shown in the original prompt (Google is
  sunsetting it). `response_schema=NarrativeReport` (a Pydantic model) lets
  the SDK validate and parse the model's JSON directly, rather than
  hand-parsing `response.text`.
- **`audit_trail` counts are computed by this code** from what was actually
  handed to/returned by the model, not self-reported by the LLM — an LLM
  counting its own citations would itself be an unverifiable claim.
- **Interpretive labels** (DSCR "strong/weak", CV "stable/volatile") reuse
  the exact threshold constants already defined in `analytics/scoring.py`
  (`interpret_dscr`, `interpret_cv`, `interpret_active_days`), so the
  narrative never contradicts the Analytics Engine's own scoring.

## Running the Streamlit Frontend

```bash
uv run streamlit run app.py
```

Open [http://localhost:8501](http://localhost:8501), log in with `admin` /
`demo123`, select a real customer on the Dashboard, and click **Generate
Health Card**. The Reports page (sidebar) shows a composite-score comparison
across all customers and lets you open any historical report in full.

**Design deviations from a literal reading of the frontend spec**, both
confirmed with the user before building rather than assumed:

- **Customer selection, not a "new customer" intake form.** The original
  spec's form lets a user type in a brand-new business (name, GST, UPI ID,
  EPFO ID, bank ref) and generate a card for it — its own sample code works
  around the lack of real data by hardcoding a static fake scorecard for
  whatever name is typed in. This POC has no live GST/UPI/AA/EPFO data
  connectors, only the customers the ETL Engine already loaded into
  Postgres have real financial history, so `components/forms.py` presents a
  dropdown of real customers instead. "Generate Health Card" always produces
  genuine, traceable output — never a fabricated number for an arbitrary
  typed-in name.
- **In-process calls, not a separate backend API.** The spec describes a
  `POST /api/generate_health_card` HTTP endpoint served by its own process.
  `analytics_engine.py` and `ai_engine.py` are already plain Python modules
  that talk directly to Postgres, so `pages/2_Dashboard.py` imports and
  calls them directly (`run_analytics(...)`, `AIEngine().generate_report(...)`)
  rather than standing up a redundant HTTP layer for a single-process demo.
- **Progress indicators reflect real work, not `time.sleep()`.** The status
  stages in the Dashboard (`st.status(...)`) update as each real pipeline
  step actually completes, rather than a fixed sequence of simulated delays.
- **Charts are Plotly, driven by the AI Engine's real `chart_configs`.**
  `components/charts.py` renders the exact same JSON schema
  `ai/render.py` renders to static PNGs with Matplotlib — one data
  contract, two renderers (on-screen interactivity here; static image
  export there) — rather than a separate hardcoded set of example figures.
- **Downloads are real JSON, not a placeholder.** The spec's sample PDF
  download button ships literal placeholder text (`data="PDF content
  here"`). Real PDF generation is a non-trivial addition no engine spec in
  this project asked for, so the health card offers the full report and
  scorecard as downloadable JSON instead — genuine, complete data rather
  than a button that does nothing useful if clicked.

**Real bugs surfaced by actually running this in a browser, not by reading the code:**

1. `db/queries.py::list_ai_reports()` originally selected `r.composite_score`
   from `ai_reports`, but that column only exists on `scorecards` — fixed by
   joining both tables. Caught immediately by the "View Reports" tab
   throwing a live `ProgrammingError`.
2. `use_container_width` (used throughout `components/cards.py` and both
   pages) is a deprecated Streamlit parameter past its removal date —
   replaced with `width='stretch'` everywhere.
3. The Reports page had no Logout button, stranding a logged-in user unable
   to sign out from it. Fixed by extracting a shared
   `components/auth.py::render_header()` used by both Dashboard and Reports.
4. A test-automation issue, not an app bug: Streamlit's `text_input` commits
   to session state on blur/Enter, not every keystroke. Automated
   fill-then-immediately-click during manual browser testing raced ahead of
   that commit, intermittently submitting a stale/empty value — real human
   typing has enough natural delay that this never surfaces.

## Querying a customer's financial footprint

```python
from db import get_customer_financials

financials = get_customer_financials("CUST_001")
# {"customer": {...}, "gst_filings": [...], "upi_transactions": [...],
#  "bank_statements": [...], "epfo_payroll": [...]}
```

## Project layout

```
db/                  config, pooled SQLAlchemy engine, schema DDL, queries
etl/                 normalizers, validators, row transforms, lineage logging
etl_engine.py         public ETL API: load_json_to_db / validate_data / run_etl
analytics/            pure stats helpers + dimension scoring/flag rules
analytics_engine.py   public Analytics API: compute_*_ratios / generate_scorecard / run_analytics
ai/                   fact retrieval, prompt templates, chart assembly, fallback narrative, Gemini client, Matplotlib rendering
ai_engine.py           public AI API: AIEngine.generate_report / generate_all_reports
components/            Streamlit UI: auth guard, customer selector, Plotly chart dispatcher, health card
pages/                 Streamlit pages: Login, Dashboard, Reports
app.py                 Streamlit entry point (redirects to Login or Dashboard)
mock_data/             synthetic source JSON/CSV + generator script
docker-compose.yml     local PostgreSQL for development
```

## Mock data fixes applied

Running both engines end-to-end against live PostgreSQL (not just unit
testing them) surfaced pre-existing quirks in `mock_data/msme_data_generator.py`.
The generator has since been patched and `mock_data/*.json` regenerated;
noted here for traceability:

1. **DSCR was identical (7.2) for every customer.** `generate_aa_data()`
   defined a `dscr` target per persona (e.g. 2.1 for healthy retail, 1.1 for
   at-risk) but never used it — DSCR was derived from a fixed EMI formula
   independent of persona. Fixed: existing/proposed EMI are now sized off
   each persona's documented target DSCR, so the stored DSCR actually varies
   by persona (verified: 2.09, 1.11, 1.5, 1.4, 1.79, 2.31 vs. documented
   2.1/1.1/1.5/1.4/1.8/2.3).

2. **GST sales were ~100x too small relative to bank credits.** `gst_monthly_range`
   tuples were commented as annual lakhs (e.g. "₹35L–45L") but coded as
   literal rupees. Fixed the ranges to true monthly values, and additionally
   tied `generate_aa_data()`'s monthly credits directly to that month's GST
   sales (± small noise) for GST-registered customers, so GST-vs-AA
   cross-validation now reconciles at ~1.0 with no false mismatches (NTC
   customers, with no GST to key off, keep the original ADB-derived estimate).

3. **Employee headcount was independently resampled every month**
   (`starting_employees + randint(0, 2)`), so even "stable" personas could
   show an apparent decline between month 1 and month 12 purely by chance —
   this caused a false "declining employee count" red flag on the healthy
   retail persona in initial testing. Fixed: headcount now evolves as a
   month-to-month walk biased by the persona's GST growth trend (growing,
   shrinking, or mean-reverting around the starting count for flat personas),
   so first-vs-last comparisons reflect an actual trend rather than sampling
   noise.

4. **Synthetic GST numbers are 14 characters, not the real 15-char GSTIN
   format** (generator's `bothify`/`postcode` combination comes up one
   character short). Left as-is — the ETL engine logs this as a non-blocking
   warning in `validation_errors` and loads the record regardless; a POC
   doesn't need real GSTIN checksums, but a production feed would.

## Success criteria checklist

- [x] All 6 synthetic customers loaded
- [x] 60 GST, 2190 UPI, 72 AA, 72 EPFO records in DB
- [x] Data lineage logged for every load (`data_lineage` table)
- [x] Validation failures logged with record ID + reason, non-blocking (`validation_errors` table)
- [x] Idempotent re-runs verified (upsert, no duplicate rows)
- [x] Scorecards generated and persisted for all 6 customers
- [x] Cross-validation metrics detect mismatches
- [x] Red/green flags populated per customer
- [x] Ratios manually sanity-checked against `context/SYNTHETIC_DATA_README.md` personas for CUST_001, CUST_002, CUST_003
- [x] All 6 scorecards → 6 reports generated, each with narrative + 5 chart configs
- [x] Every narrative claim cites a data source ("(per GST data)", "(per bank statements)", etc.)
- [x] Chart configs are valid JSON, actually rendered through Matplotlib (`ai/render.py`) and visually verified for all 5 chart types (gauge/bar/2×line/table) — this caught and fixed a real bug: the ✅/⚠️ emoji in table cells have no glyph in Matplotlib's default font and rendered as broken boxes; fixed by sanitizing to ASCII (`[OK]`/`[!]`) at render time only, leaving the underlying JSON emoji intact for web/Streamlit consumers that render Unicode natively
- [x] Reports stored in PostgreSQL (`ai_reports` table, JSONB)
- [x] No hallucinated data — chart data is 100% code-built from the DB; narrative facts are 100% scorecard/DB-sourced
- [x] Temperature set to 0.3 for factual mode; quota/timeout/invalid-output errors verified to degrade to a deterministic fallback rather than fail
- [x] Live Gemini generation confirmed successful — `gemini-2.0-flash` and `gemini-2.0-flash-lite` both returned `429 RESOURCE_EXHAUSTED` with `limit: 0` (zero free-tier quota provisioned for those two specific model names on this project — not an account-wide block, and not fixed by waiting or retrying). Switching to `gemini-flash-latest` on the *same* key worked immediately: confirmed `HTTP 200`, `generation_method: "gemini"`, persisted to `ai_reports`, and spot-checked for hallucination (every claim in the narrative traced to a real computed value — composite score, DSCR, GST turnover range, cross-validation ratios all matched the scorecard; conditional language and source citations used throughout as instructed).
- [x] Login page works with hardcoded credentials (`admin` / `demo123`)
- [x] Dashboard lets the user select a real customer and generate a health card
- [x] Progress indicator reflects real pipeline stages (not simulated delays)
- [x] Health card renders with all components: composite gauge, dimension scores, charts, flags, narrative — verified live in-browser for both a normal customer (CUST_001) and the NTC edge case (CUST_003: GST section correctly absent, UPI trend substituted, neutral GST-quality score)
- [x] Charts render correctly (gauge/bar/line/table via Plotly, interactive zoom/pan confirmed)
- [x] Green/red flags display prominently, "None recorded" shown correctly when empty
- [x] Logout clears session and redirects to Login, verified from both Dashboard and Reports pages
- [x] Reports page: composite-score comparison chart + full history browse, verified live

## Known issues (not yet fixed)

A full code read-through surfaced a handful of real bugs, currently latent
against this project's own data/environment but worth tracking. Full detail
in [context/etl_analytics_implementation_report.md](context/etl_analytics_implementation_report.md)
§12 — summary:

- `ai/facts.py` can raise `KeyError` for a hypothetical future customer
  missing AA or EPFO data (the NTC-style "no data" handling that GST/UPI
  already have isn't mirrored there).
- `etl_engine.py::validate_data()` doesn't catch malformed-JSON the same way
  its own `load_json_to_db()` does.
- A cross-validation helper in `analytics_engine.py` treats a legitimate
  zero value the same as missing data.
- `deploy-demo.sh`'s Cloud SQL tier-fallback only triggers if `timeout` is
  installed; its `docker push --quiet` flag isn't confirmed to exist on
  every Docker CLI version; and its Gemini rate limiter doesn't coordinate
  across multiple Cloud Run instances.

None of this affects the current 6-customer dataset or anything already
verified above. None of it is a new exposure beyond what's already visible
in the source — it's tracked here for follow-up, not fixed yet.
