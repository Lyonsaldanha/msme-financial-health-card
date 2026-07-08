"""Environment-driven configuration for the PostgreSQL connection."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv
from sqlalchemy.engine import URL

load_dotenv()


@dataclass(frozen=True)
class DBConfig:
    host: str
    port: int
    database: str
    user: str
    password: str
    pool_size: int
    max_overflow: int

    @property
    def url(self) -> URL:
        # Cloud Run -> Cloud SQL connects over a Unix socket mounted at
        # /cloudsql/<connection-name>, not a host:port TCP address -- psycopg2
        # expects that as a `host` query param with no port, not a network
        # location. Built via URL.create (not an f-string) so the password is
        # always correctly escaped regardless of what characters it contains.
        if self.host.startswith("/"):
            return URL.create(
                "postgresql+psycopg2",
                username=self.user,
                password=self.password,
                database=self.database,
                query={"host": self.host},
            )
        return URL.create(
            "postgresql+psycopg2",
            username=self.user,
            password=self.password,
            host=self.host,
            port=self.port,
            database=self.database,
        )


def load_db_config() -> DBConfig:
    return DBConfig(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        database=os.getenv("DB_NAME", "msme_fhc_dev"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", "postgres"),
        pool_size=int(os.getenv("DB_POOL_SIZE", "5")),
        max_overflow=int(os.getenv("DB_MAX_OVERFLOW", "10")),
    )
