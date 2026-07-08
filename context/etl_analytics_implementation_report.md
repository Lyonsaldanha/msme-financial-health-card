# MSME Financial Health Card — Implementation Report

Status as of this document: all 4 layers of the architecture (see
[msme_fhc_context.md](msme_fhc_context.md) for the 3-layer engine
architecture, plus the Streamlit frontend on top) are built, wired to real
infrastructure (PostgreSQL, Gemini), and verified end-to-end — not just
written and assumed correct. Every success criterion across all four build
prompts (ETL, Analytics, AI, Frontend) is confirmed working, including a
genuine live Gemini generation.

---

## 1. Scope

Four deliverables, per the original build prompts:

1. **ETL Engine** — load synthetic MSME data (GST, UPI, AA, EPFO) from JSON
   into PostgreSQL with normalization, validation, and full audit lineage.
2. **Analytics Engine** — compute financial ratios per data source, cross-source
   reconciliation, weighted dimension scores, a composite health score
   (0–100), and red/green risk flags per customer, stored as a JSON scorecard.
3. **AI Engine** — generate an audit-safe narrative report and chart configs
   per customer from the scorecard, using an LLM for prose only.
4. **Streamlit Frontend** — login, customer selection, health card display,
   and report history, bridging the AI Engine's output to a browser UI.

No data transformation/scoring logic lives in the ETL layer; no analysis
happens in the AI Engine or frontend — all of that is confined to the
Analytics Engine, consistent with the architecture doc's "LLM is a
templating engine, not an analyst" principle.

---

## 2. Database schema

Defined in [db/schema.sql](../db/schema.sql), created idempotently via
`db.schema.create_tables()`.

| Table | Purpose | Natural key (upsert target) |
|---|---|---|
| `customers` | Customer master | `customer_id` |
| `gst_filings` | Monthly GST returns | `customer_id, year, month` |
| `upi_transactions` | Daily UPI activity | `customer_id, txn_date` |
| `bank_statements` | Monthly AA/bank data | `customer_id, year, month` |
| `epfo_payroll` | Monthly EPFO payroll | `customer_id, year, month` |
| `data_lineage` | One row per file-load attempt (audit trail) | — (append-only) |
| `validation_errors` | One row per record-level validation failure/warning | — (append-only) |
| `scorecards` | One row per customer per scorecard date, JSONB payload | `customer_id, scorecard_date` |
| `ai_reports` | One row per customer per scorecard date, JSONB report + `generation_method` | `customer_id, scorecard_date` |

Design decisions:

- **All currency columns are `BIGINT` paise** (rupees × 100), not floating
  point rupees, to avoid rounding drift across repeated aggregation.
- `validation_errors`, `scorecards`, and `ai_reports` are additions beyond
  what the ETL prompt's six named tables covered. `validation_errors` exists
  because the ETL spec explicitly requires logging "validation failures with
  record ID + error reason" — `data_lineage` alone (one row per *file*) can't
  carry that granularity. `scorecards` and `ai_reports` are each required by
  their respective engine's own "Database Integration" spec section.
- Every fact table has a foreign key to `customers(customer_id)` with
  `ON DELETE CASCADE`, and an index on `customer_id` for the per-customer
  read pattern every engine and the frontend use.
- `ai_reports.generation_method` (`'gemini'` or `'fallback'`) records which
  path actually produced each report — an audit trail for the AI Engine
  itself, not just for the underlying financial data.

---

## 3. ETL Engine

Public API in [etl_engine.py](../etl_engine.py) (project root, per the spec's
`from etl_engine import run_etl` usage example); internals in `etl/` and `db/`.

```
load_json_to_db(file_path, table_name) -> LoadResult
validate_data(data_dir) -> dict[str, list[str]]      # dry-run, no writes
run_etl(data_dir="mock_data") -> list[LoadResult]
```

### Pipeline per file

1. Parse JSON.
2. For each record: **normalize** (`etl/normalizers.py` — currency → paise,
   dates → ISO `date` objects, sector names → canonical form, GST numbers →
   uppercased) then **validate** (`etl/validators.py`).
