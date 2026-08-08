"""Deterministic ROC, PR, and threshold evidence calculations."""

from __future__ import annotations

from collections.abc import Mapping
import math
from typing import Any

import numpy as np

from workbench.contracts.model.roc_diagnostics import make_result_envelope

from .common import (
    _DEFAULT_MAX_THRESHOLDS,
    _DEFAULT_QUANTILE_GRID_SIZE,
    _decision_evidence,
    _make_provenance,
    _probability_metrics,
    _validate_inputs,
    _validate_threshold_options,
)


def _rank_auc(y_binary: np.ndarray, scores: np.ndarray) -> float:
    """Compute the Mann-Whitney probability with average ranks for ties."""

    order = np.argsort(scores, kind="mergesort")
    sorted_scores = scores[order]
    ranks = np.empty(scores.size, dtype=float)
    start = 0
    while start < sorted_scores.size:
        end = start + 1
        while end < sorted_scores.size and sorted_scores[end] == sorted_scores[start]:
            end += 1
        average_rank = (start + 1 + end) / 2.0
        ranks[order[start:end]] = average_rank
        start = end
    positive_count = int(y_binary.sum())
    negative_count = int(y_binary.size - positive_count)
    rank_sum = float(ranks[y_binary == 1].sum())
    auc = (rank_sum - positive_count * (positive_count + 1) / 2.0) / (
        positive_count * negative_count
    )
    return float(min(1.0, max(0.0, auc)))


def _threshold_values(
    scores: np.ndarray, threshold_policy: str, quantile_grid_size: int
) -> list[float]:
    if threshold_policy == "unique_scores":
        values = np.unique(scores)
    else:
        quantiles = np.linspace(0.0, 1.0, quantile_grid_size)
        values = np.unique(np.quantile(scores, quantiles, method="linear"))
    return [float(value) for value in sorted(values.tolist(), reverse=True)]


