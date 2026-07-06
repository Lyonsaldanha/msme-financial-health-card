"""Raw JSON row -> normalized DB row, paired with its validation outcome."""

from __future__ import annotations

from typing import Any

from etl.normalizers import normalize_date, normalize_gst_number, normalize_sector, to_paise
from etl.validators import (
    validate_bank_statement,
    validate_customer,
    validate_epfo_record,
    validate_gst_filing,
    validate_upi_transaction,
)

# A transform returns (normalized_row, blocking_errors, warnings).
TransformResult = tuple[dict[str, Any], list[str], list[str]]


def transform_customer(raw: dict[str, Any]) -> TransformResult:
    row = {
        "customer_id": raw["customer_id"],
        "business_name": raw["business_name"].strip(),
        "sector": normalize_sector(raw["sector"]),
        "persona": raw.get("persona"),
        "gst_number": normalize_gst_number(raw["gst_number"]),
        "pan": raw["pan"].strip().upper(),
        "registration_date": normalize_date(raw["registration_date"]),
    }
    result = validate_customer(row)
    return row, result.blocking, result.warnings


def transform_gst_filing(raw: dict[str, Any]) -> TransformResult:
    row = {
        "customer_id": raw["customer_id"],
        "month": int(raw["month"]),
        "year": int(raw["year"]),
        "gstr_sales_paise": to_paise(raw["gstr_sales"]),
        "tax_paid_paise": to_paise(raw["tax_paid"]),
        "filing_date": normalize_date(raw["filing_date"]),
        "is_delayed": bool(raw["is_delayed"]),
    }
    result = validate_gst_filing(row)
    return row, result.blocking, result.warnings


def transform_upi_transaction(raw: dict[str, Any]) -> TransformResult:
    row = {
        "customer_id": raw["customer_id"],
        "txn_date": normalize_date(raw["date"]),
        "day_of_week": raw["day_of_week"],
        "collections_paise": to_paise(raw["collections"]),
        "num_transactions": int(raw["num_transactions"]),
        "avg_ticket_size_paise": to_paise(raw["avg_ticket_size"]),
    }
    result = validate_upi_transaction(row)
    return row, result.blocking, result.warnings


def transform_bank_statement(raw: dict[str, Any]) -> TransformResult:
    row = {
        "customer_id": raw["customer_id"],
        "month": int(raw["month"]),
        "year": int(raw["year"]),
        "total_credits_paise": to_paise(raw["total_credits"]),
        "total_debits_paise": to_paise(raw["total_debits"]),
        "payroll_paid_paise": to_paise(raw["payroll_paid"]),
        "operating_expenses_paise": to_paise(raw["operating_expenses"]),
        "tax_payments_paise": to_paise(raw["tax_payments"]),
        "existing_emi_paise": to_paise(raw["existing_emi"]),
        "operating_surplus_paise": to_paise(raw["operating_surplus"]),
        "avg_daily_balance_paise": to_paise(raw["avg_daily_balance"]),
        "dscr": float(raw["dscr"]),
        "cheque_returns": int(raw["cheque_returns"]),
        "cash_withdrawals_paise": to_paise(raw["cash_withdrawals"]),
    }
    result = validate_bank_statement(row)
    return row, result.blocking, result.warnings


def transform_epfo_record(raw: dict[str, Any]) -> TransformResult:
    row = {
        "customer_id": raw["customer_id"],
        "month": int(raw["month"]),
        "year": int(raw["year"]),
        "employee_count": int(raw["employee_count"]),
        "monthly_payroll_paise": to_paise(raw["monthly_payroll"]),
        "avg_wage_paise": to_paise(raw["avg_wage"]),
        "contribution_date": normalize_date(raw["contribution_date"]),
        "is_late_contribution": bool(raw["is_late_contribution"]),
        "employee_churn": int(raw["employee_churn"]),
    }
    result = validate_epfo_record(row)
    return row, result.blocking, result.warnings
