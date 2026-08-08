"""Moran's I, Geary's C, and Getis-Ord global G with bounded permutations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Callable

import numpy as np

from .common import SpatialStatisticsPackError, envelope, fail, permutation_policy, prepare_weights, scope_for, values_1d


def _statistic(values: np.ndarray, weights: np.ndarray, name: str) -> float:
    n = values.size
    if name == "moran_i":
        centered = values - values.mean()
        denominator = float(centered @ centered)
        s0 = float(weights.sum())
        if denominator <= 0.0 or s0 <= 0.0:
            fail("SPATIAL_DEGENERATE_VALUES", "Moran's I requires positive centered variance and weight sum")
        return float(n / s0 * (centered @ weights @ centered) / denominator)
    if name == "geary_c":
        centered = values - values.mean()
        denominator = float(centered @ centered)
        s0 = float(weights.sum())
        if denominator <= 0.0 or s0 <= 0.0:
            fail("SPATIAL_DEGENERATE_VALUES", "Geary's C requires positive centered variance and weight sum")
        numerator = float(((values[:, None] - values[None, :]) ** 2 * weights).sum())
        return float((n - 1.0) / (2.0 * s0) * numerator / denominator)
    if name == "getis_ord_g":
        denominator = float(values.sum() ** 2 - np.square(values).sum())
        if abs(denominator) <= 1e-15:
            fail("SPATIAL_DEGENERATE_VALUES", "Getis-Ord G requires a nonzero pairwise denominator")
        numerator = float((weights * values[:, None] * values[None, :]).sum())
        return float(numerator / denominator)
    raise AssertionError(name)


def _expected(name: str, values: np.ndarray, weights: np.ndarray) -> float:
    if name == "moran_i":
        return float(-1.0 / (values.size - 1))
    if name == "geary_c":
        return 1.0
    return float(weights.sum() / (values.size * (values.size - 1)))


def _permutation_evidence(values: np.ndarray, weights: np.ndarray, name: str, policy: Mapping[str, Any]) -> dict[str, Any]:
    declared = permutation_policy(policy)
    rng = np.random.default_rng(declared["seed"])
    observed = _statistic(values, weights, name)
    reference = _expected(name, values, weights)
    null = np.empty(declared["n_permutations"], dtype=float)
    extreme = 0
    for index in range(null.size):
        permuted = values[rng.permutation(values.size)]
        value = _statistic(permuted, weights, name)
        null[index] = value
        if declared["tail"] == "greater":
            # A strict one-sided comparison keeps an unchanged permutation
            # from being counted twice as its own observed tie.  The choice is
            # visible in the p-value semantics and plus-one correction.
            is_extreme = value > observed + 1e-12
        elif declared["tail"] == "less":
            is_extreme = value < observed - 1e-12
        else:
            is_extreme = abs(value - reference) >= abs(observed - reference) - 1e-12
        extreme += int(is_extreme)
    if declared["plus_one"]:
        p_value = (extreme + 1) / (null.size + 1)
        semantics = "monte_carlo_plus_one"
    else:
        p_value = extreme / null.size
        semantics = "monte_carlo_raw_tail_count"
    return {
        "seed": declared["seed"],
        "tail": declared["tail"],
        "plus_one": declared["plus_one"],
        "p_value": float(p_value),
        "extreme_count": int(extreme),
        "p_value_semantics": semantics,
        "n_permutations": int(null.size),
        "null_summary": {
            "n_permutations": int(null.size),
            "successful_permutations": int(null.size),
            "mean": float(null.mean()),
            "standard_error": float(null.std(ddof=1) / np.sqrt(null.size)) if null.size > 1 else 0.0,
            "minimum": float(null.min()),
            "maximum": float(null.max()),
        },
    }


def _run(values: Any, weights: Any, *, name: str, weight_policy: Mapping[str, Any], permutation_policy: Mapping[str, Any]) -> dict[str, Any]:
    vector = values_1d(values)
    matrix, summary = prepare_weights(vector, weights, weight_policy)
    evidence = _permutation_evidence(vector, matrix, name, permutation_policy)
    result = {
        "method": name,
        "observed_statistic": _statistic(vector, matrix, name),
        "expected_statistic": _expected(name, vector, matrix),
        "reference_semantics": "finite-population permutation expectation",
        "null_summary": evidence["null_summary"],
        "permutation": {key: value for key, value in evidence.items() if key != "null_summary"},
        "weight_summary": summary,
        "scope": scope_for(name),
    }
    return envelope(f"spatial.{name}", vector, matrix, result, summary)


def run_moran_i(values: Any, weights: Any, *, weight_policy: Mapping[str, Any], permutation_policy: Mapping[str, Any]) -> dict[str, Any]:
    return _run(values, weights, name="moran_i", weight_policy=weight_policy, permutation_policy=permutation_policy)


def run_geary_c(values: Any, weights: Any, *, weight_policy: Mapping[str, Any], permutation_policy: Mapping[str, Any]) -> dict[str, Any]:
    return _run(values, weights, name="geary_c", weight_policy=weight_policy, permutation_policy=permutation_policy)


def run_getis_ord_g(values: Any, weights: Any, *, weight_policy: Mapping[str, Any], permutation_policy: Mapping[str, Any]) -> dict[str, Any]:
    return _run(values, weights, name="getis_ord_g", weight_policy=weight_policy, permutation_policy=permutation_policy)


__all__ = ["run_geary_c", "run_getis_ord_g", "run_moran_i"]
