"""Environment-driven database configuration.

Defaults to PostgreSQL. Set DB_ENGINE=sqlite to use a local SQLite file
instead -- added for a Cloud Run deployment path with no separate database
service (see deploy-cloud-run.sh): one less billed resource on a small trial
budget, at the cost of the container's filesystem being ephemeral (data
written at runtime doesn't survive a cold start unless baked into the image
at build time -- see deploy-cloud-run.sh's own notes on that tradeoff).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()


@dataclass(frozen=True)
class DBConfig:
    engine: str  # "postgres" or "sqlite"
    url: URL | str
    pool_size: int
    max_overflow: int


def _load_postgres_config() -> DBConfig:
    host = os.getenv("DB_HOST", "localhost")
    port = int(os.getenv("DB_PORT", "5432"))
    database = os.getenv("DB_NAME", "msme_fhc_dev")
    user = os.getenv("DB_USER", "postgres")
    password = os.getenv("DB_PASSWORD", "postgres")

    # Cloud Run -> Cloud SQL connects over a Unix socket mounted at
    # /cloudsql/<connection-name>, not a host:port TCP address -- psycopg2
    # expects that as a `host` query param with no port, not a network
    # location. Built via URL.create (not an f-string) so the password is
    # always correctly escaped regardless of what characters it contains.
    if host.startswith("/"):
        url = URL.create(
            "postgresql+psycopg2", username=user, password=password, database=database, query={"host": host}
        )
    else:
        url = URL.create(
            "postgresql+psycopg2", username=user, password=password, host=host, port=port, database=database
        )

    return DBConfig(
        engine="postgres",
        url=url,
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    )


def _load_sqlite_config() -> DBConfig:
    path = os.getenv("SQLITE_PATH", "msme_fhc.db")
    # pool_size/max_overflow aren't meaningful for SQLite's pool class and
    # create_engine() rejects them outright for a sqlite:// URL -- see
    # db/connection.py, which only passes these through for engine="postgres".
    return DBConfig(engine="sqlite", url=f"sqlite:///{path}", pool_size=0, max_overflow=0)


def load_db_config() -> DBConfig:
    if os.getenv("DB_ENGINE", "postgres").lower() == "sqlite":
        return _load_sqlite_config()
    return _load_postgres_config()