3. Validation results split into:
   - **blocking** — row is dropped, logged to `validation_errors`, counted
     as skipped (e.g. GST sales ≤ 0, negative collections, future dates).
   - **warning** — row is still loaded, but the issue is logged to
     `validation_errors` (e.g. non-standard GST number length, bank debits
     exceeding credits in a given month).
4. Valid rows are **upserted** in one batch via a generically-built
   `INSERT ... ON CONFLICT (<natural key>) DO UPDATE SET ...` statement — the
   column list and `SET` clause are derived from the row's own keys, not
   hand-written per table, so adding a new source table doesn't require new
   SQL.
5. One `data_lineage` row is written per file per run: source file, table,
   record count loaded, status (`SUCCESS` / `PARTIAL` / `FAILED`), and an
   error summary if anything was skipped.

### Idempotency

Re-running `run_etl()` against the same files upserts on each table's natural
key rather than duplicating rows. Verified by running the full load twice in
a row and confirming identical row counts (see §9).

### NTC customer handling

`gst_filings` naturally has zero rows for CUST_003 (NTC clinic — no GST
registration) since the source `gst_filings.json` contains no records for
that customer. No special-casing was needed in the loader; the Analytics
Engine's ratio functions handle the empty case explicitly (§4), and the AI
Engine and frontend both propagate that "no GST data" state through to the
final display rather than masking it.

---

## 4. Analytics Engine

Public API in [analytics_engine.py](../analytics_engine.py) (project root);
internals in `analytics/` (`stats_utils.py` — pure math, `scoring.py` — pure
scoring/flag rules plus narrative interpretation labels, no DB access).

```
compute_gst_ratios(customer_id) -> dict
compute_upi_ratios(customer_id) -> dict
compute_aa_ratios(customer_id) -> dict
compute_epfo_ratios(customer_id) -> dict
compute_cross_validation(customer_id) -> dict
compute_dimension_scores(customer_id) -> dict
compute_composite_score(customer_id) -> int
generate_scorecard(customer_id) -> dict
run_analytics(customer_ids=None) -> list[dict]     # generates + persists
```

Data is read via `pandas.read_sql_query` into DataFrames, and ratios use
pandas/numpy (`.mean()`, `.std(ddof=1)`, `numpy.polyfit` for trend slopes)
rather than manual loops.

### Ratio coverage

- **GST**: CAGR (first vs. last month, annualized), MoM growth, coefficient
  of variation, filing delay count, ITC/tax-payment-status/customer-concentration
  reported as `"NA"` (no such data in this feed, per spec). NTC customers get
  an explicit `is_gst_registered: false` branch with all GST-dependent fields
  `null`/`"NA"` rather than a divide-by-zero or a misleading zero.
- **UPI**: average daily collections, total transactions, average ticket size,
  active days / active days %, weekend-vs-weekday ratio, ticket-size CV
  (used later for scoring).
- **AA**: average monthly credits, credit trend slope, credit volatility (CV),
  average daily balance, cash conversion ratio, DSCR (aggregated from the
  feed's own DSCR field, not recomputed — the proposed-EMI component it
  depends on isn't available at record level, so recomputing it would silently
  drop that term), existing debt totals, cheque return count, cash withdrawal %.
- **EPFO**: start/end/average employee count, employee count trend slope,
  employee growth %, payroll average/variance, wage average/inflation %,
  late contribution count, churn rate.
- **Cross-validation**: GST-vs-AA, GST-vs-UPI, AA-payroll-vs-EPFO-payroll,
  UPI-vs-AA-credits ratios, each flagged as a mismatch if outside 0.5–1.5 (per
  spec), plus a GST-growth-vs-employee-growth directional alignment check.

### Dimension scoring

Weighted per the spec (`analytics/scoring.py::WEIGHTS`):
AA cashflow 35%, GST quality 25%, UPI behaviour 20%, EPFO stability 10%,
compliance/bureau 10% (fixed at 80 — no bureau data source in this POC, as
the spec directs). Each dimension is built from named sub-scores (e.g. AA
cashflow = DSCR 40% + ADB sufficiency 30% + cheque returns 20% + cash
withdrawal % 10%), using threshold tables taken directly from the spec where
given. Where the spec left a threshold gap or a rule inherently needs a
judgment call, it's documented inline in `scoring.py`:

