"""Field-level normalization: currency -> paise, dates -> ISO, sector names, GST numbers."""

from __future__ import annotations

from datetime import date, datetime

PAISE_PER_RUPEE = 100
NOT_REGISTERED = "NOT_REGISTERED"

# Canonical sector names. Extend as new sectors appear in source data.
_SECTOR_ALIASES = {
    "retail": "Retail",
    "services": "Services",
    "healthcare services": "Healthcare Services",
    "food & beverage": "Food & Beverage",
    "manufacturing": "Manufacturing",
    "wholesale trade": "Wholesale Trade",
}


def to_paise(rupees: float | int) -> int:
    """Convert a rupee amount to integer paise."""
    return int(round(float(rupees) * PAISE_PER_RUPEE))


def normalize_sector(sector: str) -> str:
    cleaned = " ".join(sector.strip().split())
    return _SECTOR_ALIASES.get(cleaned.lower(), cleaned.title())


def normalize_date(value: str) -> date:
    """Parse a YYYY-MM-DD string into a date. Raises ValueError on any other format."""
    return datetime.strptime(value, "%Y-%m-%d").date()


def normalize_gst_number(gst_number: str) -> str:
    return gst_number.strip().upper()
