"""Bounded probability calibration evidence."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np

from workbench.contracts.model.roc_diagnostics import make_result_envelope

from .common import (
    _DEFAULT_MAX_BINS,
    _make_provenance,
    _probability_metrics,
    _validate_calibration_options,
    _validate_inputs,
)
from .errors import RocDiagnosticsPackError


def _calibration_edges(
    scores: np.ndarray, *, calibration_method: str, n_bins: int
) -> tuple[np.ndarray, np.ndarray]:
    if calibration_method == "equal_width":
        edges = np.linspace(0.0, 1.0, n_bins + 1)
        indices = np.searchsorted(edges[1:-1], scores, side="right")
        return edges, indices

    quantiles = np.quantile(
        scores, np.linspace(0.0, 1.0, n_bins + 1), method="linear"
    )
    edges = np.unique(quantiles)
    if edges.size == 1:
        return np.asarray([edges[0], edges[0]], dtype=float), np.zeros(
            scores.size, dtype=int
        )
    indices = np.searchsorted(edges[1:-1], scores, side="right")
    return edges, indices


def _calibration_bins(
    y_binary: np.ndarray,
    scores: np.ndarray,
    *,
    calibration_method: str,
    n_bins: int,
) -> list[dict[str, Any]]:
    edges, indices = _calibration_edges(
        scores, calibration_method=calibration_method, n_bins=n_bins
    )
    bins: list[dict[str, Any]] = []
    for index in range(edges.size - 1):
        selected = indices == index
        count = int(selected.sum())
        positive_count = int(y_binary[selected].sum())
        negative_count = count - positive_count
        if count:
            mean_probability = float(scores[selected].mean())
            observed_rate = float(y_binary[selected].mean())
            calibration_gap = float(observed_rate - mean_probability)
        else:
            mean_probability = None
            observed_rate = None
            calibration_gap = None
        bins.append(
            {
                "bin_index": index,
                "lower": float(edges[index]),
                "upper": float(edges[index + 1]),
                "interval": "[lower, upper]" if index == edges.size - 2 else "[lower, upper)",
                "count": count,
                "positive_count": positive_count,
                "negative_count": negative_count,
                "mean_predicted_probability": mean_probability,
                "observed_positive_rate": observed_rate,
                "calibration_gap": calibration_gap,
            }
        )
    return bins


def run_roc_calibration(
    y_true: Any,
    scores: Any,
    *,
    positive_label: Any,
    score_semantics: str | None = None,
    calibration_method: str | None = None,
    n_bins: int | None = None,
    max_bins: int = _DEFAULT_MAX_BINS,
    missing_policy: str = "reject",
    provenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return calibration bins for explicit probability scores only."""

    if score_semantics != "probability":
        raise RocDiagnosticsPackError(
            "ROC_DIAGNOSTICS_INVALID_SCORE_SEMANTICS",
            "roc.calibration requires score_semantics=probability",
        )
    if calibration_method is None:
        raise RocDiagnosticsPackError(
            "ROC_DIAGNOSTICS_UNKNOWN_POLICY",
            "roc.calibration requires calibration_method=equal_width or quantile",
        )
    if n_bins is None:
        raise RocDiagnosticsPackError(
            "ROC_DIAGNOSTICS_INVALID_OPTION",
            "roc.calibration requires an explicit n_bins bound",
        )
    calibration_method, n_bins, max_bins = _validate_calibration_options(
        calibration_method=calibration_method,
        n_bins=n_bins,
        max_bins=max_bins,
    )
    prepared = _validate_inputs(
        y_true,
        scores,
        positive_label=positive_label,
        score_semantics="probability",
        missing_policy=missing_policy,
    )
    bins = _calibration_bins(
        prepared.y_binary,
        prepared.scores,
        calibration_method=calibration_method,
        n_bins=n_bins,
    )
    probability_metrics = _probability_metrics(
        prepared.y_binary, prepared.scores, "probability"
    )
    result = {
        "score_semantics": "probability",
        "positive_label": prepared.positive_label,
        "negative_label": prepared.negative_label,
        "n_observations": int(prepared.y_binary.size),
        "n_positive": int(prepared.y_binary.sum()),
        "n_negative": int(prepared.y_binary.size - prepared.y_binary.sum()),
        "missing_metadata": prepared.missing_metadata,
        "calibration_method": calibration_method,
        "requested_bins": n_bins,
        "actual_bins": len(bins),
        "bins": bins,
        "brier_score": probability_metrics["brier_score"],
        "log_loss": probability_metrics["log_loss"],
        "log_loss_defined": probability_metrics["log_loss_defined"],
        "probability_metrics": probability_metrics,
    }
    return make_result_envelope(
        operation_id="roc.calibration",
        result=result,
        provenance=_make_provenance(
            provenance,
            metric_semantics="probability_calibration",
        ),
    )


compute_roc_calibration = run_roc_calibration
roc_calibration = run_roc_calibration
evaluate_calibration = run_roc_calibration


__all__ = [
    "compute_roc_calibration",
    "evaluate_calibration",
    "roc_calibration",
    "run_roc_calibration",
]