- **GST quality for NTC customers** defaults to a neutral 50 rather than 0 or
  a crash, since "no GST data" isn't the same failure mode as "bad filing
  behaviour."
- **UPI transaction frequency** ("sector-dependent High/Medium/Low" in the
  spec) is scored against an absolute daily-transaction-count band, since
  this dataset has no sector/peer benchmark table to compare against.
- **ADB sufficiency** and **revenue CV** fill in a missing middle tier
  (spec jumps straight from a "normal" band to "highly volatile") using the
  same 100/70/40/0 stepping the spec uses everywhere else, for consistency.

`scoring.py` also exposes `interpret_dscr`, `interpret_cv`, and
`interpret_active_days` — text-label versions of the same threshold
cutpoints used for numeric scoring, added specifically so the AI Engine's
narrative (§5) never describes a ratio using different boundaries than the
ones that actually produced its dimension score.

### Flags

Red/green flags implement every rule listed in the spec's Red Flags/Green
Flags bullets literally (DSCR thresholds, cheque bounce counts, filing delay
counts, EPFO late contributions, employee count trend, revenue growth/decline,
cross-validation mismatch, cash withdrawal %, ADB-vs-60-days-expenses).

---

## 5. AI Engine

Public API in [ai_engine.py](../ai_engine.py) (project root); internals in
`ai/` (`facts.py`, `prompts.py`, `charts.py`, `fallback.py`, `client.py`,
`render.py`, `schemas.py`).

```
AIEngine.retrieve_facts(scorecard) -> dict
AIEngine.augment_prompt(facts) -> str
AIEngine.generate_report(scorecard) -> dict
AIEngine.generate_all_reports(scorecards) -> list[dict]
```

### The LLM writes prose only, never data

The single biggest design deviation from a literal reading of the spec, made
deliberately and documented rather than silently: **chart configs — including
every numeric value in them — are built deterministically in `ai/charts.py`,
never generated by the LLM.** The gauge comes from `composite_score`, the bar
chart from `dimension_scores`, the two line charts from raw monthly
`gst_filings`/`upi_transactions`/`epfo_payroll` rows, the table from
`cross_validation` — all plain SQL + Python, zero model involvement. Two
reasons:

1. Asking a model to faithfully reproduce a numeric array is the highest
   hallucination-risk operation you could hand it.
2. The scorecard itself doesn't carry raw monthly time series (only
   aggregates like CAGR/CV), so a chart like the spec's own example ("GST
   Monthly Revenue Trend" with 12 monthly data points) isn't derivable from
   the stated "Scorecard JSON only" input, regardless of model behavior.

Similarly, `customer_name`/`sector`/`gst_number` (needed by the prompt
template) aren't present in the scorecard JSON; `ai_engine.py` reads them
directly from the `customers` table via the scorecard's own `customer_id` —
still real, unmodified data, never LLM-touched.

### Structured output via Pydantic + current SDK

Uses the current `google-genai` SDK, not the legacy `google.generativeai`
package shown in the original prompt's sample code (Google is sunsetting the
legacy package). `NarrativeReport` (`ai/schemas.py`) is a Pydantic model
passed as `response_schema` with `response_mime_type="application/json"` —
the SDK validates and parses the model's JSON into that Pydantic model
itself (`response.parsed`), rather than this code hand-parsing
`response.text` and hoping it's well-formed JSON.

### Error handling: quota, timeout, invalid output

Per the spec's explicit error-handling requirements, `ai/client.py::call_gemini()`
degrades to `ai/fallback.py::build_fallback_narrative()` — a deterministic,
non-LLM template built from the same facts, following the same
source-citation convention the LLM is instructed to follow — on: a missing
API key, `429`/`RESOURCE_EXHAUSTED`, schema-validation failure after one
retry, or any other exception. It never raises for these cases;
`generate_report()` always returns a usable report, with
`report["generation_method"]` (`"gemini"` or `"fallback"`) recording which
path actually ran, persisted alongside the report in `ai_reports` for audit
purposes — not silently presenting a template as if it were LLM output.

