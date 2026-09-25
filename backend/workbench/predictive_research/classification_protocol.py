"""Nested development, calibration/threshold isolation and holdout protocol."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any, Mapping, Sequence

import numpy as np
import pandas as pd

from .classification_adapters import get_classification_adapter
from .classification_contracts import ClassificationTaskSpecV1, DecisionPolicyV1
from .classification_metrics import (
    classification_metric_bundle,
    compute_calibration_bins,
    fit_probability_calibrator,
    threshold_curve,
)
from .classification_search import BoundedSearchV1, run_bounded_search
from .contracts import ContractError
from .preprocessing import ClassificationFoldPreprocessingV1, ClassificationPreprocessingStepV1
from .split_kernel import (
    ClassificationSplitManifestV1,
    build_classification_split_manifest,
    validate_classification_development_fold_windows,
)
from ..contracts.prediction.holdout import (
    HoldoutAccessKindV1,
    HoldoutAccessRequestV1,
    HoldoutMetricBundleStoreV1,
    HoldoutSealStoreV1,
    HoldoutSealV1,
)


class HoldoutSealGuardV1:
    """In-memory test/runtime guard that never exposes sealed holdout arrays."""

    _ALLOWED_METRICS = frozenset({"accuracy", "balanced_accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc", "log_loss", "brier_score"})

    def __init__(
        self,
        *,
        holdout_labels: Sequence[Any],
        holdout_probabilities: Sequence[float],
        holdout_predictions: Sequence[Any],
        metric_release_plan: Mapping[str, Any],
        positive_class: Any | None = None,
        sample_weight: Sequence[float] | None = None,
    ):
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
        if sample_weight is not None:
            weights = np.asarray(sample_weight, dtype=float)
            if len(weights) != len(self._labels) or not np.isfinite(weights).all() or (weights < 0).any() or float(weights.sum()) <= 0:
                raise ContractError("CLASSIFICATION_WEIGHT_INVALID", "holdout weights must be finite, non-negative, positive and aligned")
            self._sample_weight = tuple(float(item) for item in weights)
        else:
            self._sample_weight = None
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
            sample_weight=self._sample_weight,
        )
        return {
            "metrics": {name: bundle["metrics"].get(name) for name in self._metrics},
            "status": "released_once",
            "access_ledger": list(self.access_ledger),
            "row_count": len(self._labels),
            "weight_sum": float(sum(self._sample_weight)) if self._sample_weight is not None else float(len(self._labels)),
        }


def select_threshold_from_oof(
    *,
    actual: Sequence[Any],
    probabilities: Sequence[float],
    method: str,
    scope: str,
    positive_class: Any = 1,
    sample_weight: Sequence[float] | None = None,
    minimum_precision: float | None = None,
) -> dict[str, Any]:
    if scope not in {"development_oof", "development_calibration_eval"}:
        raise ContractError("CLASSIFICATION_THRESHOLD_SCOPE_INVALID", "threshold selection only accepts development OOF-derived probabilities")
    if method not in {"max_f1", "max_recall_at_precision", "min_log_loss"}:
        raise ContractError("CLASSIFICATION_THRESHOLD_METHOD_INVALID", method)
    if minimum_precision is not None and (
        type(minimum_precision) not in {int, float}
        or not np.isfinite(float(minimum_precision))
        or not 0 <= float(minimum_precision) <= 1
    ):
        raise ContractError("CLASSIFICATION_PRECISION_CONSTRAINT_INVALID", "minimum_precision must be in [0, 1]")
    candidates = np.linspace(0.05, 0.95, 19)
    rows = threshold_curve(
        actual,
        probabilities,
        thresholds=candidates,
        positive_class=positive_class,
        sample_weight=sample_weight,
    )
    if method == "max_f1":
        selected = max(rows, key=lambda row: (row["f1"], -row["threshold"]))
    elif method == "min_log_loss":
        selected = min(rows, key=lambda row: (row["log_loss"], row["threshold"]))
    else:
        if minimum_precision is None:
            return {
                "status": "unavailable",
                "reason_code": "CLASSIFICATION_THRESHOLD_PRECISION_CONSTRAINT_REQUIRED",
                "method": method,
                "scope": scope,
                "curve": rows,
            }
        feasible = [row for row in rows if row["precision"] >= float(minimum_precision)]
        if not feasible:
            return {
                "status": "unavailable",
                "reason_code": "CLASSIFICATION_THRESHOLD_NO_FEASIBLE_CANDIDATE",
                "method": method,
                "scope": scope,
                "minimum_precision": float(minimum_precision),
                "curve": rows,
            }
        selected = max(feasible, key=lambda row: (row["recall"], -row["threshold"]))
    return {
        "threshold": selected["threshold"],
        "method": method,
        "scope": scope,
        "curve": rows,
        "status": "frozen_development_choice",
        **({"minimum_precision": float(minimum_precision)} if minimum_precision is not None else {}),
    }


def _policy_minimum_precision(policy: DecisionPolicyV1) -> float | None:
    if policy.threshold_method != "max_recall_at_precision":
        return None
    if not isinstance(policy.cost_matrix, Mapping):
        return None
    keys = ("minimum_precision", "min_precision", "precision_constraint")
    values = [policy.cost_matrix[key] for key in keys if key in policy.cost_matrix]
    if len(values) > 1 and any(value != values[0] for value in values[1:]):
        raise ContractError(
            "CLASSIFICATION_PRECISION_CONSTRAINT_INVALID",
            "precision constraint aliases must agree",
        )
    if not values:
        return None
    value = values[0]
    if type(value) not in {int, float} or not np.isfinite(float(value)) or not 0 <= float(value) <= 1:
        raise ContractError(
            "CLASSIFICATION_PRECISION_CONSTRAINT_INVALID",
            "minimum_precision must be a finite numeric value in [0, 1]",
        )
    return float(value)


def _production_select_oof_threshold(
    *,
    actual: Sequence[Any],
    probabilities: Sequence[float],
    decision_policy: DecisionPolicyV1,
    positive_class: Any,
    sample_weight: Sequence[float] | None,
) -> dict[str, Any]:
    """Select the one development-OOF threshold used by every production comparator."""

    return select_threshold_from_oof(
        actual=actual,
        probabilities=probabilities,
        method=decision_policy.threshold_method,
        scope="development_oof",
        positive_class=positive_class,
        sample_weight=sample_weight,
        minimum_precision=_policy_minimum_precision(decision_policy),
    )


_C0_DEVELOPMENT_HASH_KEYS = (
    "code",
    "config",
    "contract",
    "data",
    "split",
    "feature_recipe",
    "candidate_search",
    "calibration",
    "threshold",
    "decision_policy",
)
_C0_HOLDOUT_METRIC_REFS = tuple(
    sorted(
        {
            "accuracy",
            "balanced_accuracy",
            "precision",
            "recall",
            "f1",
            "roc_auc",
            "pr_auc",
            "log_loss",
            "brier_score",
        }
    )
)


def _raw_c0_digest(value: Any) -> str:
    digest = _production_hash(value)
    return digest.split(":", 1)[1]


def _build_c0_development_hashes(
    *,
    task: ClassificationTaskSpecV1,
    development_refs: Sequence[str],
    development_labels: Sequence[Any],
    split: Mapping[str, Any],
    model_ids: Sequence[str],
    seed: int,
    preprocessing_steps: Sequence[ClassificationPreprocessingStepV1],
    selection_scores: Mapping[str, float],
    calibration: Mapping[str, Any],
    threshold: Mapping[str, Any],
    decision_policy: Mapping[str, Any],
) -> dict[str, str]:
    values = {
        "code": {"entrypoint": "workbench.prediction.run_classification_model_v189", "protocol": "classification.production.v1"},
        "config": {"model_ids": list(model_ids), "seed": seed},
        "contract": task.to_dict(),
        "data": {"development_row_refs": list(development_refs), "development_labels": list(development_labels)},
        "split": split,
        "feature_recipe": [step.to_dict() for step in preprocessing_steps],
        "candidate_search": {"selection_scores": dict(selection_scores), "model_ids": list(model_ids)},
        "calibration": calibration,
        "threshold": threshold,
        "decision_policy": decision_policy,
    }
    return {key: _raw_c0_digest(values[key]) for key in _C0_DEVELOPMENT_HASH_KEYS}


def _release_holdout_with_c0_store(
    *,
    holdout_seal_store: HoldoutSealStoreV1 | None,
    holdout_principal_ref: str | None,
    holdout_access_id: str | None,
    task: ClassificationTaskSpecV1,
    development_refs: Sequence[str],
    development_labels: Sequence[Any],
    split: Mapping[str, Any],
    model_ids: Sequence[str],
    seed: int,
    preprocessing_steps: Sequence[ClassificationPreprocessingStepV1],
    selection_scores: Mapping[str, float],
    selected_model: str,
    model_identity: Mapping[str, Any],
    calibration: Mapping[str, Any],
    threshold: Mapping[str, Any],
    policy_payload: Mapping[str, Any],
    holdout_labels: Sequence[Any],
    holdout_probabilities: Sequence[float],
    holdout_predictions: Sequence[Any],
    positive_class: Any,
    sample_weight: Sequence[float] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if type(holdout_seal_store) is not HoldoutSealStoreV1:
        raise ContractError(
            "CLASSIFICATION_HOLDOUT_SERVER_STORE_REQUIRED",
            "production holdout release requires C0 HoldoutSealStoreV1",
        )
    if type(holdout_principal_ref) is not str or not holdout_principal_ref.strip():
        raise ContractError(
            "CLASSIFICATION_HOLDOUT_PRINCIPAL_REQUIRED",
            "production holdout release requires a typed principal_ref",
        )
    if type(holdout_access_id) is not str or not holdout_access_id.strip():
        raise ContractError(
            "CLASSIFICATION_HOLDOUT_ACCESS_ID_REQUIRED",
            "production holdout release requires a typed access_id",
        )
    release_plan_base = {
        "metrics": list(_C0_HOLDOUT_METRIC_REFS),
        "task_hash": task.content_hash,
        "split_hash": split["split_hash"],
        "model_id": selected_model,
        "model_hash": _production_hash(model_identity),
        "calibration_hash": _production_hash(calibration),
        "threshold_hash": _production_hash(threshold),
        "policy_hash": _production_hash(policy_payload),
    }
    release_plan_base["plan_hash"] = _production_hash(release_plan_base)
    metric_bundle_ref = f"classification.metric-bundle:{release_plan_base['plan_hash']}"
    metric_bundle_reference = holdout_seal_store.metric_bundle_store.issue(
        bundle_ref=metric_bundle_ref,
        metric_refs=_C0_HOLDOUT_METRIC_REFS,
        declaration={
            "metrics": [
                {"ref": metric_ref, "definition_ref": f"workbench.classification.metric.{metric_ref}.v1"}
                for metric_ref in _C0_HOLDOUT_METRIC_REFS
            ]
        },
    )
    development_hashes = _build_c0_development_hashes(
        task=task,
        development_refs=development_refs,
        development_labels=development_labels,
        split=split,
        model_ids=model_ids,
        seed=seed,
        preprocessing_steps=preprocessing_steps,
        selection_scores=selection_scores,
        calibration=calibration,
        threshold=threshold,
        decision_policy=policy_payload,
    )
    seal = HoldoutSealV1(
        seal_id=f"classification.holdout:{release_plan_base['plan_hash']}",
        principal_ref=holdout_principal_ref,
        development_hashes=development_hashes,
        metric_release_bundle_ref=metric_bundle_reference.bundle_ref,
        metric_bundle_digest=metric_bundle_reference.content_digest,
        metric_refs=metric_bundle_reference.metric_refs,
    )
    seal_reference = holdout_seal_store.issue(
        seal,
        metric_bundle_reference=metric_bundle_reference,
    )
    access_request = HoldoutAccessRequestV1(
        access_id=holdout_access_id,
        principal_ref=holdout_principal_ref,
        kind=HoldoutAccessKindV1.DECLARED_EVALUATION,
        metric_refs=metric_bundle_reference.metric_refs,
        metric_bundle_digest=metric_bundle_reference.content_digest,
    )
    decision = holdout_seal_store.consume(seal_reference, access_request)
    if not decision.allowed:
        raise ContractError(
            "CLASSIFICATION_HOLDOUT_RELEASE_BLOCKED",
            f"C0 holdout release denied: {decision.reason_code}",
        )
    if decision.reason_code != "HOLDOUT_RELEASE_ALLOWED" or decision.seal.status != "closed" or len(decision.seal.access_ledger) != 1:
        raise ContractError(
            "CLASSIFICATION_HOLDOUT_RELEASE_INVALID",
            "C0 holdout decision did not produce one closed ledger release",
        )
    release_plan = {
        **release_plan_base,
        "metric_bundle_ref": metric_bundle_reference.bundle_ref,
        "metric_bundle_digest": metric_bundle_reference.content_digest,
        "seal_id": decision.seal.seal_id,
        "seal_digest": decision.seal.seal_digest,
        "access_id": access_request.access_id,
        "access_request_digest": access_request.request_digest,
        "principal_ref": access_request.principal_ref,
    }
    release_plan["plan_hash"] = _production_hash(release_plan)
    bundle = classification_metric_bundle(
        actual=holdout_labels,
        probabilities=holdout_probabilities,
        predictions=holdout_predictions,
        positive_class=positive_class,
        threshold=threshold["threshold"],
        sample_scope="final_holdout",
        evaluation_design="sealed_holdout",
        numerical_method="same_library_regression",
        inference_basis="descriptive",
        validation_level="validated",
        sample_weight=sample_weight,
    )
    released = {
        "metrics": {name: bundle["metrics"].get(name) for name in _C0_HOLDOUT_METRIC_REFS},
        "status": "released_once",
        "release_count": 1,
        "access_ledger": [entry.to_dict() for entry in decision.seal.access_ledger],
        "row_count": len(holdout_labels),
        "weight_sum": float(sum(sample_weight)) if sample_weight is not None else float(len(holdout_labels)),
        "c0": {
            "decision": {
                "allowed": decision.allowed,
                "reason": decision.reason_code,
                "status": decision.seal.status,
                "ledger": [entry.to_dict() for entry in decision.seal.access_ledger],
            },
            "metric_bundle": metric_bundle_reference.to_dict(),
            "seal": decision.seal.to_dict(),
            "access_request": access_request.to_dict(),
        },
        "release_plan": release_plan,
        "release_plan_hash": release_plan["plan_hash"],
    }
    return released, release_plan


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


def _production_hash(value: Any) -> str:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ContractError("CLASSIFICATION_PROTOCOL_JSON_INVALID", "classification evidence is not JSON serializable") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _production_missing(value: Any) -> bool:
    try:
        result = pd.isna(value)
        return bool(result) if not isinstance(result, (list, tuple, np.ndarray)) else False
    except (TypeError, ValueError):
        return value is None


def _production_before(left: Any, right: Any) -> bool:
    try:
        return bool(left <= right)
    except (TypeError, ValueError) as exc:
        raise ContractError("CLASSIFICATION_TIME_ORDER_INVALID", "ordered metadata values must share a comparable type") from exc


def _production_latest(values: Sequence[Any]) -> Any:
    if not values:
        raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "availability values are required")
    latest = values[0]
    for value in values[1:]:
        if _production_before(latest, value):
            latest = value
    return latest


def _production_earliest(values: Sequence[Any]) -> Any:
    if not values:
        raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "availability values are required")
    earliest = values[0]
    for value in values[1:]:
        if _production_before(value, earliest):
            earliest = value
    return earliest


def _production_column_values(frame: pd.DataFrame, column: str, *, code: str, label: str) -> tuple[Any, ...]:
    if column not in frame.columns:
        raise ContractError(code, f"declared {label} column {column!r} is missing")
    values = tuple(frame[column].tolist())
    if any(_production_missing(value) for value in values):
        raise ContractError(code, f"declared {label} column contains missing values")
    return values


def _production_bind_metadata(
    frame: pd.DataFrame,
    task: ClassificationTaskSpecV1,
    *,
    feature_available_at: Sequence[Any] | None,
    prediction_origins: Sequence[Any] | None,
    entities: Sequence[str] | None,
    periods: Sequence[Any] | None,
) -> tuple[tuple[Any, ...] | None, tuple[Any, ...] | None, tuple[Any, ...] | None, tuple[Any, ...] | None]:
    """Bind declared row metadata to frame columns before split construction."""

    n = len(frame)
    structure = task.structure

    def aligned(values: Sequence[Any] | None, *, label: str) -> tuple[Any, ...] | None:
        if values is None:
            return None
        if isinstance(values, (str, bytes)) or len(values) != n:
            raise ContractError("CLASSIFICATION_SPLIT_ALIGNMENT_INVALID", f"{label} must align with frame rows")
        result = tuple(values)
        if any(_production_missing(value) for value in result):
            raise ContractError("CLASSIFICATION_SPLIT_ALIGNMENT_INVALID", f"{label} contains missing values")
        return result

    entity_values = aligned(entities, label="entities")
    period_values = aligned(periods, label="periods")
    supplied_available = aligned(feature_available_at, label="feature_available_at")
    supplied_origins = aligned(prediction_origins, label="prediction_origins")
    if structure.kind == "iid":
        if entity_values is not None or period_values is not None or feature_available_at is not None or prediction_origins is not None:
            raise ContractError("CLASSIFICATION_SPLIT_METADATA_UNEXPECTED", "iid tasks cannot consume entity, time, or availability arrays")
    elif structure.kind == "grouped":
        if not structure.group_column:
            raise ContractError("CLASSIFICATION_GROUP_COLUMN_MISSING", "grouped task requires a group column")
        column_values = _production_column_values(
            frame,
            structure.group_column,
            code="CLASSIFICATION_GROUP_COLUMN_MISSING",
            label="group",
        )
        if entity_values is not None and entity_values != column_values:
            raise ContractError("CLASSIFICATION_ENTITY_METADATA_MISMATCH", "entities do not match the declared group column")
        entity_values = column_values
        if any(not isinstance(value, str) or not value.strip() for value in entity_values):
            raise ContractError("CLASSIFICATION_ENTITY_IDENTITY_INVALID", "group values must be non-empty strings")
    elif structure.kind in {"temporal", "panel"}:
        if not structure.time_column:
            raise ContractError("CLASSIFICATION_TIME_COLUMN_MISSING", "ordered task requires a time column")
        column_periods = _production_column_values(
            frame,
            structure.time_column,
            code="CLASSIFICATION_TIME_COLUMN_MISSING",
            label="time",
        )
        if period_values is not None and period_values != column_periods:
            raise ContractError("CLASSIFICATION_TIME_METADATA_MISMATCH", "periods do not match the declared time column")
        period_values = column_periods
        if structure.kind == "panel":
            if not structure.entity_column:
                raise ContractError("CLASSIFICATION_ENTITY_COLUMN_MISSING", "panel task requires an entity column")
            column_entities = _production_column_values(
                frame,
                structure.entity_column,
                code="CLASSIFICATION_ENTITY_COLUMN_MISSING",
                label="entity",
            )
            if entity_values is not None and entity_values != column_entities:
                raise ContractError("CLASSIFICATION_ENTITY_METADATA_MISMATCH", "entities do not match the declared entity column")
            entity_values = column_entities
            if any(not isinstance(value, str) or not value.strip() for value in entity_values):
                raise ContractError("CLASSIFICATION_ENTITY_IDENTITY_INVALID", "panel entity values must be non-empty strings")

        if (supplied_available is None) != (supplied_origins is None):
            raise ContractError(
                "CLASSIFICATION_INFORMATION_SET_INCOMPLETE",
                "feature availability and prediction origins must be supplied together",
            )
        available_columns = tuple(item.available_at for item in task.feature_availability)
        origin_columns = tuple(item.prediction_origin for item in task.feature_availability)
        if not all(column in frame.columns for column in (*available_columns, *origin_columns)):
            missing = sorted({column for column in (*available_columns, *origin_columns) if column not in frame.columns})
            raise ContractError(
                "CLASSIFICATION_AVAILABILITY_COLUMN_MISSING",
                f"ordered tasks require row-level availability columns: {missing}",
            )
        frame_available_rows: list[Any] = []
        frame_origin_rows: list[Any] = []
        for index in range(n):
            row_available = [frame.iloc[index][column] for column in available_columns]
            row_origins = [frame.iloc[index][column] for column in origin_columns]
            if any(_production_missing(value) for value in (*row_available, *row_origins)):
                raise ContractError("CLASSIFICATION_INFORMATION_SET_VIOLATION", "availability metadata contains missing values")
            origin = _production_earliest(row_origins)
            frame_available_rows.append(_production_latest(row_available))
            frame_origin_rows.append(origin)
        frame_available = tuple(frame_available_rows)
        frame_origins = tuple(frame_origin_rows)
        if supplied_available is not None and supplied_available != frame_available:
            raise ContractError(
                "CLASSIFICATION_INFORMATION_SET_METADATA_MISMATCH",
                "feature_available_at does not match the task-declared frame columns",
            )
        if supplied_origins is not None and supplied_origins != frame_origins:
            raise ContractError(
                "CLASSIFICATION_INFORMATION_SET_METADATA_MISMATCH",
                "prediction_origins does not match the task-declared frame columns",
            )
        for index, (available, origin) in enumerate(zip(frame_available, frame_origins, strict=True)):
            if not _production_before(available, origin):
                raise ContractError(
                    "CLASSIFICATION_INFORMATION_SET_VIOLATION",
                    f"feature availability is unsafe for row {index}",
                )
        # Downstream split construction receives only the server-derived
        # values. Caller arrays are checked claims, never the authority.
        supplied_available = frame_available
        supplied_origins = frame_origins
    else:
        raise ContractError("CLASSIFICATION_DATA_STRUCTURE_INVALID", f"unsupported classification structure {structure.kind!r}")

    return entity_values, period_values, supplied_available, supplied_origins


def _production_numeric_frame(frame: pd.DataFrame) -> None:
    unsupported = [str(column) for column in frame.columns if not pd.api.types.is_numeric_dtype(frame[column])]
    if unsupported:
        raise ContractError("CLASSIFICATION_FEATURE_TYPE_BLOCKED", f"non-numeric feature columns require an explicit recipe: {unsupported}")
    try:
        values = frame.to_numpy(dtype=float, copy=True)
    except (TypeError, ValueError) as exc:
        raise ContractError("CLASSIFICATION_FEATURE_TYPE_BLOCKED", "features must be numeric") from exc
    if not np.isfinite(values).all():
        raise ContractError("CLASSIFICATION_FEATURE_TYPE_BLOCKED", "features contain missing or non-finite values without a recipe")


def _production_weights(frame: pd.DataFrame, task: ClassificationTaskSpecV1) -> np.ndarray | None:
    if task.weights is None:
        return None
    if task.weights not in frame.columns:
        raise ContractError("CLASSIFICATION_WEIGHT_COLUMN_MISSING", task.weights)
    if not pd.api.types.is_numeric_dtype(frame[task.weights]):
        raise ContractError("CLASSIFICATION_WEIGHT_INVALID", "declared weight column must be numeric")
    weights = frame[task.weights].to_numpy(dtype=float, copy=True)
    if not np.isfinite(weights).all() or (weights < 0).any() or float(weights.sum()) <= 0:
        raise ContractError("CLASSIFICATION_WEIGHT_INVALID", "declared weights must be finite, non-negative and positive")
    return weights


def _production_fit_transform(
    features: pd.DataFrame,
    fit_refs: tuple[str, ...],
    *,
    steps: tuple[ClassificationPreprocessingStepV1, ...],
    split_hash: str,
    weight_name: str | None,
    weights_by_ref: Mapping[str, float],
) -> tuple[Any, dict[str, Any]]:
    if not steps:
        _production_numeric_frame(features.loc[list(fit_refs)])
        receipt = {
            "schema_version": 1,
            "fit_scope": "identity_no_fit",
            "fit_row_refs": list(fit_refs),
            "recipe_hash": _production_hash([]),
            "split_hash": split_hash,
            "weight_name": weight_name,
            "weighted_fit": weight_name is not None,
        }

        class _IdentityTransform:
            def transform(self, values: pd.DataFrame, *, row_refs: tuple[str, ...]) -> pd.DataFrame:
                if tuple(values.index.astype(str)) != tuple(row_refs):
                    values = values.copy()
                    values.index = row_refs
                _production_numeric_frame(values)
                return values

        return _IdentityTransform(), receipt

    feature_columns = tuple(features.columns)
    if any(column not in feature_columns for step in steps for column in step.columns):
        raise ContractError("CLASSIFICATION_PREPROCESSING_COLUMN_MISSING", "preprocessing columns must be declared task features")
    fit_rows = features.loc[list(fit_refs)].to_dict(orient="index")
    sample_weight = None if weight_name is None else [weights_by_ref[ref] for ref in fit_refs]
    fitted = ClassificationFoldPreprocessingV1(steps=steps).fit(
        features.loc[list(fit_refs)],
        fit_row_refs=fit_refs,
        fit_rows=fit_rows,
        weight_name=weight_name,
        sample_weight=sample_weight,
    )
    receipt = {
        "schema_version": 1,
        **fitted.receipt,
        "split_hash": split_hash,
        "recipe_hash": _production_hash(fitted.receipt),
    }
    fitted = fitted.__class__(
        steps=fitted.steps,
        fit_row_refs=fitted.fit_row_refs,
        state=fitted.state,
        receipt=receipt,
    )
    return fitted, receipt


def _production_metric_score(bundle: Mapping[str, Any], metric_name: str) -> float:
    metric = bundle.get("metrics", {}).get(metric_name)
    if not isinstance(metric, Mapping) or metric.get("status") != "computed" or metric.get("point_estimate") is None:
        raise ContractError("CLASSIFICATION_SELECTION_INSUFFICIENT_EVIDENCE", f"primary metric {metric_name!r} is undefined")
    return float(metric["point_estimate"])


def _production_oof_metric_bundle(
    *,
    actual: Sequence[Any],
    probabilities: Sequence[float],
    threshold_record: Mapping[str, Any],
    positive_class: Any,
    negative_class: Any,
    sample_weight: Sequence[float] | None,
) -> dict[str, Any]:
    """Score one candidate on its declared development OOF decision rule.

    Probability metrics remain probability-based inside ``classification_metric_bundle``;
    only thresholded metrics consume the selected development threshold.
    """

    threshold = (
        float(threshold_record["threshold"])
        if threshold_record.get("status") == "frozen_development_choice"
        else 0.5
    )
    predictions = [
        positive_class if probability >= threshold else negative_class
        for probability in probabilities
    ]
    return classification_metric_bundle(
        actual=actual,
        probabilities=probabilities,
        predictions=predictions,
        positive_class=positive_class,
        threshold=threshold,
        sample_scope="development_oof",
        evaluation_design="cross_fitted_oof",
        numerical_method="same_library_regression",
        inference_basis="descriptive",
        validation_level="validated",
        sample_weight=sample_weight,
    )


def _production_training_refs(manifest: ClassificationSplitManifestV1, fold: int) -> tuple[str, ...]:
    explicit = manifest.training_rows_for_fold(fold)
    validation = {
        item.row_ref
        for item in manifest.assignments
        if item.partition == "development" and item.cv_fold == fold
    }
    if not explicit or set(explicit) & validation:
        raise ContractError("CLASSIFICATION_SPLIT_TRAINING_ROLE_INVALID", f"fold {fold} has an invalid training role")
    return explicit


def _classification_class_support(
    values: Sequence[Any],
    *,
    task: ClassificationTaskSpecV1,
) -> dict[str, Any]:
    labels = tuple(dict.fromkeys(str(label) for label in task.class_mapping.values()))
    counts = {label: 0 for label in labels}
    for value in values:
        label = task.class_mapping.get(value)
        if label is None:
            raise ContractError("CLASSIFICATION_CLASS_MAPPING_MISMATCH", "fold receipt contains an unmapped class")
        counts[str(label)] += 1
    return counts


def _validate_class_support_receipt(
    receipt: Mapping[str, Any],
    *,
    task: ClassificationTaskSpecV1,
    target: pd.Series,
    training_refs: tuple[str, ...],
    validation_refs: tuple[str, ...],
    fold: int,
) -> None:
    support = receipt.get("class_support")
    if not isinstance(support, Mapping) or set(support) != {"class_labels", "training", "validation"}:
        raise ContractError("CLASSIFICATION_FOLD_SUPPORT_RECEIPT_INVALID", f"fold {fold} lacks typed class-support evidence")
    expected_labels = list(dict.fromkeys(str(label) for label in task.class_mapping.values()))
    if support.get("class_labels") != expected_labels:
        raise ContractError("CLASSIFICATION_FOLD_SUPPORT_RECEIPT_INVALID", f"fold {fold} class labels are not bound to the task")
    expected = {
        "training": _classification_class_support(target.loc[list(training_refs)].tolist(), task=task),
        "validation": _classification_class_support(target.loc[list(validation_refs)].tolist(), task=task),
    }
    if support.get("training") != expected["training"] or support.get("validation") != expected["validation"]:
        raise ContractError("CLASSIFICATION_FOLD_SUPPORT_RECEIPT_INVALID", f"fold {fold} class-support counts do not match persisted row refs")
    if any(count < 1 for counts in expected.values() for count in counts.values()):
        raise ContractError("CLASSIFICATION_SPLIT_VALIDATION_CLASS_SUPPORT", f"fold {fold} lacks support for every class")


def _production_binary_labels(values: Sequence[Any], *, positive: Any) -> list[int]:
    return [1 if value == positive else 0 for value in values]


def _production_calibration_partition(
    refs: tuple[str, ...],
    labels: Sequence[Any],
    *,
    positive: Any,
    seed: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Find deterministic disjoint OOF fit/evaluation sets with class support."""

    if len(refs) < 4 or len(labels) != len(refs):
        raise ContractError("CLASSIFICATION_CALIBRATION_SUPPORT", "calibration needs at least four development OOF rows")
    order = list(range(len(refs)))
    rng = np.random.default_rng(seed)
    rng.shuffle(order)
    midpoint = len(order) // 2
    for offset in range(len(order)):
        candidate = order[offset:] + order[:offset]
        midpoint = max(2, min(len(candidate) - 2, len(candidate) // 2))
        fit_positions = candidate[:midpoint]
        eval_positions = candidate[midpoint:]
        fit_labels = {labels[index] == positive for index in fit_positions}
        eval_labels = {labels[index] == positive for index in eval_positions}
        if fit_labels == {False, True} and eval_labels == {False, True}:
            return (
                tuple(refs[index] for index in fit_positions),
                tuple(refs[index] for index in eval_positions),
            )
    raise ContractError("CLASSIFICATION_CALIBRATION_SUPPORT", "disjoint calibration fit and evaluation slices lack both classes")


def _production_oof_trial(
    feature_frame: pd.DataFrame,
    target: pd.Series,
    manifest: ClassificationSplitManifestV1,
    *,
    task: ClassificationTaskSpecV1,
    folds: Sequence[int],
    model_id: str,
    parameters: Mapping[str, Any],
    seed: int,
    steps: Sequence[ClassificationPreprocessingStepV1],
    split_hash: str,
    weight_by_ref: Mapping[str, float],
    positive: Any,
    decision_policy: DecisionPolicyV1,
) -> dict[str, Any]:
    """Evaluate one parameter set on the immutable development split only."""

    oof_by_ref: dict[str, float] = {}
    fold_receipts: list[dict[str, Any]] = []
    for fold in folds:
        validation_refs = tuple(
            item.row_ref
            for item in manifest.assignments
            if item.partition == "development" and item.cv_fold == fold
        )
        training_refs = _production_training_refs(manifest, fold)
        if len(set(target.loc[list(training_refs)].tolist())) < 2:
            raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", f"fold {fold} lacks training class support")
        if len(set(target.loc[list(validation_refs)].tolist())) < 2:
            raise ContractError(
                "CLASSIFICATION_SPLIT_VALIDATION_CLASS_SUPPORT",
                f"fold {fold} lacks validation support for both classes",
            )
        fitted, receipt = _production_fit_transform(
            feature_frame,
            training_refs,
            steps=steps,
            split_hash=split_hash,
            weight_name=task.weights,
            weights_by_ref=weight_by_ref,
        )
        receipt = {
            **receipt,
            "class_support": {
                "class_labels": list(dict.fromkeys(str(label) for label in task.class_mapping.values())),
                "training": _classification_class_support(target.loc[list(training_refs)].tolist(), task=task),
                "validation": _classification_class_support(target.loc[list(validation_refs)].tolist(), task=task),
            },
        }
        _validate_class_support_receipt(
            receipt,
            task=task,
            target=target,
            training_refs=training_refs,
            validation_refs=validation_refs,
            fold=fold,
        )
        train_features = fitted.transform(feature_frame.loc[list(training_refs)], row_refs=training_refs)
        validation_features = fitted.transform(feature_frame.loc[list(validation_refs)], row_refs=validation_refs)
        adapter = get_classification_adapter(model_id, seed=seed, parameters=dict(parameters))
        if task.weights is not None and not adapter.supports_weight:
            raise ContractError(
                "CLASSIFICATION_WEIGHT_UNSUPPORTED",
                f"model {model_id!r} does not consume declared weights",
            )
        train_weight = None if not weight_by_ref else [weight_by_ref[ref] for ref in training_refs]
        adapter.fit(train_features, target.loc[list(training_refs)], sample_weight=train_weight)
        probabilities = adapter.predict_proba(validation_features)
        try:
            positive_index = list(adapter._classes).index(positive)
        except ValueError as exc:
            raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in adapter class order") from exc
        for ref, probability in zip(validation_refs, probabilities[:, positive_index], strict=True):
            oof_by_ref[ref] = float(probability)
        fold_receipts.append(
            {
                "fold": fold,
                "training_row_refs": list(training_refs),
                "validation_row_refs": list(validation_refs),
                "receipt": receipt,
            }
        )
    oof_refs = tuple(
        item.row_ref
        for item in manifest.assignments
        if item.partition == "development" and item.cv_fold is not None
    )
    if set(oof_refs) != set(oof_by_ref):
        raise ContractError("CLASSIFICATION_OOF_INCOMPLETE", "every development validation row needs one OOF probability")
    oof_actual = [target.loc[ref] for ref in oof_refs]
    oof_probabilities = [oof_by_ref[ref] for ref in oof_refs]
    oof_weight = None if not weight_by_ref else [weight_by_ref[ref] for ref in oof_refs]
    negative = next(value for value in set(oof_actual) if value != positive)
    selection_threshold = _production_select_oof_threshold(
        actual=oof_actual,
        probabilities=oof_probabilities,
        decision_policy=decision_policy,
        positive_class=positive,
        sample_weight=oof_weight,
    )
    oof_bundle = _production_oof_metric_bundle(
        actual=oof_actual,
        probabilities=oof_probabilities,
        threshold_record=selection_threshold,
        positive_class=positive,
        negative_class=negative,
        sample_weight=oof_weight,
    )
    return {
        "sample_scope": "development_oof",
        "evaluation_design": "cross_fitted_oof",
        "split_hash": split_hash,
        "oof_metrics": oof_bundle,
        "fold_receipts": fold_receipts,
        "oof_row_refs": list(oof_refs),
    }


def _run_production_classification_protocol(
    frame: pd.DataFrame,
    *,
    task: ClassificationTaskSpecV1,
    model_ids: Sequence[str],
    row_refs: Sequence[str] | None,
    decision_policy: DecisionPolicyV1 | None,
    final_holdout_fraction: float,
    cv_folds: int,
    seed: int,
    feature_available_at: Sequence[Any] | None = None,
    prediction_origins: Sequence[Any] | None = None,
    label_windows: Sequence[tuple[Any, Any]] | None = None,
    entities: Sequence[str] | None = None,
    periods: Sequence[Any] | None = None,
    purge_gap: Any | None = None,
    embargo: Any | None = None,
    embargo_basis: str | None = None,
    preprocessing_steps: Sequence[ClassificationPreprocessingStepV1] | None = None,
    calibration_method: str = "platt",
    model_parameters: Mapping[str, Mapping[str, Any]] | None = None,
    bounded_search: BoundedSearchV1 | None = None,
    holdout_seal_store: HoldoutSealStoreV1 | None = None,
    holdout_principal_ref: str | None = None,
    holdout_access_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise ContractError("CLASSIFICATION_DATASET_INVALID", "classification input must be a non-empty DataFrame")
    task.validate()
    if task.task_type != "binary":
        raise ContractError("CLASSIFICATION_TASK_TYPE_UNSUPPORTED", "production protocol currently supports binary tasks only")
    if not isinstance(seed, int) or isinstance(seed, bool) or seed < 0:
        raise ContractError("CLASSIFICATION_SEED_INVALID", "seed must be a non-negative integer")
    refs = tuple(row_refs) if row_refs is not None else tuple(str(value) for value in frame.index)
    if len(refs) != len(frame) or len(set(refs)) != len(refs) or any(not isinstance(ref, str) or not ref for ref in refs):
        raise ContractError("CLASSIFICATION_ROW_IDENTITY_INVALID", "row_refs must be unique non-empty strings aligned to frame")
    required_columns = (task.target_column, *task.feature_columns)
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise ContractError("CLASSIFICATION_COLUMN_REF_MISSING", f"server-bound columns are missing: {missing}")
    if frame.columns.duplicated().any():
        raise ContractError("CLASSIFICATION_DATASET_SCHEMA_INVALID", "classification columns must be unique")
    work = frame.copy()
    work.index = refs
    target = work.loc[:, task.target_column]
    if target.isna().any():
        raise ContractError("CLASSIFICATION_TARGET_MISSING", "classification target contains missing values")
    raw_labels = tuple(task.class_mapping.keys())
    if any(value not in raw_labels for value in target.tolist()):
        raise ContractError("CLASSIFICATION_CLASS_MAPPING_MISMATCH", "target contains a class absent from class_mapping")
    positive_matches = [raw for raw, label in task.class_mapping.items() if label == task.positive_class]
    if len(positive_matches) != 1:
        raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class must map to one raw label")
    positive = positive_matches[0]
    observed_classes = set(target.tolist())
    if len(observed_classes) != 2 or positive not in observed_classes:
        raise ContractError("CLASSIFICATION_CLASS_SUPPORT", "binary production tasks need both classes in the observed target")
    negative = next(value for value in observed_classes if value != positive)
    model_ids_tuple = tuple(model_ids)
    if not model_ids_tuple or len(set(model_ids_tuple)) != len(model_ids_tuple):
        raise ContractError("CLASSIFICATION_MODEL_SET_INVALID", "model_ids must be non-empty and unique")
    if calibration_method not in {"none", "platt", "isotonic"}:
        raise ContractError("CLASSIFICATION_CALIBRATION_METHOD_INVALID", calibration_method)
    if decision_policy is None:
        decision_policy = DecisionPolicyV1(
            cost_matrix=None,
            capacity=None,
            abstain_allowed=True,
            manual_review_allowed=True,
            threshold_scope="development_oof",
            threshold_method="max_f1",
            policy_version="1.0",
            population="all",
            time_validity="not_declared",
        )
    if not isinstance(decision_policy, DecisionPolicyV1):
        raise ContractError("CLASSIFICATION_POLICY_INVALID", "decision_policy must be DecisionPolicyV1")
    decision_policy.validate()
    if decision_policy.selection_status == "SCENARIOS_ONLY":
        blocked_reasons = ["CLASSIFICATION_POLICY_SCENARIO_ONLY"]
    else:
        blocked_reasons = []
    if task.availability_status != "VALIDATED":
        blocked_reasons.append("CLASSIFICATION_AVAILABILITY_UNVALIDATED")
    if decision_policy.threshold_scope != "development_oof":
        raise ContractError("CLASSIFICATION_THRESHOLD_SCOPE_INVALID", "threshold policy must use development_oof")
    if decision_policy.threshold_method not in {"max_f1", "max_recall_at_precision", "min_log_loss"}:
        raise ContractError("CLASSIFICATION_THRESHOLD_METHOD_INVALID", decision_policy.threshold_method)
    minimum_precision = _policy_minimum_precision(decision_policy)
    steps = tuple(preprocessing_steps or ())
    if any(not isinstance(step, ClassificationPreprocessingStepV1) for step in steps):
        raise ContractError("CLASSIFICATION_PREPROCESSING_CONTRACT_INVALID", "preprocessing steps must be typed")
    entity_values, period_values, availability_values, origin_values = _production_bind_metadata(
        work,
        task,
        feature_available_at=feature_available_at,
        prediction_origins=prediction_origins,
        entities=entities,
        periods=periods,
    )
    effective_purge_gap = purge_gap
    if task.label_definition.purge_gap is not None and label_windows is None:
        raise ContractError("CLASSIFICATION_LABEL_WINDOW_REQUIRED", "declared purge gap requires row-level label windows")
    if task.label_definition.purge_gap is not None and effective_purge_gap is None:
        raise ContractError("CLASSIFICATION_PURGE_GAP_VALUE_REQUIRED", "purge gap value must be supplied for executable windows")
    weights = _production_weights(work, task)
    weight_by_ref = {} if weights is None else {ref: float(weights[index]) for index, ref in enumerate(refs)}
    manifest = build_classification_split_manifest(
        row_refs=refs,
        labels=target.tolist(),
        profile=task.split_profile,
        final_holdout_fraction=final_holdout_fraction,
        cv_folds=cv_folds,
        random_seed=seed,
        feature_available_at=availability_values,
        prediction_origins=origin_values,
        label_windows=label_windows,
        entities=None if entity_values is None else tuple(str(value) for value in entity_values),
        periods=period_values,
        purge_gap=effective_purge_gap,
        embargo=embargo,
        embargo_basis=embargo_basis,
    )
    validate_classification_development_fold_windows(
        manifest,
        label_windows=label_windows,
        purge_gap=effective_purge_gap,
    )
    split_hash = manifest.content_hash
    feature_frame = work.loc[:, list(task.feature_columns)]
    development_refs = tuple(item.row_ref for item in manifest.assignments if item.partition == "development")
    holdout_refs = tuple(item.row_ref for item in manifest.assignments if item.partition == "final_holdout")
    folds = tuple(sorted({item.cv_fold for item in manifest.assignments if item.partition == "development" and item.cv_fold is not None}))
    if not development_refs or not holdout_refs or not folds:
        raise ContractError("CLASSIFICATION_SPLIT_SUPPORT", "production split needs development rows, holdout rows and folds")
    search_receipt: dict[str, Any] | None = None
    effective_model_parameters = {
        model_id: dict(parameters)
        for model_id, parameters in (model_parameters or {}).items()
    }
    if bounded_search is not None:
        if not isinstance(bounded_search, BoundedSearchV1):
            raise ContractError("CLASSIFICATION_SEARCH_INVALID", "bounded_search must be BoundedSearchV1")
        if tuple(bounded_search.candidates) != model_ids_tuple:
            raise ContractError(
                "CLASSIFICATION_SEARCH_MODEL_SET_MISMATCH",
                "bounded search candidates must match the protocol model_ids in order",
            )
        search_receipt = run_bounded_search(
            bounded_search,
            evaluate_trial=lambda model_id, parameters, trial_seed: _production_oof_trial(
                feature_frame,
                target,
                manifest,
                task=task,
                folds=folds,
                model_id=model_id,
                parameters=parameters,
                seed=trial_seed,
                steps=steps,
                split_hash=split_hash,
                weight_by_ref=weight_by_ref,
                positive=positive,
                decision_policy=decision_policy,
            ),
        )
        if search_receipt.get("status") != "selected":
            return {
                "status": "blocked",
                "blocked_reasons": [search_receipt.get("reason_code", "CLASSIFICATION_SEARCH_BLOCKED")],
                "models": {},
                "comparison": {
                    "same_split": True,
                    "split_hash": split_hash,
                    "ranking": [],
                    "selection_status": "bounded_search_blocked",
                    "selection_metric": task.primary_metric,
                    "selection_scope": "development_oof",
                    "selected_model": None,
                    "selection_scores": {},
                },
                "split": manifest.to_dict(),
                "holdout": {
                    "status": "sealed",
                    "access_boundary": "sealed_until_authorized_release",
                    "release_count": 0,
                },
                "baselines": [],
                "controls": [],
                "calibration": {"status": "unavailable", "reason_code": "CLASSIFICATION_SEARCH_BLOCKED"},
                "decision_policy": decision_policy.to_dict(),
                "search": search_receipt,
            }
        for model_id, parameters in search_receipt.get("best_parameters_by_model", {}).items():
            effective_model_parameters[model_id] = dict(parameters)
    models: dict[str, Any] = {}
    selection_scores: dict[str, float] = {}
    candidate_adapters: dict[str, Any] = {}
    candidate_transforms: dict[str, Any] = {}
    candidate_calibrators: dict[str, Any] = {}
    candidate_thresholds: dict[str, dict[str, Any]] = {}
    for position, model_id in enumerate(model_ids_tuple):
        oof_by_ref: dict[str, float] = {}
        fold_receipts: list[dict[str, Any]] = []
        for fold in folds:
            validation_refs = tuple(
                item.row_ref
                for item in manifest.assignments
                if item.partition == "development" and item.cv_fold == fold
            )
            training_refs = _production_training_refs(manifest, fold)
            if len(set(target.loc[list(training_refs)].tolist())) < 2:
                raise ContractError("CLASSIFICATION_SPLIT_CLASS_SUPPORT", f"fold {fold} lacks training class support")
            if len(set(target.loc[list(validation_refs)].tolist())) < 2:
                raise ContractError(
                    "CLASSIFICATION_SPLIT_VALIDATION_CLASS_SUPPORT",
                    f"fold {fold} lacks validation support for both classes",
                )
            fitted, receipt = _production_fit_transform(
                feature_frame,
                training_refs,
                steps=steps,
                split_hash=split_hash,
                weight_name=task.weights,
                weights_by_ref=weight_by_ref,
            )
            receipt = {
                **receipt,
                "class_support": {
                    "class_labels": list(dict.fromkeys(str(label) for label in task.class_mapping.values())),
                    "training": _classification_class_support(target.loc[list(training_refs)].tolist(), task=task),
                    "validation": _classification_class_support(target.loc[list(validation_refs)].tolist(), task=task),
                },
            }
            _validate_class_support_receipt(
                receipt,
                task=task,
                target=target,
                training_refs=training_refs,
                validation_refs=validation_refs,
                fold=fold,
            )
            train_features = fitted.transform(feature_frame.loc[list(training_refs)], row_refs=training_refs)
            validation_features = fitted.transform(feature_frame.loc[list(validation_refs)], row_refs=validation_refs)
            adapter = get_classification_adapter(
                model_id,
                seed=seed + position,
                parameters=dict(effective_model_parameters.get(model_id, {})),
            )
            if task.weights is not None and not adapter.supports_weight:
                raise ContractError(
                    "CLASSIFICATION_WEIGHT_UNSUPPORTED",
                    f"model {model_id!r} does not consume declared weights",
                )
            train_weight = None if weights is None else [weight_by_ref[ref] for ref in training_refs]
            adapter.fit(train_features, target.loc[list(training_refs)], sample_weight=train_weight)
            probabilities = adapter.predict_proba(validation_features)
            try:
                positive_index = list(adapter._classes).index(positive)
            except ValueError as exc:
                raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in adapter class order") from exc
            for ref, probability in zip(validation_refs, probabilities[:, positive_index], strict=True):
                oof_by_ref[ref] = float(probability)
            fold_receipts.append(
                {
                    "fold": fold,
                    "training_row_refs": list(training_refs),
                    "validation_row_refs": list(validation_refs),
                    "receipt": receipt,
                }
            )
        oof_refs = tuple(
            item.row_ref
            for item in manifest.assignments
            if item.partition == "development" and item.cv_fold is not None
        )
        if set(oof_refs) != set(oof_by_ref):
            raise ContractError("CLASSIFICATION_OOF_INCOMPLETE", "every development validation row needs one OOF probability")
        oof_actual = [target.loc[ref] for ref in oof_refs]
        oof_probabilities = [oof_by_ref[ref] for ref in oof_refs]
        oof_weight = None if weights is None else [weight_by_ref[ref] for ref in oof_refs]
        selection_threshold = _production_select_oof_threshold(
            actual=oof_actual,
            probabilities=oof_probabilities,
            decision_policy=decision_policy,
            positive_class=positive,
            sample_weight=oof_weight,
        )
        selection_threshold = {
            **selection_threshold,
            "row_refs": list(oof_refs),
            "input_scope": "development_oof",
            "probability_scale": "raw_model_probability",
        }
        if selection_threshold.get("status") != "frozen_development_choice":
            blocked_reasons.append(str(selection_threshold.get("reason_code", "CLASSIFICATION_THRESHOLD_UNAVAILABLE")))
        oof_bundle = _production_oof_metric_bundle(
            actual=oof_actual,
            probabilities=oof_probabilities,
            threshold_record=selection_threshold,
            positive_class=positive,
            negative_class=negative,
            sample_weight=oof_weight,
        )
        try:
            score = _production_metric_score(oof_bundle, task.primary_metric)
        except ContractError:
            if task.primary_metric not in {"accuracy", "balanced_accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc", "log_loss", "brier_score"}:
                raise ContractError("CLASSIFICATION_SELECTION_METRIC_UNSUPPORTED", task.primary_metric)
            raise
        higher_is_better = task.primary_metric in {"accuracy", "balanced_accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc"}
        selection_scores[model_id] = score if higher_is_better else -score

        calibration_fit_refs, calibration_eval_refs = _production_calibration_partition(
            oof_refs,
            oof_actual,
            positive=positive,
            seed=seed + position,
        )
        probability_by_ref = dict(zip(oof_refs, oof_probabilities, strict=True))
        actual_by_ref = dict(zip(oof_refs, oof_actual, strict=True))
        fit_probabilities = [probability_by_ref[ref] for ref in calibration_fit_refs]
        fit_actual = _production_binary_labels([actual_by_ref[ref] for ref in calibration_fit_refs], positive=positive)
        fit_weight = None if weights is None else [weight_by_ref[ref] for ref in calibration_fit_refs]
        calibrator = fit_probability_calibrator(
            method=calibration_method,
            probabilities=fit_probabilities,
            actual_binary=fit_actual,
            fit_row_refs=calibration_fit_refs,
            sample_weight=fit_weight,
        )
        calibration_eval_probabilities = calibrator.transform(
            [probability_by_ref[ref] for ref in calibration_eval_refs]
        )
        calibration_eval_actual = [actual_by_ref[ref] for ref in calibration_eval_refs]
        calibration_eval_weight = None if weights is None else [weight_by_ref[ref] for ref in calibration_eval_refs]
        threshold = select_threshold_from_oof(
            actual=calibration_eval_actual,
            probabilities=calibration_eval_probabilities.tolist(),
            method=decision_policy.threshold_method,
            scope="development_calibration_eval",
            positive_class=positive,
            sample_weight=calibration_eval_weight,
            minimum_precision=minimum_precision,
        )
        if threshold.get("status") != "frozen_development_choice":
            blocked_reasons.append(str(threshold.get("reason_code", "CLASSIFICATION_THRESHOLD_UNAVAILABLE")))
        if decision_policy.selected_threshold is not None and threshold.get("status") == "frozen_development_choice" and minimum_precision is not None:
            requested = threshold_curve(
                calibration_eval_actual,
                calibration_eval_probabilities.tolist(),
                thresholds=[float(decision_policy.selected_threshold)],
                positive_class=positive,
                sample_weight=calibration_eval_weight,
            )[0]
            if requested["precision"] < minimum_precision:
                blocked_reasons.append("CLASSIFICATION_THRESHOLD_POLICY_CONSTRAINT_UNSATISFIED")
        threshold["row_refs"] = list(calibration_eval_refs)
        threshold["input_scope"] = "development_calibration_eval"
        threshold["probability_scale"] = (
            "calibrated_probability" if calibration_method != "none" else "raw_model_probability"
        )
        calibration = compute_calibration_bins(
            _production_binary_labels(calibration_eval_actual, positive=positive),
            calibration_eval_probabilities.tolist(),
            sample_scope="development_calibration_eval",
            sample_weight=calibration_eval_weight,
        )
        calibration.update(
            {
                "status": "computed" if calibration_method != "none" else "not_applied",
                "method": calibration_method,
                "fit_scope": "development_oof_calibration_fit" if calibration_method != "none" else "not_applied",
                "fit_row_refs": list(calibration_fit_refs),
                "evaluation_row_refs": list(calibration_eval_refs),
                "split_hash": split_hash,
                "model_id": model_id,
                "calibrator_hash": _production_hash(calibrator.to_dict()),
            }
        )
        if calibration_method == "none":
            blocked_reasons.append("CLASSIFICATION_CALIBRATION_NOT_APPLIED")
        final_transform, final_receipt = _production_fit_transform(
            feature_frame,
            development_refs,
            steps=steps,
            split_hash=split_hash,
            weight_name=task.weights,
            weights_by_ref=weight_by_ref,
        )
        final_features = final_transform.transform(feature_frame.loc[list(development_refs)], row_refs=development_refs)
        final_adapter = get_classification_adapter(
            model_id,
            seed=seed + position,
            parameters=dict(effective_model_parameters.get(model_id, {})),
        )
        final_weight = None if weights is None else [weight_by_ref[ref] for ref in development_refs]
        final_adapter.fit(final_features, target.loc[list(development_refs)], sample_weight=final_weight)
        candidate_adapters[model_id] = final_adapter
        candidate_transforms[model_id] = final_transform
        candidate_calibrators[model_id] = calibrator
        candidate_thresholds[model_id] = threshold
        reported_threshold = threshold
        reported_selection_threshold = selection_threshold
        if decision_policy.selection_status == "SCENARIOS_ONLY":
            reported_threshold = {
                "status": "unavailable",
                "reason_code": "CLASSIFICATION_POLICY_SCENARIO_ONLY",
                "method": decision_policy.threshold_method,
                "scope": "development_oof",
                "curve": [],
            }
            reported_selection_threshold = {
                "status": "unavailable",
                "reason_code": "CLASSIFICATION_POLICY_SCENARIO_ONLY",
                "method": decision_policy.threshold_method,
                "scope": "development_oof",
            }
        models[model_id] = {
            "metadata": final_adapter.metadata,
            "oof": {"folds": [item["fold"] for item in fold_receipts], "oof_row_refs": list(oof_refs)},
            "oof_metrics": oof_bundle,
            "threshold": reported_threshold,
            "selection_threshold": reported_selection_threshold,
            "calibration": calibration,
            "preprocessing": {"folds": fold_receipts, "final": final_receipt},
            "weights": {
                "column": task.weights,
                "status": "consumed" if task.weights is not None else "not_declared",
                "sample_scope": "training_and_oof" if task.weights is not None else "not_applicable",
            },
            "holdout": {"status": "sealed_candidate"},
            "holdout_row_refs": list(holdout_refs),
        }
        if task.structure.kind != "iid":
            controls = {
                "control": "permuted_target",
                "model_id": model_id,
                "status": "blocked",
                "reason_code": "CLASSIFICATION_CONTROL_EXCHANGEABILITY_UNIT_UNAVAILABLE",
                "exchangeability_unit": "row_position_not_authorized_for_declared_structure",
                "sample_scope": "development_oof",
                "split_hash": split_hash,
            }
        else:
            controls = {"control": "permuted_target", "model_id": model_id, "status": "not_requested", "sample_scope": "development_oof", "split_hash": split_hash}
        models[model_id]["control"] = controls
    ranking = sorted(model_ids_tuple, key=lambda model_id: (-selection_scores[model_id], model_ids_tuple.index(model_id)))
    selected_model = ranking[0]
    selected_adapter = candidate_adapters[selected_model]
    selected_transform = candidate_transforms[selected_model]
    selected_calibrator = candidate_calibrators[selected_model]
    selected_threshold = candidate_thresholds[selected_model]
    releasable_threshold = selected_threshold.get("status") == "frozen_development_choice"
    release_blocker_prefixes = (
        "CLASSIFICATION_THRESHOLD_",
        "CLASSIFICATION_CALIBRATION_NOT_APPLIED",
        "CLASSIFICATION_AVAILABILITY_UNVALIDATED",
    )
    release_blocked = (
        decision_policy.selection_status == "SCENARIOS_ONLY"
        or not releasable_threshold
        or any(
            reason == "CLASSIFICATION_CALIBRATION_NOT_APPLIED"
            or reason == "CLASSIFICATION_AVAILABILITY_UNVALIDATED"
            or reason.startswith("CLASSIFICATION_THRESHOLD_")
            for reason in blocked_reasons
        )
    )
    if not release_blocked:
        threshold_value = float(
            decision_policy.selected_threshold
            if decision_policy.selected_threshold is not None
            else selected_threshold["threshold"]
        )
        consumed_threshold = dict(selected_threshold)
        if decision_policy.selected_threshold is not None:
            consumed_threshold = {
                **selected_threshold,
                "development_selected_threshold": selected_threshold["threshold"],
                "threshold": threshold_value,
                "status": "policy_selected_threshold_consumed",
                "consumed_by": "final_holdout",
            }
        models[selected_model]["threshold"] = consumed_threshold
    else:
        threshold_value = None
        consumed_threshold = models[selected_model]["threshold"]
    policy_payload = {**decision_policy.to_dict(), "threshold": consumed_threshold}
    if not release_blocked:
        policy_payload["consumed_threshold"] = threshold_value
        policy_payload["threshold_source"] = (
            "policy_selected_threshold"
            if decision_policy.selected_threshold is not None
            else "development_calibration_eval"
        )
    model_identity = {
        "model_id": selected_model,
        "metadata": models[selected_model]["metadata"],
        "preprocessing": models[selected_model]["preprocessing"],
    }
    release_plan = {
        "metrics": list(_C0_HOLDOUT_METRIC_REFS),
        "task_hash": task.content_hash,
        "split_hash": split_hash,
        "model_id": selected_model,
        "model_hash": _production_hash(model_identity),
        "calibration_hash": _production_hash(models[selected_model]["calibration"]),
        "threshold_hash": _production_hash(consumed_threshold),
        "policy_hash": _production_hash(policy_payload),
    }
    release_plan["plan_hash"] = _production_hash(release_plan)
    if release_blocked:
        released = {
            "status": "sealed",
            "access_boundary": "server_store_consume_required",
            "release_count": 0,
            "release_plan": release_plan,
            "release_plan_hash": release_plan["plan_hash"],
            "row_refs": list(holdout_refs),
        }
    else:
        holdout_features = selected_transform.transform(feature_frame.loc[list(holdout_refs)], row_refs=holdout_refs)
        holdout_probabilities_matrix = selected_adapter.predict_proba(holdout_features)
        positive_index = list(selected_adapter._classes).index(positive)
        holdout_raw_probabilities = holdout_probabilities_matrix[:, positive_index]
        holdout_probabilities = selected_calibrator.transform(holdout_raw_probabilities.tolist())
        holdout_predictions = np.where(
            holdout_probabilities >= threshold_value,
            positive,
            negative,
        )
        released, release_plan = _release_holdout_with_c0_store(
            holdout_seal_store=holdout_seal_store,
            holdout_principal_ref=holdout_principal_ref,
            holdout_access_id=holdout_access_id,
            task=task,
            development_refs=development_refs,
            development_labels=target.loc[list(development_refs)].tolist(),
            split={"split_hash": split_hash},
            model_ids=model_ids_tuple,
            seed=seed,
            preprocessing_steps=steps,
            selection_scores=selection_scores,
            selected_model=selected_model,
            model_identity=model_identity,
            calibration=models[selected_model]["calibration"],
            threshold=consumed_threshold,
            policy_payload=policy_payload,
            holdout_labels=target.loc[list(holdout_refs)].tolist(),
            holdout_probabilities=holdout_probabilities.tolist(),
            holdout_predictions=holdout_predictions.tolist(),
            positive_class=positive,
            sample_weight=None if weights is None else [weight_by_ref[ref] for ref in holdout_refs],
        )
        released["row_refs"] = list(holdout_refs)
    for model_id in model_ids_tuple:
        models[model_id]["holdout"] = (
            released
            if model_id == selected_model
            else {"status": "not_evaluated", "reason": "holdout is reserved for the development-selected model"}
        )
    development_labels = target.loc[list(development_refs)].tolist()
    majority_class, majority_count = Counter(development_labels).most_common(1)[0]
    majority_probability = sum(value == positive for value in development_labels) / len(development_labels)
    majority_bundle = classification_metric_bundle(
        actual=development_labels,
        probabilities=[majority_probability] * len(development_labels),
        predictions=[majority_class] * len(development_labels),
        positive_class=positive,
        threshold=0.5 if threshold_value is None else threshold_value,
        sample_scope="development",
        evaluation_design="majority_baseline",
        numerical_method="known_answer",
        inference_basis="descriptive",
        validation_level="validated",
        sample_weight=None if weights is None else [weight_by_ref[ref] for ref in development_refs],
    )
    controls = [models[model_id]["control"] for model_id in model_ids_tuple]
    if any(control["status"] == "blocked" for control in controls):
        blocked_reasons.append("CLASSIFICATION_CONTROL_BLOCKED_FOR_STRUCTURE")
    unique_blocked_reasons = list(dict.fromkeys(blocked_reasons))
    result = {
        "status": "degraded" if unique_blocked_reasons else "validated",
        "blocked_reasons": unique_blocked_reasons,
        "models": models,
        "comparison": {
            "same_split": True,
            "split_hash": split_hash,
            "ranking": ranking,
            "selection_status": "selected_from_development_oof",
            "selection_metric": task.primary_metric,
            "selection_scope": "development_oof",
            "selected_model": selected_model,
            "selection_scores": selection_scores,
        },
        "split": manifest.to_dict(),
        "holdout": {
            **released,
            "model_id": selected_model,
        },
        "baselines": [
            {
                "model_id": "majority",
                "development_only": True,
                "majority_class": majority_class,
                "row_count": len(development_labels),
                "sample_scope": "development",
                "support": majority_count,
                "metrics": majority_bundle["metrics"],
            }
        ],
        "controls": controls,
        "calibration": models[selected_model]["calibration"],
        "decision_policy": policy_payload,
    }
    if search_receipt is not None:
        result["search"] = search_receipt
    return result


def run_classification_protocol(
    frame: pd.DataFrame,
    target: pd.Series | None = None,
    *,
    row_refs: Sequence[str] | None = None,
    model_ids: Sequence[str] = ("logistic_regression", "random_forest"),
    final_holdout_fraction: float = 0.2,
    cv_folds: int = 3,
    seed: int = 0,
    positive_class: Any | None = None,
    task: ClassificationTaskSpecV1 | None = None,
    decision_policy: DecisionPolicyV1 | None = None,
    feature_available_at: Sequence[Any] | None = None,
    prediction_origins: Sequence[Any] | None = None,
    label_windows: Sequence[tuple[Any, Any]] | None = None,
    entities: Sequence[str] | None = None,
    periods: Sequence[Any] | None = None,
    purge_gap: Any | None = None,
    embargo: Any | None = None,
    embargo_basis: str | None = None,
    preprocessing_steps: Sequence[ClassificationPreprocessingStepV1] | None = None,
    calibration_method: str = "platt",
    model_parameters: Mapping[str, Mapping[str, Any]] | None = None,
    bounded_search: BoundedSearchV1 | None = None,
    holdout_seal_store: HoldoutSealStoreV1 | None = None,
    holdout_principal_ref: str | None = None,
    holdout_access_id: str | None = None,
) -> dict[str, Any]:
    if task is not None:
        return _run_production_classification_protocol(
            frame,
            task=task,
            model_ids=model_ids,
            row_refs=row_refs,
            decision_policy=decision_policy,
            final_holdout_fraction=final_holdout_fraction,
            cv_folds=cv_folds,
            seed=seed,
            feature_available_at=feature_available_at,
            prediction_origins=prediction_origins,
            label_windows=label_windows,
            entities=entities,
            periods=periods,
            purge_gap=purge_gap,
            embargo=embargo,
            embargo_basis=embargo_basis,
            preprocessing_steps=preprocessing_steps,
            calibration_method=calibration_method,
            model_parameters=model_parameters,
            bounded_search=bounded_search,
            holdout_seal_store=holdout_seal_store,
            holdout_principal_ref=holdout_principal_ref,
            holdout_access_id=holdout_access_id,
        )
    if bounded_search is not None:
        raise ContractError("CLASSIFICATION_SEARCH_TASK_REQUIRED", "bounded search requires the typed classification task protocol")
    if target is None or row_refs is None or not isinstance(frame, pd.DataFrame) or len(frame) != len(target) or len(frame) != len(row_refs):
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


__all__ = [
    "BoundedSearchV1",
    "HoldoutSealGuardV1",
    "run_bounded_search",
    "run_classification_protocol",
    "select_threshold_from_oof",
]
