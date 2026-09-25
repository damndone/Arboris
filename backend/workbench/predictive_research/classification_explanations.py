"""Descriptive, model-agnostic classification explanations."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

from ..canonical import sha256_canonical
from .contracts import ContractError


def compute_permutation_explanations(
    frame: pd.DataFrame,
    target: Sequence[Any],
    *,
    model_id: str,
    predict_proba: Callable[[pd.DataFrame], Sequence[float]],
    validation_row_refs: Sequence[str],
    feature_mapping: Mapping[str, str],
    seed: int,
    repeats: int = 5,
    positive_label: Any | None = None,
) -> dict[str, Any]:
    if len(frame) != len(target) or len(frame) != len(validation_row_refs) or repeats < 1:
        raise ContractError("CLASSIFICATION_EXPLANATION_INPUT_INVALID", "validation inputs must align")
    if set(feature_mapping) != set(frame.columns):
        raise ContractError("CLASSIFICATION_FEATURE_MAPPING_INVALID", "feature mapping must cover validation columns")
    y = np.asarray(target)
    base_probability = np.asarray(predict_proba(frame), dtype=float)
    positive = sorted(set(y.tolist()))[-1] if positive_label is None else positive_label
    binary = (y == positive).astype(int)
    try:
        base_score = float(roc_auc_score(binary, base_probability))
    except ValueError:
        raise ContractError("CLASSIFICATION_EXPLANATION_CLASS_SUPPORT", "validation explanation needs two classes")
    rng = np.random.default_rng(seed)
    importance: list[dict[str, Any]] = []
    for column in frame.columns:
        values: list[float] = []
        for _ in range(repeats):
            shuffled = frame.copy()
            shuffled[column] = rng.permutation(shuffled[column].to_numpy())
            probability = np.asarray(predict_proba(shuffled), dtype=float)
            try:
                score = float(roc_auc_score(binary, probability))
            except ValueError:
                score = base_score
            values.append(base_score - score)
        importance.append(
            {
                "feature": feature_mapping[column],
                "source_column": column,
                "importance": float(np.mean(values)),
                "stability_std": float(np.std(values, ddof=0)),
                "repeats": repeats,
                "direction": "positive" if np.mean(values) >= 0 else "negative",
            }
        )
    importance.sort(key=lambda row: (-row["importance"], row["feature"]))
    for rank, row in enumerate(importance, start=1):
        row["rank"] = rank
    return {
        "model_id": model_id,
        "method": "permutation_importance",
        "causal_interpretation": "not_causal",
        "sample_scope": "outer_validation",
        "validation_row_refs": list(validation_row_refs),
        "seed": seed,
        "importance": importance,
        "stability": {row["feature"]: {"rank": row["rank"], "std": row["stability_std"]} for row in importance},
    }


def compute_cross_fitted_permutation_explanations(
    folds: Sequence[Mapping[str, Any]],
    *,
    model_id: str,
    feature_mapping: Mapping[str, str],
    seed: int,
    repeats: int,
    positive_label: Any | None = None,
) -> dict[str, Any]:
    """Aggregate bounded permutation evidence across development validation folds."""

    if not folds or repeats < 1 or repeats > 5:
        raise ContractError("CLASSIFICATION_EXPLANATION_BUDGET_INVALID", "cross-fitted explanations need one to five repeats")
    per_fold: list[dict[str, Any]] = []
    validation_row_refs: list[str] = []
    for fold_number, fold in enumerate(folds):
        frame = fold.get("frame")
        target = fold.get("target")
        row_refs = fold.get("validation_row_refs")
        predict_proba = fold.get("predict_proba")
        if not isinstance(frame, pd.DataFrame) or not callable(predict_proba):
            raise ContractError("CLASSIFICATION_EXPLANATION_VALIDATION_DATA_UNAVAILABLE", "validation predictor is unavailable")
        if not isinstance(row_refs, Sequence) or isinstance(row_refs, (str, bytes)):
            raise ContractError("CLASSIFICATION_EXPLANATION_VALIDATION_DATA_UNAVAILABLE", "validation row identity is unavailable")
        refs = tuple(str(ref) for ref in row_refs)
        explanation = compute_permutation_explanations(
            frame,
            target,
            model_id=model_id,
            predict_proba=predict_proba,
            validation_row_refs=refs,
            feature_mapping=feature_mapping,
            seed=seed + fold_number,
            repeats=repeats,
            positive_label=positive_label,
        )
        explanation["fold"] = fold.get("fold", fold_number)
        per_fold.append(explanation)
        validation_row_refs.extend(refs)

    by_feature: dict[str, list[dict[str, Any]]] = {}
    for fold in per_fold:
        for row in fold["importance"]:
            by_feature.setdefault(row["feature"], []).append(row)
    importance: list[dict[str, Any]] = []
    rank_values: dict[str, list[int]] = {}
    for feature, rows in by_feature.items():
        values = [float(row["importance"]) for row in rows]
        std_values = [float(row["stability_std"]) for row in rows]
        importance.append(
            {
                "feature": feature,
                "source_column": rows[0]["source_column"],
                "importance": float(np.mean(values)),
                "stability_std": float(np.mean(std_values)),
                "folds": len(rows),
                "repeats": repeats,
                "direction": "positive" if np.mean(values) >= 0 else "negative",
            }
        )
        rank_values[feature] = [int(row["rank"]) for row in rows]
    importance.sort(key=lambda row: (-row["importance"], row["feature"]))
    for rank, row in enumerate(importance, start=1):
        row["rank"] = rank
    refs = list(dict.fromkeys(validation_row_refs))
    row_hash = f"sha256:{sha256_canonical(refs)}"
    stability = {
        "status": "computed",
        "interpretation": "descriptive_not_deployment_safety",
        "model_id": model_id,
        "sample_scope": "outer_validation",
        "fold_count": len(per_fold),
        "validation_row_refs": refs,
        "validation_row_refs_hash": row_hash,
        "feature_rank_values": rank_values,
        "feature_rank_range": {
            feature: [min(ranks), max(ranks)] for feature, ranks in rank_values.items()
        },
    }
    return {
        "status": "computed",
        "model_id": model_id,
        "method": "permutation_importance",
        "causal_interpretation": "not_causal",
        "sample_scope": "outer_validation",
        "validation_row_refs": refs,
        "validation_row_refs_hash": row_hash,
        "seed": seed,
        "repeats": repeats,
        "fold_count": len(per_fold),
        "importance": importance,
        "stability": stability,
    }


def summarize_shift(
    *,
    development: pd.DataFrame,
    validation: pd.DataFrame,
    subgroup_values: Mapping[str, Sequence[Any]] | None = None,
    minimum_support: int = 20,
) -> dict[str, Any]:
    if development.empty or validation.empty or not development.columns.tolist():
        return {
            "status": "unavailable",
            "reason_code": "CLASSIFICATION_SHIFT_DATA_UNAVAILABLE",
            "interpretation": "descriptive_not_deployment_safety",
            "features": [],
            "subgroups": {},
        }
    if set(development.columns) != set(validation.columns):
        raise ContractError("CLASSIFICATION_SHIFT_SCHEMA_MISMATCH", "shift frames must share feature columns")
    features: list[dict[str, Any]] = []
    for column in development.columns:
        left = pd.to_numeric(development[column], errors="coerce")
        right = pd.to_numeric(validation[column], errors="coerce")
        if left.isna().all() or right.isna().all():
            features.append({"feature": column, "status": "not_available", "reason": "non_numeric_or_all_missing"})
        else:
            features.append({"feature": column, "status": "descriptive", "development_mean": float(left.mean()), "validation_mean": float(right.mean()), "mean_difference": float(right.mean() - left.mean())})
    if not any(feature["status"] == "descriptive" for feature in features):
        return {
            "status": "unavailable",
            "reason_code": "CLASSIFICATION_SHIFT_NUMERIC_DATA_UNAVAILABLE",
            "interpretation": "descriptive_not_deployment_safety",
            "features": features,
            "subgroups": {},
        }
    subgroups: dict[str, Any] = {}
    for name, values in (subgroup_values or {}).items():
        if len(values) < minimum_support:
            subgroups[name] = {"status": "insufficient_support", "support": len(values), "minimum_support": minimum_support}
        else:
            subgroups[name] = {"status": "descriptive", "support": len(values), "minimum_support": minimum_support}
    return {"status": "descriptive", "interpretation": "descriptive_not_deployment_safety", "features": features, "subgroups": subgroups}


def compute_shap_explanations(*_: Any, **__: Any) -> dict[str, Any]:
    raise ContractError("CLASSIFICATION_EXPLANATION_PROVIDER_UNAVAILABLE", "SHAP is an optional provider in this release")


__all__ = [
    "compute_cross_fitted_permutation_explanations",
    "compute_permutation_explanations",
    "compute_shap_explanations",
    "summarize_shift",
]
