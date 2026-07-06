"""Idempotent table creation from schema.sql."""

from __future__ import annotations

from pathlib import Path

from db.connection import get_engine

_SCHEMA_FILE = Path(__file__).parent / "schema.sql"


def create_tables() -> None:
    """Create all tables/indexes if they do not already exist."""
    ddl = _SCHEMA_FILE.read_text(encoding="utf-8")
    with get_engine().begin() as conn:
        conn.exec_driver_sql(ddl)
