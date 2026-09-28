"""Classification metrics with explicit sample and evidence semantics.

This module is intentionally independent of a model family.  It accepts
predictions and probabilities produced by an already-admitted evaluation
stage and never treats an undefined statistic as zero.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn import metrics as sk_metrics
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from .contracts import ContractError


def _error(code: str, message: str) -> ContractError:
    return ContractError(code, message)


def _stable_labels(values: Sequence[Any]) -> tuple[Any, ...]:
    try:
        return tuple(sorted(set(values)))
    except TypeError:
        return tuple(sorted(set(values), key=lambda value: (type(value).__name__, repr(value))))


def _validate_threshold(threshold: Any) -> float:
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float, np.integer, np.floating)):
        raise _error("CLASSIFICATION_THRESHOLD_INVALID", "threshold must be finite and in [0, 1]")
    value = float(threshold)
    if not math.isfinite(value) or not 0 <= value <= 1:
        raise _error("CLASSIFICATION_THRESHOLD_INVALID", "threshold must be finite and in [0, 1]")
    return value


def _validated_inputs(
    *,
    actual: Sequence[Any],
    probabilities: Sequence[Any],
    predictions: Sequence[Any] | None,
    class_order: Sequence[Any] | None,
    positive_class: Any | None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray | None, tuple[Any, ...], Any | None, int]:
    y_true = np.asarray(actual)
    if y_true.ndim != 1 or len(y_true) == 0:
        raise _error("CLASSIFICATION_METRIC_INPUT_INVALID", "actual must be a non-empty one-dimensional sequence")
    if pd_is_missing(y_true):
        raise _error("CLASSIFICATION_METRIC_INPUT_INVALID", "actual contains missing labels")
    y_pred = None if predictions is None else np.asarray(predictions)
    if y_pred is not None and (y_pred.ndim != 1 or len(y_pred) != len(y_true)):
        raise _error("CLASSIFICATION_METRIC_INPUT_INVALID", "predictions must align with actual")
    if y_pred is not None and pd_is_missing(y_pred):
        raise _error("CLASSIFICATION_METRIC_INPUT_INVALID", "predictions contains missing labels")
    observed = list(y_true.tolist())
    if y_pred is not None:
        observed.extend(y_pred.tolist())
    try:
        if isinstance(class_order, (str, bytes)):
            raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class_order must be a sequence of labels, not text")
        labels = tuple(class_order) if class_order is not None else _stable_labels(observed)
    except TypeError as exc:
        raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class order must be a sequence of unique labels") from exc
    if len(labels) < 2 or len(set(labels)) != len(labels) or len({str(label) for label in labels}) != len(labels):
        raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class_order must contain at least two unique labels")
    label_set = set(labels)
    if not set(y_true.tolist()).issubset(label_set) or (y_pred is not None and not set(y_pred.tolist()).issubset(label_set)):
        raise _error("CLASSIFICATION_CLASS_ORDER_MISMATCH", "actual/predictions contain labels outside class_order")
    if positive_class is not None and positive_class not in label_set:
        raise _error("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in class_order")
    probability_array = np.asarray(probabilities, dtype=float)
    effective_positive = positive_class
    if len(labels) == 2 and effective_positive is None:
        effective_positive = 1 if 1 in labels else labels[-1]
    if probability_array.ndim == 1:
        if len(labels) != 2:
            raise _error("CLASSIFICATION_PROBABILITY_INVALID", "one probability per row is binary-only")
        if len(probability_array) != len(y_true):
            raise _error("CLASSIFICATION_METRIC_INPUT_INVALID", "probabilities must align with actual")
        if not np.isfinite(probability_array).all() or ((probability_array < 0) | (probability_array > 1)).any():
            raise _error("CLASSIFICATION_PROBABILITY_INVALID", "probabilities must be finite and in [0, 1]")
        positive_index = labels.index(effective_positive)
        probability_matrix = np.zeros((len(y_true), 2), dtype=float)
        probability_matrix[:, positive_index] = probability_array
        probability_matrix[:, 1 - positive_index] = 1.0 - probability_array
        probability_width = 2
    elif probability_array.ndim == 2:
        if probability_array.shape != (len(y_true), len(labels)):
            raise _error("CLASSIFICATION_PROBABILITY_INVALID", "probability columns must match class_order")
        if (
            not np.isfinite(probability_array).all()
            or (probability_array < -1e-12).any()
            or (probability_array > 1 + 1e-12).any()
            or not np.allclose(probability_array.sum(axis=1), 1.0, atol=1e-8)
        ):
            raise _error("CLASSIFICATION_PROBABILITY_INVALID", "probabilities must be finite, bounded and row-normalized")
        probability_matrix = probability_array
        probability_width = probability_array.shape[1]
    else:
        raise _error("CLASSIFICATION_PROBABILITY_INVALID", "probabilities must be one- or two-dimensional")
    if len(labels) != probability_width:
        raise _error("CLASSIFICATION_CLASS_ORDER_MISMATCH", "probability width does not match class_order")
    return y_true, probability_matrix, y_pred, labels, effective_positive, probability_width


def pd_is_missing(values: np.ndarray) -> bool:
    try:
        return bool(pd.isna(values).any())
    except (TypeError, ValueError):
        return False


def _weights(sample_weight: Sequence[float] | None, row_count: int) -> tuple[np.ndarray, float, float]:
    values = np.ones(row_count, dtype=float) if sample_weight is None else np.asarray(sample_weight, dtype=float)
    if (
        values.ndim != 1
        or len(values) != row_count
        or not np.isfinite(values).all()
        or (values < 0).any()
        or float(values.sum()) <= 0
    ):
        raise _error("CLASSIFICATION_WEIGHT_INVALID", "weights must be finite, non-negative and have positive total")
    total = float(values.sum())
    effective = float(total * total / np.square(values).sum())
    return values, total, effective


_METRIC_DEFINITIONS = {
    "accuracy": "correct predictions divided by the evaluation denominator",
    "precision": "true positives divided by predicted positive support",
    "recall": "true positives divided by actual positive support",
    "f1": "2 times true positives divided by 2 times true positives plus false positives plus false negatives",
    "balanced_accuracy": "the unweighted mean of per-class recall values",
    "roc_auc": "the area under the receiver operating characteristic curve from probability rankings",
    "pr_auc": "average precision from the precision-recall curve",
    "log_loss": "the weighted mean negative log probability assigned to the observed class",
    "brier_score": "the weighted mean squared probability error",
}


def _evidence_basis(evaluation_design: str, numerical_method: str) -> str:
    design = evaluation_design.lower()
    method = numerical_method.lower()
    if "known_answer" in design or method == "known_answer":
        return "known_answer"
    if "same_library" in design or "regression" in design:
        return "same_library_regression"
    return "runtime_computation"


def _denominator(kind: str, value: float | int | None) -> dict[str, Any]:
    if value is None or not math.isfinite(float(value)) or float(value) <= 0:
        return {"kind": kind, "status": "undefined", "value": None}
    return {"kind": kind, "status": "declared", "value": float(value)}


def _metric_context(
    context: Mapping[str, Any],
    *,
    denominator_kind: str,
    denominator_value: float | int | None,
) -> dict[str, Any]:
    return {
        **context,
        "denominator": _denominator(denominator_kind, denominator_value),
    }


def _record(
    name: str,
    value: float | None,
    *,
    row_count: int,
    weight_sum: float,
    effective_sample_size: float,
    sample_scope: str,
    evaluation_design: str,
    numerical_method: str,
    inference_basis: str,
    validation_level: str,
    threshold: float | None,
    averaging: str,
    class_order: Sequence[Any],
    positive_class: Any | None,
    denominator: Mapping[str, Any],
    weighted: bool,
    evidence_basis: str,
    status: str = "computed",
    reason: str | None = None,
) -> dict[str, Any]:
    try:
        metric_definition = _METRIC_DEFINITIONS[name]
    except KeyError as exc:
        raise _error("CLASSIFICATION_METRIC_DEFINITION_INVALID", f"metric definition is missing for {name!r}") from exc
    result: dict[str, Any] = {
        "definition_version": "classification-metric.v1",
        "name": name,
        "metric_definition": metric_definition,
        "status": status,
        "point_estimate": value,
        "positive_class": positive_class,
        "class_order": list(class_order),
        "threshold": threshold,
        "averaging": averaging,
        "sample_scope": sample_scope,
        "row_count": row_count,
        "weight_sum": weight_sum,
        "unweighted_denominator": row_count,
        "weighted_denominator": weight_sum,
        "effective_sample_size": effective_sample_size,
        "denominator": dict(denominator),
        "weighted": weighted,
        "weighted_status": "weighted" if weighted else "unweighted",
        "fold_distribution": [],
        "interval": None,
        "numerical_method": numerical_method,
        "inference_basis": inference_basis,
        "evaluation_design": evaluation_design,
        "validation_level": validation_level,
        "evidence_basis": {"kind": evidence_basis, "independent_oracle": False},
        "independent_oracle": False,
    }
    if reason is not None:
        result["reason"] = reason
    return result


def _undefined(
    name: str,
    reason: str,
    *,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    return _record(name, None, status="undefined", reason=f"undefined: {reason}", **context)


def _computed(name: str, value: float, *, context: Mapping[str, Any]) -> dict[str, Any]:
    if not math.isfinite(float(value)):
        return _undefined(name, "non-finite result", context=context)
    return _record(name, float(value), **context)


def _class_stats(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    label: Any,
    weights: np.ndarray,
    *,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    actual = y_true == label
    predicted = y_pred == label
    tp = float(weights[actual & predicted].sum())
    fp = float(weights[~actual & predicted].sum())
    fn = float(weights[actual & ~predicted].sum())
    support = float(weights[actual].sum())
    predicted_support = float(weights[predicted].sum())
    if predicted_support <= 0:
        precision = _undefined(
            "precision",
            "no predicted support",
            context=_metric_context(context, denominator_kind="predicted_positive_support", denominator_value=predicted_support),
        )
    else:
        precision = _computed(
            "precision",
            tp / predicted_support,
            context=_metric_context(context, denominator_kind="predicted_positive_support", denominator_value=predicted_support),
        )
    if support <= 0:
        recall = _undefined(
            "recall",
            "no actual support",
            context=_metric_context(context, denominator_kind="actual_positive_support", denominator_value=support),
        )
    else:
        recall = _computed(
            "recall",
            tp / support,
            context=_metric_context(context, denominator_kind="actual_positive_support", denominator_value=support),
        )
    f1_denominator = 2 * tp + fp + fn
    if support <= 0 or predicted_support <= 0 or f1_denominator <= 0:
        f1 = _undefined(
            "f1",
            "positive class support is absent from actuals or predictions",
            context=_metric_context(context, denominator_kind="f1_confusion_sum", denominator_value=f1_denominator),
        )
    else:
        f1 = _computed(
            "f1",
            2 * tp / f1_denominator,
            context=_metric_context(context, denominator_kind="f1_confusion_sum", denominator_value=f1_denominator),
        )
    return {
        "support": int(np.count_nonzero(actual)),
        "weighted_support": support,
        "predicted_support": int(np.count_nonzero(predicted)),
        "weighted_predicted_support": predicted_support,
        "true_positive": tp,
        "false_positive": fp,
        "false_negative": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _macro_or_weighted(
    name: str,
    per_class: Mapping[Any, Mapping[str, Any]],
    *,
    averaging: str,
    context: Mapping[str, Any],
) -> dict[str, Any]:
    denominator_kind = "total_weight" if averaging == "weighted" else "class_count"
    denominator_value = (
        sum(float(row["weighted_support"]) for row in per_class.values())
        if averaging == "weighted"
        else len(per_class)
    )
    metric_context = _metric_context(
        context,
        denominator_kind=denominator_kind,
        denominator_value=denominator_value,
    )
    if any(row[name]["status"] != "computed" for row in per_class.values()):
        return _undefined(name, "one or more classes has undefined support", context=metric_context)
    values: list[float] = []
    supports: list[float] = []
    for row in per_class.values():
        metric = row[name]
        if metric["status"] == "computed":
            values.append(float(metric["point_estimate"]))
            supports.append(float(row["weighted_support"]))
    if not values:
        return _undefined(name, "no class has sufficient support", context=metric_context)
    if averaging == "weighted":
        denominator = sum(supports)
        value = sum(score * support for score, support in zip(values, supports, strict=True)) / denominator if denominator else math.nan
    else:
        value = float(np.mean(values))
    return _computed(name, value, context=metric_context)


def classification_metric_bundle(
    *,
    actual: Sequence[Any],
    probabilities: Sequence[Any],
    predictions: Sequence[Any],
    positive_class: Any | None = None,
    threshold: float = 0.5,
    sample_scope: str = "unspecified",
    evaluation_design: str = "unspecified",
    numerical_method: str = "sklearn",
    inference_basis: str = "descriptive",
    validation_level: str = "unknown",
    sample_weight: Sequence[float] | None = None,
    averaging: str = "binary_positive_class",
    class_order: Sequence[Any] | None = None,
    calibration_bins: int = 10,
) -> dict[str, Any]:
    threshold_value = _validate_threshold(threshold)
    if not all(isinstance(value, str) and value.strip() for value in (sample_scope, evaluation_design, numerical_method, inference_basis, validation_level)):
        raise _error("CLASSIFICATION_METRIC_EVIDENCE_INVALID", "evidence axes must be non-empty strings")
    if averaging not in {"binary_positive_class", "macro", "weighted"}:
        raise _error("CLASSIFICATION_AVERAGING_INVALID", "unsupported classification averaging")
    y_true, probability_matrix, y_pred, labels, positive, _ = _validated_inputs(
        actual=actual,
        probabilities=probabilities,
        predictions=predictions,
        class_order=class_order,
        positive_class=positive_class,
    )
    if len(labels) > 2 and averaging == "binary_positive_class":
        raise _error("CLASSIFICATION_AVERAGING_INVALID", "multiclass metrics require macro or weighted averaging")
    assert y_pred is not None
    weights, weight_sum, effective_sample_size = _weights(sample_weight, len(y_true))
    context = {
        "row_count": len(y_true),
        "weight_sum": weight_sum,
        "effective_sample_size": effective_sample_size,
        "sample_scope": sample_scope,
        "evaluation_design": evaluation_design,
        "numerical_method": numerical_method,
        "inference_basis": inference_basis,
        "validation_level": validation_level,
        "threshold": threshold_value if len(labels) == 2 else None,
        "averaging": averaging,
        "class_order": labels,
        "positive_class": positive,
        "denominator": _denominator("total_weight", weight_sum),
        "weighted": sample_weight is not None,
        "evidence_basis": _evidence_basis(evaluation_design, numerical_method),
    }
    binary = len(labels) == 2
    metrics: dict[str, dict[str, Any]] = {}
    accuracy = float(weights[y_true == y_pred].sum() / weight_sum)
    metrics["accuracy"] = _computed("accuracy", accuracy, context=context)
    per_class = {label: _class_stats(y_true, y_pred, label, weights, context=context) for label in labels}

    if averaging == "binary_positive_class" and binary:
        assert positive is not None
        metrics["precision"] = per_class[positive]["precision"]
        metrics["recall"] = per_class[positive]["recall"]
        metrics["f1"] = per_class[positive]["f1"]
    else:
        metrics["precision"] = _macro_or_weighted("precision", per_class, averaging=averaging, context=context)
        metrics["recall"] = _macro_or_weighted("recall", per_class, averaging=averaging, context=context)
        metrics["f1"] = _macro_or_weighted("f1", per_class, averaging=averaging, context=context)

    all_classes_present = all(row["weighted_support"] > 0 for row in per_class.values())
    if not all_classes_present:
        metrics["balanced_accuracy"] = _undefined(
            "balanced_accuracy",
            "every class needs actual support",
            context=_metric_context(context, denominator_kind="class_count", denominator_value=len(labels)),
        )
    else:
        recalls = [float(row["recall"]["point_estimate"]) for row in per_class.values()]
        metrics["balanced_accuracy"] = _computed(
            "balanced_accuracy",
            float(np.mean(recalls)),
            context=_metric_context(context, denominator_kind="class_count", denominator_value=len(labels)),
        )

    if not all_classes_present:
        metrics["roc_auc"] = _undefined(
            "roc_auc",
            "every class needs actual support",
            context=_metric_context(context, denominator_kind="ranked_probability_support", denominator_value=weight_sum),
        )
        metrics["pr_auc"] = _undefined(
            "pr_auc",
            "every class needs actual support",
            context=_metric_context(context, denominator_kind="precision_recall_support", denominator_value=weight_sum),
        )
    else:
        try:
            if binary:
                assert positive is not None
                positive_index = labels.index(positive)
                roc = sk_metrics.roc_auc_score(
                    (y_true == positive).astype(int),
                    probability_matrix[:, positive_index],
                    sample_weight=weights,
                )
                pr = sk_metrics.average_precision_score(
                    (y_true == positive).astype(int),
                    probability_matrix[:, positive_index],
                    sample_weight=weights,
                )
            else:
                roc = sk_metrics.roc_auc_score(
                    y_true,
                    probability_matrix,
                    labels=list(labels),
                    multi_class="ovr",
                    average="macro" if averaging == "binary_positive_class" else averaging,
                    sample_weight=weights,
                )
                one_hot = np.column_stack([(y_true == label).astype(int) for label in labels])
                pr = sk_metrics.average_precision_score(
                    one_hot,
                    probability_matrix,
                    average="macro" if averaging == "binary_positive_class" else averaging,
                    sample_weight=weights,
                )
            metrics["roc_auc"] = _computed(
                "roc_auc",
                float(roc),
                context=_metric_context(context, denominator_kind="ranked_probability_support", denominator_value=weight_sum),
            )
            metrics["pr_auc"] = _computed(
                "pr_auc",
                float(pr),
                context=_metric_context(context, denominator_kind="precision_recall_support", denominator_value=weight_sum),
            )
        except (ValueError, TypeError) as exc:
            metrics["roc_auc"] = _undefined(
                "roc_auc",
                str(exc),
                context=_metric_context(context, denominator_kind="ranked_probability_support", denominator_value=weight_sum),
            )
            metrics["pr_auc"] = _undefined(
                "pr_auc",
                str(exc),
                context=_metric_context(context, denominator_kind="precision_recall_support", denominator_value=weight_sum),
            )

    try:
        label_indexes = np.asarray([labels.index(value) for value in y_true], dtype=int)
        observed_probability = np.clip(
            probability_matrix[np.arange(len(y_true)), label_indexes],
            np.finfo(float).eps,
            1.0,
        )
        loss = float(-np.sum(weights * np.log(observed_probability)) / weight_sum)
        metrics["log_loss"] = _computed("log_loss", float(loss), context=context)
    except (ValueError, TypeError) as exc:
        metrics["log_loss"] = _undefined("log_loss", str(exc), context=context)

    try:
        if binary and positive is not None:
            positive_index = labels.index(positive)
            brier = float(
                sk_metrics.brier_score_loss(
                    (y_true == positive).astype(int),
                    probability_matrix[:, positive_index],
                    sample_weight=weights,
                )
            )
        else:
            one_hot = np.column_stack([(y_true == label).astype(float) for label in labels])
            brier = float(np.average(np.square(one_hot - probability_matrix).sum(axis=1), weights=weights))
        metrics["brier_score"] = _computed("brier_score", brier, context=context)
    except (ValueError, TypeError) as exc:
        metrics["brier_score"] = _undefined("brier_score", str(exc), context=context)

    confusion = sk_metrics.confusion_matrix(y_true, y_pred, labels=list(labels), sample_weight=weights)
    calibration = compute_calibration_bins(
        actual=y_true if binary else np.asarray(
            [bool(y_true[index] == labels[int(probability_matrix[index].argmax())]) for index in range(len(y_true))]
        ),
        probabilities=probability_matrix[:, labels.index(positive)] if binary and positive is not None else probability_matrix.max(axis=1),
        n_bins=calibration_bins,
        sample_scope=sample_scope,
        positive_class=positive if binary else True,
        sample_weight=weights,
        calibration_kind="binary_positive_class" if binary else "multiclass_top_label",
    )
    per_class_payload = {str(label): value for label, value in per_class.items()}
    return {
        "metrics": metrics,
        "confusion_matrix": {"labels": list(labels), "values": confusion.tolist()},
        "per_class": per_class_payload,
        "class_order": list(labels),
        "positive_class": positive,
        "threshold": {"value": threshold_value, "scope": sample_scope, "status": "declared"},
        "threshold_value": threshold_value,
        "calibration": calibration,
        "sample_scope": sample_scope,
        "evaluation_design": evaluation_design,
        "row_count": len(y_true),
        "weight_sum": weight_sum,
        "effective_sample_size": effective_sample_size,
        "averaging": averaging,
    }


def compute_calibration_bins(
    actual: Sequence[Any],
    probabilities: Sequence[float],
    *,
    n_bins: int = 10,
    sample_scope: str = "development_oof",
    positive_class: Any | None = 1,
    sample_weight: Sequence[float] | None = None,
    calibration_kind: str = "binary_positive_class",
) -> dict[str, Any]:
    if not isinstance(n_bins, int) or isinstance(n_bins, bool) or not 1 <= n_bins <= 100:
        raise _error("CLASSIFICATION_CALIBRATION_INPUT_INVALID", "n_bins must be an integer in [1, 100]")
    y = np.asarray(actual)
    p = np.asarray(probabilities, dtype=float)
    if y.ndim != 1 or p.ndim != 1 or len(y) == 0 or len(y) != len(p):
        raise _error("CLASSIFICATION_CALIBRATION_INPUT_INVALID", "calibration inputs must be non-empty and aligned")
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise _error("CLASSIFICATION_CALIBRATION_INPUT_INVALID", "probabilities must be finite and in [0, 1]")
    weights, weight_sum, effective_sample_size = _weights(sample_weight, len(y))
    binary = (y == positive_class).astype(float)
    edges = np.linspace(0, 1, n_bins + 1)
    bins: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(n_bins):
        mask = (p >= edges[index]) & ((p < edges[index + 1]) if index < n_bins - 1 else (p <= edges[index + 1]))
        if not mask.any():
            continue
        bin_weight = float(weights[mask].sum())
        predicted = float(np.average(p[mask], weights=weights[mask]))
        observed = float(np.average(binary[mask], weights=weights[mask]))
        gap = abs(predicted - observed)
        ece += bin_weight / weight_sum * gap
        bins.append(
            {
                "bin": index,
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "count": int(mask.sum()),
                "weight_sum": bin_weight,
                "mean_predicted": predicted,
                "fraction_positive": observed,
                "absolute_gap": gap,
            }
        )
    return {
        "status": "computed",
        "method": "uniform_probability_bins",
        "kind": calibration_kind,
        "sample_scope": sample_scope,
        "positive_class": positive_class,
        "n_bins": n_bins,
        "bins": bins,
        "expected_calibration_error": float(ece),
        "row_count": len(y),
        "weight_sum": weight_sum,
        "effective_sample_size": effective_sample_size,
    }


_CALIBRATOR_METHODS = frozenset({"none", "platt", "isotonic"})
_CALIBRATOR_TRANSFORM_SCOPES = frozenset(
    {"development_oof", "development_calibration_eval", "outer_holdout", "final_holdout"}
)


def _calibrator_probability_vector(values: Sequence[float], *, error_code: str) -> np.ndarray:
    try:
        probabilities = np.asarray(values, dtype=float)
    except (TypeError, ValueError) as exc:
        raise _error(error_code, "probabilities must be numeric") from exc
    if probabilities.ndim != 1 or len(probabilities) == 0:
        raise _error(error_code, "probabilities must be a non-empty one-dimensional sequence")
    if not np.isfinite(probabilities).all() or ((probabilities < 0) | (probabilities > 1)).any():
        raise _error(error_code, "probabilities must be finite and in [0, 1]")
    return probabilities


def _calibrator_weights(
    sample_weight: Sequence[float] | None,
    *,
    row_count: int,
) -> tuple[np.ndarray, float, float, bool]:
    weighted_fit = sample_weight is not None
    try:
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            values, weight_sum, effective_sample_size = _weights(sample_weight, row_count)
    except (TypeError, ValueError) as exc:
        raise _error(
            "CLASSIFICATION_WEIGHT_INVALID",
            "weights must be finite, non-negative and have positive total",
        ) from exc
    if not math.isfinite(weight_sum) or not math.isfinite(effective_sample_size) or effective_sample_size <= 0:
        raise _error(
            "CLASSIFICATION_WEIGHT_INVALID",
            "weights must have finite total and effective sample size",
        )
    return values, weight_sum, effective_sample_size, weighted_fit


def _calibrator_training_labels(
    values: Sequence[Any],
    *,
    class_order: Sequence[Any] | None,
    positive_class: Any | None,
) -> tuple[np.ndarray, tuple[Any, Any], Any, np.ndarray]:
    try:
        labels_array = np.asarray(values)
    except (TypeError, ValueError) as exc:
        raise _error("CLASSIFICATION_CALIBRATOR_LABEL_INVALID", "fit labels must be a one-dimensional sequence") from exc
    if labels_array.ndim != 1 or len(labels_array) == 0:
        raise _error("CLASSIFICATION_CALIBRATOR_LABEL_INVALID", "fit labels must be non-empty and one-dimensional")
    if pd_is_missing(labels_array):
        raise _error("CLASSIFICATION_CALIBRATOR_LABEL_INVALID", "fit labels must not contain missing values")
    try:
        if class_order is None:
            labels = _stable_labels(labels_array.tolist())
        elif isinstance(class_order, (str, bytes)):
            raise TypeError("class_order must be a sequence")
        else:
            labels = tuple(class_order)
        if len(labels) != 2 or len(set(labels)) != 2 or len({str(label) for label in labels}) != 2:
            raise ValueError("calibration requires exactly two unique classes")
        observed = set(labels_array.tolist())
        if observed != set(labels):
            raise ValueError("both declared binary classes must be present in fit labels")
    except (TypeError, ValueError) as exc:
        raise _error("CLASSIFICATION_CALIBRATOR_LABEL_INVALID", str(exc)) from exc
    effective_positive = positive_class
    if effective_positive is None:
        effective_positive = 1 if 1 in labels else labels[-1]
    if effective_positive not in labels:
        raise _error("CLASSIFICATION_CALIBRATOR_LABEL_INVALID", "positive_class must be one of class_order")
    binary_labels = np.asarray([int(label == effective_positive) for label in labels_array], dtype=int)
    if not binary_labels.any() or bool(binary_labels.all()):
        raise _error("CLASSIFICATION_CALIBRATOR_LABEL_INVALID", "fit labels must contain both binary classes")
    return labels_array, (labels[0], labels[1]), effective_positive, binary_labels


def _calibrator_fit_refs(values: Sequence[str], *, row_count: int) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise _error("CLASSIFICATION_CALIBRATOR_FIT_REFS_INVALID", "fit_row_refs must be a sequence of row references")
    try:
        refs = tuple(values)
    except TypeError as exc:
        raise _error("CLASSIFICATION_CALIBRATOR_FIT_REFS_INVALID", "fit_row_refs must be a sequence") from exc
    if len(refs) != row_count or not refs:
        raise _error("CLASSIFICATION_CALIBRATOR_FIT_REFS_INVALID", "fit_row_refs must align with fit probabilities")
    if any(not isinstance(ref, str) or not ref.strip() for ref in refs):
        raise _error("CLASSIFICATION_CALIBRATOR_FIT_REFS_INVALID", "fit_row_refs must be non-empty strings")
    if len(set(refs)) != len(refs):
        raise _error("CLASSIFICATION_CALIBRATOR_FIT_REFS_INVALID", "fit_row_refs must be unique")
    return refs


def _calibrator_recipe(recipe: Mapping[str, Any], *, method: str) -> dict[str, Any]:
    if not isinstance(recipe, Mapping) or not recipe:
        raise _error("CLASSIFICATION_CALIBRATOR_RECIPE_INVALID", "recipe must be a non-empty mapping")
    recipe_copy = copy.deepcopy(dict(recipe))
    for key in ("recipe_id", "version"):
        value = recipe_copy.get(key)
        if not isinstance(value, str) or not value.strip():
            raise _error("CLASSIFICATION_CALIBRATOR_RECIPE_INVALID", f"recipe.{key} must be a non-empty string")
    declared_method = recipe_copy.get("method")
    if declared_method is not None and declared_method != method:
        raise _error("CLASSIFICATION_CALIBRATOR_RECIPE_INVALID", "recipe.method must match method")
    return recipe_copy


def _calibrator_evidence_receipt(receipt: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(receipt, Mapping) or not receipt:
        raise _error("CLASSIFICATION_CALIBRATOR_EVIDENCE_INVALID", "evidence_receipt must be a non-empty mapping")
    receipt_copy = copy.deepcopy(dict(receipt))
    receipt_id = receipt_copy.get("receipt_id")
    if not isinstance(receipt_id, str) or not receipt_id.strip():
        raise _error("CLASSIFICATION_CALIBRATOR_EVIDENCE_INVALID", "evidence_receipt.receipt_id is required")
    sources = receipt_copy.get("source_artifacts")
    if isinstance(sources, (str, bytes)) or not isinstance(sources, Sequence) or not sources:
        raise _error("CLASSIFICATION_CALIBRATOR_EVIDENCE_INVALID", "evidence_receipt.source_artifacts is required")
    if any(not isinstance(source, str) or not source.strip() for source in sources):
        raise _error("CLASSIFICATION_CALIBRATOR_EVIDENCE_INVALID", "source artifacts must be non-empty strings")
    validation_level = receipt_copy.get("validation_level")
    if not isinstance(validation_level, str) or not validation_level.strip():
        raise _error("CLASSIFICATION_CALIBRATOR_EVIDENCE_INVALID", "evidence_receipt.validation_level is required")
    return receipt_copy


def _calibrator_logit(probabilities: np.ndarray) -> np.ndarray:
    clipped = np.clip(probabilities, np.finfo(float).eps, 1.0 - np.finfo(float).eps)
    return np.log(clipped / (1.0 - clipped))


@dataclass(frozen=True, eq=False)
class ProbabilityCalibratorV1:
    """A typed, development-OOF-only probability calibration fit.

    The fit stores only the admitted development OOF metadata and the fitted
    sklearn estimator.  ``transform`` accepts probabilities plus a declared
    output scope; it intentionally has no label argument, so a holdout label
    cannot enter calibration fitting or transformation through this seam.
    """

    method: str
    fit_scope: str
    fit_row_refs: tuple[str, ...]
    seed: int
    recipe: Mapping[str, Any]
    evidence_receipt: Mapping[str, Any]
    class_order: tuple[Any, Any]
    positive_class: Any
    numerical_method: str
    _estimator: Any = field(repr=False, compare=False)
    weighted_fit: bool = False
    weight_sum: float = 0.0
    effective_sample_size: float = 0.0

    @classmethod
    def fit(
        cls,
        *,
        method: str,
        fit_probabilities: Sequence[float],
        fit_labels: Sequence[Any],
        fit_scope: str,
        fit_row_refs: Sequence[str],
        seed: int,
        recipe: Mapping[str, Any],
        evidence_receipt: Mapping[str, Any],
        class_order: Sequence[Any] | None = None,
        positive_class: Any | None = None,
        sample_weight: Sequence[float] | None = None,
    ) -> "ProbabilityCalibratorV1":
        if not isinstance(method, str) or method not in _CALIBRATOR_METHODS:
            raise _error("CLASSIFICATION_CALIBRATOR_METHOD_INVALID", "method must be none, platt or isotonic")
        if fit_scope != "development_oof":
            raise _error("CLASSIFICATION_CALIBRATOR_SCOPE_INVALID", "calibrator fitting only accepts development_oof")
        if not isinstance(seed, (int, np.integer)) or isinstance(seed, bool) or int(seed) < 0:
            raise _error("CLASSIFICATION_CALIBRATOR_SEED_INVALID", "seed must be a non-negative integer")
        probabilities = _calibrator_probability_vector(
            fit_probabilities,
            error_code="CLASSIFICATION_CALIBRATOR_INPUT_INVALID",
        )
        _, normalized_class_order, normalized_positive, binary_labels = _calibrator_training_labels(
            fit_labels,
            class_order=class_order,
            positive_class=positive_class,
        )
        if len(binary_labels) != len(probabilities):
            raise _error("CLASSIFICATION_CALIBRATOR_INPUT_INVALID", "fit labels and probabilities must align")
        weights, weight_sum, effective_sample_size, weighted_fit = _calibrator_weights(
            sample_weight,
            row_count=len(probabilities),
        )
        refs = _calibrator_fit_refs(fit_row_refs, row_count=len(probabilities))
        recipe_copy = _calibrator_recipe(recipe, method=method)
        receipt_copy = _calibrator_evidence_receipt(evidence_receipt)

        estimator: Any = None
        numerical_method = "identity"
        if method == "platt":
            try:
                estimator = LogisticRegression(
                    C=1_000_000.0,
                    max_iter=1_000,
                    random_state=int(seed),
                    solver="lbfgs",
                )
                estimator.fit(
                    _calibrator_logit(probabilities).reshape(-1, 1),
                    binary_labels,
                    sample_weight=weights if weighted_fit else None,
                )
            except (TypeError, ValueError) as exc:
                raise _error("CLASSIFICATION_CALIBRATOR_FIT_INVALID", str(exc)) from exc
            numerical_method = "sklearn_1.x"
        elif method == "isotonic":
            try:
                estimator = IsotonicRegression(
                    y_min=0.0,
                    y_max=1.0,
                    out_of_bounds="clip",
                )
                estimator.fit(
                    probabilities,
                    binary_labels,
                    sample_weight=weights if weighted_fit else None,
                )
            except (TypeError, ValueError) as exc:
                raise _error("CLASSIFICATION_CALIBRATOR_FIT_INVALID", str(exc)) from exc
            numerical_method = "sklearn_1.x"

        return cls(
            method=method,
            fit_scope=fit_scope,
            fit_row_refs=refs,
            seed=int(seed),
            recipe=recipe_copy,
            evidence_receipt=receipt_copy,
            class_order=normalized_class_order,
            positive_class=normalized_positive,
            numerical_method=numerical_method,
            _estimator=estimator,
            weighted_fit=weighted_fit,
            weight_sum=weight_sum,
            effective_sample_size=effective_sample_size,
        )

    def transform(self, probabilities: Sequence[float], *, sample_scope: str) -> np.ndarray:
        if sample_scope not in _CALIBRATOR_TRANSFORM_SCOPES:
            raise _error(
                "CLASSIFICATION_CALIBRATOR_TRANSFORM_SCOPE_INVALID",
                "transform scope must be development_oof or a declared holdout scope",
            )
        values = _calibrator_probability_vector(
            probabilities,
            error_code="CLASSIFICATION_CALIBRATOR_TRANSFORM_INPUT_INVALID",
        )
        if self.method == "none":
            transformed = values.copy()
        elif self.method == "platt":
            transformed = np.asarray(self._estimator.predict_proba(_calibrator_logit(values).reshape(-1, 1))[:, 1], dtype=float)
        else:
            transformed = np.asarray(self._estimator.predict(values), dtype=float)
        if not np.isfinite(transformed).all():
            raise _error("CLASSIFICATION_CALIBRATOR_TRANSFORM_OUTPUT_INVALID", "calibrated probabilities must be finite")
        return np.clip(transformed, 0.0, 1.0)

    def evidence(self) -> dict[str, Any]:
        return {
            "payload_schema": "workbench.classification.probability-calibrator",
            "schema_version": 1,
            "method": self.method,
            "fit_scope": self.fit_scope,
            "fit_row_refs": list(self.fit_row_refs),
            "seed": self.seed,
            "recipe": copy.deepcopy(dict(self.recipe)),
            "evidence_receipt": copy.deepcopy(dict(self.evidence_receipt)),
            "class_order": list(self.class_order),
            "positive_class": self.positive_class,
            "numerical_method": self.numerical_method,
            "weighted_fit": self.weighted_fit,
            "weight_sum": self.weight_sum,
            "effective_sample_size": self.effective_sample_size,
            "independent_oracle": False,
        }


def fit_probability_calibrator(
    *,
    method: str,
    fit_probabilities: Sequence[float],
    fit_labels: Sequence[Any],
    fit_scope: str,
    fit_row_refs: Sequence[str],
    seed: int,
    recipe: Mapping[str, Any],
    evidence_receipt: Mapping[str, Any],
    class_order: Sequence[Any] | None = None,
    positive_class: Any | None = None,
    sample_weight: Sequence[float] | None = None,
) -> ProbabilityCalibratorV1:
    """Fit a calibrator without accepting any holdout labels."""

    return ProbabilityCalibratorV1.fit(
        method=method,
        fit_probabilities=fit_probabilities,
        fit_labels=fit_labels,
        fit_scope=fit_scope,
        fit_row_refs=fit_row_refs,
        seed=seed,
        recipe=recipe,
        evidence_receipt=evidence_receipt,
        class_order=class_order,
        positive_class=positive_class,
        sample_weight=sample_weight,
    )


def threshold_curve(
    actual: Sequence[Any],
    probabilities: Sequence[float],
    *,
    thresholds: Sequence[float],
    positive_class: Any = 1,
    sample_weight: Sequence[float] | None = None,
    cost_matrix: Mapping[str, Any] | None = None,
    capacity: int | float | None = None,
    capacity_unit: str = "rate",
) -> list[dict[str, Any]]:
    y = np.asarray(actual)
    p = np.asarray(probabilities, dtype=float)
    if y.ndim != 1 or p.ndim != 1 or len(y) == 0 or len(y) != len(p):
        raise _error("CLASSIFICATION_THRESHOLD_INPUT_INVALID", "threshold inputs must be non-empty and aligned")
    if not np.isfinite(p).all() or ((p < 0) | (p > 1)).any():
        raise _error("CLASSIFICATION_THRESHOLD_INPUT_INVALID", "probabilities must be finite and in [0, 1]")
    if capacity_unit not in {"rate", "count"}:
        raise _error("CLASSIFICATION_POLICY_CAPACITY_INVALID", "capacity_unit must be either rate or count")
    if capacity is not None:
        if isinstance(capacity, bool) or not isinstance(capacity, (int, float)) or not np.isfinite(float(capacity)) or float(capacity) < 0:
            raise _error("CLASSIFICATION_POLICY_CAPACITY_INVALID", "capacity must be finite and non-negative")
    normalized_costs: dict[str, float] | None = None
    if cost_matrix is not None:
        if not isinstance(cost_matrix, Mapping):
            raise _error("CLASSIFICATION_POLICY_COSTS_INVALID", "cost_matrix must be an object")
        required = {"false_positive", "false_negative"}
        missing = required - set(cost_matrix)
        if missing:
            raise _error("CLASSIFICATION_POLICY_COSTS_INVALID", "cost_matrix requires false_positive and false_negative")
        normalized_costs = {}
        for key, raw_value in cost_matrix.items():
            if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float, np.integer, np.floating)):
                raise _error("CLASSIFICATION_POLICY_COSTS_INVALID", f"cost_matrix entry {key!r} must be finite numeric")
            value = float(raw_value)
            if not np.isfinite(value):
                raise _error("CLASSIFICATION_POLICY_COSTS_INVALID", f"cost_matrix entry {key!r} must be finite numeric")
            normalized_costs[str(key)] = value
    weights, weight_sum, _ = _weights(sample_weight, len(y))
    binary = (y == positive_class).astype(int)
    actual_support = float(weights[binary == 1].sum())
    rows: list[dict[str, Any]] = []
    for raw_threshold in thresholds:
        threshold = _validate_threshold(raw_threshold)
        predicted = (p >= threshold).astype(int)
        predicted_support = float(weights[predicted == 1].sum())
        row: dict[str, Any] = {
            "threshold": threshold,
            "positive_rate": float(predicted_support / weight_sum),
            "positive_count": int((predicted == 1).sum()),
            "precision": None,
            "recall": None,
            "f1": None,
            "status": "computed",
        }
        if capacity is not None:
            if capacity_unit == "rate":
                capacity_satisfied = row["positive_rate"] <= float(capacity) + 1e-12
                capacity_value = row["positive_rate"]
            else:
                capacity_satisfied = row["positive_count"] <= float(capacity) + 1e-12
                capacity_value = row["positive_count"]
            row["capacity"] = {
                "unit": capacity_unit,
                "limit": float(capacity),
                "observed": capacity_value,
                "satisfied": capacity_satisfied,
            }
        if normalized_costs is not None:
            true_positive = float(weights[(binary == 1) & (predicted == 1)].sum())
            false_positive = float(weights[(binary == 0) & (predicted == 1)].sum())
            false_negative = float(weights[(binary == 1) & (predicted == 0)].sum())
            true_negative = float(weights[(binary == 0) & (predicted == 0)].sum())
            expected_cost = (
                normalized_costs.get("true_positive", 0.0) * true_positive
                + normalized_costs.get("true_negative", 0.0) * true_negative
                + normalized_costs["false_positive"] * false_positive
                + normalized_costs["false_negative"] * false_negative
            ) / weight_sum
            row["confusion_weight"] = {
                "true_positive": true_positive,
                "true_negative": true_negative,
                "false_positive": false_positive,
                "false_negative": false_negative,
            }
            row["expected_cost"] = float(expected_cost)
            row["expected_utility"] = float(-expected_cost)
        if predicted_support <= 0 or actual_support <= 0:
            row["status"] = "undefined"
            row["reason"] = "positive class support is absent from predictions or actuals"
        else:
            precision = float(weights[(binary == 1) & (predicted == 1)].sum() / predicted_support)
            recall = float(weights[(binary == 1) & (predicted == 1)].sum() / actual_support)
            row["precision"] = precision
            row["recall"] = recall
            row["f1"] = 2 * precision * recall / (precision + recall) if precision + recall else None
            if row["f1"] is None:
                row["status"] = "undefined"
                row["reason"] = "precision and recall are both zero"
        rows.append(row)
    return rows


def select_threshold_from_oof(
    *,
    actual: Sequence[Any],
    probabilities: Sequence[float],
    method: str,
    scope: str,
    positive_class: Any = 1,
    thresholds: Sequence[float] | None = None,
    min_precision: float | None = None,
    sample_weight: Sequence[float] | None = None,
    cost_matrix: Mapping[str, Any] | None = None,
    capacity: int | float | None = None,
    capacity_unit: str = "rate",
) -> dict[str, Any]:
    if scope not in {"development_oof", "development_calibration_eval"}:
        raise _error(
            "CLASSIFICATION_THRESHOLD_SCOPE_INVALID",
            "threshold selection only accepts development OOF or disjoint calibration-evaluation probabilities",
        )
    if method not in {"max_f1", "max_recall_at_precision", "min_log_loss", "expected_utility"}:
        raise _error("CLASSIFICATION_THRESHOLD_METHOD_INVALID", method)
    if method == "expected_utility" and cost_matrix is None:
        raise _error("CLASSIFICATION_POLICY_COSTS_INVALID", "expected_utility requires a declared cost matrix")
    candidates = tuple(thresholds) if thresholds is not None else tuple(np.linspace(0.05, 0.95, 19))
    rows = threshold_curve(
        actual,
        probabilities,
        thresholds=candidates,
        positive_class=positive_class,
        sample_weight=sample_weight,
        cost_matrix=cost_matrix,
        capacity=capacity,
        capacity_unit=capacity_unit,
    )
    valid = [
        row
        for row in rows
        if row["status"] == "computed"
        and (capacity is None or bool(row.get("capacity", {}).get("satisfied", False)))
    ]
    if not valid:
        reason = "no threshold satisfies the declared capacity" if capacity is not None else "no threshold has defined positive-class support"
        raise _error("CLASSIFICATION_THRESHOLD_SUPPORT_INSUFFICIENT", reason)
    if method == "max_f1":
        selected = max(valid, key=lambda row: (float(row["f1"]), -float(row["threshold"])))
    elif method == "max_recall_at_precision":
        required = 0.0 if min_precision is None else float(min_precision)
        if not 0 <= required <= 1:
            raise _error("CLASSIFICATION_THRESHOLD_INVALID", "min_precision must be in [0, 1]")
        candidates_by_precision = [row for row in valid if float(row["precision"]) >= required]
        if not candidates_by_precision:
            return {
                "status": "undefined",
                "reason": "no development OOF threshold meets the declared precision constraint",
                "method": method,
                "scope": scope,
                "curve": rows,
            }
        selected = max(candidates_by_precision, key=lambda row: (float(row["recall"]), -float(row["threshold"])))
    elif method == "expected_utility":
        selected = max(valid, key=lambda row: (float(row["expected_utility"]), -float(row["threshold"])))
    else:
        return {
            "status": "undefined",
            "reason": "log loss evaluates probabilities and is independent of a hard threshold",
            "method": method,
            "scope": scope,
            "curve": rows,
            "positive_class": positive_class,
        }
    return {
        "status": "frozen_development_choice",
        "threshold": float(selected["threshold"]),
        "method": method,
        "scope": scope,
        "curve": rows,
        "positive_class": positive_class,
        "capacity_constraint": {
            "status": "applied" if capacity is not None else "not_declared",
            "unit": capacity_unit,
            "limit": float(capacity) if capacity is not None else None,
        },
        "selection_basis": {
            "method": method,
            "cost_matrix": (
                {str(key): float(value) for key, value in sorted((cost_matrix or {}).items(), key=lambda item: str(item))}
                if cost_matrix is not None else None
            ),
        },
    }


__all__ = [
    "ProbabilityCalibratorV1",
    "classification_metric_bundle",
    "compute_calibration_bins",
    "fit_probability_calibrator",
    "select_threshold_from_oof",
    "threshold_curve",
]