def _rate(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return float(numerator / denominator)


def _threshold_point(
    y_binary: np.ndarray,
    scores: np.ndarray,
    *,
    threshold: float | None,
    threshold_role: str,
) -> dict[str, Any]:
    if threshold_role == "above_max":
        predicted_positive = np.zeros(scores.size, dtype=bool)
    elif threshold_role == "below_min":
        predicted_positive = np.ones(scores.size, dtype=bool)
    else:
        predicted_positive = scores >= float(threshold)

    positive = y_binary == 1
    negative = ~positive
    tp = int(np.sum(predicted_positive & positive))
    fp = int(np.sum(predicted_positive & negative))
    tn = int(np.sum(~predicted_positive & negative))
    fn = int(np.sum(~predicted_positive & positive))
    sensitivity = _rate(tp, tp + fn)
    specificity = _rate(tn, tn + fp)
    ppv = _rate(tp, tp + fp)
    npv = _rate(tn, tn + fn)
    f1 = _rate(2 * tp, 2 * tp + fp + fn)
    false_positive_rate = _rate(fp, fp + tn)
    true_positive_rate = sensitivity
    precision = ppv
    recall = sensitivity
    return {
        "threshold": threshold,
        "threshold_role": threshold_role,
        "threshold_direction": "predict_positive_if_score_gte",
        "confusion_counts": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "sensitivity": sensitivity,
        "specificity": specificity,
        "ppv": ppv,
        "npv": npv,
        "f1": f1,
        "fpr": false_positive_rate,
        "tpr": true_positive_rate,
        "false_positive_rate": false_positive_rate,
        "true_positive_rate": true_positive_rate,
        "precision": precision,
        "recall": recall,
    }


def _stepwise_pr_auc(points: list[Mapping[str, Any]]) -> float:
    previous_recall = 0.0
    area = 0.0
    for point in points:
        precision = point["precision"]
        recall = float(point["recall"])
        if precision is not None and recall > previous_recall:
            area += (recall - previous_recall) * float(precision)
        previous_recall = max(previous_recall, recall)
    return float(min(1.0, max(0.0, area)))


def _trapezoid_roc_auc(points: list[Mapping[str, Any]]) -> float:
    area = 0.0
    for left, right in zip(points, points[1:]):
        area += (float(right["fpr"]) - float(left["fpr"])) * (
            float(left["tpr"]) + float(right["tpr"])
        ) / 2.0
    return float(min(1.0, max(0.0, area)))


def run_roc_curve(
    y_true: Any,
    scores: Any,
    *,
    positive_label: Any,
    score_semantics: str = "score",
    threshold_policy: str = "unique_scores",
    quantile_grid_size: int | None = None,
    max_thresholds: int = _DEFAULT_MAX_THRESHOLDS,
    missing_policy: str = "reject",
    constraint_policy: Mapping[str, Any] | None = None,
    cost_policy: Mapping[str, Any] | None = None,
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return bounded ROC/PR and threshold evidence without fitting a model."""

    prepared = _validate_inputs(
        y_true,
        scores,
        positive_label=positive_label,
        score_semantics=score_semantics,
        missing_policy=missing_policy,
    )
    threshold_policy, quantile_grid_size, max_thresholds = _validate_threshold_options(
        threshold_policy=threshold_policy,
        quantile_grid_size=quantile_grid_size,
        max_thresholds=max_thresholds,
    )
    values = _threshold_values(prepared.scores, threshold_policy, quantile_grid_size)
    if len(values) + 2 > max_thresholds:
        from .errors import RocDiagnosticsPackError

        raise RocDiagnosticsPackError(
            "ROC_DIAGNOSTICS_OUTPUT_TOO_LARGE",
            "threshold evidence exceeds max_thresholds",
        )

    threshold_evidence = [
        _threshold_point(
            prepared.y_binary,
            prepared.scores,
            threshold=None,
            threshold_role="above_max",
        )
    ]
    threshold_evidence.extend(
        _threshold_point(
            prepared.y_binary,
            prepared.scores,
            threshold=value,
            threshold_role="score",
        )
        for value in values
    )
    threshold_evidence.append(
        _threshold_point(
            prepared.y_binary,
            prepared.scores,
            threshold=None,
            threshold_role="below_min",
        )
    )

    roc_points = [
        {
            "threshold": point["threshold"],
            "threshold_role": point["threshold_role"],
            "fpr": point["fpr"],
            "tpr": point["tpr"],
            "false_positive_rate": point["false_positive_rate"],
            "true_positive_rate": point["true_positive_rate"],
        }
        for point in threshold_evidence
    ]
    pr_points = [
        {
            "threshold": point["threshold"],
            "threshold_role": point["threshold_role"],
            "precision": point["precision"],
            "recall": point["recall"],
        }
        for point in threshold_evidence
    ]
    probability_metrics = _probability_metrics(
        prepared.y_binary, prepared.scores, score_semantics
    )
    decision_evidence = _decision_evidence(
        threshold_evidence,
        constraint_policy=constraint_policy,
        cost_policy=cost_policy,
    )
    exact_auc = _rank_auc(prepared.y_binary, prepared.scores)
    sampled_roc_auc = _trapezoid_roc_auc(roc_points)
    sampled_pr_auc = _stepwise_pr_auc(pr_points)
    sampled_area_semantics = (
        "grid_based_trapezoid"
        if threshold_policy == "quantile_grid"
        else "unique_scores_trapezoid"
    )
    sampled_pr_semantics = (
        "grid_based_stepwise"
        if threshold_policy == "quantile_grid"
        else "unique_scores_stepwise"
    )
    metric_semantics = (
        "exact_rank_auc_and_grid_based_sampled_areas"
        if threshold_policy == "quantile_grid"
        else "exact_rank_auc_and_unique_threshold_sampled_areas"
    )
    result = {
        "score_semantics": score_semantics,
        "positive_label": prepared.positive_label,
        "negative_label": prepared.negative_label,
        "n_observations": int(prepared.y_binary.size),
        "n_positive": int(prepared.y_binary.sum()),
        "n_negative": int(prepared.y_binary.size - prepared.y_binary.sum()),
        "missing_metadata": prepared.missing_metadata,
        "threshold_policy": {
            "name": threshold_policy,
            **(
                {"quantile_grid_size": quantile_grid_size}
                if threshold_policy == "quantile_grid"
                else {}
            ),
            "max_thresholds": max_thresholds,
        },
        "tie_policy": "average_rank_half_credit",
        "auc_method": "rank_wilcoxon_average_ties",
        "auc": exact_auc,
        "auc_alias_of": "exact_auc",
        "auc_semantics": "exact_rank",
        "exact_auc": exact_auc,
        "exact_auc_method": "rank_wilcoxon_average_ties",
        "sampled_roc_auc": sampled_roc_auc,
        "sampled_roc_auc_method": "trapezoid",
        "sampled_roc_auc_semantics": sampled_area_semantics,
        "roc_points": roc_points,
        "pr_points": pr_points,
        "pr_auc_method": "stepwise_recall_precision",
        "pr_auc": sampled_pr_auc,
        "pr_auc_alias_of": "sampled_pr_auc",
        "pr_auc_semantics": sampled_pr_semantics,
        "sampled_pr_auc": sampled_pr_auc,
        "sampled_pr_auc_method": "stepwise_recall_precision",
        "sampled_pr_auc_semantics": sampled_pr_semantics,
        "threshold_evidence": threshold_evidence,
        "brier_score": probability_metrics["brier_score"],
        "log_loss": probability_metrics["log_loss"],
        "log_loss_defined": probability_metrics["log_loss_defined"],
        "probability_metrics": probability_metrics,
        "decision_evidence": decision_evidence,
    }
    return make_result_envelope(
        operation_id="roc.curve",
        result=result,
        provenance=_make_provenance(
            provenance,
            metric_semantics=metric_semantics,
        ),
    )


compute_roc_curve = run_roc_curve
roc_curve = run_roc_curve
evaluate_roc = run_roc_curve


__all__ = [
    "compute_roc_curve",
    "evaluate_roc",
    "roc_curve",
    "run_roc_curve",
]