### Chart rendering (Matplotlib)

`ai/render.py` renders `chart_configs` to static PNGs with Matplotlib — the
"Tool call renders charts" step named in the architecture doc's Layer 3 flow.
Actually rendering all 5 chart types (gauge/bar/2×line/table) for real,
persisted reports surfaced a genuine bug: the ✅/⚠️ emoji used in the
cross-validation table have no glyph in Matplotlib's default font (DejaVu
Sans) and rendered as broken boxes. Fixed by sanitizing to ASCII (`[OK]`/`[!]`)
only at Matplotlib render time — the underlying `chart_configs` JSON keeps
the emoji unchanged, since a web/Streamlit frontend renders Unicode
natively; only the static-image consumer needed the workaround.

### The Gemini quota investigation

Every early attempt to call Gemini for real (`gemini-2.0-flash`, then
`gemini-2.0-flash-lite`) returned `429 Too Many Requests`. A raw diagnostic
call (bypassing the SDK's exception-swallowing to read the full error body)
revealed the actual message: `limit: 0` for
`generate_content_free_tier_requests` — genuinely zero quota, not merely
exhausted. This was initially documented as a project-wide billing
configuration problem requiring the user to link a billing account. That
conclusion was **wrong, and corrected**: switching to `gemini-flash-latest`
on the identical API key succeeded immediately (`HTTP 200`), proving the
zero-quota condition was specific to those two exact model names on this
project, not an account-wide block. `ai/client.py::DEFAULT_MODEL` is now
`gemini-flash-latest`.

A second discovery in the same investigation: `gemini-flash-latest` is a
"thinking" model that spends part of `max_output_tokens` on internal
reasoning before emitting visible text — confirmed empirically (a 10-token
budget produced zero visible characters, all consumed by ~45 thinking
tokens, per `response.usage_metadata.thoughts_token_count`).
`MAX_OUTPUT_TOKENS` raised from 2000 to 4096 accordingly.

A separate, self-inflicted issue during testing (not a code defect, but
worth recording): while trying to verify the fallback path *without* hitting
the live API, `env -u GEMINI_API_KEY` was used to strip the key from the
shell before invoking Python. `db/config.py`'s `load_dotenv()` (default
`override=False`) only skips a variable if it's *already set* — since it had
been removed from the environment, dotenv read it straight back from `.env`.
Six unintended live calls went out during what was meant to be an
offline-only test run. All six correctly hit `429` and degraded to the
fallback (so no incorrect output resulted), but real API attempts were spent
needlessly against a rate-limited key — a reminder that shell-level env
manipulation doesn't reliably prevent a `dotenv`-based module from loading a
secret from a `.env` file.

Once resolved, the live narrative was spot-checked against the source
scorecard, not just accepted on a `200` response: composite score, DSCR, GST
turnover range, and cross-validation ratios in the generated prose all
traced to real computed values, with source citations and conditional
language ("indicates", "shows") used throughout as instructed.

---

## 6. Streamlit Frontend

Entry point [app.py](../app.py); pages in `pages/` (`1_Login.py`,
`2_Dashboard.py`, `3_Reports.py`); shared UI in `components/` (`auth.py`,
`forms.py`, `charts.py`, `cards.py`).

### Two design decisions confirmed with the user before building

1. **Customer selection, not a "new customer" intake form.** The spec's form
   lets a user type in a brand-new business (name, GST, UPI ID, EPFO ID, bank
   ref) and generate a card for it — its own sample code works around the
   lack of real data by hardcoding a static fake scorecard for whatever name
   is typed in. This POC has no live GST/UPI/AA/EPFO data connectors; only
   customers the ETL Engine already loaded have real financial history, so
   `components/forms.py::customer_selector()` presents a dropdown of real
   customers instead. "Generate Health Card" always produces genuine,
   traceable output — never a fabricated number for an arbitrary typed-in
   name.
