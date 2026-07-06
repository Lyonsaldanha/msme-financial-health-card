"""Row-level validation rules.

Each validator returns a ValidationResult splitting failures into:
- blocking: the row is corrupt/unsafe to load and is skipped (still logged).
- warnings: a data-quality issue worth flagging but not severe enough to drop the row
  (e.g. synthetic GST numbers that don't match the real 15-char GSTIN format).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from etl.normalizers import NOT_REGISTERED


@dataclass
class ValidationResult:
    blocking: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.blocking


def _reject_future_date(value: date, field_name: str, errors: list[str]) -> None:
    if value > date.today():
        errors.append(f"{field_name} '{value}' is in the future")


def validate_customer(row: dict) -> ValidationResult:
    result = ValidationResult()
    if not row.get("business_name"):
        result.blocking.append("business_name is required")
    if not row.get("pan"):
        result.blocking.append("pan is required")

    gst_number = row.get("gst_number", "")
    if gst_number != NOT_REGISTERED and len(gst_number) != 15:
        result.warnings.append(
            f"gst_number '{gst_number}' is {len(gst_number)} chars, "
            f"expected 15 (or '{NOT_REGISTERED}' for an NTC customer)"
        )

    _reject_future_date(row["registration_date"], "registration_date", result.blocking)
    return result


def validate_gst_filing(row: dict) -> ValidationResult:
    result = ValidationResult()
    if not 1 <= row["month"] <= 12:
        result.blocking.append(f"month {row['month']} out of range 1-12")
    if row["gstr_sales_paise"] <= 0:
        result.blocking.append("gstr_sales must be > 0 for a GST-registered customer")
    if row["tax_paid_paise"] < 0:
        result.blocking.append("tax_paid cannot be negative")
    _reject_future_date(row["filing_date"], "filing_date", result.blocking)
    return result


def validate_upi_transaction(row: dict) -> ValidationResult:
    result = ValidationResult()
    if row["collections_paise"] < 0:
        result.blocking.append("collections cannot be negative")
    if row["num_transactions"] <= 0:
        result.blocking.append("num_transactions must be > 0")
    _reject_future_date(row["txn_date"], "txn_date", result.blocking)
    return result


def validate_bank_statement(row: dict) -> ValidationResult:
    result = ValidationResult()
    if not 1 <= row["month"] <= 12:
        result.blocking.append(f"month {row['month']} out of range 1-12")
    if row["dscr"] <= 0:
        result.blocking.append(f"dscr {row['dscr']} must be > 0")
    if row["total_credits_paise"] < 0 or row["total_debits_paise"] < 0:
        result.blocking.append("credits/debits cannot be negative")
    if row["total_debits_paise"] > row["total_credits_paise"]:
        result.warnings.append(
            f"total_debits ({row['total_debits_paise']}) exceeds "
            f"total_credits ({row['total_credits_paise']}) - cash flow anomaly"
        )
    return result


def validate_epfo_record(row: dict) -> ValidationResult:
    result = ValidationResult()
    if not 1 <= row["month"] <= 12:
        result.blocking.append(f"month {row['month']} out of range 1-12")
    if row["employee_count"] <= 0:
        result.blocking.append("employee_count must be > 0")
    if row["monthly_payroll_paise"] < 0:
        result.blocking.append("monthly_payroll cannot be negative")
    _reject_future_date(row["contribution_date"], "contribution_date", result.blocking)
    return result
