"""Scheffe and Games-Howell pairwise comparisons with explicit semantics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from itertools import combinations
import math
from typing import Any

import numpy as np
from scipy import stats

from workbench.canonical import sha256_canonical
from workbench.contracts.model.multiple_comparisons import make_multiple_comparisons_result

from .studentized_range import studentized_range_upper_tail


MAX_GROUPS = 100
MAX_OBSERVATIONS = 100_000


class MultipleComparisonsPackError(ValueError):
    """Stable, machine-readable multiple-comparisons failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _reject(reason_code: str, message: str) -> None:
    raise MultipleComparisonsPackError(reason_code, message)


def _alpha(value: Any) -> float:
    if type(value) not in {int, float} or isinstance(value, bool):
        _reject("MULTIPLE_COMPARISONS_INVALID_INPUT", "alpha must be finite in (0, 1)")
    alpha = float(value)
    if not math.isfinite(alpha) or not 0.0 < alpha < 1.0:
        _reject("MULTIPLE_COMPARISONS_INVALID_INPUT", "alpha must be finite in (0, 1)")
    return alpha


def _groups(groups: Mapping[str, Sequence[float]]) -> tuple[list[str], dict[str, np.ndarray]]:
    if not isinstance(groups, Mapping):
        _reject("MULTIPLE_COMPARISONS_INVALID_INPUT", "groups must be a mapping")
    if len(groups) < 2:
        _reject("MULTIPLE_COMPARISONS_TOO_FEW_GROUPS", "at least two groups are required")
    if len(groups) > MAX_GROUPS:
        _reject("MULTIPLE_COMPARISONS_INVALID_INPUT", "group count exceeds the hard bound")
    if any(type(name) is not str or not name for name in groups):
        _reject("MULTIPLE_COMPARISONS_INVALID_INPUT", "group names must be non-empty strings")
    labels = sorted(groups)
    normalized: dict[str, np.ndarray] = {}
    total = 0
    for label in labels:
        values = groups[label]
        if isinstance(values, (str, bytes)):
            _reject("MULTIPLE_COMPARISONS_INVALID_INPUT", f"group {label!r} is not numeric")
        try:
            raw = np.asarray(values)
            if raw.ndim != 1 or raw.dtype.kind in {"b", "c"}:
                raise ValueError
            array = np.asarray(values, dtype=float).copy()
        except (TypeError, ValueError, OverflowError) as exc:
            raise MultipleComparisonsPackError(
                "MULTIPLE_COMPARISONS_INVALID_INPUT", f"group {label!r} is not numeric"
            ) from exc
        if len(array) < 2:
            _reject(
                "MULTIPLE_COMPARISONS_TOO_FEW_OBSERVATIONS",
                f"group {label!r} must contain at least two observations",
            )
        if not np.isfinite(array).all():
            _reject(
                "MULTIPLE_COMPARISONS_INVALID_INPUT",
                f"group {label!r} contains a non-finite value",
            )
        if float(np.var(array, ddof=1)) <= 0.0:
            _reject(
                "MULTIPLE_COMPARISONS_DEGENERATE_VARIANCE",
                f"group {label!r} has zero sample variance",
            )
        normalized[label] = array
        total += len(array)
    if total > MAX_OBSERVATIONS:
        _reject("MULTIPLE_COMPARISONS_INVALID_INPUT", "observation count exceeds the hard bound")
    return labels, normalized


