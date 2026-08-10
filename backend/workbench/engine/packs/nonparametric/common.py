"""Validation and bounded result helpers for nonparametric kernels."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import math
from typing import Any

import numpy as np

from workbench.contracts.model.nonparametric import (
    MAX_NONPARAMETRIC_OBSERVATIONS,
    make_result_envelope,
)
from workbench.engine.packs.p7_common import make_p7_scope


MAX_PERMUTATION_RESAMPLES = 20_000
MIN_PERMUTATION_RESAMPLES = 99


class NonparametricPackError(ValueError):
    """Stable machine-readable nonparametric failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def reject(reason_code: str, message: str) -> None:
    raise NonparametricPackError(reason_code, message)


def _numeric_1d(values: Sequence[float], name: str) -> np.ndarray:
    if isinstance(values, (str, bytes)):
        reject("NONPARAMETRIC_INVALID_INPUT", f"{name} must be a numeric sequence")
    try:
        raw = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise NonparametricPackError("NONPARAMETRIC_INVALID_INPUT", f"{name} is not an array") from exc
    if raw.ndim != 1 or raw.dtype.kind in {"b", "c", "O", "S", "U"}:
        reject("NONPARAMETRIC_INVALID_INPUT", f"{name} must be a one-dimensional real numeric sequence")
    try:
        array = np.asarray(values, dtype=float).copy()
    except (TypeError, ValueError, OverflowError) as exc:
        raise NonparametricPackError("NONPARAMETRIC_INVALID_INPUT", f"{name} is not numeric") from exc
    if array.size == 0:
        reject("NONPARAMETRIC_TOO_FEW_OBSERVATIONS", f"{name} must not be empty")
    if array.size > MAX_NONPARAMETRIC_OBSERVATIONS:
        reject("NONPARAMETRIC_OUTPUT_TOO_LARGE", f"{name} exceeds the observation bound")
    return array


def clean_1d(values: Sequence[float], name: str, *, missing_policy: str) -> np.ndarray:
    if missing_policy not in {"reject", "complete_case_v1"}:
        reject("NONPARAMETRIC_UNSUPPORTED_POLICY", "missing_policy is not declared")
    array = _numeric_1d(values, name)
    if np.isinf(array).any():
        reject("NONPARAMETRIC_NONFINITE_VALUE", f"{name} contains infinity")
    if np.isnan(array).any():
        if missing_policy == "reject":
            reject("NONPARAMETRIC_NONFINITE_VALUE", f"{name} contains missing values")
        array = array[np.isfinite(array)]
    if array.size == 0:
        reject("NONPARAMETRIC_NO_COMPLETE_CASES", f"{name} has no complete observations")
    return array


def paired_clean(
    left: Sequence[float], right: Sequence[float], *, missing_policy: str
) -> tuple[np.ndarray, np.ndarray]:
    x = _numeric_1d(left, "left")
    y = _numeric_1d(right, "right")
    if x.size != y.size:
        reject("NONPARAMETRIC_INVALID_INPUT", "paired samples must have equal length")
    if np.isinf(x).any() or np.isinf(y).any():
        reject("NONPARAMETRIC_NONFINITE_VALUE", "paired samples contain infinity")
    mask = np.isfinite(x) & np.isfinite(y)
    if not mask.all() and missing_policy == "reject":
        reject("NONPARAMETRIC_NONFINITE_VALUE", "paired samples contain missing values")
    if missing_policy not in {"reject", "complete_case_v1"}:
        reject("NONPARAMETRIC_UNSUPPORTED_POLICY", "missing_policy is not declared")
    x, y = x[mask], y[mask]
    if x.size == 0:
        reject("NONPARAMETRIC_NO_COMPLETE_CASES", "paired samples have no complete observations")
    return x, y


def groups_clean(
    groups: Mapping[str, Sequence[float]], *, missing_policy: str
) -> tuple[list[str], list[np.ndarray]]:
    if not isinstance(groups, Mapping) or not groups:
        reject("NONPARAMETRIC_INVALID_INPUT", "groups must be a non-empty mapping")
    if any(type(label) is not str or not label for label in groups):
        reject("NONPARAMETRIC_INVALID_INPUT", "group labels must be non-empty strings")
    labels = sorted(groups)
    arrays = [clean_1d(groups[label], f"group {label}", missing_policy=missing_policy) for label in labels]
    if sum(array.size for array in arrays) > MAX_NONPARAMETRIC_OBSERVATIONS:
        reject("NONPARAMETRIC_OUTPUT_TOO_LARGE", "group observations exceed the bound")
    return labels, arrays


def matrix_clean(values: Sequence[Sequence[float]], name: str) -> np.ndarray:
    try:
        raw = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise NonparametricPackError("NONPARAMETRIC_INVALID_INPUT", f"{name} is not a matrix") from exc
    if raw.ndim != 2 or raw.dtype.kind in {"b", "c", "O", "S", "U"}:
        reject("NONPARAMETRIC_INVALID_INPUT", f"{name} must be a two-dimensional real matrix")
    array = np.asarray(values, dtype=float).copy()
    if array.shape[0] < 2 or array.shape[1] < 2:
        reject("NONPARAMETRIC_TOO_FEW_OBSERVATIONS", f"{name} needs at least two rows and columns")
    if array.size > MAX_NONPARAMETRIC_OBSERVATIONS:
        reject("NONPARAMETRIC_OUTPUT_TOO_LARGE", f"{name} exceeds the observation bound")
    if not np.isfinite(array).all():
        reject("NONPARAMETRIC_NONFINITE_VALUE", f"{name} must be finite")
    return array


def alpha_value(alpha: float) -> float:
    if type(alpha) not in {int, float} or isinstance(alpha, bool):
        reject("NONPARAMETRIC_INVALID_INPUT", "alpha must be finite in (0, 1)")
    value = float(alpha)
    if not math.isfinite(value) or not 0.0 < value < 1.0:
        reject("NONPARAMETRIC_INVALID_INPUT", "alpha must be finite in (0, 1)")
    return value


def result(
    *,
    operation_id: str,
    n_observations: int,
    method: str,
    estimand: str,
    input_semantics: str,
    assumptions: Sequence[str],
    limitations: Sequence[str],
    not_claimed: Sequence[str],
    unsupported_extensions: Sequence[str],
    **fields: Any,
) -> dict[str, Any]:
    scope = make_p7_scope(
        estimand=estimand,
        input_semantics=input_semantics,
        assumptions=tuple(assumptions),
        limitations=tuple(limitations),
        not_claimed=tuple(not_claimed),
        unsupported_extensions=tuple(unsupported_extensions),
    )
    payload = {"method": method, "scope": scope, **fields}
    return make_result_envelope(
        operation_id=operation_id,
        status="completed",
        reason_code="NONPARAMETRIC_COMPLETED",
        n_observations=int(n_observations),
        result=payload,
    )