2. **In-process function calls, not a separate backend HTTP API.** The spec
   describes a `POST /api/generate_health_card` endpoint served by its own
   process. `analytics_engine.py`/`ai_engine.py` are already plain Python
   modules that talk to Postgres directly, so `pages/2_Dashboard.py` imports
   and calls them (`run_analytics(...)`, `AIEngine().generate_report(...)`)
   rather than standing up a redundant HTTP layer for a single-process demo.

### Other deviations, documented rather than silent

- Progress indicators (`st.status(...)`) reflect real pipeline stages
  completing, not `time.sleep()`-simulated delays.
- Charts are Plotly (`components/charts.py`), driven by the AI Engine's real
  `chart_configs` — the same JSON schema `ai/render.py` renders to static
  PNGs, one data contract with two renderers for two consumption contexts
  (on-screen interactivity vs. static image export).
- Downloads are real JSON (full report + scorecard), not the spec's
  placeholder `data="PDF content here"` — real PDF generation wasn't
  requested by any engine spec in this project, so a button that would do
  nothing useful if clicked was replaced with genuine, complete data.

### Bugs found by actually running it in a browser, not by reading the code

1. `db/queries.py::list_ai_reports()` selected `r.composite_score` from
   `ai_reports`, but that column only exists on `scorecards` — the "View
   Reports" tab threw a live `sqlalchemy.exc.ProgrammingError` the first time
   it was clicked. Fixed by joining both tables.
2. `use_container_width` (used throughout `components/cards.py`,
   `pages/2_Dashboard.py`, `pages/3_Reports.py`) is a deprecated Streamlit
   parameter past its announced removal date — replaced with `width='stretch'`
   at every call site.
3. The Reports page had no Logout button, which would strand a logged-in
   user unable to sign out from that page. Fixed by extracting a shared
   `components/auth.py::render_header()` used by both Dashboard and Reports,
   so a header/logout mismatch can't silently reappear on a future page.
