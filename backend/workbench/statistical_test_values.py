"""Shared statistical-test constants, the contract error and finite-float conversion."""

from __future__ import annotations

import math
from typing import Any
import pandas as pd


CATEGORY_MAX_UNIQUE = 20


class StatisticalTestContractError(ValueError):
    """A requested statistical comparison lacks explicit semantic columns."""


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    if not math.isfinite(parsed):
        return None
    return parsed
