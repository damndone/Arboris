"""Shared validation and bounded evidence helpers for ROC diagnostics."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Any

import numpy as np
import pandas as pd

from workbench.contracts.model.roc_diagnostics import (
    ROC_CALIBRATION_METHODS,
    ROC_DIAGNOSTICS_CONTRACT_VERSION,
    ROC_MISSING_POLICIES,
    ROC_SCORE_SEMANTICS,
    ROC_THRESHOLD_POLICIES,
)

from .errors import RocDiagnosticsPackError


_DEFAULT_QUANTILE_GRID_SIZE = 21
_DEFAULT_MAX_THRESHOLDS = 1001
_DEFAULT_MAX_BINS = 50
_ALLOWED_CONSTRAINT_METRICS = frozenset(
    {"sensitivity", "specificity", "ppv", "npv", "f1", "tpr", "fpr", "precision", "recall"}
)
_ALLOWED_CONSTRAINT_OPERATORS = frozenset({">=", "<=", ">", "<", "=="})


@dataclass(frozen=True)
class PreparedBinaryData:
    y_binary: np.ndarray
    scores: np.ndarray
    positive_label: Any
    negative_label: Any
    missing_metadata: dict[str, Any]


def _fail(reason_code: str, message: str) -> None:
    raise RocDiagnosticsPackError(reason_code, message)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        marker = pd.isna(value)
        if isinstance(marker, (bool, np.bool_)):
            return bool(marker)
    except (TypeError, ValueError):
        pass
    try:
        marker = np.asarray(value)
    except Exception:
        return False
    if marker.ndim != 0:
        return False
    try:
        return bool(np.isnan(marker.item()))
    except (TypeError, ValueError):
        return False


def _safe_equal(left: Any, right: Any) -> bool:
    try:
        value = left == right
    except Exception:
        return False
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    return False


def _json_scalar(value: Any, field_name: str) -> Any:
    if isinstance(value, np.generic):
        value = value.item()
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            _fail("ROC_DIAGNOSTICS_NON_FINITE_INPUT", f"{field_name} must be finite")
        return value
    _fail("ROC_DIAGNOSTICS_INVALID_TARGET", f"{field_name} must be a JSON scalar")


def _as_1d_list(value: Any, field_name: str) -> list[Any]:
    if isinstance(value, (str, bytes)):
        _fail("ROC_DIAGNOSTICS_INVALID_INPUT", f"{field_name} must be a one-dimensional sequence")
    if not isinstance(value, Sequence):
        if not isinstance(value, np.ndarray) and not hasattr(value, "__iter__"):
            _fail("ROC_DIAGNOSTICS_INVALID_INPUT", f"{field_name} must be a one-dimensional sequence")
    try:
        values = list(value)
    except (TypeError, ValueError):
        _fail("ROC_DIAGNOSTICS_INVALID_INPUT", f"{field_name} must be a one-dimensional sequence")
    if any(isinstance(item, (list, tuple, np.ndarray)) and np.asarray(item).ndim > 0 for item in values):
        _fail("ROC_DIAGNOSTICS_INVALID_INPUT", f"{field_name} must be one-dimensional")
    return values


def _validate_choice(value: Any, choices: frozenset[str], field_name: str) -> str:
    if type(value) is not str or value not in choices:
        _fail("ROC_DIAGNOSTICS_UNKNOWN_POLICY", f"{field_name} is not declared")
    return value


def _validate_positive_integer(value: Any, field_name: str) -> int:
    if type(value) is not int or value < 1:
        _fail("ROC_DIAGNOSTICS_INVALID_OPTION", f"{field_name} must be a positive integer")
    return value


def _validate_nonnegative_finite(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
        _fail("ROC_DIAGNOSTICS_INVALID_OPTION", f"{field_name} must be a finite non-negative number")
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0.0:
        _fail("ROC_DIAGNOSTICS_INVALID_OPTION", f"{field_name} must be a finite non-negative number")
    return normalized


def _validate_inputs(
    y_true: Any,
    scores: Any,
    *,
    positive_label: Any,
    score_semantics: str,
    missing_policy: str,
) -> PreparedBinaryData:
    if type(score_semantics) is not str or score_semantics not in ROC_SCORE_SEMANTICS:
        _fail("ROC_DIAGNOSTICS_INVALID_SCORE_SEMANTICS", "score_semantics is not declared")
    _validate_choice(missing_policy, ROC_MISSING_POLICIES, "missing_policy")
    y_values = _as_1d_list(y_true, "y_true")
    score_values = _as_1d_list(scores, "scores")
    n_input = len(y_values)
    if len(y_values) != len(score_values):
        _fail("ROC_DIAGNOSTICS_LENGTH_MISMATCH", "y_true and scores must have equal length")
    if not y_values:
        _fail("ROC_DIAGNOSTICS_EMPTY_INPUT", "at least one observation is required")

    missing_indices = [
        index
        for index, (target, score) in enumerate(zip(y_values, score_values))
        if _is_missing(target) or _is_missing(score)
    ]
    if missing_indices and missing_policy == "reject":
        _fail(
            "ROC_DIAGNOSTICS_MISSING_VALUE",
            "missing target or score requires missing_policy=drop_explicit",
        )
    if missing_indices:
        keep = [index for index in range(len(y_values)) if index not in set(missing_indices)]
        y_values = [y_values[index] for index in keep]
        score_values = [score_values[index] for index in keep]

    numeric_scores: list[float] = []
    for score in score_values:
        try:
            if isinstance(score, (bool, np.bool_)):
                raise TypeError
            normalized = float(score)
        except (TypeError, ValueError, OverflowError):
            _fail("ROC_DIAGNOSTICS_INVALID_SCORE", "scores must be numeric and finite")
        if not math.isfinite(normalized):
            _fail("ROC_DIAGNOSTICS_NON_FINITE_INPUT", "scores must be finite")
        if score_semantics == "probability" and not 0.0 <= normalized <= 1.0:
            _fail("ROC_DIAGNOSTICS_INVALID_PROBABILITY", "probability scores must lie in [0, 1]")
        numeric_scores.append(normalized)

    labels: list[Any] = []
    for target in y_values:
        if not any(_safe_equal(target, existing) for existing in labels):
            labels.append(target)
    if not any(_safe_equal(positive_label, label) for label in labels):
        _fail("ROC_DIAGNOSTICS_EMPTY_CLASS", "positive_label is absent from the target")
    if len(labels) != 2:
        _fail("ROC_DIAGNOSTICS_NON_BINARY_TARGET", "target must contain exactly two classes")
    negative_label = next(label for label in labels if not _safe_equal(label, positive_label))

    y_binary = np.asarray(
        [1 if _safe_equal(target, positive_label) else 0 for target in y_values],
        dtype=np.int64,
    )
    positive_count = int(y_binary.sum())
    negative_count = int(len(y_binary) - positive_count)
    if positive_count == 0 or negative_count == 0:
        _fail("ROC_DIAGNOSTICS_EMPTY_CLASS", "both target classes must be non-empty")

    return PreparedBinaryData(
        y_binary=y_binary,
        scores=np.asarray(numeric_scores, dtype=float),
        positive_label=_json_scalar(positive_label, "positive_label"),
        negative_label=_json_scalar(negative_label, "negative_label"),
        missing_metadata={
            "missing_policy": missing_policy,
            "n_input": n_input,
            "n_used": len(y_values),
            "dropped_count": len(missing_indices),
        },
    )


def _validate_threshold_options(
    *,
    threshold_policy: str,
    quantile_grid_size: int | None,
    max_thresholds: int,
) -> tuple[str, int, int]:
    _validate_choice(threshold_policy, ROC_THRESHOLD_POLICIES, "threshold_policy")
    _validate_positive_integer(max_thresholds, "max_thresholds")
    if max_thresholds < 3:
        _fail("ROC_DIAGNOSTICS_OUTPUT_TOO_LARGE", "max_thresholds must allow curve endpoints")
    if quantile_grid_size is None:
        quantile_grid_size = _DEFAULT_QUANTILE_GRID_SIZE
    _validate_positive_integer(quantile_grid_size, "quantile_grid_size")
    if threshold_policy == "quantile_grid" and quantile_grid_size < 2:
        _fail("ROC_DIAGNOSTICS_INVALID_OPTION", "quantile_grid_size must be at least 2")
    if threshold_policy == "quantile_grid" and quantile_grid_size + 2 > max_thresholds:
        _fail(
            "ROC_DIAGNOSTICS_OUTPUT_TOO_LARGE",
            "quantile grid request exceeds max_thresholds",
        )
    return threshold_policy, quantile_grid_size, max_thresholds


def _validate_calibration_options(
    *, calibration_method: str, n_bins: int, max_bins: int
) -> tuple[str, int, int]:
    _validate_choice(calibration_method, ROC_CALIBRATION_METHODS, "calibration_method")
    _validate_positive_integer(n_bins, "n_bins")
    _validate_positive_integer(max_bins, "max_bins")
    if n_bins > max_bins:
        _fail("ROC_DIAGNOSTICS_OUTPUT_TOO_LARGE", "n_bins exceeds max_bins")
    return calibration_method, n_bins, max_bins


def _make_provenance(
    provenance: Mapping[str, Any] | None,
    *,
    metric_semantics: str,
) -> dict[str, Any]:
    if provenance is not None and not isinstance(provenance, Mapping):
        _fail("ROC_DIAGNOSTICS_INVALID_PROVENANCE", "provenance must be a mapping")
    protected: dict[str, Any] = {
        "pack": "roc_diagnostics",
        "runtime": "score_only",
        "implementation": "numpy",
        "contract_version": ROC_DIAGNOSTICS_CONTRACT_VERSION,
        "metric_semantics": metric_semantics,
    }
    supplied = {} if provenance is None else dict(provenance)
    for key, expected in protected.items():
        if key in supplied and not _safe_equal(supplied[key], expected):
            _fail(
                "ROC_DIAGNOSTICS_PROVENANCE_CONFLICT",
                f"provenance field {key} is reserved",
            )
    value = {**protected, **supplied}
    try:
        from workbench.contracts.common.envelope import freeze_json, thaw_json

        return thaw_json(freeze_json(value, "provenance"))
    except Exception as exc:
        if isinstance(exc, RocDiagnosticsPackError):
            raise
        _fail("ROC_DIAGNOSTICS_INVALID_PROVENANCE", "provenance must be finite JSON")


def _probability_metrics(y_binary: np.ndarray, scores: np.ndarray, score_semantics: str) -> dict[str, Any]:
    if score_semantics != "probability":
        return {
            "available": False,
            "score_semantics": score_semantics,
            "brier_score": None,
            "log_loss": None,
            "log_loss_defined": False,
        }
    brier = float(np.mean((scores - y_binary) ** 2))
    invalid_log_loss = bool(
        np.any((scores == 0.0) & (y_binary == 1))
        or np.any((scores == 1.0) & (y_binary == 0))
    )
    if invalid_log_loss:
        log_loss = None
    else:
        contributions = [
            -math.log(score) if label == 1 else -math.log1p(-score)
            for label, score in zip(y_binary.tolist(), scores.tolist())
        ]
        log_loss = float(np.mean(contributions))
    return {
        "available": True,
        "score_semantics": "probability",
        "brier_score": brier,
        "log_loss": log_loss,
        "log_loss_defined": not invalid_log_loss,
    }


def _policy_copy(
    constraint_policy: Mapping[str, Any] | None,
    cost_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    constraint: dict[str, Any] | None = None
    if constraint_policy is not None:
        if not isinstance(constraint_policy, Mapping):
            _fail("ROC_DIAGNOSTICS_INVALID_POLICY", "constraint_policy must be a mapping")
        required = {"metric", "operator", "value"}
        if set(constraint_policy) != required:
            _fail("ROC_DIAGNOSTICS_INVALID_POLICY", "constraint_policy must declare metric, operator, and value")
        metric = constraint_policy["metric"]
        operator = constraint_policy["operator"]
        if (
            type(metric) is not str
            or type(operator) is not str
            or metric not in _ALLOWED_CONSTRAINT_METRICS
            or operator not in _ALLOWED_CONSTRAINT_OPERATORS
        ):
            _fail("ROC_DIAGNOSTICS_INVALID_POLICY", "constraint metric or operator is not declared")
        value = constraint_policy["value"]
        if isinstance(value, bool) or not isinstance(value, (int, float, np.integer, np.floating)):
            _fail("ROC_DIAGNOSTICS_INVALID_POLICY", "constraint value must be finite")
        value = float(value)
        if not math.isfinite(value):
            _fail("ROC_DIAGNOSTICS_INVALID_POLICY", "constraint value must be finite")
        constraint = {"metric": metric, "operator": operator, "value": value}

    cost: dict[str, Any] | None = None
    if cost_policy is not None:
        if not isinstance(cost_policy, Mapping):
            _fail("ROC_DIAGNOSTICS_INVALID_POLICY", "cost_policy must be a mapping")
        required = {"false_positive_cost", "false_negative_cost"}
        if set(cost_policy) != required:
            _fail("ROC_DIAGNOSTICS_INVALID_POLICY", "cost_policy must declare false-positive and false-negative costs")
        cost = {
            key: _validate_nonnegative_finite(cost_policy[key], key)
            for key in sorted(required)
        }
    return {"constraint": constraint, "cost": cost}


def _compare_policy(value: float | None, operator: str, target: float) -> bool:
    if value is None:
        return False
    if operator == ">=":
        return value >= target
    if operator == "<=":
        return value <= target
    if operator == ">":
        return value > target
    if operator == "<":
        return value < target
    return value == target


def _constraint_value(point: Mapping[str, Any], metric: str) -> float | None:
    aliases = {
        "tpr": "sensitivity",
        "fpr": "false_positive_rate",
        "precision": "ppv",
        "recall": "sensitivity",
    }
    value = point.get(aliases.get(metric, metric))
    return None if value is None else float(value)


def _decision_evidence(
    points: list[dict[str, Any]],
    *,
    constraint_policy: Mapping[str, Any] | None,
    cost_policy: Mapping[str, Any] | None,
) -> dict[str, Any]:
    policy = _policy_copy(constraint_policy, cost_policy)
    constraint = policy["constraint"]
    candidates: list[dict[str, Any]] = []
    for point in points:
        if constraint is not None and not _compare_policy(
            _constraint_value(point, constraint["metric"]),
            constraint["operator"],
            constraint["value"],
        ):
            continue
        candidate = {
            "threshold": point["threshold"],
            "threshold_role": point["threshold_role"],
            "confusion_counts": dict(point["confusion_counts"]),
            "sensitivity": point["sensitivity"],
            "specificity": point["specificity"],
            "ppv": point["ppv"],
            "npv": point["npv"],
            "f1": point["f1"],
        }
        if policy["cost"] is not None:
            candidate["expected_cost"] = float(
                policy["cost"]["false_positive_cost"] * point["confusion_counts"]["fp"]
                + policy["cost"]["false_negative_cost"] * point["confusion_counts"]["fn"]
            )
        candidates.append(candidate)
    return {
        "mode": "evidence_only",
        "policy": policy if constraint is not None or policy["cost"] is not None else None,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


__all__ = [
    "PreparedBinaryData",
    "RocDiagnosticsPackError",
    "_DEFAULT_MAX_BINS",
    "_DEFAULT_MAX_THRESHOLDS",
    "_DEFAULT_QUANTILE_GRID_SIZE",
    "_decision_evidence",
    "_json_scalar",
    "_make_provenance",
    "_policy_copy",
    "_probability_metrics",
    "_validate_calibration_options",
    "_validate_inputs",
    "_validate_threshold_options",
]