4. A test-automation issue, not an app defect: Streamlit's `text_input`
   commits its value to server-side session state on blur/Enter, not on
   every keystroke. Automated fill-then-immediately-click sequences during
   manual browser testing raced ahead of that commit, intermittently
   submitting a stale/empty value for whichever field was filled first ("Invalid
   credentials" despite the browser visibly showing the correct values). Real
   human interaction has enough natural delay between typing and clicking
   that this never surfaces; resolved in testing by giving each field's
   commit a real round-trip before the next action.

Verified live in-browser: login; the Dashboard generate-flow for a normal
customer (CUST_001) and the NTC edge case (CUST_003 — GST section correctly
absent, UPI-substituted trend chart, neutral GST-quality score, `NA`
cross-validation); all 4 Plotly chart types rendering and interactive; flags
display including the "None recorded" empty state; JSON downloads; the
Reports page's composite-score comparison chart, full history table, and
individual report viewer; and logout from both Dashboard and Reports.

---

## 7. Environment issues found and resolved

Caught by actually running the pipeline against live infrastructure rather
than trusting the code in isolation.

1. **Port collision, not a real conflict.** A native Windows PostgreSQL
   service was already bound to 5432. Docker's WSL2-backed port forwarding
   showed up alongside it in `netstat` without actually being reachable,
   causing password-auth failures against the *wrong* server. Fixed by
   remapping the container to host port **5433** (see `docker-compose.yml`,
   `.env.example`).

2. **Stale `pg_hba.conf` from a broken first boot.** After fixing the port,
   connections still failed with "no pg_hba.conf entry for host". Root cause:
   Postgres only writes `pg_hba.conf` once, on first init of an empty data
   directory — and the *first* `docker compose up` (before the port fix) had
   already created the named volume. Every subsequent boot reused that
   volume and skipped re-init (`Database directory appears to contain a
   database; Skipping initialization` in the logs), so whatever `pg_hba.conf`
   resulted from that first, possibly-incomplete boot stuck around
   regardless of later config changes. Fixed by `docker compose down -v` to
   drop the volume and force a genuinely clean init, confirmed via the
   container's own startup log before retrying the app connection.

3. **Gemini `429`s were a model-quota provisioning issue, not a rate limit**
   — see §5 for the full investigation. Resolved by switching the default
   model rather than waiting or contacting billing.

---

## 8. Mock data defects found and fixed

Confirmed by cross-checking generated ratios against the documented persona
characteristics in [SYNTHETIC_DATA_README.md](../mock_data/SYNTHETIC_DATA_README.md)
— not assumed from reading the generator code alone.

| # | Defect | Root cause | Fix |
|---|---|---|---|
| 1 | DSCR identical (7.2) for every customer | `generate_aa_data()` defined a per-persona `dscr` target but never read it; DSCR was derived from a persona-invariant EMI formula | Existing/proposed EMI now sized from `avg_credit_base / persona['dscr']`, so DSCR reflects the documented target per persona |
| 2 | GST sales ~100x too small vs. bank credits | `gst_monthly_range` tuples commented as annual lakhs (e.g. "₹35L–45L") but coded as literal rupees | Corrected ranges to true monthly values (annual ÷ 12); additionally tied `total_credits` directly to that month's GST sales (± 5% noise) for GST-registered customers so the two sources actually reconcile |
| 3 | Employee headcount resampled independently every month, causing spurious first-vs-last "decline" flags on stable personas | `employee_count = starting_employees + randint(0, 2)`, redrawn from scratch each month with no path dependency | Headcount now evolves as a walk biased by the persona's GST growth trend (growing/shrinking directionally, mean-reverting toward the starting count when flat) |
| 4 | Synthetic GST numbers are 14 chars, not the real 15-char GSTIN format | `bothify`/`postcode` combination comes up one character short | Left as-is — logged as a non-blocking warning in `validation_errors`; a POC doesn't need real GSTIN checksums |

Defects 1–3 required regenerating `mock_data/*.json` and reloading; the ETL
and Analytics engine code itself needed no changes for this, since neither
hardcodes assumptions about the underlying numeric ranges.

---

## 9. Verification evidence

**ETL, first run and after regeneration (identical both times):**

| Table | Records |
|---|---|
| customers | 6 |
| gst_filings | 60 |
| upi_transactions | 2190 |
| bank_statements | 72 |
| epfo_payroll | 72 |

- `data_lineage`: one `SUCCESS` row per file per run.
- `validation_errors`: non-blocking warnings only (GST number length, a few
  months of debits > credits for the "mixed signals" restaurant persona) —
  zero blocking failures, zero rows dropped.
- Idempotency: re-running produced the same row counts both times (no
  duplicates), and NTC customer CUST_003 correctly loaded with 0 GST rows
  and full UPI/AA/EPFO rows (365/12/12).

**Analytics, before vs. after the mock data fix:**

| Customer | Persona | DSCR before | DSCR after (documented target) | Composite before | Composite after |
|---|---|---|---|---|---|
| CUST_001 | Healthy retail | 7.2 | 2.09 (2.1) | 87 | 98 |
| CUST_002 | At-risk services | 7.2 | 1.11 (1.1) | 60 | 53 |
| CUST_003 | NTC clinic | 7.2 | 1.5 (1.5) | 75 | 70 |
| CUST_004 | Mixed signals restaurant | 7.2 | 1.4 (1.4) | 81 | 66 |
| CUST_005 | Manufacturing | 7.2 | 1.79 (1.8) | 89 | 95 |
| CUST_006 | Wholesale trader | 7.2 | 2.31 (2.3) | 83 | 97 |

Composite score spread widened from 60–89 to 53–98, and dimension/flag
outputs now match each persona's documented narrative (e.g. CUST_002 carries
3 red flags — cheque bounces, late GST filings, declining headcount — and
lands in "Fair"; CUST_001/005/006 carry zero red flags and land in
"Excellent").

Scorecards persisted to the `scorecards` table: one row per customer per
calendar date (upsert on `customer_id, scorecard_date`), confirmed via direct
query — historical scorecards from before the data fix remain intact under
their original date, current-day scorecards reflect the corrected data.

**AI Engine:**

- All 6 customers produced a full report (narrative + 5 chart configs) via
  the deterministic fallback path first — verified before any live API
  usage, so the pipeline's correctness didn't depend on Gemini being
  reachable.
