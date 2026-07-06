"""Pure statistics helpers shared by the ratio computations.

All functions are defensive about the small-sample, empty-series, and
divide-by-zero edge cases that show up with 12-point monthly series
(e.g. a single month of history, or a customer with zero GST records).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def coefficient_of_variation(series: pd.Series) -> float | None:
    """StdDev / Mean, as a fraction (0.12 == 12%). None if mean is 0 or no data."""
    if series.empty:
        return None
    avg = series.mean()
    if avg == 0:
        return None
    return float(series.std(ddof=1) / avg) if len(series) > 1 else 0.0


def cagr(first_value: float, last_value: float, years: float = 1.0) -> float | None:
    """Compound annual growth rate as a fraction. None if first_value <= 0."""
    if first_value <= 0:
        return None
    return (last_value / first_value) ** (1 / years) - 1


def mom_growth(previous_value: float, current_value: float) -> float | None:
    """Month-over-month growth as a fraction. None if previous_value is 0."""
    if previous_value == 0:
        return None
    return (current_value - previous_value) / previous_value


def linregress_slope(series: pd.Series) -> float:
    """Slope of a simple linear regression against the point index (0..n-1)."""
    if len(series) < 2:
        return 0.0
    x = np.arange(len(series))
    slope, _intercept = np.polyfit(x, series.to_numpy(dtype=float), 1)
    return float(slope)
