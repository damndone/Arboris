"""Known-answer classification metrics with explicit evidence axes."""

from __future__ import annotations

from collections import Counter
from typing import Any, Sequence

import numpy as np
from sklearn import metrics as sk_metrics

from .contracts import ContractError


def _record(
    name: str,
    value: float | None,
    *,
    status: str = "computed",
    reason: str | None = None,
    row_count: int,
    weight_sum: float,
    sample_scope: str,
    evaluation_design: str,
    numerical_method: str,
    inference_basis: str,
    validation_level: str,
    threshold: float,
    averaging: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "definition_version": "classification-metric.v1",
        "name": name,
        "status": status,
        "point_estimate": value,
        "positive_class": None,
        "threshold": threshold,
        "averaging": averaging,
        "sample_scope": sample_scope,
        "row_count": row_count,
        "weight_sum": weight_sum,
        "unweighted_denominator": row_count,
        "weighted_denominator": weight_sum,
        "effective_sample_size": row_count if weight_sum == row_count else None,
        "fold_distribution": [],
        "interval": None,
        "numerical_method": numerical_method,
        "inference_basis": inference_basis,
        "evaluation_design": evaluation_design,
        "validation_level": validation_level,
    }
    if reason is not None:
        result["reason"] = reason
    return result


def _safe_metric(function: Any, *, name: str, kwargs: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    try:
        value = float(function(**kwargs))
        if not np.isfinite(value):
            raise ValueError("non-finite metric")
        return _record(name, value, row_count=context["row_count"], weight_sum=context["weight_sum"], **context["evidence"])
    except (ValueError, ZeroDivisionError) as exc:
        return _record(
            name,
            None,
            status="undefined",
            reason=f"undefined: {exc}",
            row_count=context["row_count"],
            weight_sum=context["weight_sum"],
            **context["evidence"],
        )


def _undefined_metric(name: str, reason: str, *, context: dict[str, Any]) -> dict[str, Any]:
    return _record(
        name,
        None,
        status="undefined",
        reason=f"undefined: {reason}",
        row_count=context["row_count"],
        weight_sum=context["weight_sum"],
        **context["evidence"],
    )


def classification_metric_bundle(
    *,
    actual: Sequence[Any],
    probabilities: Sequence[float],
    predictions: Sequence[Any],
    positive_class: Any,
    threshold: float,
    sample_scope: str,
    evaluation_design: str,
    numerical_method: str,
    inference_basis: str,
    validation_level: str,
    sample_weight: Sequence[float] | None = None,
    averaging: str = "binary_positive_class",
) -> dict[str, Any]:
    y_true = np.asarray(actual)
    y_probability = np.asarray(probabilities, dtype=float)
    y_pred = np.asarray(predictions)
    if len(y_true) == 0 or len(y_true) != len(y_probability) or len(y_true) != len(y_pred):
        raise ContractError("CLASSIFICATION_METRIC_INPUT_INVALID", "metric inputs must be non-empty and aligned")
    if not 0 <= threshold <= 1 or not np.isfinite(y_probability).all():
        raise ContractError("CLASSIFICATION_METRIC_INPUT_INVALID", "probabilities or threshold are invalid")
    weights = np.ones(len(y_true), dtype=float) if sample_weight is None else np.asarray(sample_weight, dtype=float)
    if len(weights) != len(y_true) or not np.isfinite(weights).all() or (weights < 0).any():
        raise ContractError("CLASSIFICATION_WEIGHT_INVALID", "metric weights must be finite and non-negative")
    weight_sum = float(weights.sum())
    evidence = {
        "sample_scope": sample_scope,
        "evaluation_design": evaluation_design,
        "numerical_method": numerical_method,
        "inference_basis": inference_basis,
        "validation_level": validation_level,
        "threshold": threshold,
        "averaging": averaging,
    }
    context = {"row_count": len(y_true), "weight_sum": weight_sum, "evidence": evidence}
    metrics: dict[str, dict[str, Any]] = {}
    binary_actual = (y_true == positive_class).astype(int)
    binary_pred = (y_pred == positive_class).astype(int)
    actual_positive_weight = float(weights[binary_actual == 1].sum())
    predicted_positive_weight = float(weights[binary_pred == 1].sum())
    metrics["accuracy"] = _safe_metric(sk_metrics.accuracy_score, name="accuracy", kwargs={"y_true": y_true, "y_pred": y_pred, "sample_weight": weights}, context=context)
    metrics["balanced_accuracy"] = (
        _undefined_metric("balanced_accuracy", "both classes are required in actuals", context=context)
        if np.unique(y_true).size < 2
        else _safe_metric(sk_metrics.balanced_accuracy_score, name="balanced_accuracy", kwargs={"y_true": y_true, "y_pred": y_pred, "sample_weight": weights}, context=context)
    )
    metrics["precision"] = (
        _undefined_metric("precision", "no predicted positive support", context=context)
        if predicted_positive_weight <= 0
        else _safe_metric(sk_metrics.precision_score, name="precision", kwargs={"y_true": y_true, "y_pred": y_pred, "pos_label": positive_class, "average": "binary", "zero_division": 0, "sample_weight": weights}, context=context)
    )
    metrics["recall"] = (
        _undefined_metric("recall", "no actual positive support", context=context)
        if actual_positive_weight <= 0
        else _safe_metric(sk_metrics.recall_score, name="recall", kwargs={"y_true": y_true, "y_pred": y_pred, "pos_label": positive_class, "average": "binary", "zero_division": 0, "sample_weight": weights}, context=context)
    )
    metrics["f1"] = (
        _undefined_metric("f1", "positive class support is absent from actuals or predictions", context=context)
        if actual_positive_weight <= 0 or predicted_positive_weight <= 0
        else _safe_metric(sk_metrics.f1_score, name="f1", kwargs={"y_true": y_true, "y_pred": y_pred, "pos_label": positive_class, "average": "binary", "zero_division": 0, "sample_weight": weights}, context=context)
    )
    if np.unique(binary_actual).size < 2:
        metrics["roc_auc"] = _undefined_metric("roc_auc", "both classes are required in actuals", context=context)
        metrics["pr_auc"] = _undefined_metric("pr_auc", "both classes are required in actuals", context=context)
    else:
        metrics["roc_auc"] = _safe_metric(sk_metrics.roc_auc_score, name="roc_auc", kwargs={"y_true": binary_actual, "y_score": y_probability, "sample_weight": weights}, context=context)
        metrics["pr_auc"] = _safe_metric(sk_metrics.average_precision_score, name="pr_auc", kwargs={"y_true": binary_actual, "y_score": y_probability, "sample_weight": weights}, context=context)
    metrics["log_loss"] = _safe_metric(
        lambda *, y_true, y_probability, labels, sample_weight: sk_metrics.log_loss(
            y_true,
            y_probability,
            labels=labels,
            sample_weight=sample_weight,
        ),
        name="log_loss",
        kwargs={"y_true": binary_actual, "y_probability": np.column_stack((1.0 - y_probability, y_probability)), "labels": [0, 1], "sample_weight": weights},
        context=context,
    )
    metrics["brier_score"] = _safe_metric(
        lambda *, y_true, y_probability, sample_weight: sk_metrics.brier_score_loss(
            y_true,
            y_probability,
            sample_weight=sample_weight,
        ),
        name="brier_score",
        kwargs={"y_true": binary_actual, "y_probability": y_probability, "sample_weight": weights},
        context=context,
    )
    for record in metrics.values():
        record["positive_class"] = positive_class
    labels = list(dict.fromkeys(y_true.tolist() + y_pred.tolist()))
    if positive_class not in labels:
        labels.append(positive_class)
    cm = sk_metrics.confusion_matrix(y_true, y_pred, labels=labels, sample_weight=weights)
    per_class = {
        str(label): {"support": int((y_true == label).sum()), "predicted_support": int((y_pred == label).sum())}
        for label in labels
    }
    return {
        "metrics": metrics,
        "confusion_matrix": {"labels": labels, "values": cm.tolist()},
        "per_class": per_class,
        "threshold": threshold,
        "positive_class": positive_class,
        "sample_scope": sample_scope,
        "row_count": len(y_true),
        "weight_sum": weight_sum,
        "averaging": averaging,
    }


def compute_calibration_bins(
    actual: Sequence[Any], probabilities: Sequence[float], *, n_bins: int = 10, sample_scope: str = "development_oof"
) -> dict[str, Any]:
    if n_bins < 1 or len(actual) != len(probabilities) or not actual:
        raise ContractError("CLASSIFICATION_CALIBRATION_INPUT_INVALID", "calibration inputs are invalid")
    y = np.asarray(actual)
    p = np.asarray(probabilities, dtype=float)
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise ContractError("CLASSIFICATION_CALIBRATION_INPUT_INVALID", "probabilities must be in [0, 1]")
    bins: list[dict[str, Any]] = []
    edges = np.linspace(0, 1, n_bins + 1)
    for index in range(n_bins):
        mask = (p >= edges[index]) & ((p < edges[index + 1]) if index < n_bins - 1 else (p <= edges[index + 1]))
        if not mask.any():
            continue
        observed = y[mask].astype(float)
        bins.append({"bin": index, "lower": float(edges[index]), "upper": float(edges[index + 1]), "count": int(mask.sum()), "mean_predicted": float(p[mask].mean()), "fraction_positive": float(observed.mean())})
    return {"method": "uniform_probability_bins", "sample_scope": sample_scope, "n_bins": n_bins, "bins": bins}


def threshold_curve(actual: Sequence[Any], probabilities: Sequence[float], *, thresholds: Sequence[float], positive_class: Any = 1) -> list[dict[str, Any]]:
    y = np.asarray(actual)
    p = np.asarray(probabilities, dtype=float)
    if len(y) != len(p) or not len(y):
        raise ContractError("CLASSIFICATION_THRESHOLD_INPUT_INVALID", "threshold inputs are invalid")
    rows: list[dict[str, Any]] = []
    binary = (y == positive_class).astype(int)
    for threshold in thresholds:
        if not 0 <= threshold <= 1:
            raise ContractError("CLASSIFICATION_THRESHOLD_INVALID", "threshold must be in [0, 1]")
        pred = (p >= threshold).astype(int)
        rows.append({"threshold": float(threshold), "precision": float(sk_metrics.precision_score(binary, pred, zero_division=0)), "recall": float(sk_metrics.recall_score(binary, pred, zero_division=0)), "f1": float(sk_metrics.f1_score(binary, pred, zero_division=0)), "positive_rate": float(pred.mean())})
    return rows


__all__ = ["classification_metric_bundle", "compute_calibration_bins", "threshold_curve"]
