# MSME Financial Health Card — Project Context

## Problem Statement
Banks evaluate MSME credit using traditional financial documents. Most New-to-Credit (NTC) and New-to-Bank (NTB) enterprises lack these documents or maintain them inadequately. Rich alternate data (GST, UPI, AA, EPFO) exists but is fragmented with no unified assessment framework. This leads to high rejection rates, missed viable borrowers, and slow financial inclusion progress.

## Goal
Build an AI/ML-driven MSME Financial Health Card that:
- Aggregates alternate data (GST, UPI, AA, EPFO)
- Computes a multidimensional financial health score
- Visualizes strengths and risks
- Integrates with ULI/AA ecosystems
- Enables near real-time credit assessment

---

## Architecture: 3-Layer System

### Layer 1: ETL Engine
- Ingests alternate data from GST, UPI, AA, EPFO sources
- Normalizes data using **AA (Account Aggregator) specs** via Sahamati — which are RBI-compliant by default. There is no separate "RBI format"; AA specs serve as the data contract.
- Target integration ecosystems: **ULI (Unified Lending Interface)** and **AA (Account Aggregator)**
- Stores normalized records in PostgreSQL
- Maintains full audit log with data lineage (source → field → transformation)

### Layer 2: Analytics Engine
Performs ratio analysis and descriptive analytics per customer. No dimensional modelling or peer comparison — single customer focus only.

#### GST Ratios
- Revenue CAGR, MoM growth
- Coefficient of Variation (CV) for sales consistency (< 15% stable, > 40% volatile)
- Filing behaviour: GSTR-1 and GSTR-3B delay counts
- ITC utilization (sudden drops flag fake invoices)
- Customer concentration risk (top customer % of revenue)

#### UPI Ratios
- Average daily collections, transaction count
- Average ticket size (collections / transactions)
- Active days per month
- Repeat customer rate (if payer identifiers available)
- Weekend vs weekday transaction patterns

#### AA (Account Aggregator / Banking) Ratios
- Average monthly credits (trend + volatility)
- Average daily balance (vs EMI obligations)
- Cash conversion (credits vs debits → operating surplus)
- DSCR = Operating Cash Flow ÷ (Existing EMI + Proposed EMI)
  - > 1.75: Strong | 1.25–1.75: Acceptable | < 1.0: Weak
- Existing debt identification (loans, OD, CC, BNPL)
- Cheque/ECS/ACH return counts
- Cash withdrawal patterns (flagged for digital businesses)

#### EPFO Ratios
- Employee count trend (MoM growth)
- Payroll stability and variance
- Contribution timeliness (late deposits = working capital stress)
- Employee churn rate
- Wage inflation (avg wage trend)

#### Cross-Validation (Most Powerful)
| Compare | Why |
|---|---|
| GST sales vs AA bank credits | Revenue consistency |
| GST sales vs UPI receipts | Digital collection share |
| EPFO payroll vs AA salary payments | Payroll authenticity |
| UPI inflows vs bank deposits | Settlement behaviour |
| GST growth vs employee growth | Staffing alignment |
| GST tax payments vs bank outflows | Compliance validation |
| Bank collections vs existing EMIs | Repayment capacity |

#### Composite Score Weights
| Component | Weight |
|---|---|
| AA (Bank cash flow) | 35% |
| GST quality | 25% |
| UPI behaviour | 20% |
| EPFO stability | 10% |
| Bureau & compliance | 10% |

**Output:** Structured JSON scorecard with all ratios, flags, and composite score.

---

### Layer 3: AI Engine
Generates audit-safe reports and visualizations from the Analytics Engine scorecard.

#### Design: Anonymized Prompt Templates (Structured RAG)
- Retrieval = structured facts pulled directly from Analytics Engine scorecard (not vector search)
- Augmentation = facts injected into prompt templates
- LLM role = **templating only** (no creativity, no hallucination risk)
- Every claim in the output is tagged with its source data point for audit traceability

#### Flow
```
Analytics Scorecard (JSON)
    ↓
Fetch structured facts (DSCR, CV, active days, flags, composite score etc.)
    ↓
Inject into anonymized prompt template
    ↓
LLM (Gemini) outputs:
    ├─ Narrative (markdown)
    └─ Chart configs (JSON array)
    ↓
Tool call → Matplotlib renders charts
    ↓
PDF report (narrative + charts, fully traceable)
```

#### Chart Types
- **Bar** — GST monthly turnover, employee count, payroll
- **Line** — Revenue trend, cash balance over time
- **Gauge** — DSCR, Composite Score, CV
- **Table** — Cross-validation reconciliation
- **Pie** — Debt composition, revenue concentration

#### Chart Config Schema (LLM output)
```json
[
  {
    "type": "bar",
    "title": "GST Monthly Turnover",
    "data": [2200000, 2300000, 2400000, 2500000],
    "labels": ["Jan", "Feb", "Mar", "Apr"],
    "source": "GST Analytics Engine"
  },
  {
    "type": "gauge",
    "title": "DSCR",
    "value": 1.85,
    "thresholds": {"weak": 1.0, "acceptable": 1.75},
    "source": "AA Analytics Engine"
  }
]
```

---

## Tech Stack
| Layer | Technology |
|---|---|
| Backend | Python |
| Database | PostgreSQL |
| LLM | Gemini (AI Studio key — prototype only, rate-limited) |
| Charts | Matplotlib (via tool call from LLM chart config JSON) |
| Frontend | Streamlit (Python native, prototype) |
| Data Contract | AA Specs (Sahamati) + ULI APIs |

---

## Key Design Principles
1. **LLM is a templating engine, not an analyst.** All analysis happens in the Analytics Engine. LLM only formats and narrates pre-computed facts.
2. **Every claim is traceable.** Ratio → source field → raw data. Full audit lineage in PostgreSQL.
3. **No invented formats.** AA specs are the data contract. They are RBI-compliant by default.
4. **Alternate data only.** GST, UPI, AA, EPFO. No traditional financial documents required.
5. **Single customer focus.** Ratio analysis and descriptive analytics. No peer/dimensional comparison.

---

## PostgreSQL Schema (High Level)
- `customers` — normalized customer record (from ETL)
- `ratios` — computed ratio output per customer per data source (from Analytics Engine)
- `scorecards` — composite score + flags per customer
- `audit_log` — data lineage (source → transformation → output)

> This is the original pre-implementation sketch. The actual schema is more
> granular (separate `gst_filings`/`upi_transactions`/`bank_statements`/
> `epfo_payroll` tables rather than one generic `ratios` table, plus
> `validation_errors` and `ai_reports`) — see
> [../context/etl_analytics_implementation_report.md](etl_analytics_implementation_report.md)
> §2 for the real schema and why it differs.

---

## Current Status
All 3 layers plus the Streamlit frontend are implemented and verified
end-to-end against real infrastructure (PostgreSQL, Gemini) — see
[../context/etl_analytics_implementation_report.md](etl_analytics_implementation_report.md)
for the full implementation record, verification evidence, deviations from
these original specs (each documented with rationale), and known
limitations. See [../README.md](../README.md) for setup and usage.
