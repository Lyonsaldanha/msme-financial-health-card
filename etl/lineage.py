"""Audit trail writers for data_lineage and validation_errors."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def log_lineage(
    conn: Connection,
    *,
    source_file: str,
    table_name: str,
    record_count: int,
    status: str,
    error_message: str | None = None,
) -> None:
    conn.execute(
        text(
            """
            INSERT INTO data_lineage (source_file, table_name, record_count, status, error_message)
            VALUES (:source_file, :table_name, :record_count, :status, :error_message)
            """
        ),
        {
            "source_file": source_file,
            "table_name": table_name,
            "record_count": record_count,
            "status": status,
            "error_message": error_message,
        },
    )


def log_validation_errors(
    conn: Connection,
    *,
    source_file: str,
    table_name: str,
    record_identifier: str,
    errors: list[str],
) -> None:
    if not errors:
        return
    conn.execute(
        text(
            """
            INSERT INTO validation_errors (source_file, table_name, record_identifier, error_reason)
            VALUES (:source_file, :table_name, :record_identifier, :error_reason)
            """
        ),
        [
            {
                "source_file": source_file,
                "table_name": table_name,
                "record_identifier": record_identifier,
                "error_reason": error,
            }
            for error in errors
        ],
    )
