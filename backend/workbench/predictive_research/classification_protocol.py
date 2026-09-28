"""Nested development, calibration/threshold isolation and holdout protocol."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .classification_adapters import get_classification_adapter
from .classification_metrics import classification_metric_bundle, compute_calibration_bins, threshold_curve
from .contracts import ContractError
from .split_kernel import ClassificationSplitManifestV1, build_classification_split_manifest


class HoldoutSealGuardV1:
    """In-memory test/runtime guard that never exposes sealed holdout arrays."""

    _ALLOWED_METRICS = frozenset({"accuracy", "balanced_accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc", "log_loss", "brier_score"})

    def __init__(self, *, holdout_labels: Sequence[Any], holdout_probabilities: Sequence[float], holdout_predictions: Sequence[Any], metric_release_plan: Mapping[str, Any], positive_class: Any | None = None):
        if len(holdout_labels) == 0 or len(holdout_labels) != len(holdout_probabilities) or len(holdout_labels) != len(holdout_predictions):
            raise ContractError("CLASSIFICATION_HOLDOUT_INPUT_INVALID", "holdout arrays must align and be non-empty")
        metrics = metric_release_plan.get("metrics") if isinstance(metric_release_plan, Mapping) else None
        if (
            not isinstance(metrics, list)
            or not metrics
            or any(not isinstance(item, str) for item in metrics)
            or len(set(metrics)) != len(metrics)
            or set(metrics) - self._ALLOWED_METRICS
        ):
            raise ContractError("CLASSIFICATION_METRIC_RELEASE_PLAN_INVALID", "holdout metric release plan must list metrics")
        self._labels = tuple(holdout_labels)
        self._probabilities = tuple(float(item) for item in holdout_probabilities)
        self._predictions = tuple(holdout_predictions)
        self._metrics = tuple(metrics)
        self._positive_class = positive_class
        self._released = False
        self.access_ledger: list[dict[str, Any]] = []

    def read_labels(self) -> tuple[Any, ...]:
        self.access_ledger.append({"kind": "label_read", "decision": "rejected"})
        raise ContractError("CLASSIFICATION_HOLDOUT_SEALED", "holdout labels are unavailable before one authorized release")

    def read_probabilities(self) -> tuple[float, ...]:
        self.access_ledger.append({"kind": "prediction_read", "decision": "rejected"})
        raise ContractError("CLASSIFICATION_HOLDOUT_SEALED", "holdout predictions are unavailable before one authorized release")

    def release(self, *, authorization: str) -> dict[str, Any]:
        if self._released:
            self.access_ledger.append({"kind": "declared_evaluation", "decision": "rejected", "reason": "repeated"})
            raise ContractError("CLASSIFICATION_HOLDOUT_RELEASE_REPEATED", "holdout release is one-time")
        if authorization != "one-time":
            self.access_ledger.append({"kind": "declared_evaluation", "decision": "rejected", "reason": "authorization"})
            raise ContractError("CLASSIFICATION_HOLDOUT_AUTHORIZATION_REQUIRED", "one-time authorization is required")
        self._released = True
        self.access_ledger.append({"kind": "declared_evaluation", "decision": "allowed", "metrics": list(self._metrics)})
        actual = np.asarray(self._labels)
        probabilities = np.asarray(self._probabilities)
        predictions = np.asarray(self._predictions)
        positive = self._positive_class
        if positive is None:
            positive = 1 if 1 in actual else sorted(set(actual.tolist()))[-1]
        bundle = classification_metric_bundle(
            actual=actual,
            probabilities=probabilities,
            predictions=predictions,
            positive_class=positive,
            threshold=0.5,
            sample_scope="final_holdout",
            evaluation_design="sealed_holdout",
            numerical_method="same_library_regression",
            inference_basis="descriptive",
            validation_level="validated",
        )
        return {"metrics": {name: bundle["metrics"].get(name) for name in self._metrics}, "status": "released_once", "access_ledger": list(self.access_ledger)}


@dataclass(frozen=True)
class BoundedSearchV1:
    candidates: tuple[str, ...]
    search_space: Mapping[str, Any]
    primary_metric: str
    max_trials: int
    max_seconds: int
    max_cpu_seconds: int
    seed: int
    status: str = "declared"

    def validate(self, *, allowed_parameters: set[str] | frozenset[str]) -> None:
        if not self.candidates or not isinstance(self.search_space, Mapping):
            raise ContractError("CLASSIFICATION_SEARCH_INVALID", "search candidates and search_space are required")
        if self.max_trials < 1 or self.max_seconds < 1 or self.max_cpu_seconds < 1:
            raise ContractError("CLASSIFICATION_SEARCH_BUDGET_INVALID", "search budgets must be positive")
        unknown = set(self.search_space) - set(allowed_parameters)
        if unknown:
            raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_UNKNOWN", f"unknown search parameters: {sorted(unknown)}")

    def validate_candidate(self, candidate: Mapping[str, Any], *, allowed_parameters: set[str] | frozenset[str]) -> None:
        unknown = set(candidate) - set(allowed_parameters)
        if unknown:
            raise ContractError("CLASSIFICATION_SEARCH_PARAMETER_UNKNOWN", f"unknown candidate parameters: {sorted(unknown)}")


def select_threshold_from_oof(*, actual: Sequence[Any], probabilities: Sequence[float], method: str, scope: str, positive_class: Any = 1) -> dict[str, Any]:
    if scope != "development_oof":
        raise ContractError("CLASSIFICATION_THRESHOLD_SCOPE_INVALID", "threshold selection only accepts development OOF probabilities")
    if method not in {"max_f1", "max_recall_at_precision", "min_log_loss"}:
        raise ContractError("CLASSIFICATION_THRESHOLD_METHOD_INVALID", method)
    candidates = np.linspace(0.05, 0.95, 19)
    rows = threshold_curve(actual, probabilities, thresholds=candidates, positive_class=positive_class)
    if method == "max_f1":
        selected = max(rows, key=lambda row: (row["f1"], -row["threshold"]))
    elif method == "min_log_loss":
        selected = min(rows, key=lambda row: abs(row["threshold"] - 0.5))
    else:
        selected = max(rows, key=lambda row: (row["recall"], -row["threshold"]))
    return {"threshold": selected["threshold"], "method": method, "scope": scope, "curve": rows, "status": "frozen_development_choice"}


def _oof_probabilities(
    frame: pd.DataFrame,
    target: pd.Series,
    manifest: ClassificationSplitManifestV1,
    *,
    model_id: str,
    seed: int,
    positive_class: Any,
) -> tuple[np.ndarray, dict[str, Any]]:
    result = np.full(len(frame), np.nan, dtype=float)
    development = [index for index, assignment in enumerate(manifest.assignments) if assignment.partition == "development"]
    folds = sorted({manifest.assignments[index].cv_fold for index in development if manifest.assignments[index].cv_fold is not None})
    if not folds:
        raise ContractError("CLASSIFICATION_SPLIT_FOLD_INVALID", "development split has no validation folds")
    for fold in folds:
        validation = [index for index in development if manifest.assignments[index].cv_fold == fold]
        training = [index for index in development if index not in validation]
        if not validation or not training or len(set(target.iloc[training].tolist())) < 2:
            raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", "fold lacks training class support")
        adapter = get_classification_adapter(model_id, seed=seed)
        adapter.fit(frame.iloc[training], target.iloc[training])
        probabilities = adapter.predict_proba(frame.iloc[validation])
        try:
            positive_index = list(adapter._classes).index(positive_class)
        except ValueError as exc:
            raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in adapter class order") from exc
        result[validation] = probabilities[:, positive_index]
    if np.isnan(result[development]).any():
        raise ContractError("CLASSIFICATION_OOF_INCOMPLETE", "every development row needs one OOF probability")
    return result, {"folds": folds, "oof_row_refs": [manifest.assignments[index].row_ref for index in development]}


def _derangement(values: list[Any], *, rng: np.random.Generator) -> list[Any] | None:
    """Find an exact reproducible value-level derangement without changing counts."""

    if len(values) < 2 or len(set(values)) < 2:
        return None
    counts = Counter(values)
    if max(counts.values()) * 2 > len(values):
        return None

    labels = list(dict.fromkeys(values))
    tie_order = rng.permutation(len(labels)).tolist()
    tie_rank = {labels[index]: rank for rank, index in enumerate(tie_order)}
    labels.sort(key=lambda label: (-counts[label], tie_rank[label]))
    ordered_positions = [
        position
        for label in labels
        for position, value in enumerate(values)
        if value == label
    ]
    ordered_values = [values[position] for position in ordered_positions]
    shift = max(counts.values())
    rotated_values = ordered_values[shift:] + ordered_values[:shift]
    candidate: list[Any] = [None] * len(values)
    for position, value in zip(ordered_positions, rotated_values, strict=True):
        candidate[position] = value
    if all(candidate[index] != values[index] for index in range(len(values))):
        return candidate
    return None


def _permuted_target_control(
    target: pd.Series,
    development: list[int],
    manifest: ClassificationSplitManifestV1,
    *,
    seed: int,
) -> tuple[pd.Series | None, dict[str, Any]]:
    """Build a row-unit derangement constrained by the frozen CV folds."""

    rng = np.random.default_rng(seed)
    values = target.iloc[development].tolist()
    positions_by_fold: dict[int, list[int]] = {}
    for position, row_index in enumerate(development):
        fold = manifest.assignments[row_index].cv_fold
        if fold is None:
            return None, {
                "status": "blocked",
                "reason_code": "CLASSIFICATION_CONTROL_FOLD_UNIT_UNAVAILABLE",
                "evidence_level": "insufficient",
            }
        positions_by_fold.setdefault(fold, []).append(position)
    for fold, positions in positions_by_fold.items():
        original = [values[position] for position in positions]
        permuted = _derangement(original, rng=rng)
        if permuted is None:
            return None, {
                "status": "blocked",
                "reason_code": "CLASSIFICATION_CONTROL_DERANGEMENT_INSUFFICIENT_SUPPORT",
                "evidence_level": "insufficient",
                "exchangeability_unit": "row_within_development_fold",
                "fold": fold,
                "fold_row_count": len(positions),
            }
        for position, value in zip(positions, permuted, strict=True):
            values[position] = value
    permuted_target = target.copy()
    permuted_target.iloc[development] = values
    return permuted_target, {
        "status": "computed",
        "exchangeability_unit": "row_within_development_fold",
        "permutation": "value_level_derangement",
        "seed": seed,
    }


def run_classification_protocol(
    frame: pd.DataFrame,
    target: pd.Series,
    *,
    row_refs: Sequence[str],
    model_ids: Sequence[str] = ("logistic_regression", "random_forest"),
    final_holdout_fraction: float = 0.2,
    cv_folds: int = 3,
    seed: int = 0,
    positive_class: Any | None = None,
) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame) or len(frame) != len(target) or len(frame) != len(row_refs):
        raise ContractError("CLASSIFICATION_PROTOCOL_INPUT_INVALID", "frame, target and row_refs must align")
    model_ids_tuple = tuple(model_ids)
    if not model_ids_tuple or len(set(model_ids_tuple)) != len(model_ids_tuple):
        raise ContractError("CLASSIFICATION_MODEL_SET_INVALID", "model_ids must be non-empty and unique")
    manifest = build_classification_split_manifest(
        row_refs=row_refs,
        labels=target.tolist(),
        profile="iid_stratified",
        final_holdout_fraction=final_holdout_fraction,
        cv_folds=cv_folds,
        random_seed=seed,
    )
    development = [index for index, assignment in enumerate(manifest.assignments) if assignment.partition == "development"]
    holdout = [index for index, assignment in enumerate(manifest.assignments) if assignment.partition == "final_holdout"]
    development_labels = target.iloc[development].tolist()
    development_classes = set(development_labels)
    if len(development_classes) != 2:
        raise ContractError("CLASSIFICATION_TASK_TYPE_UNSUPPORTED", "the protocol slice currently requires binary development labels")
    positive = positive_class
    if positive is None:
        positive = 1 if 1 in development_classes else sorted(development_classes)[-1]
    if positive not in development_classes:
        raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is absent from development labels")
    negative = next(value for value in development_classes if value != positive)
    models: dict[str, Any] = {}
    candidate_adapters: dict[str, Any] = {}
    selection_scores: dict[str, float] = {}
    controls: list[dict[str, Any]] = []
    for position, model_id in enumerate(model_ids_tuple):
        oof, oof_receipt = _oof_probabilities(
            frame,
            target,
            manifest,
            model_id=model_id,
            seed=seed + position,
            positive_class=positive,
        )
        threshold = select_threshold_from_oof(
            actual=development_labels,
            probabilities=oof[development].tolist(),
            method="max_f1",
            scope="development_oof",
            positive_class=positive,
        )
        oof_predictions = np.where(oof[development] >= threshold["threshold"], positive, negative)
        oof_bundle = classification_metric_bundle(
            actual=development_labels,
            probabilities=oof[development].tolist(),
            predictions=oof_predictions.tolist(),
            positive_class=positive,
            threshold=threshold["threshold"],
            sample_scope="development_oof",
            evaluation_design="cross_fitted_oof",
            numerical_method="same_library_regression",
            inference_basis="descriptive",
            validation_level="validated",
        )
        calibration = compute_calibration_bins(
            development_labels,
            oof[development].tolist(),
            sample_scope="development_oof",
        )
        calibration.update(
            {
                "status": "descriptive",
                "brier_score": oof_bundle["metrics"]["brier_score"],
            }
        )
        final_adapter = get_classification_adapter(model_id, seed=seed + position)
        final_adapter.fit(frame.iloc[development], target.iloc[development])
        candidate_adapters[model_id] = final_adapter
        score = oof_bundle["metrics"]["roc_auc"]["point_estimate"]
        selection_scores[model_id] = float(score) if score is not None else float("-inf")
        models[model_id] = {
            "metadata": final_adapter.metadata,
            "oof": oof_receipt,
            "threshold": threshold,
            "oof_metrics": oof_bundle,
            "calibration": calibration,
            "holdout": {"status": "sealed_candidate"},
            "holdout_row_refs": [row_refs[index] for index in holdout],
        }
        permuted_target, control_receipt = _permuted_target_control(
            target,
            development,
            manifest,
            seed=seed + position,
        )
        if permuted_target is None:
            controls.append(
                {
                    "control": "permuted_target",
                    "model_id": model_id,
                    **control_receipt,
                    "sample_scope": "development_oof",
                    "split_hash": manifest.content_hash,
                }
            )
            continue
        control_oof, _ = _oof_probabilities(
            frame,
            permuted_target,
            manifest,
            model_id=model_id,
            seed=seed + position,
            positive_class=positive,
        )
        control_predictions = np.where(control_oof[development] >= 0.5, positive, negative)
        control_bundle = classification_metric_bundle(
            actual=development_labels,
            probabilities=control_oof[development].tolist(),
            predictions=control_predictions.tolist(),
            positive_class=positive,
            threshold=0.5,
            sample_scope="development_oof",
            evaluation_design="permuted_target_control",
            numerical_method="same_library_regression",
            inference_basis="descriptive",
                validation_level="validated",
            )
        controls.append(
            {
                "control": "permuted_target",
                "model_id": model_id,
                "status": "computed",
                "sample_scope": "development_oof",
                "split_hash": manifest.content_hash,
                **control_receipt,
                "metrics": control_bundle["metrics"],
            }
        )
    ranking = sorted(model_ids_tuple, key=lambda model_id: (-selection_scores[model_id], model_ids_tuple.index(model_id)))
    selected_model = ranking[0]
    selected_adapter = candidate_adapters[selected_model]
    try:
        positive_index = list(selected_adapter._classes).index(positive)
    except ValueError as exc:
        raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in selected adapter class order") from exc
    holdout_probabilities = selected_adapter.predict_proba(frame.iloc[holdout])[:, positive_index]
    holdout_predictions = selected_adapter.predict_at_threshold(
        frame.iloc[holdout],
        threshold=models[selected_model]["threshold"]["threshold"],
        positive_class=positive,
    )
    guard = HoldoutSealGuardV1(
        holdout_labels=target.iloc[holdout].tolist(),
        holdout_probabilities=holdout_probabilities.tolist(),
        holdout_predictions=holdout_predictions.tolist(),
        positive_class=positive,
        metric_release_plan={"metrics": sorted(HoldoutSealGuardV1._ALLOWED_METRICS)},
    )
    released = guard.release(authorization="one-time")
    for model_id in model_ids_tuple:
        models[model_id]["holdout"] = (
            released
            if model_id == selected_model
            else {"status": "not_evaluated", "reason": "holdout is reserved for the development-selected model"}
        )
    majority_class, majority_count = Counter(development_labels).most_common(1)[0]
    majority_probability = sum(value == positive for value in development_labels) / len(development_labels)
    majority_predictions = [majority_class] * len(development_labels)
    majority_bundle = classification_metric_bundle(
        actual=development_labels,
        probabilities=[majority_probability] * len(development_labels),
        predictions=majority_predictions,
        positive_class=positive,
        threshold=0.5,
        sample_scope="development",
        evaluation_design="majority_baseline",
        numerical_method="known_answer",
        inference_basis="descriptive",
        validation_level="validated",
    )
    return {
        "status": "validated",
        "models": models,
        "comparison": {
            "same_split": True,
            "split_hash": manifest.content_hash,
            "ranking": ranking,
            "selection_status": "selected_from_development_oof",
            "selection_metric": "roc_auc",
            "selection_scope": "development_oof",
            "selected_model": selected_model,
            "selection_scores": selection_scores,
        },
        "split": manifest.to_dict(),
        "holdout": {
            "status": "released_once",
            "model_id": selected_model,
            "access_boundary": "sealed_until_authorized_release",
            "release_count": 1,
        },
        "baselines": {
            "majority": {
                "model_id": "majority",
                "development_only": True,
                "majority_class": majority_class,
                "row_count": len(development_labels),
                "sample_scope": "development",
                "support": majority_count,
                "metrics": majority_bundle["metrics"],
            }
        },
        "controls": controls,
    }


__all__ = ["BoundedSearchV1", "HoldoutSealGuardV1", "run_classification_protocol", "select_threshold_from_oof"]
