"""Environment-driven configuration for the PostgreSQL connection."""

from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

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
    def url(self) -> str:
        return (
            f"postgresql+psycopg2://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}"
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
