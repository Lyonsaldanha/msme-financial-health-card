-- MSME Financial Health Card -- SQLite variant of schema.sql, for a Cloud Run
-- deployment with no separate database service (see deploy-cloud-run.sh).
-- Table/column names are identical to schema.sql on purpose -- every query in
-- this codebase works unchanged against either backend. Only the types that
-- SQLite doesn't have are swapped: BIGSERIAL -> INTEGER PRIMARY KEY AUTOINCREMENT,
-- TIMESTAMPTZ/now() -> TEXT/CURRENT_TIMESTAMP, JSONB -> TEXT (the app already
-- round-trips these through json.dumps/json.loads at the Python layer -- see
-- db/queries.py's _parse_json_field).

CREATE TABLE IF NOT EXISTS customers (
    customer_id        VARCHAR(20) PRIMARY KEY,
    business_name       VARCHAR(200) NOT NULL,
    sector              VARCHAR(100) NOT NULL,
    persona             VARCHAR(100),
    gst_number          VARCHAR(20) NOT NULL,
    pan                 VARCHAR(10) NOT NULL,
    registration_date   DATE NOT NULL,
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS gst_filings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id         VARCHAR(20) NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    month               SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    year                SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    gstr_sales_paise    BIGINT NOT NULL CHECK (gstr_sales_paise >= 0),
    tax_paid_paise      BIGINT NOT NULL CHECK (tax_paid_paise >= 0),
    filing_date         DATE NOT NULL,
    is_delayed          BOOLEAN NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_gst_filings_customer_period UNIQUE (customer_id, year, month)
);
CREATE INDEX IF NOT EXISTS idx_gst_filings_customer ON gst_filings(customer_id);

CREATE TABLE IF NOT EXISTS upi_transactions (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id             VARCHAR(20) NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    txn_date                DATE NOT NULL,
    day_of_week             VARCHAR(10) NOT NULL,
    collections_paise       BIGINT NOT NULL CHECK (collections_paise >= 0),
    num_transactions        INTEGER NOT NULL CHECK (num_transactions > 0),
    avg_ticket_size_paise   BIGINT NOT NULL CHECK (avg_ticket_size_paise >= 0),
    created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_upi_customer_date UNIQUE (customer_id, txn_date)
);
CREATE INDEX IF NOT EXISTS idx_upi_customer ON upi_transactions(customer_id);
CREATE INDEX IF NOT EXISTS idx_upi_date ON upi_transactions(txn_date);

CREATE TABLE IF NOT EXISTS bank_statements (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id                 VARCHAR(20) NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    month                       SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    year                        SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    total_credits_paise         BIGINT NOT NULL CHECK (total_credits_paise >= 0),
    total_debits_paise          BIGINT NOT NULL CHECK (total_debits_paise >= 0),
    payroll_paid_paise          BIGINT NOT NULL CHECK (payroll_paid_paise >= 0),
    operating_expenses_paise    BIGINT NOT NULL CHECK (operating_expenses_paise >= 0),
    tax_payments_paise          BIGINT NOT NULL CHECK (tax_payments_paise >= 0),
    existing_emi_paise          BIGINT NOT NULL CHECK (existing_emi_paise >= 0),
    operating_surplus_paise     BIGINT NOT NULL,
    avg_daily_balance_paise     BIGINT NOT NULL CHECK (avg_daily_balance_paise >= 0),
    dscr                        NUMERIC(8, 2) NOT NULL CHECK (dscr > 0),
    cheque_returns              INTEGER NOT NULL DEFAULT 0 CHECK (cheque_returns >= 0),
    cash_withdrawals_paise      BIGINT NOT NULL CHECK (cash_withdrawals_paise >= 0),
    created_at                  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at                  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_bank_customer_period UNIQUE (customer_id, year, month)
);
CREATE INDEX IF NOT EXISTS idx_bank_customer ON bank_statements(customer_id);

CREATE TABLE IF NOT EXISTS epfo_payroll (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id             VARCHAR(20) NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    month                   SMALLINT NOT NULL CHECK (month BETWEEN 1 AND 12),
    year                    SMALLINT NOT NULL CHECK (year BETWEEN 2000 AND 2100),
    employee_count          INTEGER NOT NULL CHECK (employee_count > 0),
    monthly_payroll_paise   BIGINT NOT NULL CHECK (monthly_payroll_paise >= 0),
    avg_wage_paise          BIGINT NOT NULL CHECK (avg_wage_paise >= 0),
    contribution_date       DATE NOT NULL,
    is_late_contribution    BOOLEAN NOT NULL DEFAULT 0,
    employee_churn          INTEGER NOT NULL DEFAULT 0 CHECK (employee_churn >= 0),
    created_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at              TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_epfo_customer_period UNIQUE (customer_id, year, month)
);
CREATE INDEX IF NOT EXISTS idx_epfo_customer ON epfo_payroll(customer_id);

-- Audit lineage: one row per file load attempt.
CREATE TABLE IF NOT EXISTS data_lineage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file     VARCHAR(255) NOT NULL,
    table_name      VARCHAR(100) NOT NULL,
    record_count    INTEGER NOT NULL DEFAULT 0,
    load_timestamp  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status          VARCHAR(20) NOT NULL CHECK (status IN ('SUCCESS', 'PARTIAL', 'FAILED')),
    error_message   TEXT
);
CREATE INDEX IF NOT EXISTS idx_lineage_table ON data_lineage(table_name);
CREATE INDEX IF NOT EXISTS idx_lineage_timestamp ON data_lineage(load_timestamp);

-- Record-level validation failures, referenced by data_lineage's aggregate error_message.
CREATE TABLE IF NOT EXISTS validation_errors (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_file         VARCHAR(255) NOT NULL,
    table_name          VARCHAR(100) NOT NULL,
    record_identifier   VARCHAR(255) NOT NULL,
    error_reason        TEXT NOT NULL,
    logged_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_validation_table ON validation_errors(table_name);

-- Analytics Engine output: one scorecard per customer per computation date.
CREATE TABLE IF NOT EXISTS scorecards (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id         VARCHAR(20) NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    scorecard_date       DATE NOT NULL,
    scorecard_json       TEXT NOT NULL,
    composite_score      INTEGER NOT NULL CHECK (composite_score BETWEEN 0 AND 100),
    created_at           TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_scorecard_customer_date UNIQUE (customer_id, scorecard_date)
);
CREATE INDEX IF NOT EXISTS idx_scorecards_customer ON scorecards(customer_id);

-- AI Engine output: one report per scorecard (customer_id, scorecard_date) generated.
CREATE TABLE IF NOT EXISTS ai_reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id         VARCHAR(20) NOT NULL REFERENCES customers(customer_id) ON DELETE CASCADE,
    scorecard_date       DATE NOT NULL,
    report_json          TEXT NOT NULL,
    generation_method     VARCHAR(20) NOT NULL CHECK (generation_method IN ('gemini', 'fallback')),
    generated_at          TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_ai_report_customer_date UNIQUE (customer_id, scorecard_date)
);
CREATE INDEX IF NOT EXISTS idx_ai_reports_customer ON ai_reports(customer_id);