- All 5 chart configs (gauge/bar/table/2×line) actually rendered through
  Matplotlib (`ai/render.py`) and visually inspected — this is what caught
  the emoji-glyph bug (§5).
- One genuine live Gemini generation confirmed: `HTTP 200`,
  `generation_method: "gemini"`, persisted to `ai_reports`, narrative
  spot-checked line-by-line against the source scorecard for hallucination
  (none found).

**Streamlit Frontend:**

- Full login → select customer → generate → view card → logout flow
  exercised live in a real browser session (not just code review), for both
  a normal customer and the NTC edge case.
- Reports page comparison chart and historical browse confirmed against
  real persisted data.

---

## 10. Success criteria status

**ETL Engine**
- [x] All 6 synthetic customers loaded
- [x] 60 GST, 2190 UPI, 72 AA, 72 EPFO records in DB
- [x] Data lineage logged for every load
- [x] No blocking validation errors; warnings logged with record ID + reason
- [x] Idempotent re-runs (upsert, verified no duplicates)

**Analytics Engine**
- [x] Scorecards generated and persisted for all 6 customers
- [x] Composite scores span a range reflecting persona diversity (53–98)
- [x] Red/green flags populated per customer, consistent with documented personas
- [x] Cross-validation metrics detect mismatches (and correctly report `null`/no-mismatch for NTC and well-reconciled customers)
- [x] Ratios manually sanity-checked against documented personas for CUST_001, CUST_002, CUST_003

**AI Engine**
- [x] All 6 scorecards → 6 reports generated, each with narrative + 5 chart configs
- [x] Every narrative claim cites a data source
- [x] Chart configs valid JSON, actually rendered through Matplotlib (all 5 types)
- [x] Reports stored in PostgreSQL (`ai_reports`, JSONB)
- [x] No hallucinated data — chart data 100% code-built, narrative facts 100% scorecard/DB-sourced
- [x] Temperature 0.3; quota/timeout/invalid-output errors verified to degrade to fallback rather than fail
- [x] Live Gemini generation confirmed successful (see §5, §9)

**Streamlit Frontend**
- [x] Login works with hardcoded credentials
- [x] Dashboard: real customer selection + real pipeline call
- [x] Progress indicator reflects real pipeline stages
- [x] Health card renders all components, verified for a normal customer and the NTC edge case
- [x] Charts render correctly and interactively (Plotly)
- [x] Green/red flags display prominently, including the empty state
- [x] Logout clears session, verified from every authenticated page
- [x] Reports page: comparison chart + full history, verified live

---

## 11. Known limitations / not yet done

- Employee headcount trend is a stochastic walk, not a deterministic fit to
  each persona's stated growth rate; occasional larger swings (e.g. a
  small-base customer going from 4 to 10 employees) are possible by chance
  and are directionally but not numerically tied to the persona description.
- `existing_debt_instrument_count`, `days_sales_outstanding`,
  `repeat_customer_rate`, ITC utilization, and customer concentration are all
  reported as `"NA"` — the source data has no instrument-level, receivables,
  payer-level, or invoice-level detail to compute them from, per the original
  spec's own notes.
- No separate backend HTTP API exists — a deliberate choice (§6), not an
  oversight, but means the frontend and engines share one Python process
  rather than being independently deployable services.
- No real PDF generation — the frontend offers JSON downloads instead (§6);
  adding PDF export would be new scope no engine spec in this project asked for.
- No automated test suite exists yet (`tests/` directory was scaffolded but
  is empty) — verification throughout has been live, manual runs against
  Docker Postgres and a real browser session, documented in §7–9 of this
  report.

---

## 12. Known bugs (identified, not yet fixed)

Found via a full read-through of every module, not surfaced by the live
verification runs in §9 because none of the 6 current customers actually
trigger them. Recorded here so they're tracked rather than forgotten;
deliberately left unfixed for now per explicit instruction.

**Real logic bugs:**

