"""Shared JSON and numeric helpers for the standalone time-series pack."""

from __future__ import annotations

from typing import Any

import numpy as np

from .errors import TimeSeriesPackError


def json_native(value: Any) -> Any:
    """Convert finite NumPy/pandas-compatible values to JSON-shaped values."""

    if isinstance(value, np.ndarray):
        return [json_native(item) for item in value.tolist()]
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        number = float(value)
        if not np.isfinite(number):
            raise TimeSeriesPackError(
                "TIME_SERIES_NON_FINITE_RESULT", "result contains a non-finite number"
            )
        return number
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, (complex, np.complexfloating)):
        number = complex(value)
        if not np.isfinite(number.real) or not np.isfinite(number.imag) or abs(number.imag) > 1e-10:
            raise TimeSeriesPackError(
                "TIME_SERIES_NON_FINITE_RESULT",
                "result contains a materially complex number",
            )
        return float(number.real)
    if isinstance(value, dict):
        if any(type(key) is not str for key in value):
            raise TimeSeriesPackError(
                "TIME_SERIES_BAD_RESULT", "result mapping keys must already be strings"
            )
        return {key: json_native(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_native(item) for item in value]
    if isinstance(value, float) and not np.isfinite(value):
        raise TimeSeriesPackError(
            "TIME_SERIES_NON_FINITE_RESULT", "result contains a non-finite number"
        )
    return value


__all__ = ["json_native"]
