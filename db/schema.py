"""Idempotent table creation from schema.sql (Postgres) or schema_sqlite.sql."""

from __future__ import annotations

from pathlib import Path

from db.connection import get_engine

_SCHEMA_FILE_POSTGRES = Path(__file__).parent / "schema.sql"
_SCHEMA_FILE_SQLITE = Path(__file__).parent / "schema_sqlite.sql"


def create_tables() -> None:
    """Create all tables/indexes if they do not already exist."""
    engine = get_engine()
    schema_file = _SCHEMA_FILE_SQLITE if engine.dialect.name == "sqlite" else _SCHEMA_FILE_POSTGRES
    ddl = schema_file.read_text(encoding="utf-8")

    # Split into individual statements rather than one exec_driver_sql(ddl) call:
    # SQLite's DBAPI rejects multiple ;-separated statements in a single execute()
    # (psycopg2 accepts it, but this works identically for both, so there's no
    # need for dialect-specific execution here, only a dialect-specific DDL file).
    statements = [s.strip() for s in ddl.split(";") if s.strip()]
    with engine.begin() as conn:
        for statement in statements:
            conn.exec_driver_sql(statement)
