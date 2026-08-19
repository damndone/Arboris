"""Descriptive, model-agnostic classification explanations."""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score

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
) -> dict[str, Any]:
    if len(frame) != len(target) or len(frame) != len(validation_row_refs) or repeats < 1:
        raise ContractError("CLASSIFICATION_EXPLANATION_INPUT_INVALID", "validation inputs must align")
    if set(feature_mapping) != set(frame.columns):
        raise ContractError("CLASSIFICATION_FEATURE_MAPPING_INVALID", "feature mapping must cover validation columns")
    y = np.asarray(target)
    base_probability = np.asarray(predict_proba(frame), dtype=float)
    binary = (y == sorted(set(y.tolist()))[-1]).astype(int)
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


def summarize_shift(
    *,
    development: pd.DataFrame,
    validation: pd.DataFrame,
    subgroup_values: Mapping[str, Sequence[Any]] | None = None,
    minimum_support: int = 20,
) -> dict[str, Any]:
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
    subgroups: dict[str, Any] = {}
    for name, values in (subgroup_values or {}).items():
        if len(values) < minimum_support:
            subgroups[name] = {"status": "insufficient_support", "support": len(values), "minimum_support": minimum_support}
        else:
            subgroups[name] = {"status": "descriptive", "support": len(values), "minimum_support": minimum_support}
    return {"status": "descriptive", "interpretation": "descriptive_not_deployment_safety", "features": features, "subgroups": subgroups}


def compute_shap_explanations(*_: Any, **__: Any) -> dict[str, Any]:
    raise ContractError("CLASSIFICATION_EXPLANATION_PROVIDER_UNAVAILABLE", "SHAP is an optional provider in this release")


__all__ = ["compute_permutation_explanations", "compute_shap_explanations", "summarize_shift"]
