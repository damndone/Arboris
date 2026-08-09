"""Explicit graph validation and permutation evidence for spatial statistics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

import numpy as np

from workbench.canonical import sha256_canonical
from workbench.contracts.model.spatial_statistics import make_spatial_statistics_result
from workbench.engine.packs.p7_common import make_p7_scope


class SpatialStatisticsPackError(ValueError):
    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def fail(reason_code: str, message: str) -> None:
    raise SpatialStatisticsPackError(reason_code, message)


def values_1d(values: Any) -> np.ndarray:
    if isinstance(values, (str, bytes)):
        fail("SPATIAL_INVALID_INPUT", "values must be a one-dimensional numeric sequence")
    try:
        raw = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise SpatialStatisticsPackError("SPATIAL_INVALID_INPUT", "values are not an array") from exc
    if raw.ndim != 1 or raw.size < 2 or raw.dtype.kind in {"b", "c", "O", "S", "U"}:
        fail("SPATIAL_INVALID_INPUT", "values must be a one-dimensional real vector of length at least two")
    try:
        result = np.asarray(values, dtype=float).copy()
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpatialStatisticsPackError("SPATIAL_INVALID_INPUT", "values must be numeric") from exc
    if not np.isfinite(result).all():
        fail("SPATIAL_NONFINITE_VALUE", "values must be finite")
    if result.size > 100_000:
        fail("SPATIAL_OUTPUT_TOO_LARGE", "values exceed the supported bound")
    if np.all(result == result[0]):
        fail("SPATIAL_DEGENERATE_VALUES", "values must have positive centered variance")
    return result


def _matrix_from_weights(weights: Any, n: int) -> np.ndarray:
    if isinstance(weights, Mapping):
        kind = weights.get("kind")
        if kind == "matrix":
            if set(weights) != {"kind", "n_nodes", "matrix"}:
                fail("SPATIAL_INVALID_WEIGHTS", "matrix weights have an undeclared field")
            if weights["n_nodes"] != n:
                fail("SPATIAL_DIMENSION_MISMATCH", "weight n_nodes does not match values")
            source = weights["matrix"]
        elif kind == "edges":
            if set(weights) != {"kind", "n_nodes", "edges"}:
                fail("SPATIAL_INVALID_WEIGHTS", "edge weights have an undeclared field")
            if weights["n_nodes"] != n:
                fail("SPATIAL_DIMENSION_MISMATCH", "weight n_nodes does not match values")
            result = np.zeros((n, n), dtype=float)
            seen: set[tuple[int, int]] = set()
            for edge in weights["edges"]:
                if not isinstance(edge, Sequence) or len(edge) != 3:
                    fail("SPATIAL_INVALID_WEIGHTS", "each edge must contain source, target, and weight")
                source_i, target_i, weight = edge
                if type(source_i) is not int or type(target_i) is not int or not 0 <= source_i < n or not 0 <= target_i < n:
                    fail("SPATIAL_INVALID_WEIGHTS", "edge endpoint is outside the graph")
                if (source_i, target_i) in seen:
                    fail("SPATIAL_DUPLICATE_EDGE", "duplicate directed edges are not allowed")
                seen.add((source_i, target_i))
                try:
                    result[source_i, target_i] = float(weight)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise SpatialStatisticsPackError("SPATIAL_INVALID_WEIGHTS", "edge weight must be numeric") from exc
            return result
        else:
            fail("SPATIAL_INVALID_WEIGHTS", "weights kind is not declared")
    else:
        source = weights
    try:
        result = np.asarray(source, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SpatialStatisticsPackError("SPATIAL_INVALID_WEIGHTS", "weights must be a numeric matrix or explicit edge graph") from exc
    if result.shape != (n, n):
        fail("SPATIAL_DIMENSION_MISMATCH", "weights must be square and match values")
    return result.copy()


def prepare_weights(values: np.ndarray, weights: Any, policy: Mapping[str, Any]) -> tuple[np.ndarray, dict[str, Any]]:
    expected = {"normalization", "symmetry_policy", "row_sum_policy", "zero_diagonal_policy", "islands_policy", "negative_weight_policy"}
    if not isinstance(policy, Mapping) or set(policy) != expected:
        fail("SPATIAL_INVALID_POLICY", "weight_policy must be a closed explicit policy")
    allowed = {
        "normalization": {"none", "row_standardize"},
        "symmetry_policy": {"require_symmetric", "allow_asymmetric"},
        "row_sum_policy": {"require_positive", "allow_zero_islands"},
        "zero_diagonal_policy": {"require_zero"},
        "islands_policy": {"reject", "keep_zero"},
        "negative_weight_policy": {"reject"},
    }
    for field, choices in allowed.items():
        if policy[field] not in choices:
            fail("SPATIAL_INVALID_POLICY", f"{field} is not declared")
    matrix = _matrix_from_weights(weights, len(values))
    if not np.isfinite(matrix).all():
        fail("SPATIAL_NONFINITE_WEIGHT", "weights must be finite")
    if np.any(matrix < 0.0):
        fail("SPATIAL_NEGATIVE_WEIGHT", "negative weights are not supported in this pack")
    if np.any(np.diag(matrix) != 0.0):
        fail("SPATIAL_NONZERO_DIAGONAL", "diagonal weights must be zero")
    if policy["symmetry_policy"] == "require_symmetric" and not np.allclose(matrix, matrix.T, rtol=0.0, atol=1e-12):
        fail("SPATIAL_ASYMMETRIC_WEIGHTS", "the declared policy requires a symmetric graph")
    row_sums = matrix.sum(axis=1)
    islands = np.flatnonzero(row_sums == 0.0)
    if islands.size and policy["islands_policy"] == "reject":
        fail("SPATIAL_ISLANDS_PRESENT", "islands require islands_policy=keep_zero")
    if policy["row_sum_policy"] == "require_positive" and islands.size:
        fail("SPATIAL_ZERO_ROW_SUM", "every row must have positive weight")
    normalized = matrix
    if policy["normalization"] == "row_standardize":
        normalized = matrix.copy()
        nonisland = row_sums > 0.0
        normalized[nonisland] /= row_sums[nonisland, None]
    nonzero = normalized != 0.0
    component_edges = (matrix + matrix.T) != 0.0
    components = _component_count(component_edges)
    summary = {
        "n_nodes": int(len(values)),
        "n_edges": int(np.count_nonzero(matrix)),
        "normalization": policy["normalization"],
        "n_islands": int(islands.size),
        "n_components": int(components),
    }
    return normalized, summary


def _component_count(adjacency: np.ndarray) -> int:
    visited: set[int] = set()
    count = 0
    for node in range(adjacency.shape[0]):
        if node in visited:
            continue
        count += 1
        stack = [node]
        visited.add(node)
        while stack:
            current = stack.pop()
            neighbours = np.flatnonzero(adjacency[current])
            for neighbour in neighbours:
                if int(neighbour) not in visited:
                    visited.add(int(neighbour))
                    stack.append(int(neighbour))
    return count


def permutation_policy(policy: Mapping[str, Any]) -> dict[str, Any]:
    expected = {"n_permutations", "seed", "tail", "plus_one"}
    if not isinstance(policy, Mapping) or set(policy) != expected:
        fail("SPATIAL_INVALID_POLICY", "permutation_policy must be a closed explicit policy")
    n = policy["n_permutations"]
    if type(n) is not int or not 1 <= n <= 20_000:
        fail("SPATIAL_INVALID_POLICY", "n_permutations is outside the bounded range")
    seed = policy["seed"]
    if seed is not None and (type(seed) is not int or seed < 0):
        fail("SPATIAL_INVALID_POLICY", "seed must be a non-negative integer or null")
    if policy["tail"] not in {"two-sided", "greater", "less"} or type(policy["plus_one"]) is not bool:
        fail("SPATIAL_INVALID_POLICY", "tail and plus_one must be declared")
    return {"n_permutations": n, "seed": seed, "tail": policy["tail"], "plus_one": policy["plus_one"]}


def scope_for(statistic: str) -> dict[str, Any]:
    return make_p7_scope(
        estimand="global spatial association statistic",
        input_semantics="finite numeric vector and explicit nonnegative weight graph",
        assumptions=[
            "the declared graph represents the relevant spatial-neighbour relation",
            "permutation exchangeability is appropriate under the null",
        ],
        limitations=[
            "permutation evidence is conditional on the supplied weights and observed values",
            "global statistics can conceal local heterogeneity and graph misspecification",
        ],
        not_claimed=[
            "not a local hotspot result, causal effect, or spatial regression coefficient",
            "a small permutation p-value does not identify a spatial mechanism",
        ],
        unsupported_extensions=[
            "local Moran, local Getis, spatial lag/error regression, learned adjacency",
        ],
    )


def envelope(operation_id: str, values: np.ndarray, weights: np.ndarray, result: Mapping[str, Any], summary: Mapping[str, Any]) -> dict[str, Any]:
    digest = sha256_canonical({"operation_id": operation_id, "result": result})
    return make_spatial_statistics_result(
        operation_id=operation_id,
        status="completed",
        reason_code="SPATIAL_COMPLETED",
        n_observations=int(values.size),
        n_edges=int(summary["n_edges"]),
        result=result,
        evidence_digest=digest,
    )


__all__ = ["SpatialStatisticsPackError", "envelope", "fail", "permutation_policy", "prepare_weights", "scope_for", "values_1d"]
