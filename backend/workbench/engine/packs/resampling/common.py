"""Shared safe input/statistic and envelope helpers for resampling packs."""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from workbench.canonical import sha256_canonical
from workbench.contracts.model.resampling import make_resampling_result
from workbench.engine.replicate_combine import ReplicateCombinedResult


MAX_RESAMPLES = 10_000
MAX_OBSERVATIONS = 100_000
MAX_EXACT_PERMUTATION_STATES = 10_000
BOOTSTRAP_STATISTICS = frozenset({"mean", "median"})
PERMUTATION_STATISTICS = frozenset(
    {"difference_in_means", "difference_in_medians"}
)


class ResamplingPackError(ValueError):
    """Stable, machine-readable input or numerical failure."""

    def __init__(self, reason_code: str, message: str) -> None:
        self.reason_code = reason_code
        super().__init__(f"{reason_code}: {message}")


def _reject(reason_code: str, message: str) -> None:
    raise ResamplingPackError(reason_code, message)


def numeric_sample(values: Any, *, label: str, minimum: int = 2) -> np.ndarray:
    """Copy a finite real vector without parsing strings or accepting booleans."""

    if isinstance(values, (str, bytes)):
        _reject("RESAMPLING_INVALID_INPUT", f"{label} must be a numeric vector")
    try:
        raw = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise ResamplingPackError(
            "RESAMPLING_INVALID_INPUT", f"{label} must be a numeric vector"
        ) from exc
    if raw.ndim != 1 or raw.dtype.kind in {"b", "c"}:
        _reject("RESAMPLING_INVALID_INPUT", f"{label} must be a one-dimensional real vector")
    try:
        normalized = np.asarray(values, dtype=float).copy()
    except (TypeError, ValueError, OverflowError) as exc:
        raise ResamplingPackError(
            "RESAMPLING_INVALID_INPUT", f"{label} must contain real numeric values"
        ) from exc
    if len(normalized) < minimum:
        _reject(
            "RESAMPLING_TOO_FEW_OBSERVATIONS",
            f"{label} must contain at least {minimum} observations",
        )
    if len(normalized) > MAX_OBSERVATIONS:
        _reject("RESAMPLING_INVALID_INPUT", f"{label} exceeds the observation bound")
    if not np.isfinite(normalized).all():
        _reject("RESAMPLING_INVALID_INPUT", f"{label} contains a non-finite value")
    return normalized


def bounded_resamples(value: Any) -> int:
    if type(value) is not int or isinstance(value, bool) or value < 2:
        _reject(
            "RESAMPLING_TOO_FEW_REPLICATES",
            "n_resamples must be an integer of at least 2",
        )
    if value > MAX_RESAMPLES:
        _reject("RESAMPLING_INVALID_INPUT", "n_resamples exceeds the hard bound")
    return value


def bounded_seed(value: Any) -> int:
    if type(value) is not int or isinstance(value, bool) or not 0 <= value < (1 << 63):
        _reject("RESAMPLING_INVALID_INPUT", "seed must be a bounded non-negative integer")
    return value


def confidence_alpha(confidence_level: Any) -> tuple[float, float]:
    if type(confidence_level) not in {int, float} or isinstance(confidence_level, bool):
        _reject("RESAMPLING_INVALID_INPUT", "confidence_level must be a finite value in (0, 1)")
    level = float(confidence_level)
    if not math.isfinite(level) or not 0.0 < level < 1.0:
        _reject("RESAMPLING_INVALID_INPUT", "confidence_level must be a finite value in (0, 1)")
    return level, 1.0 - level


def statistic_value(statistic_id: str, values: np.ndarray) -> float:
    if statistic_id not in BOOTSTRAP_STATISTICS:
        _reject("RESAMPLING_UNSUPPORTED_STATISTIC", "statistic_id is not declared for bootstrap")
    if statistic_id == "mean":
        value = float(np.mean(values))
    else:
        value = float(np.median(values))
    if not math.isfinite(value):
        _reject("RESAMPLING_DEGENERATE_STATISTIC", "statistic is not finite")
    return value


def two_sample_statistic(
    statistic_id: str, left: np.ndarray, right: np.ndarray
) -> float:
    if statistic_id not in PERMUTATION_STATISTICS:
        _reject(
            "RESAMPLING_UNSUPPORTED_STATISTIC",
            "statistic_id is not declared for permutation",
        )
    if statistic_id == "difference_in_means":
        value = float(np.mean(left) - np.mean(right))
    else:
        value = float(np.median(left) - np.median(right))
    if not math.isfinite(value):
        _reject("RESAMPLING_DEGENERATE_STATISTIC", "statistic is not finite")
    return value


def completed_envelope(
    *,
    operation_id: str,
    n_observations: int,
    combined: ReplicateCombinedResult,
    result: dict[str, Any],
) -> dict[str, Any]:
    batch = combined.batch.to_dict()
    evidence_digest = sha256_canonical({"batch": batch, "result": result})
    return make_resampling_result(
        operation_id=operation_id,
        status="completed",
        reason_code="RESAMPLING_COMPLETED",
        n_observations=n_observations,
        result=result,
        batch=batch,
        evidence_digest=evidence_digest,
    )


def rejected_envelope(
    *,
    operation_id: str,
    n_observations: int,
    reason_code: str,
    message: str,
) -> dict[str, Any]:
    return make_resampling_result(
        operation_id=operation_id,
        status="rejected",
        reason_code=reason_code,
        n_observations=n_observations,
        result={"message": message},
        batch=None,
        evidence_digest=None,
    )


__all__ = [
    "BOOTSTRAP_STATISTICS",
    "MAX_EXACT_PERMUTATION_STATES",
    "MAX_OBSERVATIONS",
    "MAX_RESAMPLES",
    "PERMUTATION_STATISTICS",
    "ResamplingPackError",
    "bounded_resamples",
    "bounded_seed",
    "completed_envelope",
    "confidence_alpha",
    "numeric_sample",
    "rejected_envelope",
    "statistic_value",
    "two_sample_statistic",
]
