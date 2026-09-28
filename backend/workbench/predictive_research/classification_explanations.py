"""Bounded predictive explanations for classification validation evidence."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from .contracts import ContractError


_VALIDATION_SCOPES = frozenset({"validation", "outer_validation", "cross_fitted_validation"})


def _error(code: str, message: str) -> ContractError:
    return ContractError(code, message)


def _probability_for_positive(
    output: Sequence[Any],
    *,
    row_count: int,
    class_order: tuple[Any, ...],
    positive_class: Any,
) -> tuple[np.ndarray, str]:
    values = np.asarray(output, dtype=float)
    if values.ndim == 1:
        probability = values
        if len(class_order) != 2:
            raise _error("CLASSIFICATION_EXPLANATION_PROBABILITY_INVALID", "one probability per row is binary-only")
        if len(probability) != row_count or not np.isfinite(probability).all():
            raise _error("CLASSIFICATION_EXPLANATION_PROBABILITY_INVALID", "one-dimensional prediction output must be finite")
        output_kind = "probability" if ((probability >= 0) & (probability <= 1)).all() else "ranking_score"
    elif values.ndim == 2:
        if values.shape != (row_count, len(class_order)):
            raise _error("CLASSIFICATION_EXPLANATION_PROBABILITY_INVALID", "probability output does not match class order")
        if not np.isfinite(values).all() or (values < -1e-12).any() or (values > 1 + 1e-12).any() or not np.allclose(values.sum(axis=1), 1.0, atol=1e-8):
            raise _error("CLASSIFICATION_EXPLANATION_PROBABILITY_INVALID", "probability output is not finite and normalized")
        probability = values[:, class_order.index(positive_class)]
        output_kind = "probability"
    else:
        raise _error("CLASSIFICATION_EXPLANATION_PROBABILITY_INVALID", "probability output must be one- or two-dimensional")
    if len(probability) != row_count or not np.isfinite(probability).all():
        raise _error("CLASSIFICATION_EXPLANATION_PROBABILITY_INVALID", "positive prediction output must be finite")
    return probability, output_kind


def _stable_classes(values: Sequence[Any]) -> tuple[Any, ...]:
    try:
        return tuple(sorted(set(values)))
    except TypeError:
        return tuple(sorted(set(values), key=lambda value: (type(value).__name__, repr(value))))


def compute_permutation_explanations(
    frame: pd.DataFrame,
    target: Sequence[Any],
    *,
    model_id: str,
    predict_proba: Callable[[pd.DataFrame], Sequence[Any]],
    validation_row_refs: Sequence[str],
    feature_mapping: Mapping[str, str],
    seed: int,
    repeats: int = 5,
    n_repeats: int | None = None,
    class_order: Sequence[Any] | None = None,
    positive_class: Any | None = None,
    sample_scope: str = "outer_validation",
    minimum_support: int = 2,
) -> dict[str, Any]:
    """Compute seeded permutation importance using only the supplied validation rows.

    There is intentionally no training-frame argument.  A caller must pass an
    already-fitted prediction function and explicitly identify the validation
    scope; this keeps the explanation from becoming a second route to sealed
    holdout labels or development rows.
    """

    if sample_scope not in _VALIDATION_SCOPES:
        raise _error("CLASSIFICATION_EXPLANATION_SCOPE_INVALID", "permutation explanations require validation rows")
    if not isinstance(frame, pd.DataFrame) or frame.empty or frame.shape[1] == 0:
        raise _error("CLASSIFICATION_EXPLANATION_INPUT_INVALID", "validation frame must be a non-empty DataFrame")
    y = np.asarray(target)
    refs = tuple(validation_row_refs)
    if (
        y.ndim != 1
        or len(frame) != len(y)
        or len(frame) != len(refs)
        or not all(isinstance(ref, str) and ref for ref in refs)
        or len(set(refs)) != len(refs)
    ):
        raise _error("CLASSIFICATION_EXPLANATION_INPUT_INVALID", "validation frame, target and row refs must align")
    if not isinstance(model_id, str) or not model_id.strip():
        raise _error("CLASSIFICATION_EXPLANATION_INPUT_INVALID", "model_id must be non-empty")
    if not callable(predict_proba):
        raise _error("CLASSIFICATION_EXPLANATION_INPUT_INVALID", "predict_proba must be callable")
    if not isinstance(seed, (int, np.integer)) or isinstance(seed, bool) or int(seed) < 0:
        raise _error("CLASSIFICATION_SEED_INVALID", "seed must be a non-negative integer")
    if n_repeats is not None:
        if repeats != 5 and repeats != n_repeats:
            raise _error("CLASSIFICATION_EXPLANATION_INPUT_INVALID", "repeats and n_repeats disagree")
        repeats = n_repeats
    if not isinstance(repeats, int) or isinstance(repeats, bool) or not 1 <= repeats <= 100:
        raise _error("CLASSIFICATION_EXPLANATION_INPUT_INVALID", "repeats must be an integer in [1, 100]")
    if not isinstance(minimum_support, int) or isinstance(minimum_support, bool) or minimum_support < 2:
        raise _error("CLASSIFICATION_EXPLANATION_SUPPORT_INVALID", "minimum_support must be at least two")
    if not isinstance(feature_mapping, Mapping) or set(feature_mapping) != set(frame.columns):
        raise _error("CLASSIFICATION_FEATURE_MAPPING_INVALID", "feature mapping must cover validation columns exactly")
    if any(not isinstance(value, str) or not value.strip() for value in feature_mapping.values()):
        raise _error("CLASSIFICATION_FEATURE_MAPPING_INVALID", "mapped feature names must be non-empty")
    if isinstance(class_order, (str, bytes)):
        raise _error("CLASSIFICATION_CLASS_ORDER_INVALID", "class_order must be a sequence of labels, not text")
    classes = tuple(class_order) if class_order is not None else _stable_classes(y.tolist())
    if (
        len(classes) < 2
        or len(set(classes)) != len(classes)
        or len({str(label) for label in classes}) != len(classes)
        or not set(y.tolist()).issubset(set(classes))
    ):
        raise _error("CLASSIFICATION_CLASS_ORDER_MISMATCH", "class_order must cover validation labels")
    positive = positive_class
    if len(classes) == 2 and positive is None:
        positive = 1 if 1 in classes else classes[-1]
    if positive is None or positive not in classes:
        raise _error("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is required for permutation AUC")
    support = {
        "row_count": len(y),
        "positive_count": int(np.count_nonzero(y == positive)),
        "negative_count": int(np.count_nonzero(y != positive)),
        "minimum_required": minimum_support,
    }
    if min(support["positive_count"], support["negative_count"]) < minimum_support:
        return {
            "status": "insufficient_support",
            "reason": "validation support is below the declared minimum",
            "model_id": model_id,
            "method": "permutation_importance",
            "causal_interpretation": "not_causal",
            "interpretation": "predictive_association_only",
            "sample_scope": sample_scope,
            "validation_row_refs": list(refs),
            "seed": int(seed),
            "support": {"status": "insufficient_support", **support},
            "importance": [],
            "stability": {},
        }
    try:
        base_probability, output_kind = _probability_for_positive(
            predict_proba(frame.copy()),
            row_count=len(frame),
            class_order=classes,
            positive_class=positive,
        )
        base_score = float(roc_auc_score((y == positive).astype(int), base_probability))
    except (ValueError, TypeError) as exc:
        raise _error("CLASSIFICATION_EXPLANATION_CLASS_SUPPORT", "validation explanation needs two supported classes") from exc
    rng = np.random.default_rng(int(seed))
    importance: list[dict[str, Any]] = []
    for column in frame.columns:
        drops: list[float] = []
        for _ in range(repeats):
            shuffled = frame.copy()
            shuffled[column] = rng.permutation(shuffled[column].to_numpy(copy=True))
            probability, permutation_output_kind = _probability_for_positive(
                predict_proba(shuffled),
                row_count=len(shuffled),
                class_order=classes,
                positive_class=positive,
            )
            try:
                score = float(roc_auc_score((y == positive).astype(int), probability))
            except (ValueError, TypeError) as exc:
                raise _error("CLASSIFICATION_EXPLANATION_SCORE_FAILED", "permuted validation score is undefined") from exc
            drops.append(base_score - score)
            if permutation_output_kind != output_kind:
                output_kind = "mixed_probability_and_ranking_score"
        mean_drop = float(np.mean(drops))
        standard_deviation = float(np.std(drops, ddof=0))
        importance.append(
            {
                "feature": feature_mapping[column],
                "source_column": column,
                "importance": mean_drop,
                "stability_std": standard_deviation,
                "stability_status": "stable" if standard_deviation <= 0.05 else "variable",
                "repeat_values": drops,
                "repeats": repeats,
                "direction": "positive" if mean_drop >= 0 else "negative",
            }
        )
    importance.sort(key=lambda row: (-row["importance"], row["feature"]))
    for rank, row in enumerate(importance, start=1):
        row["rank"] = rank
    return {
        "status": "computed",
        "model_id": model_id,
        "method": "permutation_importance",
        "causal_interpretation": "not_causal",
        "interpretation": "predictive_association_only",
        "sample_scope": sample_scope,
        "validation_row_refs": list(refs),
        "seed": int(seed),
        "positive_class": positive,
        "prediction_output_kind": output_kind,
        "support": {"status": "adequate", **support},
        "base_score": base_score,
        "importance": importance,
        "stability": {
            row["feature"]: {
                "rank": row["rank"],
                "std": row["stability_std"],
                "status": row["stability_status"],
            }
            for row in importance
        },
    }


def summarize_shift(
    *,
    development: pd.DataFrame,
    validation: pd.DataFrame,
    subgroup_values: Mapping[str, Sequence[Any]] | None = None,
    minimum_support: int = 20,
    bins: int = 10,
    statistics: Sequence[str] = ("mean", "distribution"),
) -> dict[str, Any]:
    """Return bounded descriptive shift facts; this is not a causal or safety claim."""

    if not isinstance(development, pd.DataFrame) or not isinstance(validation, pd.DataFrame):
        raise _error("CLASSIFICATION_SHIFT_INPUT_INVALID", "shift inputs must be DataFrames")
    if tuple(development.columns) != tuple(validation.columns):
        raise _error("CLASSIFICATION_SHIFT_SCHEMA_MISMATCH", "shift frames must share feature columns in order")
    if not isinstance(minimum_support, int) or isinstance(minimum_support, bool) or minimum_support < 1:
        raise _error("CLASSIFICATION_SHIFT_SUPPORT_INVALID", "minimum_support must be positive")
    if not isinstance(bins, int) or isinstance(bins, bool) or not 1 <= bins <= 100:
        raise _error("CLASSIFICATION_SHIFT_BINS_INVALID", "bins must be an integer in [1, 100]")
    if (
        isinstance(statistics, (str, bytes))
        or not isinstance(statistics, Sequence)
        or not statistics
        or any(
            not isinstance(statistic, str) or statistic not in {"mean", "distribution"}
            for statistic in statistics
        )
        or len(set(statistics)) != len(statistics)
    ):
        raise _error("CLASSIFICATION_SHIFT_STATISTICS_INVALID", "statistics must be a unique non-empty subset of mean and distribution")
    features: list[dict[str, Any]] = []
    for column in development.columns:
        left = pd.to_numeric(development[column], errors="coerce")
        right = pd.to_numeric(validation[column], errors="coerce")
        left_valid = left.dropna()
        right_valid = right.dropna()
        if left_valid.empty or right_valid.empty:
            features.append(
                {
                    "feature": column,
                    "status": "not_available",
                    "reason": "non_numeric_or_all_missing",
                    "causal_interpretation": "not_causal",
                }
            )
            continue
        combined_min = float(min(left_valid.min(), right_valid.min()))
        combined_max = float(max(left_valid.max(), right_valid.max()))
        if combined_min == combined_max:
            edges = np.linspace(combined_min - 0.5, combined_max + 0.5, bins + 1)
        else:
            edges = np.linspace(combined_min, combined_max, bins + 1)
        development_counts, _ = np.histogram(left_valid.to_numpy(dtype=float), bins=edges)
        validation_counts, _ = np.histogram(right_valid.to_numpy(dtype=float), bins=edges)
        feature = {
            "feature": column,
            "status": "descriptive",
            "development_support": int(len(left_valid)),
            "validation_support": int(len(right_valid)),
            "causal_interpretation": "not_causal",
        }
        if "mean" in statistics:
            feature.update(
                {
                    "development_mean": float(left_valid.mean()),
                    "validation_mean": float(right_valid.mean()),
                    "mean_difference": float(right_valid.mean() - left_valid.mean()),
                }
            )
        if "distribution" in statistics:
            feature["distribution"] = {
                "status": "descriptive",
                "bin_edges": [float(value) for value in edges],
                "development_counts": [int(value) for value in development_counts],
                "validation_counts": [int(value) for value in validation_counts],
            }
        features.append(feature)
    subgroups: dict[str, Any] = {}
    for name, values in (subgroup_values or {}).items():
        support = len(values)
        if support < minimum_support:
            subgroups[name] = {
                "status": "insufficient_support",
                "support": support,
                "minimum_support": minimum_support,
                "reason": "support below descriptive minimum",
            }
        else:
            subgroups[name] = {"status": "descriptive", "support": support, "minimum_support": minimum_support}
    return {
        "status": "descriptive",
        "interpretation": "descriptive_not_deployment_safety",
        "causal_interpretation": "not_causal",
        "inference_note": "descriptive_not_causal",
        "bin_count": bins,
        "statistics": list(statistics),
        "weighting": "unweighted",
        "features": features,
        "subgroups": subgroups,
    }


def compute_shap_explanations(*_: Any, **__: Any) -> dict[str, Any]:
    raise _error("CLASSIFICATION_EXPLANATION_PROVIDER_UNAVAILABLE", "SHAP is an optional provider in this release")


permutation_importance = compute_permutation_explanations


__all__ = [
    "compute_permutation_explanations",
    "compute_shap_explanations",
    "permutation_importance",
    "summarize_shift",
]
