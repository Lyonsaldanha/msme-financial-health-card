"""ETL Engine: loads synthetic MSME data (GST, UPI, AA, EPFO) into PostgreSQL
with normalization, validation, and full audit lineage.

Public API:
    load_json_to_db(file_path, table_name) -> LoadResult
    validate_data(data_dir) -> dict[str, list[str]]
    run_etl(data_dir="mock_data") -> list[LoadResult]
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from sqlalchemy import text

from db.connection import get_engine
from db.schema import create_tables
from etl.lineage import log_lineage, log_validation_errors
from etl.transform import (
    TransformResult,
    transform_bank_statement,
    transform_customer,
    transform_epfo_record,
    transform_gst_filing,
    transform_upi_transaction,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadResult:
    table_name: str
    source_file: str
    attempted: int
    loaded: int
    skipped: int


@dataclass(frozen=True)
class TableSpec:
    transform: Callable[[dict], TransformResult]
    conflict_columns: tuple[str, ...]
    record_id: Callable[[dict], str]


def _period_id(row: dict) -> str:
    return f"{row['customer_id']}:{row['year']}-{row['month']:02d}"


# Insertion order matters: customers must load before FK-dependent tables.
TABLE_SPECS: dict[str, TableSpec] = {
    "customers": TableSpec(transform_customer, ("customer_id",), lambda r: r["customer_id"]),
    "gst_filings": TableSpec(transform_gst_filing, ("customer_id", "year", "month"), _period_id),
    "upi_transactions": TableSpec(
        transform_upi_transaction,
        ("customer_id", "txn_date"),
        lambda r: f"{r['customer_id']}:{r['txn_date']}",
    ),
    "bank_statements": TableSpec(transform_bank_statement, ("customer_id", "year", "month"), _period_id),
    "epfo_payroll": TableSpec(transform_epfo_record, ("customer_id", "year", "month"), _period_id),
}


def _build_upsert_sql(table: str, columns: list[str], conflict_columns: tuple[str, ...]) -> str:
    """Generic INSERT ... ON CONFLICT DO UPDATE, built from the row's own columns."""
    col_list = ", ".join(columns)
    placeholders = ", ".join(f":{c}" for c in columns)
    update_columns = [c for c in columns if c not in conflict_columns]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_columns)
    set_clause = f"{set_clause}, updated_at = now()" if set_clause else "updated_at = now()"
    return (
        f"INSERT INTO {table} ({col_list}) VALUES ({placeholders}) "
        f"ON CONFLICT ({', '.join(conflict_columns)}) DO UPDATE SET {set_clause}"
    )


def load_json_to_db(file_path: str | Path, table_name: str) -> LoadResult:
    """Load one JSON source file into its target table, upserting idempotently."""
    spec = TABLE_SPECS.get(table_name)
    if spec is None:
        raise ValueError(f"Unknown table_name: {table_name}")

    file_path = Path(file_path)
    try:
        raw_records = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        with get_engine().begin() as conn:
            log_lineage(
                conn,
                source_file=str(file_path),
                table_name=table_name,
                record_count=0,
                status="FAILED",
                error_message=str(exc),
            )
        return LoadResult(table_name, str(file_path), attempted=0, loaded=0, skipped=0)

    rows_to_upsert: list[dict] = []
    skipped = 0

    with get_engine().begin() as conn:
        for raw in raw_records:
            try:
                row, blocking, warnings = spec.transform(raw)
            except (KeyError, ValueError, TypeError) as exc:
                skipped += 1
                log_validation_errors(
                    conn,
                    source_file=file_path.name,
                    table_name=table_name,
                    record_identifier=str(raw.get("customer_id", "UNKNOWN")),
                    errors=[f"transform failed: {exc}"],
                )
                continue

            record_id = spec.record_id(row)
            if warnings:
                log_validation_errors(
                    conn,
                    source_file=file_path.name,
                    table_name=table_name,
                    record_identifier=record_id,
                    errors=warnings,
                )
            if blocking:
                skipped += 1
                log_validation_errors(
                    conn,
                    source_file=file_path.name,
                    table_name=table_name,
                    record_identifier=record_id,
                    errors=blocking,
                )
                continue

            rows_to_upsert.append(row)

        if rows_to_upsert:
            columns = list(rows_to_upsert[0].keys())
            upsert_sql = _build_upsert_sql(table_name, columns, spec.conflict_columns)
            conn.execute(text(upsert_sql), rows_to_upsert)

        status = "SUCCESS" if skipped == 0 else ("PARTIAL" if rows_to_upsert else "FAILED")
        log_lineage(
            conn,
            source_file=file_path.name,
            table_name=table_name,
            record_count=len(rows_to_upsert),
            status=status,
            error_message=None if skipped == 0 else f"{skipped} record(s) failed validation",
        )

    logger.info(
        "Loaded %s: %d/%d rows (%d skipped)",
        table_name,
        len(rows_to_upsert),
        len(raw_records),
        skipped,
    )
    return LoadResult(table_name, str(file_path), len(raw_records), len(rows_to_upsert), skipped)


def validate_data(data_dir: str | Path) -> dict[str, list[str]]:
    """Dry-run validation across all known source files, without writing to the database."""
    data_dir = Path(data_dir)
    report: dict[str, list[str]] = {}

    for table_name, spec in TABLE_SPECS.items():
        file_path = data_dir / f"{table_name}.json"
        if not file_path.exists():
            report[table_name] = [f"{file_path.name} not found"]
            continue

        raw_records = json.loads(file_path.read_text(encoding="utf-8"))
        issues: list[str] = []
        for raw in raw_records:
            try:
                row, blocking, warnings = spec.transform(raw)
            except (KeyError, ValueError, TypeError) as exc:
                issues.append(f"{raw.get('customer_id', 'UNKNOWN')}: transform failed: {exc}")
                continue
            record_id = spec.record_id(row)
            issues.extend(f"{record_id}: {e}" for e in blocking)
            issues.extend(f"{record_id}: {e} (warning)" for e in warnings)
        report[table_name] = issues

    return report


def run_etl(data_dir: str | Path = "mock_data") -> list[LoadResult]:
    """Create tables if needed, then load every known source file in FK-safe order."""
    create_tables()
    data_dir = Path(data_dir)

    results = []
    for table_name in TABLE_SPECS:
        file_path = data_dir / f"{table_name}.json"
        if not file_path.exists():
            logger.warning("Skipping %s: %s not found", table_name, file_path)
            continue
        results.append(load_json_to_db(file_path, table_name))

    return results


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    for result in run_etl():
        print(f"{result.table_name}: loaded {result.loaded}/{result.attempted} (skipped {result.skipped})")
