"""Closed numeric boundaries shared by the standalone GMM pack."""

from __future__ import annotations

from collections.abc import Sequence
import math
from typing import Any

import numpy as np


MAX_OBSERVATIONS = 100_000
MAX_COLUMNS = 100
MAX_CONDITION_NUMBER = 1.0e12


class IVGMMPackError(ValueError):
    """Stable, machine-readable GMM/weak-instrument failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def reject(reason_code: str, message: str) -> None:
    raise IVGMMPackError(reason_code, message)


def numeric_vector(values: Any, *, label: str) -> np.ndarray:
    if isinstance(values, (str, bytes)):
        reject("IV_GMM_INVALID_INPUT", f"{label} must be a numeric vector")
    try:
        raw = np.asarray(values)
        if raw.ndim != 1 or raw.dtype.kind in {"b", "c"}:
            raise ValueError
        normalized = np.asarray(values, dtype=float).copy()
    except (TypeError, ValueError, OverflowError) as exc:
        raise IVGMMPackError(
            "IV_GMM_INVALID_INPUT", f"{label} must be a one-dimensional real vector"
        ) from exc
    if normalized.size < 2 or normalized.size > MAX_OBSERVATIONS:
        reject("IV_GMM_INVALID_INPUT", f"{label} has an unsupported observation count")
    if not np.isfinite(normalized).all():
        reject("IV_GMM_NONFINITE_INPUT", f"{label} contains a non-finite value")
    return normalized


def numeric_matrix(values: Any, *, label: str, rows: int | None = None) -> np.ndarray:
    if isinstance(values, (str, bytes)):
        reject("IV_GMM_INVALID_INPUT", f"{label} must be a numeric matrix")
    try:
        raw = np.asarray(values)
        if raw.ndim != 2 or raw.dtype.kind in {"b", "c"}:
            raise ValueError
        normalized = np.asarray(values, dtype=float).copy()
    except (TypeError, ValueError, OverflowError) as exc:
        raise IVGMMPackError(
            "IV_GMM_INVALID_INPUT", f"{label} must be a two-dimensional real matrix"
        ) from exc
    if normalized.shape[1] < 1 or normalized.shape[1] > MAX_COLUMNS:
        reject("IV_GMM_INVALID_INPUT", f"{label} has an unsupported column count")
    if rows is not None and normalized.shape[0] != rows:
        reject("IV_GMM_INVALID_INPUT", f"{label} row count does not match y")
    if not np.isfinite(normalized).all():
        reject("IV_GMM_NONFINITE_INPUT", f"{label} contains a non-finite value")
    return normalized


def names(value: Sequence[str] | None, *, prefix: str, count: int) -> list[str]:
    if value is None:
        return [f"{prefix}_{index + 1}" for index in range(count)]
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        reject("IV_GMM_INVALID_NAMES", f"{prefix}_names must be a sequence")
    result = list(value)
    if len(result) != count or any(type(item) is not str or not item for item in result):
        reject("IV_GMM_INVALID_NAMES", f"{prefix}_names length does not match its matrix")
    if len(set(result)) != len(result):
        reject("IV_GMM_INVALID_NAMES", f"{prefix}_names must be unique")
    return result


def require_full_rank(matrix: np.ndarray, *, label: str) -> None:
    rank = int(np.linalg.matrix_rank(matrix))
    if rank < matrix.shape[1]:
        reject("IV_GMM_SINGULAR_DESIGN", f"{label} is rank deficient")
    try:
        condition = float(np.linalg.cond(matrix))
    except np.linalg.LinAlgError as exc:
        raise IVGMMPackError("IV_GMM_SINGULAR_DESIGN", f"{label} condition is unavailable") from exc
    if not math.isfinite(condition) or condition > MAX_CONDITION_NUMBER:
        reject("IV_GMM_SINGULAR_DESIGN", f"{label} is numerically ill-conditioned")


def solve(matrix: np.ndarray, vector: np.ndarray, *, label: str) -> np.ndarray:
    try:
        result = np.linalg.solve(matrix, vector)
    except np.linalg.LinAlgError as exc:
        raise IVGMMPackError("IV_GMM_SINGULAR_WEIGHTING", f"{label} cannot be solved") from exc
    if not np.isfinite(result).all():
        reject("IV_GMM_NUMERICAL_FAILURE", f"{label} solution is not finite")
    return np.asarray(result, dtype=float)


def symmetric(matrix: np.ndarray) -> np.ndarray:
    return (np.asarray(matrix, dtype=float) + np.asarray(matrix, dtype=float).T) / 2.0


def finite_scalar(value: Any, *, label: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(
        value, (int, float, np.integer, np.floating)
    ) or not math.isfinite(float(value)):
        reject("IV_GMM_NUMERICAL_FAILURE", f"{label} is not finite")
    return float(value)


__all__ = [
    "IVGMMPackError",
    "MAX_COLUMNS",
    "MAX_CONDITION_NUMBER",
    "MAX_OBSERVATIONS",
    "finite_scalar",
    "names",
    "numeric_matrix",
    "numeric_vector",
    "reject",
    "require_full_rank",
    "solve",
    "symmetric",
]
