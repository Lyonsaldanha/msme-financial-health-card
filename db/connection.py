"""Pooled SQLAlchemy engine/session management."""

from __future__ import annotations

import json
from contextlib import contextmanager
from functools import lru_cache
from typing import Any, Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from db.config import load_db_config


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    config = load_db_config()
    if config.engine == "sqlite":
        # SQLite's default pool class doesn't accept pool_size/max_overflow --
        # create_engine() raises TypeError if you pass them for a sqlite:// URL.
        engine = create_engine(config.url, pool_pre_ping=True, future=True)
        # Unlike Postgres, SQLite enforces foreign keys only if explicitly
        # turned on per-connection -- without this, an orphaned row (e.g. a
        # gst_filings insert for a nonexistent customer_id) would be silently
        # allowed instead of rejected, a safety net the Postgres path always had.
        event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys = ON"))
        return engine
    return create_engine(
        config.url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_pre_ping=True,
        future=True,
    )


def parse_json_field(value: Any) -> Any:
    """Postgres JSONB columns already deserialize to dict/list; SQLite TEXT
    columns (see db/schema_sqlite.sql) come back as a raw JSON string and need
    an explicit parse. Safe to call on either -- a no-op for anything not a str."""
    return json.loads(value) if isinstance(value, str) else value


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional session that commits on success, rolls back on error."""
    session = _session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
