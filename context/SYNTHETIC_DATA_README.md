# MSME Financial Health Card — Synthetic Data Documentation

## Overview
This directory contains realistic synthetic data for 6 MSME customers across 4 data sources (GST, UPI, AA, EPFO) for 12 months (Jan-Dec 2024).

---

## File Structure

### Customer Profiles
- `customers.json` / `customers.csv`
- 6 customers across different sectors and personas
- Fields: customer_id, business_name, sector, persona, gst_number, pan, registration_date

### GST Filings (Monthly)
- `gst_filings.json` / `gst_filings.csv`
- 12 months × 6 customers = 60 records
- Fields: customer_id, month, year, gstr_sales, tax_paid, filing_date, is_delayed
- Note: NTC (No GST) customer has 0 records

### UPI Transactions (Daily)
- `upi_transactions.json` / `upi_transactions.csv`
- 365 days × 6 customers = 2,190 records
- CSV has sample (first 30 days); JSON has full year
- Fields: customer_id, date, day_of_week, collections, num_transactions, avg_ticket_size

### Bank Statements (AA Data) (Monthly)
- `bank_statements.json` / `bank_statements.csv`
- 12 months × 6 customers = 72 records
- Fields: customer_id, month, year, total_credits, total_debits, payroll_paid, operating_expenses, tax_payments, existing_emi, operating_surplus, avg_daily_balance, dscr, cheque_returns, cash_withdrawals

### EPFO Payroll (Monthly)
- `epfo_payroll.json` / `epfo_payroll.csv`
- 12 months × 6 customers = 72 records
- Fields: customer_id, month, year, employee_count, monthly_payroll, avg_wage, contribution_date, is_late_contribution, employee_churn

---

## Customer Personas

### 1. CUST_001: Healthy Retail
- **Sector:** Retail
- **GST Monthly:** ₹35L–45L (8% growth)
- **UPI Daily:** ₹3K–5K (80–120 tx/day)
- **ADB:** ₹6L–9L
- **DSCR:** 2.1 (Strong)
- **Employees:** 6–10
- **Characteristics:** Clean filing, no delays, no cheque bounces, stable

### 2. CUST_002: At-Risk Services
- **Sector:** Services
- **GST Monthly:** ₹18L–24L (-5% YoY decline)
- **UPI Daily:** ₹500–1500 (sparse)
- **ADB:** ₹1L–2.5L (Low)
- **DSCR:** 1.1 (Weak)
- **Employees:** 2–4
- **Characteristics:** Late GST filings (3/year), low UPI, 3 cheque bounces, 2 late EPFO deposits

### 3. CUST_003: NTC (No GST) Clinic
- **Sector:** Healthcare Services
- **GST:** NOT_REGISTERED (New-to-Credit)
- **UPI Daily:** ₹15K–25K
- **ADB:** ₹2L–4L
- **DSCR:** 1.5 (Acceptable)
- **Employees:** 2–4
- **Characteristics:** No GST but strong UPI + AA data, good EPFO

### 4. CUST_004: Mixed Signals Restaurant
- **Sector:** Food & Beverage
- **GST Monthly:** ₹45L–65L (10% growth, seasonal)
- **UPI Daily:** ₹8K–15K (150–250 tx/day, high frequency)
- **ADB:** ₹1.5L–3L (Low for turnover)
- **DSCR:** 1.4
- **Employees:** 8–15
- **Characteristics:** High UPI frequency, high cash withdrawals (20% of credits), 1 cheque bounce

### 5. CUST_005: Manufacturing (Small)
- **Sector:** Manufacturing
- **GST Monthly:** ₹55L–75L (7% growth)
- **UPI Daily:** ₹2K–3.5K (30–60 tx/day, B2B)
- **ADB:** ₹9L–14L
- **DSCR:** 1.8 (Strong)
- **Employees:** 12–18
- **Characteristics:** Clean filings, strong cash position, reliable payroll

### 6. CUST_006: Wholesale Trader
- **Sector:** Wholesale Trade
- **GST Monthly:** ₹35L–50L (6% growth)
- **UPI Daily:** ₹3K–5K (60–100 tx/day)
- **ADB:** ₹4L–6L
- **DSCR:** 2.3 (Very Strong)
- **Employees:** 4–8
- **Characteristics:** Excellent metrics across all sources, very creditworthy

---

## Key Characteristics by Data Source

### GST (Revenue & Compliance)
- Revenue trends: Mix of growth, decline, and stability
- Filing delays: 0–3 per year (flagged as "is_delayed")
- Tax payment tracking: Embedded in monthly data

### UPI (Cash Flow & Customer Activity)
- Daily collections vary by sector (retail higher, manufacturing lower)
- Transaction counts inversely related to avg ticket size
- Weekend/holiday effects (70% of weekday activity)
- Seasonal spikes for restaurant (seasonal=true in generator)

### AA (Bank Statements & Liquidity)
- Monthly credits = proxies for business turnover
- Operating surplus = credits − (payroll + operating expenses + tax + EMI)
- DSCR = monthly credits ÷ (existing EMI + proposed EMI)
- Cheque returns flag liquidity stress
- Cash withdrawals flag working capital usage

### EPFO (Payroll & Stability)
- Employee count growth YoY (0–2 employees/year typical)
- Monthly payroll aligned with employee count
- Contribution delays (0–2 per year) indicate working capital stress
- Employee churn (0–1 per year) indicates operational risk

---

## Data Quality Notes

### Realism
- ✅ GST aligned with UPI (collections consistency)
- ✅ Bank credits align with GST + UPI flows
- ✅ Payroll credible vs. employee count
- ✅ DSCR reflects actual business health
- ✅ Cheque bounces correlate with low ADB

### Synthetic Artifacts
- ❓ No invoice-level GST detail (only monthly totals)
- ❓ No real banking counterparties (AA data is directional)
- ❓ Employee names/IDs not included (only counts)
- ❓ No ITC (Input Tax Credit) detail in GST

### For Analytics Testing
All key ratios can be computed:
- **GST Stability:** CV (Coefficient of Variation)
- **UPI Metrics:** Daily collections, ticket size, active days, transaction count
- **AA Metrics:** DSCR, ADB, operating surplus, cheque returns
- **EPFO Metrics:** Employee growth, payroll variance, contribution timeliness
- **Cross-Validation:** GST vs UPI, AA payroll vs EPFO, etc.

---

## Usage

### Load into PostgreSQL (Example)
```python
import json

# Load customers
with open('customers.json') as f:
    customers = json.load(f)

# Load GST
with open('gst_filings.json') as f:
    gst = json.load(f)

# ... repeat for others
```

### Data Refresh
To regenerate with different parameters:
```bash
python msme_data_generator.py
```

Modify `PERSONAS` dict in `msme_data_generator.py` to adjust ranges, growth rates, persona counts, etc.

---

## Next Steps

1. **ETL:** Load JSON/CSV into PostgreSQL with lineage tracking
2. **Analytics:** Compute ratios for each customer
3. **Scoring:** Calculate composite scores + dimension scores
4. **AI Engine:** Feed scorecards to LLM for report generation
5. **Streamlit:** Display cards in UI, validate flow end-to-end