def _envelope(
    *,
    operation_id: str,
    labels: list[str],
    n_observations: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    digest = sha256_canonical(
        {
            "operation_id": operation_id,
            "n_observations": n_observations,
            "group_names": labels,
            "result": result,
        }
    )
    return make_multiple_comparisons_result(
        operation_id=operation_id,
        status="completed",
        reason_code="MULTIPLE_COMPARISONS_COMPLETED",
        n_observations=n_observations,
        group_names=labels,
        result=result,
        evidence_digest=digest,
    )


def _common_result(
    *,
    method: str,
    labels: list[str],
    arrays: dict[str, np.ndarray],
    alpha: float,
) -> dict[str, Any]:
    return {
        "method": method,
        "alpha": alpha,
        "family": "all_group_pairs",
        "group_count": len(labels),
        "observation_count": sum(len(arrays[label]) for label in labels),
        "group_sizes": {label: len(arrays[label]) for label in labels},
        "assumptions": [
            "independent observations within and between groups",
            "finite real-valued outcomes",
        ],
    }


def run_scheffe(
    groups: Mapping[str, Sequence[float]], *, alpha: float = 0.05
) -> dict[str, Any]:
    """Run Scheffe-adjusted pairwise comparisons using pooled ANOVA MSE."""

    level = _alpha(alpha)
    labels, arrays = _groups(groups)
    total_n = sum(len(arrays[label]) for label in labels)
    group_count = len(labels)
    degrees_between = group_count - 1
    degrees_within = total_n - group_count
    if degrees_within <= 0:
        _reject("MULTIPLE_COMPARISONS_TOO_FEW_OBSERVATIONS", "within-group degrees of freedom must be positive")
    grand_mean = sum(float(np.sum(arrays[label])) for label in labels) / total_n
    ss_between = sum(
        len(arrays[label]) * (float(np.mean(arrays[label])) - grand_mean) ** 2
        for label in labels
    )
    ss_within = sum(
        float(np.sum((arrays[label] - np.mean(arrays[label])) ** 2)) for label in labels
    )
    mse = ss_within / degrees_within
    if not math.isfinite(mse) or mse <= 0.0:
        _reject("MULTIPLE_COMPARISONS_DEGENERATE_VARIANCE", "pooled MSE is not positive")
    omnibus_f = (ss_between / degrees_between) / mse
    omnibus_p = float(stats.f.sf(omnibus_f, degrees_between, degrees_within))
    comparisons: list[dict[str, Any]] = []
    critical = float(stats.f.ppf(1.0 - level, degrees_between, degrees_within))
    for left, right in combinations(labels, 2):
        left_values, right_values = arrays[left], arrays[right]
        difference = float(np.mean(left_values) - np.mean(right_values))
        standard_error = math.sqrt(mse * (1.0 / len(left_values) + 1.0 / len(right_values)))
        statistic = difference / standard_error
        p_value = float(stats.f.sf(statistic**2 / degrees_between, degrees_between, degrees_within))
        half_width = math.sqrt(degrees_between * critical) * standard_error
        comparisons.append(
            {
                "group1": left,
                "group2": right,
                "mean_difference": difference,
                "standard_error": standard_error,
                "statistic": statistic,
                "distribution": "F",
                "degrees_of_freedom": degrees_within,
                "p_value": p_value,
                "confidence_interval": [difference - half_width, difference + half_width],
                "reject": p_value < level,
            }
        )
    result = _common_result(method="scheffe", labels=labels, arrays=arrays, alpha=level)
    result.update(
        {
            "degrees_of_freedom_between": degrees_between,
            "degrees_of_freedom_within": degrees_within,
            "pooled_mean_square_error": mse,
            "omnibus": {
                "statistic": omnibus_f,
                "p_value": omnibus_p,
                "distribution": "F",
            },
            "comparisons": comparisons,
        }
    )
    return _envelope(
        operation_id="multiple_comparisons.scheffe",
        labels=labels,
        n_observations=total_n,
        result=result,
    )


def run_games_howell(
    groups: Mapping[str, Sequence[float]], *, alpha: float = 0.05
) -> dict[str, Any]:
    """Run Games-Howell comparisons with Welch df and studentized-range tails."""

    level = _alpha(alpha)
    labels, arrays = _groups(groups)
    total_n = sum(len(arrays[label]) for label in labels)
    comparisons: list[dict[str, Any]] = []
    for left, right in combinations(labels, 2):
        left_values, right_values = arrays[left], arrays[right]
        left_variance = float(np.var(left_values, ddof=1))
        right_variance = float(np.var(right_values, ddof=1))
        variance_sum = left_variance / len(left_values) + right_variance / len(right_values)
        if variance_sum <= 0.0 or not math.isfinite(variance_sum):
            _reject("MULTIPLE_COMPARISONS_DEGENERATE_VARIANCE", "Games-Howell standard error is invalid")
        degrees_of_freedom = variance_sum**2 / (
            (left_variance / len(left_values)) ** 2 / (len(left_values) - 1)
            + (right_variance / len(right_values)) ** 2 / (len(right_values) - 1)
        )
        difference = float(np.mean(left_values) - np.mean(right_values))
        welch_standard_error = math.sqrt(variance_sum)
        welch_statistic = difference / welch_standard_error
        welch_p_value = float(2.0 * stats.t.sf(abs(welch_statistic), degrees_of_freedom))
        studentized_range_standard_error = math.sqrt(0.5 * variance_sum)
        studentized_statistic = abs(difference) / studentized_range_standard_error
        p_value, p_value_backend = studentized_range_upper_tail(
            studentized_statistic, len(labels), degrees_of_freedom
        )
        critical = float(
            stats.studentized_range.ppf(
                1.0 - level, len(labels), degrees_of_freedom
            )
        )
        half_width = critical * math.sqrt(0.5 * variance_sum)
        comparisons.append(
            {
                "group1": left,
                "group2": right,
                "mean_difference": difference,
                "standard_error": studentized_range_standard_error,
                "welch_standard_error": welch_standard_error,
                "statistic": studentized_statistic,
                "welch_statistic": welch_statistic,
                "distribution": "studentized_range",
                "p_value_backend": p_value_backend,
                "degrees_of_freedom": degrees_of_freedom,
                "p_value": p_value,
                "critical_value": critical,
                "welch_p_value": welch_p_value,
                "confidence_interval": [difference - half_width, difference + half_width],
                "reject": p_value < level,
            }
        )
    result = _common_result(method="games_howell", labels=labels, arrays=arrays, alpha=level)
    result.update(
        {
            "critical_distribution": "studentized_range",
            "p_value_semantics": "studentized_range_tail_with_welch_df",
            "comparisons": comparisons,
        }
    )
    return _envelope(
        operation_id="multiple_comparisons.games_howell",
        labels=labels,
        n_observations=total_n,
        result=result,
    )


__all__ = ["MAX_GROUPS", "MAX_OBSERVATIONS", "MultipleComparisonsPackError", "run_games_howell", "run_scheffe"]