1. **`ai/facts.py::retrieve_facts()` — latent `KeyError` crash.** It does
   direct dict indexing (`aa["avg_monthly_credits"]`,
   `epfo["employee_growth_percent"]`, etc.), assuming
   `compute_aa_ratios()`/`compute_epfo_ratios()` always return a
   fully-populated dict. Both instead return a bare `{}` when a customer has
   zero `bank_statements`/`epfo_payroll` rows — unlike `compute_gst_ratios()`/
   `compute_upi_ratios()`, which always return a full dict with `None`/0
   defaults even when empty (the pattern already established for the NTC
   case). Every current customer has full AA/EPFO data, so this never fires
   today, but it's a real crash waiting for any future customer missing one
   of those two sources, and it's inconsistent with how the other two
   sources already handle exactly that case.
2. **`etl_engine.py::validate_data()` — inconsistent error handling versus
   its own `load_json_to_db()`.** The real loader catches
   `(OSError, json.JSONDecodeError)` around reading/parsing a source file and
   logs a graceful lineage failure. The dry-run validator (meant to be the
   *safe* preview of that same path) doesn't wrap its `json.loads()` call the
   same way — a malformed JSON file crashes the dry run with an uncaught
   exception instead of reporting it like the real load does.
3. **`analytics_engine.py`'s `ratio_and_flag()` helper conflates "zero" with
   "missing".** `if not numerator or not denominator: return None, None`
   treats a legitimately-zero value the same as `None`. Current DB
   constraints make this unreachable for GST/UPI/AA-credits (all required
   `> 0`), but `payroll_paid_paise` only requires `>= 0` — a future
   zero-payroll month would silently report the cross-validation as `"NA"`
   instead of surfacing what should be an informative mismatch (real EPFO
   payroll vs. zero AA payroll).

**Real bugs in `deploy-demo.sh` / `Dockerfile`** (never executed yet — see
§6's design notes for the rationale behind the script's choices; these are
bugs within that implementation, not disagreements with the design):

4. **Cloud SQL tier-fallback only works if `timeout` happens to be
   installed.** The retry-with-`db-custom-1-3840` logic (for when
   `db-f1-micro` isn't a valid tier for the Postgres version/region) lives
   entirely inside the `if command -v timeout` branch. On a system without
   GNU `timeout`, an invalid-tier failure hits the bare `else` with no retry
   and no friendly message — under `set -euo pipefail` it just exits on a raw
   `gcloud` error instead of the intended graceful fallback.
5. **`docker push --quiet` (line ~183) — flag support unconfirmed.** Not
   verified against the actual installed Docker CLI version; `--quiet` is a
   much newer addition to `docker push` than to `docker build`. If the local
   Docker version predates it, this line fails outright before ever reaching
   Cloud Run.
6. **`ai/client.py`'s rate limiter is per-process, not distributed.**
   `_last_call_at` is a module-level global. With `--max-instances=2` on
   Cloud Run, two concurrently-running instances each enforce the 4-second
   gap independently without coordinating — the real combined outbound rate
   to Gemini could approach double the intended throttle. Not reachable in
   local single-process dev; only matters once actually deployed with more
   than one live instance.

**Minor / informational** (not bugs, no behavior change needed):

- `db/connection.py::session_scope()` appears unused — nothing in the
  codebase uses ORM sessions; everything goes through
  `get_engine().connect()`/`.begin()` with Core `text()` queries.
- `ai/facts.py`'s `months` field defaults to a hardcoded `12` for NTC
  customers rather than deriving it from that customer's actual UPI/AA/EPFO
  row count — coincidentally correct since every customer here spans exactly
  12 months, but not actually sourced from the right place for an NTC
  customer specifically.
- The Login page's "Demo Credentials" expander displays the hardcoded
  credentials directly in the UI, by design (matches the original spec) —
  worth remembering this makes a deployed instance's login effectively
  decorative the moment it's public. This is exactly why `deploy-demo.sh`'s
  own output emphasizes tearing down promptly; it isn't a new exposure, just
  a reason the existing "tear down promptly" guidance matters.
- `Dockerfile` has no `EXPOSE` directive and runs as root — neither affects
  Cloud Run functionality (Cloud Run doesn't consult `EXPOSE`, and doesn't
  require a non-root user), just minor deviations from general Docker best
  practice.
