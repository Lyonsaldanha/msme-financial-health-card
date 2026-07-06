# ETL Engine & Analytics Engine — Implementation Report

Status as of this document: Layers 1 and 2 of the 3-layer architecture
(see [msme_fhc_context.md](msme_fhc_context.md)) are built, wired to a real
PostgreSQL instance, and verified end-to-end — not just written and assumed
correct. Layer 3 (AI Engine) is not started.

---

## 1. Scope

Two deliverables, per the original build prompts:

1. **ETL Engine** — load synthetic MSME data (GST, UPI, AA, EPFO) from JSON
   into PostgreSQL with normalization, validation, and full audit lineage.
2. **Analytics Engine** — compute financial ratios per data source, cross-source
   reconciliation, weighted dimension scores, a composite health score
   (0–100), and red/green risk flags per customer, stored as a JSON scorecard.

No data transformation/scoring logic lives in the ETL layer, and no LLM/
narrative generation is in scope here — that's Layer 3.

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

Design decisions:

- **All currency columns are `BIGINT` paise** (rupees × 100), not floating
  point rupees, to avoid rounding drift across repeated aggregation.
- `validation_errors` and `scorecards` are additions beyond the six tables
  named in the original ETL prompt. `validation_errors` was added because the
  spec explicitly requires logging "validation failures with record ID +
  error reason" — `data_lineage` alone (one row per *file*) can't carry that
  granularity. `scorecards` is required by the Analytics Engine's own spec
  ("Database Integration" section).
- Every fact table has a foreign key to `customers(customer_id)` with
  `ON DELETE CASCADE`, and an index on `customer_id` for the per-customer
  read pattern both engines use.

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
a row and confirming identical row counts (see §6).

### NTC customer handling

`gst_filings` naturally has zero rows for CUST_003 (NTC clinic — no GST
registration) since the source `gst_filings.json` contains no records for
that customer. No special-casing was needed in the loader; the Analytics
Engine's ratio functions handle the empty case explicitly (§4).

---

## 4. Analytics Engine

Public API in [analytics_engine.py](../analytics_engine.py) (project root);
internals in `analytics/` (`stats_utils.py` — pure math, `scoring.py` — pure
scoring/flag rules, no DB access).

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

### Flags

Red/green flags implement every rule listed in the spec's Red Flags/Green
Flags bullets literally (DSCR thresholds, cheque bounce counts, filing delay
counts, EPFO late contributions, employee count trend, revenue growth/decline,
cross-validation mismatch, cash withdrawal %, ADB-vs-60-days-expenses).

---

## 5. Environment issues found and resolved

Both were caught by actually running the pipeline against live PostgreSQL in
Docker rather than trusting the code in isolation.

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

---

## 6. Mock data defects found and fixed

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

## 7. Verification evidence

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

---

## 8. Success criteria status

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

---

## 9. Known limitations / not yet done

- **Layer 3 (AI Engine)** — narrative/report generation from the scorecard
  JSON — is not started.
- Employee headcount trend is still a stochastic walk, not a deterministic
  fit to each persona's stated growth rate; occasional larger swings (e.g.
  a small-base customer going from 4 to 10 employees) are possible by chance
  and are directionally but not numerically tied to the persona description.
- `existing_debt_instrument_count`, `days_sales_outstanding`,
  `repeat_customer_rate`, ITC utilization, and customer concentration are all
  reported as `"NA"` — the source data has no instrument-level, receivables,
  payer-level, or invoice-level detail to compute them from, per the original
  spec's own notes.
- No automated test suite exists yet (`tests/` directory was scaffolded but
  is empty) — verification so far has been live, manual runs against Docker
  Postgres, documented in §6–7 of this report.
