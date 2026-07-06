"""Pooled SQLAlchemy engine/session management."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from db.config import load_db_config


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    config = load_db_config()
    return create_engine(
        config.url,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_pre_ping=True,
        future=True,
    )


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
