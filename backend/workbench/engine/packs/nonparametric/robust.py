"""Bounded robust descriptive summaries."""

from __future__ import annotations

from collections.abc import Sequence
import math
from typing import Any

import numpy as np

from .common import alpha_value, clean_1d, reject, result


def _fraction(value: float, name: str) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        reject("NONPARAMETRIC_INVALID_INPUT", f"{name} must be finite in [0, 0.5)")
    fraction = float(value)
    if not math.isfinite(fraction) or not 0.0 <= fraction < 0.5:
        reject("NONPARAMETRIC_INVALID_INPUT", f"{name} must be finite in [0, 0.5)")
    return fraction


def _winsorized(values: np.ndarray, fraction: float) -> float:
    sorted_values = np.sort(values.copy())
    count = int(np.floor(fraction * sorted_values.size))
    if count:
        sorted_values[:count] = sorted_values[count]
        sorted_values[-count:] = sorted_values[-count - 1]
    return float(np.mean(sorted_values))


def run_robust_summary(
    values: Sequence[float],
    *,
    trim_fraction: float = 0.2,
    winsor_fraction: float = 0.2,
    missing_policy: str = "reject",
    alpha: float = 0.05,
) -> dict[str, Any]:
    level = alpha_value(alpha)
    trim = _fraction(trim_fraction, "trim_fraction")
    winsor = _fraction(winsor_fraction, "winsor_fraction")
    array = clean_1d(values, "values", missing_policy=missing_policy)
    if array.size < 3:
        reject("NONPARAMETRIC_TOO_FEW_OBSERVATIONS", "robust summary needs at least three observations")
    median = float(np.median(array))
    mad = float(np.median(np.abs(array - median)))
    q1, q3 = np.quantile(array, [0.25, 0.75])
    trim_count = int(np.floor(trim * array.size))
    if trim_count * 2 >= array.size:
        reject("NONPARAMETRIC_INVALID_INPUT", "trim_fraction leaves no observations")
    trimmed = np.sort(array)[trim_count : array.size - trim_count]
    return result(
        operation_id="nonparametric.robust_summary",
        n_observations=array.size,
        method="robust_descriptive_summary",
        estimand="descriptive robust location and spread summaries",
        input_semantics="one finite numeric sample",
        assumptions=["observations are treated as a declared descriptive sample"],
        limitations=["summaries are not structural-model estimates", "confidence intervals are not included in this descriptive operation"],
        not_claimed=["does not establish a causal effect", "does not prove a population distribution from a finite sample"],
        unsupported_extensions=["survey-weighted robust variance and robust regression are not included"],
        alpha=level,
        sample_size=int(array.size),
        summary={
            "median": median,
            "mad": mad,
            "mad_normal_consistent": float(1.4826 * mad),
            "q1": float(q1),
            "q3": float(q3),
            "trimmed_mean": float(np.mean(trimmed)),
            "winsorized_mean": _winsorized(array, winsor),
            "trim_fraction": trim,
            "winsor_fraction": winsor,
        },
        inference={"method": "descriptive", "confidence_level": 1.0 - level},
        spread={"iqr": float(q3 - q1), "min": float(np.min(array)), "max": float(np.max(array))},
    )
