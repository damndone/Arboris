"""Bounded, model-agnostic classification protocol for v1.8.9.

The protocol owns the order of operations, not the model families.  Every
candidate uses the same split manifest and fold-local numeric transform; model
selection and threshold selection consume development OOF evidence only.  A
sealed holdout is evaluated once, after the model and policy are frozen.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import threading
import math
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import numpy as np
import pandas as pd

from .classification_adapters import get_classification_adapter
from .classification_contracts import (
    ClassificationDiagnosticsPlanV1,
    ClassificationPreprocessingStepV1,
    ClassificationTaskSpecV1,
    DecisionPolicyV1,
    StageCapabilityV1,
    validate_weight_support,
)
from .classification_metrics import (
    classification_metric_bundle,
    compute_calibration_bins,
    fit_probability_calibrator,
    select_threshold_from_oof,
)
from .classification_explanations import compute_permutation_explanations, summarize_shift
from .contracts import ContractError
from .preprocessing import ClassificationFoldPreprocessingV1
from .schema import build_classification_packet, classification_content_hash
from .split_kernel import ClassificationSplitManifestV1, build_classification_split_manifest


def _error(code: str, message: str) -> ContractError:
    return ContractError(code, message)


def _canonical_hash(value: Any) -> str:
    try:
        encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise _error("CLASSIFICATION_PROTOCOL_JSON_INVALID", "protocol evidence is not JSON serializable") from exc
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class _FrozenMapping(dict[str, Any]):
    """JSON-compatible immutable mapping for a sealed release plan."""

    def __setitem__(self, key: str, value: Any) -> None:
        raise TypeError("sealed release plans are immutable")

    def __delitem__(self, key: str) -> None:
        raise TypeError("sealed release plans are immutable")

    def clear(self) -> None:
        raise TypeError("sealed release plans are immutable")

    def pop(self, key: str, default: Any = None) -> Any:
        raise TypeError("sealed release plans are immutable")

    def popitem(self) -> tuple[str, Any]:
        raise TypeError("sealed release plans are immutable")

    def setdefault(self, key: str, default: Any = None) -> Any:
        raise TypeError("sealed release plans are immutable")

    def update(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("sealed release plans are immutable")

    def __ior__(self, other: Any) -> "_FrozenMapping":
        raise TypeError("sealed release plans are immutable")


def _freeze_plan_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _FrozenMapping({str(key): _freeze_plan_value(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_plan_value(item) for item in value)
    return value


def _dataset_hash(frame: pd.DataFrame) -> str:
    try:
        metadata = json.dumps(
            {"columns": [str(column) for column in frame.columns], "dtypes": [str(dtype) for dtype in frame.dtypes]},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        values = pd.util.hash_pandas_object(frame, index=True).to_numpy().tobytes()
    except (TypeError, ValueError) as exc:
        raise _error("CLASSIFICATION_DATASET_INVALID", "dataset snapshot could not be hashed") from exc
    return "sha256:" + hashlib.sha256(metadata + values).hexdigest()


def _metadata_scalar_equal(left: Any, right: Any) -> bool:
    """Compare one declared split-key value without silently coercing it."""

    try:
        left_missing = bool(pd.isna(left))
        right_missing = bool(pd.isna(right))
    except (TypeError, ValueError):
        left_missing = left is None
        right_missing = right is None
    if left_missing or right_missing:
        return left_missing and right_missing
    try:
        comparison = left == right
        return bool(comparison)
    except (TypeError, ValueError):
        return False


def _bind_split_metadata(
    frame: pd.DataFrame,
    task: ClassificationTaskSpecV1,
    *,
    entities: Sequence[str] | None,
    periods: Sequence[Any] | None,
) -> tuple[tuple[Any, ...] | None, tuple[Any, ...] | None, tuple[str, ...]]:
    """Bind split metadata to server-owned columns before any split is built.

    A caller may repeat metadata as a typed convenience, but it cannot supply
    a second, out-of-band time/entity sequence that changes the split while
    the DataFrame says something else.  The bound columns are retained in the
    dataset identity even though they are never model features.
    """

    structure = task.structure
    kind = structure.kind
    entity_values: tuple[Any, ...] | None = None
    period_values: tuple[Any, ...] | None = None
    metadata_columns: list[str] = []

    def bind_column(
        column: str,
        provided: Sequence[Any] | None,
        *,
        missing_code: str,
        mismatch_code: str,
        label: str,
    ) -> tuple[Any, ...]:
        if column not in frame.columns:
            raise _error(missing_code, f"declared {label} column {column!r} is missing")
        values = tuple(frame[column].tolist())
        if any(value is None or (isinstance(value, float) and not np.isfinite(value)) for value in values):
            raise _error(mismatch_code, f"declared {label} column contains missing or non-finite values")
        if provided is not None:
            if isinstance(provided, (str, bytes)):
                raise _error(mismatch_code, f"declared {label} metadata must align with rows")
            try:
                supplied = tuple(provided)
            except TypeError as exc:
                raise _error(mismatch_code, f"declared {label} metadata must align with rows") from exc
            if len(supplied) != len(values) or any(
                not _metadata_scalar_equal(actual, declared)
                for actual, declared in zip(values, supplied, strict=True)
            ):
                raise _error(mismatch_code, f"declared {label} metadata does not match the DataFrame column")
        return values

    if kind == "iid":
        if entities is not None or periods is not None:
            raise _error(
                "CLASSIFICATION_SPLIT_METADATA_UNEXPECTED",
                "iid classification splits do not consume entity or period metadata",
            )
    elif kind == "grouped":
        if structure.group_column is None:
            raise _error("CLASSIFICATION_GROUP_COLUMN_MISSING", "grouped structure requires a group column")
        entity_values = bind_column(
            structure.group_column,
            entities,
            missing_code="CLASSIFICATION_GROUP_COLUMN_MISSING",
            mismatch_code="CLASSIFICATION_ENTITY_METADATA_MISMATCH",
            label="group",
        )
        metadata_columns.append(structure.group_column)
    elif kind == "temporal":
        if structure.time_column is None:
            raise _error("CLASSIFICATION_TIME_COLUMN_MISSING", "temporal structure requires a time column")
        period_values = bind_column(
            structure.time_column,
            periods,
            missing_code="CLASSIFICATION_TIME_COLUMN_MISSING",
            mismatch_code="CLASSIFICATION_TIME_METADATA_MISMATCH",
            label="time",
        )
        metadata_columns.append(structure.time_column)
        if entities is not None:
            raise _error(
                "CLASSIFICATION_SPLIT_METADATA_UNEXPECTED",
                "temporal classification splits do not consume entity metadata",
            )
    elif kind == "panel":
        if structure.entity_column is None:
            raise _error("CLASSIFICATION_ENTITY_COLUMN_MISSING", "panel structure requires an entity column")
        if structure.time_column is None:
            raise _error("CLASSIFICATION_TIME_COLUMN_MISSING", "panel structure requires a time column")
        entity_values = bind_column(
            structure.entity_column,
            entities,
            missing_code="CLASSIFICATION_ENTITY_COLUMN_MISSING",
            mismatch_code="CLASSIFICATION_ENTITY_METADATA_MISMATCH",
            label="entity",
        )
        period_values = bind_column(
            structure.time_column,
            periods,
            missing_code="CLASSIFICATION_TIME_COLUMN_MISSING",
            mismatch_code="CLASSIFICATION_TIME_METADATA_MISMATCH",
            label="time",
        )
        metadata_columns.extend((structure.entity_column, structure.time_column))
    else:
        raise _error("CLASSIFICATION_DATA_STRUCTURE_INVALID", f"unsupported classification structure {kind!r}")

    return entity_values, period_values, tuple(dict.fromkeys(metadata_columns))


@dataclass
class HoldoutSealV1:
    """One-shot release capability for a frozen holdout metric bundle."""

    data_hash: str
    split_hash: str
    metric_release_plan: Mapping[str, Any]
    _released: bool = field(default=False, init=False, repr=False)
    _access_count: int = field(default=0, init=False, repr=False)
    _in_progress: bool = field(default=False, init=False, repr=False)
    _state_lock: threading.Lock = field(default_factory=threading.Lock, init=False, repr=False)
    _plan_initialized: bool = field(default=False, init=False, repr=False)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in {"data_hash", "split_hash", "metric_release_plan"} and getattr(self, "_plan_initialized", False):
            raise AttributeError("sealed release identity is immutable")
        object.__setattr__(self, name, value)

    def __post_init__(self) -> None:
        for value, label in ((self.data_hash, "data_hash"), (self.split_hash, "split_hash")):
            if not isinstance(value, str) or not value.strip():
                raise _error("CLASSIFICATION_HOLDOUT_SEAL_INVALID", f"{label} is required")
        if not isinstance(self.metric_release_plan, Mapping) or not self.metric_release_plan:
            raise _error("CLASSIFICATION_HOLDOUT_SEAL_INVALID", "metric_release_plan is required")
        metrics = self.metric_release_plan.get("metrics")
        if (
            isinstance(metrics, (str, bytes))
            or not isinstance(metrics, Sequence)
            or not metrics
            or any(not isinstance(metric, str) or not metric.strip() for metric in metrics)
        ):
            raise _error("CLASSIFICATION_HOLDOUT_SEAL_INVALID", "metric_release_plan.metrics must be a non-empty list")
        subgroups = self.metric_release_plan.get("subgroups", [])
        if isinstance(subgroups, (str, bytes)) or not isinstance(subgroups, Sequence):
            raise _error("CLASSIFICATION_HOLDOUT_SEAL_INVALID", "metric_release_plan.subgroups must be a list")
        sections = self.metric_release_plan.get("sections")
        if sections is not None and (
            isinstance(sections, (str, bytes))
            or not isinstance(sections, Sequence)
            or not sections
            or any(not isinstance(section, str) or not section.strip() for section in sections)
            or len(set(sections)) != len(sections)
        ):
            raise _error("CLASSIFICATION_HOLDOUT_SEAL_INVALID", "metric_release_plan.sections must be unique non-empty strings")
        metrics_by_section = self.metric_release_plan.get("metrics_by_section")
        if metrics_by_section is not None:
            if not isinstance(metrics_by_section, Mapping):
                raise _error("CLASSIFICATION_HOLDOUT_SEAL_INVALID", "metric_release_plan.metrics_by_section must be an object")
            for section, section_metrics in metrics_by_section.items():
                if not isinstance(section, str) or not section.strip() or (
                    isinstance(section_metrics, (str, bytes))
                    or not isinstance(section_metrics, Sequence)
                    or any(not isinstance(metric, str) or not metric.strip() for metric in section_metrics)
                    or len(set(section_metrics)) != len(section_metrics)
                ):
                    raise _error("CLASSIFICATION_HOLDOUT_SEAL_INVALID", "metric_release_plan.metrics_by_section is invalid")
        section_fields = self.metric_release_plan.get("section_fields")
        if section_fields is not None:
            if not isinstance(section_fields, Mapping) or sections is None:
                raise _error(
                    "CLASSIFICATION_HOLDOUT_SEAL_INVALID",
                    "metric_release_plan.section_fields requires declared sections",
                )
            for section, fields in section_fields.items():
                if (
                    not isinstance(section, str)
                    or section not in sections
                    or isinstance(fields, (str, bytes))
                    or not isinstance(fields, Sequence)
                    or not fields
                    or any(not isinstance(field, str) or not field.strip() for field in fields)
                    or len(set(fields)) != len(fields)
                ):
                    raise _error("CLASSIFICATION_HOLDOUT_SEAL_INVALID", "metric_release_plan.section_fields is invalid")
        if "shift" in self.metric_release_plan and not isinstance(self.metric_release_plan["shift"], bool):
            raise _error("CLASSIFICATION_HOLDOUT_SEAL_INVALID", "metric_release_plan.shift must be boolean")
        frozen_plan = _freeze_plan_value(dict(self.metric_release_plan))
        _canonical_hash(frozen_plan)
        object.__setattr__(self, "metric_release_plan", frozen_plan)
        object.__setattr__(self, "_plan_initialized", True)

    @property
    def metric_release_plan_hash(self) -> str:
        return _canonical_hash(dict(self.metric_release_plan))

    @property
    def access_count(self) -> int:
        return self._access_count

    def consume(self, metric_bundle: Mapping[str, Any] | Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
        with self._state_lock:
            if self._released:
                raise _error("CLASSIFICATION_HOLDOUT_ALREADY_RELEASED", "holdout metrics have already been released")
            if self._in_progress:
                raise _error("CLASSIFICATION_HOLDOUT_RELEASE_IN_PROGRESS", "holdout release is already in progress")
            self._in_progress = True
        try:
            candidate = metric_bundle() if callable(metric_bundle) else metric_bundle
            if not isinstance(candidate, Mapping) or not candidate:
                raise _error("CLASSIFICATION_HOLDOUT_RELEASE_INVALID", "holdout release must contain a metric bundle")
        except ContractError:
            with self._state_lock:
                self._in_progress = False
            raise
        except Exception as exc:
            with self._state_lock:
                self._in_progress = False
            raise _error("CLASSIFICATION_HOLDOUT_RELEASE_FAILED", "holdout release callback failed") from exc

        required_metrics = tuple(self.metric_release_plan["metrics"])
        declared_sections = self.metric_release_plan.get("sections")
        if declared_sections is not None:
            if isinstance(declared_sections, (str, bytes)) or not isinstance(declared_sections, Sequence):
                with self._state_lock:
                    self._in_progress = False
                raise _error("CLASSIFICATION_HOLDOUT_RELEASE_PLAN_MISMATCH", "metric release sections must be a list")
            if set(candidate) != set(declared_sections):
                with self._state_lock:
                    self._in_progress = False
                raise _error("CLASSIFICATION_HOLDOUT_RELEASE_PLAN_MISMATCH", "holdout release sections do not match the sealed plan")
        metrics_by_section = self.metric_release_plan.get("metrics_by_section")
        if isinstance(metrics_by_section, Mapping):
            for section, declared_metrics in metrics_by_section.items():
                section_payload = candidate.get(section)
                section_metrics = (
                    section_payload.get("metrics")
                    if isinstance(section_payload, Mapping) and isinstance(section_payload.get("metrics"), Mapping)
                    else section_payload
                )
                if not isinstance(section_metrics, Mapping) or set(section_metrics) != set(declared_metrics):
                    with self._state_lock:
                        self._in_progress = False
                    raise _error(
                        "CLASSIFICATION_HOLDOUT_RELEASE_PLAN_MISMATCH",
                        f"holdout release metrics for section {section!r} do not match the sealed plan",
                    )
        section_fields = self.metric_release_plan.get("section_fields")
        if isinstance(section_fields, Mapping):
            for section, declared_fields in section_fields.items():
                section_payload = candidate.get(section)
                if not isinstance(section_payload, Mapping) or set(section_payload) != set(declared_fields):
                    with self._state_lock:
                        self._in_progress = False
                    raise _error(
                        "CLASSIFICATION_HOLDOUT_RELEASE_PLAN_MISMATCH",
                        f"holdout release fields for section {section!r} do not match the sealed plan",
                    )
        metric_section = candidate.get("selected_model") if isinstance(candidate.get("selected_model"), Mapping) else candidate
        if isinstance(metric_section, Mapping) and isinstance(metric_section.get("metrics"), Mapping):
            metric_section = metric_section["metrics"]
        exact_metrics = declared_sections is not None or bool(self.metric_release_plan.get("strict_metrics"))
        if (
            not isinstance(metric_section, Mapping)
            or any(metric not in metric_section for metric in required_metrics)
            or (exact_metrics and set(metric_section) != set(required_metrics))
        ):
            with self._state_lock:
                self._in_progress = False
            raise _error(
                "CLASSIFICATION_HOLDOUT_RELEASE_PLAN_MISMATCH" if exact_metrics else "CLASSIFICATION_HOLDOUT_RELEASE_INCOMPLETE",
                "holdout release metrics do not match the sealed plan",
            )
        with self._state_lock:
            self._released = True
            self._in_progress = False
            self._access_count = 1
        return {
            "status": "evaluated_once",
            "data_hash": self.data_hash,
            "split_hash": self.split_hash,
            "metric_release_plan_hash": self.metric_release_plan_hash,
            "authorization_ref": "holdout-release:1",
            "access_count": self._access_count,
            "metric_bundle": dict(candidate),
        }

    def release(self, metric_bundle: Mapping[str, Any] | Callable[[], Mapping[str, Any]]) -> dict[str, Any]:
        """Backward-compatible alias for the typed one-shot consume operation."""

        return self.consume(metric_bundle)


@dataclass(frozen=True)
class _FoldTransform:
    columns: tuple[str, ...]
    fit_row_refs: tuple[str, ...]
    fitted: Any

    @property
    def recipe_hash(self) -> str:
        return str(self.fitted.receipt["recipe_hash"])

    def transform(self, frame: pd.DataFrame) -> pd.DataFrame:
        if any(column not in frame.columns for column in self.columns):
            raise _error("CLASSIFICATION_PREPROCESSING_SCHEMA_MISMATCH", "fold transform columns do not match fit schema")
        original_index = frame.index
        # The fold preprocessor is keyed by explicit row_refs.  Give its
        # pandas implementation a positional index so assignment alignment
        # cannot turn a non-default server row identity into NaNs, then restore
        # the caller's index after the typed transform.
        working = frame.loc[:, list(self.columns)].copy()
        working.index = range(len(working))
        transformed = self.fitted.transform(
            working,
            row_refs=tuple(str(value) for value in original_index),
        )
        result = transformed.loc[:, list(self.columns)].copy()
        result.index = original_index
        if not np.isfinite(result.to_numpy(dtype=float, copy=True)).all():
            raise _error("CLASSIFICATION_PREPROCESSING_FEATURE_INVALID", "fold-local transform produced non-finite features")
        return result


def _fit_fold_transform(
    frame: pd.DataFrame,
    columns: tuple[str, ...],
    fit_row_refs: tuple[str, ...],
    *,
    weight_name: str | None = None,
) -> _FoldTransform:
    if not columns or any(not isinstance(column, str) or not column.strip() for column in columns):
        raise _error("CLASSIFICATION_PREPROCESSING_SCHEMA_MISMATCH", "feature columns are required")
    fit_columns = list(columns) + ([weight_name] if weight_name and weight_name not in columns else [])
    fit_rows = frame.loc[list(fit_row_refs), fit_columns].to_dict(orient="index")
    steps = tuple(
        step
        for column in columns
        for step in (
            ClassificationPreprocessingStepV1(
                step_id=f"impute_{column}",
                kind="mean_impute",
                columns=(column,),
                supports_weight=True,
            ),
            ClassificationPreprocessingStepV1(
                step_id=f"scale_{column}",
                kind="standard_scale",
                columns=(column,),
                supports_weight=True,
            ),
        )
    )
    fitted = ClassificationFoldPreprocessingV1(steps=steps).fit(
        frame.loc[list(fit_row_refs), fit_columns],
        fit_row_refs=fit_row_refs,
        fit_rows=fit_rows,
        weight_name=weight_name,
    )
    return _FoldTransform(tuple(columns), tuple(fit_row_refs), fitted)


def _class_order(task: ClassificationTaskSpecV1, target: pd.Series) -> tuple[tuple[Any, ...], Any | None]:
    labels = tuple(task.class_mapping.keys())
    observed = set(target.tolist())
    if not observed.issubset(set(labels)):
        raise _error("CLASSIFICATION_CLASS_MAPPING_MISMATCH", "target contains a class absent from class_mapping")
    if len(observed) < 2:
        raise _error("CLASSIFICATION_SINGLE_CLASS", "classification task needs at least two observed classes")
    if task.positive_class is None:
        return labels, None
    matches = [raw for raw, label in task.class_mapping.items() if label == task.positive_class]
    if len(matches) != 1:
        raise _error("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class does not map to exactly one raw label")
    return labels, matches[0]


def _row_refs(frame: pd.DataFrame) -> tuple[str, ...]:
    refs = tuple(str(value) for value in frame.index)
    if len(refs) != len(set(refs)):
        raise _error("CLASSIFICATION_ROW_IDENTITY_INVALID", "row identity must be unique after serialization")
    return refs


def _fold_roles(manifest: ClassificationSplitManifestV1, fold: int) -> tuple[tuple[str, ...], tuple[str, ...]]:
    development = manifest.rows(partition="development")
    validation = tuple(
        item.row_ref for item in manifest.assignments if item.partition == "development" and item.cv_fold == fold
    )
    ordered_profiles = {"temporal_rolling", "panel_known_entity_future", "panel_new_entity"}
    training_rows_for_fold = getattr(manifest, "training_rows_for_fold", None)
    if manifest.profile in ordered_profiles and callable(training_rows_for_fold):
        train = tuple(training_rows_for_fold(fold))
        development_set = set(development)
        if not train or any(row not in development_set for row in train) or set(train) & set(validation):
            raise _error(
                "CLASSIFICATION_SPLIT_TRAINING_ROLE_INVALID",
                f"manifest training role for fold {fold} is not a valid development-only complement",
            )
    else:
        # IID/group manifests retain the historical complement-of-validation
        # fallback.  Ordered profiles must never reach this branch when the
        # manifest exposes its explicit forward-only training role.
        train = tuple(row for row in development if row not in set(validation))
    if not train or not validation:
        raise _error("CLASSIFICATION_SPLIT_CLASS_SUPPORT", f"fold {fold} has empty training or validation rows")
    return train, validation


def _metric_score(bundle: Mapping[str, Any], metric_name: str) -> float:
    metric = bundle.get("metrics", {}).get(metric_name)
    if not isinstance(metric, Mapping) or metric.get("status") != "computed" or metric.get("point_estimate") is None:
        raise _error("CLASSIFICATION_SELECTION_INSUFFICIENT_EVIDENCE", f"primary metric {metric_name!r} is undefined")
    return float(metric["point_estimate"])


_HIGHER_IS_BETTER_METRICS = frozenset(
    {"accuracy", "roc_auc", "balanced_accuracy", "pr_auc", "f1", "precision", "recall"}
)
_LOWER_IS_BETTER_METRICS = frozenset({"log_loss", "brier_score"})
_SELECTION_TOLERANCE = 1e-12


def _metric_direction(metric_name: str) -> str:
    if metric_name in _HIGHER_IS_BETTER_METRICS:
        return "higher_is_better"
    if metric_name in _LOWER_IS_BETTER_METRICS:
        return "lower_is_better"
    raise _error(
        "CLASSIFICATION_SELECTION_METRIC_DIRECTION_UNSUPPORTED",
        f"primary metric {metric_name!r} has no declared selection direction",
    )


def _validate_search_budget(
    task: ClassificationTaskSpecV1,
    model_ids: tuple[str, ...],
) -> dict[str, Any]:
    """Validate the model-count budget before any candidate is fitted."""

    budget = task.resource_budget
    if "max_trials" not in budget:
        raise _error(
            "CLASSIFICATION_SEARCH_MAX_TRIALS_MISSING",
            "resource_budget.max_trials is required for bounded model search",
        )
    max_trials = budget["max_trials"]
    if isinstance(max_trials, bool) or not isinstance(max_trials, (int, np.integer)) or int(max_trials) < 1:
        raise _error(
            "CLASSIFICATION_SEARCH_MAX_TRIALS_INVALID",
            "resource_budget.max_trials must be a positive integer",
        )
    max_trials = int(max_trials)
    if len(model_ids) > max_trials:
        raise _error(
            "CLASSIFICATION_SEARCH_BUDGET_EXCEEDED",
            f"candidate count {len(model_ids)} exceeds max_trials {max_trials}",
        )

    max_cpu_seconds = budget.get("max_cpu_seconds")
    if max_cpu_seconds is not None:
        if (
            isinstance(max_cpu_seconds, bool)
            or not isinstance(max_cpu_seconds, (int, float, np.integer, np.floating))
            or not math.isfinite(float(max_cpu_seconds))
            or float(max_cpu_seconds) <= 0
        ):
            raise _error(
                "CLASSIFICATION_SEARCH_MAX_CPU_SECONDS_INVALID",
                "resource_budget.max_cpu_seconds must be a positive finite number",
            )
        max_cpu_seconds = float(max_cpu_seconds)

    return {"max_trials": max_trials, "max_cpu_seconds": max_cpu_seconds}


def _resampling_unit(structure_kind: str) -> str:
    if structure_kind == "iid":
        return "row"
    if structure_kind in {"grouped", "panel"}:
        return "entity"
    if structure_kind == "temporal":
        return "time_block"
    return "unavailable"


def _fold_distribution(
    fold_scores: Sequence[float],
    *,
    structure_kind: str,
) -> dict[str, Any]:
    values = np.asarray(tuple(float(score) for score in fold_scores), dtype=float)
    if values.ndim != 1 or len(values) == 0 or not np.isfinite(values).all():
        raise _error(
            "CLASSIFICATION_SELECTION_INSUFFICIENT_EVIDENCE",
            "primary metric fold scores must be finite and non-empty",
        )
    return {
        "fold_scores": [float(value) for value in values],
        "count": int(len(values)),
        "mean": float(values.mean()),
        "std": float(values.std(ddof=0)),
        "min": float(values.min()),
        "max": float(values.max()),
        "resampling_unit": _resampling_unit(structure_kind),
        "summary_status": "descriptive",
        "interval": {
            "status": "unavailable",
            "reason": "no predeclared independent interval method is available for development fold scores",
        },
    }


def _scalar_for_evidence(value: Any) -> Any:
    """Convert one estimator scalar into a JSON-compatible evidence value."""

    return value.item() if hasattr(value, "item") else value


def _paired_prediction_refs(
    model_outputs: Sequence[Mapping[str, Any]],
    *,
    oof_refs: Sequence[str],
    resampling_unit: str,
) -> dict[str, Any]:
    """Build auditable, paired development-only row and fold prediction refs."""

    if not model_outputs or not oof_refs:
        raise _error(
            "CLASSIFICATION_COMPARISON_PAIRING_INVALID",
            "paired comparison evidence requires model outputs and OOF row references",
        )

    row_prediction_refs: list[dict[str, Any]] = []
    fold_prediction_refs: list[dict[str, Any]] = []
    rows_by_model = {
        str(model["model_id"]): {
            str(row["row_ref"]): row
            for row in model["oof_probability_rows"]
        }
        for model in model_outputs
    }
    folds_by_model = {
        str(model["model_id"]): {
            int(fold["fold"]): tuple(str(ref) for ref in fold["validation_row_refs"])
            for fold in model["folds"]
        }
        for model in model_outputs
    }
    model_ids = tuple(str(model["model_id"]) for model in model_outputs)
    for row_ref in oof_refs:
        row_ref = str(row_ref)
        prediction_refs: dict[str, str] = {}
        for model_id in model_ids:
            row = rows_by_model[model_id].get(row_ref)
            if row is None:
                raise _error(
                    "CLASSIFICATION_COMPARISON_PAIRING_INVALID",
                    f"model {model_id!r} is missing paired OOF row {row_ref!r}",
                )
            prediction_refs[model_id] = "prediction:classification:oof:" + _canonical_hash(
                {
                    "model_id": model_id,
                    "row_ref": row_ref,
                    "probabilities": row["probabilities"],
                    "positive_probability": row["positive_probability"],
                    "prediction": row.get("prediction"),
                }
            )
        row_prediction_refs.append({"row_ref": row_ref, "prediction_refs": prediction_refs})

    first_model_folds = folds_by_model[model_ids[0]]
    for fold_number, row_refs in sorted(first_model_folds.items()):
        prediction_refs: dict[str, str] = {}
        for model_id in model_ids:
            if folds_by_model[model_id].get(fold_number) != row_refs:
                raise _error(
                    "CLASSIFICATION_COMPARISON_PAIRING_INVALID",
                    f"fold {fold_number} does not have paired validation rows across candidates",
                )
            row_refs_payload = [
                item["row_ref"] for item in row_prediction_refs if item["row_ref"] in row_refs
            ]
            prediction_refs[model_id] = "prediction:classification:fold:" + _canonical_hash(
                {
                    "model_id": model_id,
                    "fold": fold_number,
                    "row_refs": row_refs_payload,
                    "row_prediction_refs": {
                        item["row_ref"]: item["prediction_refs"][model_id]
                        for item in row_prediction_refs
                        if item["row_ref"] in row_refs
                    },
                }
            )
        fold_prediction_refs.append(
            {
                "fold": fold_number,
                "row_refs": list(row_refs),
                "resampling_unit": resampling_unit,
                "prediction_refs": prediction_refs,
            }
        )

    return {
        "sample_scope": "development_oof",
        "resampling_unit": resampling_unit,
        "row_refs": [str(ref) for ref in oof_refs],
        "row_prediction_refs": row_prediction_refs,
        "fold_prediction_refs": fold_prediction_refs,
        "holdout_access": "none",
    }


def _pareto_tradeoff(
    model_outputs: Sequence[Mapping[str, Any]],
    *,
    task: ClassificationTaskSpecV1,
    selection_direction: str,
) -> dict[str, Any]:
    """Describe a development-only Pareto frontier without causal claims."""

    objective_names = tuple(dict.fromkeys((task.primary_metric, *task.secondary_metrics)))
    objectives: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for metric_name in objective_names:
        try:
            direction = _metric_direction(metric_name)
            values = {
                str(model["model_id"]): _metric_score(model["development_oof"], metric_name)
                for model in model_outputs
            }
        except ContractError as exc:
            excluded.append({"metric": metric_name, "status": "unavailable", "reason": str(exc)})
            continue
        objectives.append({"metric": metric_name, "direction": direction, "values": values})

    if not objectives:
        return {
            "status": "insufficient_evidence",
            "causal_interpretation": "not_causal",
            "objectives": [],
            "excluded_objectives": excluded,
            "frontier_model_ids": [],
            "tradeoffs": [],
        }

    model_ids = [str(model["model_id"]) for model in model_outputs]
    normalized = {
        model_id: {
            objective["metric"]: (
                float(objective["values"][model_id])
                if objective["direction"] == "higher_is_better"
                else -float(objective["values"][model_id])
            )
            for objective in objectives
        }
        for model_id in model_ids
    }

    def dominates(left: str, right: str) -> bool:
        left_values = normalized[left]
        right_values = normalized[right]
        no_worse = all(
            left_values[metric] >= right_values[metric] - _SELECTION_TOLERANCE
            for metric in left_values
        )
        strictly_better = any(
            left_values[metric] > right_values[metric] + _SELECTION_TOLERANCE
            for metric in left_values
        )
        return no_worse and strictly_better

    frontier = [
        model_id
        for model_id in model_ids
        if not any(dominates(other, model_id) for other in model_ids if other != model_id)
    ]
    tradeoffs = [
        {
            "model_id": model_id,
            "objective_values": {
                objective["metric"]: objective["values"][model_id]
                for objective in objectives
            },
            "dominates_model_ids": [other for other in model_ids if other != model_id and dominates(model_id, other)],
            "dominated_by_model_ids": [other for other in model_ids if other != model_id and dominates(other, model_id)],
        }
        for model_id in model_ids
    ]
    return {
        "status": "descriptive",
        "causal_interpretation": "not_causal",
        "selection_direction": selection_direction,
        "objectives": objectives,
        "excluded_objectives": excluded,
        "frontier_model_ids": frontier,
        "tradeoffs": tradeoffs,
        "dominance_rule": "no worse on every available development objective and strictly better on one",
    }


def _calibration_partition(
    row_refs: Sequence[str],
    labels: Sequence[Any],
    *,
    structure_kind: str,
    seed: int,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Create a deterministic, disjoint calibration-fit/evaluation split.

    The selected model's OOF probabilities are already out-of-sample for the
    model fit, but fitting a calibrator and scoring its curve on those same
    rows is still optimistic.  A temporal task keeps chronological order; IID
    and panel tasks use a seeded permutation.  Both sides must retain binary
    class support or the protocol stops rather than inventing a calibration
    result.
    """

    refs = tuple(row_refs)
    values = tuple(labels)
    if len(refs) != len(values) or len(refs) < 6:
        raise _error(
            "CLASSIFICATION_CALIBRATION_SUPPORT_INSUFFICIENT",
            "nested calibration requires at least six aligned development OOF rows",
        )
    if structure_kind == "temporal":
        order = np.arange(len(refs), dtype=int)
    else:
        order = np.arange(len(refs), dtype=int)
        np.random.default_rng(int(seed)).shuffle(order)
    preferred = max(2, min(len(refs) - 2, int(math.ceil(len(refs) * 0.6))))
    candidate_splits = sorted(range(2, len(refs) - 1), key=lambda value: (abs(value - preferred), value))
    for split_at in candidate_splits:
        fit_indices = order[:split_at]
        evaluation_indices = order[split_at:]
        fit_labels = {values[index] for index in fit_indices}
        evaluation_labels = {values[index] for index in evaluation_indices}
        if len(fit_labels) >= 2 and len(evaluation_labels) >= 2:
            return (
                tuple(refs[index] for index in fit_indices),
                tuple(refs[index] for index in evaluation_indices),
            )
    raise _error(
        "CLASSIFICATION_CALIBRATION_SUPPORT_INSUFFICIENT",
        "nested calibration fit and evaluation partitions must each contain both classes",
    )


def _parameter_source(model_id: str, model_parameters: Mapping[str, Mapping[str, Any]] | None) -> str:
    if isinstance(model_parameters, Mapping) and model_id in model_parameters:
        return "typed_model_parameters"
    return "adapter_defaults"


def _score_is_better(candidate: float, incumbent: float, direction: str) -> bool:
    if direction == "higher_is_better":
        return candidate > incumbent + _SELECTION_TOLERANCE
    return candidate < incumbent - _SELECTION_TOLERANCE


def _policy_with_threshold(policy: DecisionPolicyV1, threshold: float | None) -> dict[str, Any]:
    payload = policy.to_dict()
    payload["selected_threshold"] = threshold
    payload["selection_status"] = "SELECTED" if threshold is not None else "SCENARIOS_ONLY"
    return payload


def _diagnostic_scalar(value: Any) -> Any:
    """Convert one subgroup label to a finite JSON scalar without guessing."""

    if isinstance(value, np.generic):
        value = value.item()
    if value is None:
        return None
    try:
        missing = pd.isna(value)
    except (TypeError, ValueError):
        missing = False
    if isinstance(missing, (bool, np.bool_)) and bool(missing):
        return None
    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    return str(value)


def _diagnostic_is_missing(value: Any) -> bool:
    return _diagnostic_scalar(value) is None


def _blocked_availability_packet(
    frame: pd.DataFrame,
    *,
    task: ClassificationTaskSpecV1,
    model_ids: tuple[str, ...],
    decision_policy: DecisionPolicyV1,
    diagnostics_plan: ClassificationDiagnosticsPlanV1 | None = None,
) -> dict[str, Any]:
    """Build a source-level blocked packet without materializing dataset rows.

    Exploration is allowed to describe an unknown information set, but it must
    not cross the split, preprocessing, model, or holdout capability boundary.
    Keep the identity limited to schema metadata because even a dataset hash
    would read values from the unvalidated final holdout.
    """

    reason = (
        "classification packet is exploration-only because feature availability is not validated; "
        "final holdout evidence is unavailable"
    )
    schema_identity = {
        "columns": [str(column) for column in frame.columns],
        "row_count": int(len(frame)),
    }
    blocked_identity = {
        "task": task.content_hash,
        "models": list(model_ids),
        "policy": decision_policy.to_dict(),
        "availability": task.availability_status,
        "schema": schema_identity,
        "diagnostics_plan": diagnostics_plan.content_hash if diagnostics_plan is not None else None,
    }
    blocked_ref = "artifact:classification:blocked:" + _canonical_hash(blocked_identity)
    blocked_split_hash = _canonical_hash({"status": "blocked", **schema_identity, "profile": task.split_profile})
    blocked_plan_hash = _canonical_hash({"status": "blocked", "reason": reason})
    packet = build_classification_packet(
        packet_id="classification:" + _canonical_hash(blocked_identity),
        status="blocked",
        task=task.to_dict(),
        split={
            "status": "blocked",
            "profile": task.split_profile,
            "split_hash": blocked_split_hash,
            "reason": reason,
        },
        models=[],
        selected_model=None,
        evaluation={"status": "unavailable", "metrics": {}},
        calibration={"status": "unavailable"},
        baselines=[],
        controls=[],
        comparison={"status": "unavailable"},
        explanations={"status": "unavailable"},
        decision_policy={"status": "unavailable"},
        holdout_boundary={
            "status": "blocked",
            "metric_release_plan_hash": blocked_plan_hash,
            "access_count": 0,
        },
        availability={
            "status": task.availability_status,
            "deployment_safe": False,
            "reason": reason,
        },
        warnings=[reason],
        artifact_refs={
            "dataset": blocked_ref,
            "task": "artifact:task:" + task.content_hash,
            "split": "artifact:split:" + blocked_split_hash,
            "comparison": blocked_ref,
            "holdout": blocked_ref,
            "evidence": blocked_ref,
            **(
                {"diagnostics_plan": "artifact:diagnostics-plan:" + diagnostics_plan.content_hash}
                if diagnostics_plan is not None
                else {}
            ),
        },
        evidence_receipt={
            "receipt_id": "receipt:classification:blocked:" + _canonical_hash(blocked_identity),
            "source_artifacts": [blocked_ref],
            "validation_level": "blocked",
        },
    )
    packet["protocol"] = "classification_ml_v1"
    packet["packet_hash"] = classification_content_hash(packet)
    return packet


def _run_iid_shuffle_control(
    *,
    frame: pd.DataFrame,
    target: pd.Series,
    split: ClassificationSplitManifestV1,
    feature_columns: tuple[str, ...],
    weights: np.ndarray | None,
    position: Mapping[str, int],
    task: ClassificationTaskSpecV1,
    model_id: str,
    class_order: tuple[Any, ...],
    positive_raw: Any | None,
    cv_folds: int,
    averaging: str,
    model_parameters: Mapping[str, Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Run a development-only target-shuffle control on the same fold manifest.

    The control is intentionally implemented only for IID rows in this first
    release.  A temporal or panel permutation needs an explicit exchangeability
    unit; silently shuffling individual rows there would create a false
    negative-control claim, so those profiles return typed unavailable evidence.
    """

    if task.structure.kind != "iid":
        return {
            "control_id": "shuffle_target",
            "status": "unavailable",
            "reason": "row-level target shuffling is not a declared exchangeability unit for temporal or panel data",
            "exchangeability_unit": "not_declared",
            "fit_scope": "development_only",
            "split_hash": split.content_hash,
            "seed": task.seed,
        }
    development_refs = split.rows(partition="development")
    if len(development_refs) < 2:
        return {
            "control_id": "shuffle_target",
            "status": "unavailable",
            "reason": "development partition is too small for a target permutation",
            "exchangeability_unit": "row",
            "fit_scope": "development_only",
            "split_hash": split.content_hash,
            "seed": task.seed,
        }
    rng = np.random.default_rng(task.seed)
    shuffled_values = rng.permutation(target.loc[list(development_refs)].to_numpy(copy=True))
    shuffled_target = dict(zip(development_refs, shuffled_values.tolist(), strict=True))
    oof_probability_matrix = np.full((len(frame), len(class_order)), np.nan, dtype=float)
    oof_predictions = np.empty(len(frame), dtype=object)
    for fold in range(cv_folds):
        train_refs, validation_refs = _fold_roles(split, fold)
        train_labels = [shuffled_target[ref] for ref in train_refs]
        validation_labels = target.loc[list(validation_refs)].tolist()
        if len(set(train_labels)) < 2 or len(set(validation_labels)) < 2:
            return {
                "control_id": "shuffle_target",
                "status": "unavailable",
                "reason": f"target permutation lacks class support in fold {fold}",
                "exchangeability_unit": "row",
                "fit_scope": "development_only",
                "split_hash": split.content_hash,
                "seed": task.seed,
            }
        transform = _fit_fold_transform(frame, feature_columns, train_refs, weight_name=task.weights)
        train_features = transform.transform(frame.loc[list(train_refs), list(feature_columns)])
        validation_features = transform.transform(frame.loc[list(validation_refs), list(feature_columns)])
        adapter = get_classification_adapter(
            model_id,
            seed=task.seed + fold,
            parameters=(model_parameters or {}).get(model_id),
            class_order=class_order,
        )
        train_weight = None if weights is None else [float(weights[position[ref]]) for ref in train_refs]
        adapter.fit(train_features, train_labels, sample_weight=train_weight, class_order=class_order)
        probabilities = adapter.predict_proba(validation_features)
        predictions = (
            adapter.predict_at_threshold(validation_features, threshold=0.5, positive_class=positive_raw)
            if positive_raw is not None
            else adapter.predict(validation_features)
        )
        for row_index, (ref, row_probabilities, prediction) in enumerate(
            zip(validation_refs, probabilities, predictions, strict=True)
        ):
            oof_probability_matrix[position[ref], :] = row_probabilities
            oof_predictions[position[ref]] = prediction
    oof_indices = [position[ref] for ref in development_refs]
    if not np.isfinite(oof_probability_matrix[oof_indices, :]).all():
        return {
            "control_id": "shuffle_target",
            "status": "unavailable",
            "reason": "target permutation did not produce a complete development OOF record",
            "exchangeability_unit": "row",
            "fit_scope": "development_only",
            "split_hash": split.content_hash,
            "seed": task.seed,
        }
    oof_weight = None if weights is None else [float(weights[index]) for index in oof_indices]
    metric = classification_metric_bundle(
        actual=target.loc[list(development_refs)].tolist(),
        probabilities=oof_probability_matrix[oof_indices, :],
        predictions=oof_predictions[oof_indices].tolist(),
        positive_class=positive_raw,
        threshold=0.5,
        sample_scope="development_control_oof",
        evaluation_design="negative_control_shuffled_target",
        numerical_method="sklearn_1.x",
        inference_basis="descriptive",
        validation_level="validated",
        sample_weight=oof_weight,
        class_order=class_order,
        averaging=averaging,
    )
    return {
        "control_id": "shuffle_target",
        "status": "computed",
        "method": "target_permutation",
        "exchangeability_unit": "row",
        "fit_scope": "development_only",
        "split_hash": split.content_hash,
        "seed": task.seed,
        "model_id": model_id,
        "metric": metric,
        "holdout_access": "none",
    }


def run_classification_protocol(
    frame: pd.DataFrame,
    *,
    task: ClassificationTaskSpecV1,
    model_ids: Sequence[str],
    decision_policy: DecisionPolicyV1,
    final_holdout_fraction: float = 0.25,
    cv_folds: int = 3,
    feature_available_at: Sequence[Any] | None = None,
    prediction_origins: Sequence[Any] | None = None,
    label_windows: Sequence[tuple[Any, Any]] | None = None,
    entities: Sequence[str] | None = None,
    periods: Sequence[Any] | None = None,
    purge_gap: Any | None = None,
    embargo: Any | None = None,
    embargo_basis: str | None = None,
    model_parameters: Mapping[str, Mapping[str, Any]] | None = None,
    calibration_method: str = "platt",
    diagnostics_plan: ClassificationDiagnosticsPlanV1 | None = None,
) -> dict[str, Any]:
    """Run the bounded classification protocol and return a typed packet.

    The function accepts a typed task and typed policy; model IDs are resolved
    through the server-owned adapter registry.  It deliberately does not
    accept provider callables, raw estimator objects, or arbitrary filesystem
    paths.
    """

    if not isinstance(frame, pd.DataFrame) or frame.empty:
        raise _error("CLASSIFICATION_DATASET_INVALID", "classification input must be a non-empty DataFrame")
    task.validate()
    decision_policy.validate()
    if calibration_method not in {"none", "platt", "isotonic"}:
        raise _error("CLASSIFICATION_CALIBRATOR_METHOD_INVALID", "calibration_method must be none, platt or isotonic")
    selection_direction = _metric_direction(task.primary_metric)
    if decision_policy.threshold_scope != "development_oof":
        raise _error(
            "CLASSIFICATION_THRESHOLD_SCOPE_INVALID",
            "classification threshold policy must be scoped to development_oof",
        )
    if not isinstance(model_ids, Sequence) or isinstance(model_ids, (str, bytes)) or not model_ids:
        raise _error("CLASSIFICATION_MODEL_SET_INVALID", "at least one model adapter is required")
    model_ids = tuple(model_ids)
    if len(set(model_ids)) != len(model_ids):
        raise _error("CLASSIFICATION_MODEL_SET_INVALID", "model adapter IDs must be unique")
    if model_parameters is not None and not isinstance(model_parameters, Mapping):
        raise _error("CLASSIFICATION_PARAMETERS_INVALID", "model_parameters must be an object")
    search_budget = _validate_search_budget(task, model_ids)
    candidate_parameter_sources = tuple(_parameter_source(model_id, model_parameters) for model_id in model_ids)
    parameter_source = (
        candidate_parameter_sources[0]
        if len(set(candidate_parameter_sources)) == 1
        else "mixed_typed_and_adapter_defaults"
    )
    tuning_status = "not_requested" if not model_parameters else "fixed_parameters_only"
    required_columns = (task.target_column, *task.feature_columns)
    missing = [column for column in required_columns if column not in frame.columns]
    if missing:
        raise _error("CLASSIFICATION_DATASET_COLUMN_MISSING", f"classification columns are missing: {missing}")
    if frame.columns.duplicated().any():
        raise _error("CLASSIFICATION_DATASET_SCHEMA_INVALID", "classification columns must be unique")
    if diagnostics_plan is not None:
        if not isinstance(diagnostics_plan, ClassificationDiagnosticsPlanV1):
            raise _error(
                "CLASSIFICATION_TYPED_REQUEST_REQUIRED",
                "diagnostics_plan must be a ClassificationDiagnosticsPlanV1",
            )
        diagnostics_plan.validate()
        diagnostic_columns = tuple(
            dict.fromkeys((*diagnostics_plan.subgroup_columns, *diagnostics_plan.shift_columns))
        )
        forbidden_diagnostic_columns = {task.target_column}
        if task.weights is not None:
            forbidden_diagnostic_columns.add(task.weights)
        forbidden = sorted(set(diagnostic_columns) & forbidden_diagnostic_columns)
        if forbidden:
            raise _error(
                "CLASSIFICATION_DIAGNOSTICS_COLUMN_INVALID",
                f"diagnostic columns cannot include target or weight columns: {forbidden}",
            )
        missing_diagnostic_columns = [column for column in diagnostic_columns if column not in frame.columns]
        if missing_diagnostic_columns:
            raise _error(
                "CLASSIFICATION_DIAGNOSTICS_COLUMN_MISSING",
                f"diagnostic columns are missing: {missing_diagnostic_columns}",
            )
    else:
        diagnostic_columns = ()
    if task.availability_status != "VALIDATED":
        return _blocked_availability_packet(
            frame,
            task=task,
            model_ids=model_ids,
            decision_policy=decision_policy,
            diagnostics_plan=diagnostics_plan,
        )
    validate_weight_support(
        [
            StageCapabilityV1("classification.preprocessing", "fold_local_preprocessing", True),
            StageCapabilityV1("classification.model", "typed_model_adapter", True),
            StageCapabilityV1("classification.calibrator", "probability_calibration", True),
            StageCapabilityV1("classification.threshold", "decision_threshold", True),
            StageCapabilityV1("classification.metrics", "weighted_metrics", True),
            StageCapabilityV1("classification.baseline", "weighted_baseline", True),
        ],
        declared_weight=task.weights,
    )
    bound_entities, bound_periods, metadata_columns = _bind_split_metadata(
        frame,
        task,
        entities=entities,
        periods=periods,
    )
    retained_columns = list(
        dict.fromkeys(
            required_columns
            + ((task.weights,) if task.weights else ())
            + metadata_columns
            + diagnostic_columns
        )
    )
    frame = frame.loc[:, retained_columns].copy()
    refs = _row_refs(frame)
    frame.index = refs
    target = frame[task.target_column]
    class_order, positive_raw = _class_order(task, target)
    averaging = "macro" if len(class_order) > 2 else "binary_positive_class"
    split = build_classification_split_manifest(
        row_refs=refs,
        labels=tuple(target.tolist()),
        profile=task.split_profile,
        final_holdout_fraction=final_holdout_fraction,
        cv_folds=cv_folds,
        random_seed=task.seed,
        feature_available_at=feature_available_at,
        prediction_origins=prediction_origins,
        label_windows=label_windows,
        entities=bound_entities,
        periods=bound_periods,
        purge_gap=purge_gap,
        embargo=embargo,
        embargo_basis=embargo_basis,
    )
    split_hash = split.content_hash
    dataset_hash = _dataset_hash(frame)
    feature_columns = tuple(task.feature_columns)
    weights = None
    if task.weights is not None:
        if task.weights not in frame.columns:
            raise _error("CLASSIFICATION_WEIGHT_COLUMN_MISSING", task.weights)
        weights = pd.to_numeric(frame[task.weights], errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(weights).all() or (weights < 0).any() or float(weights.sum()) <= 0:
            raise _error("CLASSIFICATION_WEIGHT_INVALID", "declared weights must be finite, non-negative and positive")

    development_refs = split.rows(partition="development")
    holdout_refs = split.rows(partition="final_holdout")
    oof_refs = tuple(
        item.row_ref
        for item in split.assignments
        if item.partition == "development" and item.cv_fold is not None
    )
    if not development_refs or not holdout_refs or not oof_refs:
        raise _error("CLASSIFICATION_SPLIT_SUPPORT", "classification split needs development and holdout rows")
    position = {ref: index for index, ref in enumerate(refs)}
    model_outputs: list[dict[str, Any]] = []
    selected_oof: dict[str, Any] | None = None
    selected_adapter_id: str | None = None

    for model_id in model_ids:
        oof_probability_matrix = np.full((len(refs), len(class_order)), np.nan, dtype=float)
        oof_predictions = np.empty(len(refs), dtype=object)
        fold_records: list[dict[str, Any]] = []
        fold_primary_scores: list[float] = []
        fold_explanations: list[dict[str, Any]] = []
        last_metadata: dict[str, Any] | None = None
        for fold in range(cv_folds):
            train_refs, validation_refs = _fold_roles(split, fold)
            train_target = target.loc[list(train_refs)]
            validation_target = target.loc[list(validation_refs)]
            if len(set(train_target.tolist())) < 2 or len(set(validation_target.tolist())) < 2:
                raise _error("CLASSIFICATION_SPLIT_CLASS_SUPPORT", f"model {model_id!r} fold {fold} lacks class support")
            transform = _fit_fold_transform(frame, feature_columns, train_refs, weight_name=task.weights)
            train_features = transform.transform(frame.loc[list(train_refs), list(feature_columns)])
            validation_features = transform.transform(frame.loc[list(validation_refs), list(feature_columns)])
            adapter = get_classification_adapter(
                model_id,
                seed=task.seed + fold,
                parameters=(model_parameters or {}).get(model_id),
                class_order=class_order,
            )
            train_weight = None if weights is None else [float(weights[position[ref]]) for ref in train_refs]
            adapter.fit(train_features, train_target.tolist(), sample_weight=train_weight, class_order=class_order)
            probabilities = adapter.predict_proba(validation_features)
            positive_index = class_order.index(positive_raw) if positive_raw is not None else len(class_order) - 1
            positive_probability = probabilities[:, positive_index]
            predictions = adapter.predict_at_threshold(
                validation_features,
                threshold=0.5,
                positive_class=positive_raw,
            ) if positive_raw is not None else adapter.predict(validation_features)
            for row_index, (ref, probability, prediction) in enumerate(zip(validation_refs, positive_probability, predictions, strict=True)):
                oof_probability_matrix[position[ref], :] = probabilities[row_index, :]
                oof_predictions[position[ref]] = prediction
            fold_weight = None if weights is None else [float(weights[position[ref]]) for ref in validation_refs]
            fold_metric = classification_metric_bundle(
                actual=validation_target.tolist(),
                probabilities=probabilities,
                predictions=predictions.tolist(),
                positive_class=positive_raw,
                threshold=0.5,
                sample_scope="development_cv_fold",
                evaluation_design="nested_development",
                numerical_method="sklearn_1.x",
                inference_basis="descriptive",
                validation_level="validated",
                sample_weight=fold_weight,
                class_order=class_order,
                averaging=averaging,
            )
            fold_primary_score = _metric_score(fold_metric, task.primary_metric)
            fold_primary_scores.append(fold_primary_score)
            if positive_raw is not None:
                fold_explanation = compute_permutation_explanations(
                    validation_features,
                    validation_target.tolist(),
                    model_id=model_id,
                    predict_proba=adapter.predict_proba,
                    validation_row_refs=validation_refs,
                    feature_mapping={column: column for column in feature_columns},
                    seed=task.seed + fold,
                    repeats=3,
                    class_order=class_order,
                    positive_class=positive_raw,
                    sample_scope="outer_validation",
                    minimum_support=2,
                )
            else:
                fold_explanation = {
                    "status": "unavailable",
                    "reason": "binary positive-class permutation explanation is not applicable to multiclass output",
                    "causal_interpretation": "not_causal",
                    "sample_scope": "outer_validation",
                }
            fold_explanations.append(fold_explanation)
            fold_records.append(
                {
                    "fold": fold,
                    "train_row_refs": list(train_refs),
                    "validation_row_refs": list(validation_refs),
                    "preprocessing": {
                        "fit_row_refs": list(transform.fit_row_refs),
                        "recipe_hash": transform.recipe_hash,
                        "output_schema": list(transform.columns),
                    },
                    "metrics": fold_metric,
                    "primary_metric_score": fold_primary_score,
                    "explanations": fold_explanation,
                }
            )
            last_metadata = adapter.metadata
        oof_mask = np.asarray(
            [np.isfinite(oof_probability_matrix[position[ref], :]).all() for ref in oof_refs],
            dtype=bool,
        )
        if not oof_mask.all():
            raise _error("CLASSIFICATION_OOF_INCOMPLETE", f"model {model_id!r} did not produce a complete OOF record")
        oof_indices = [position[ref] for ref in oof_refs]
        oof_actual = target.loc[list(oof_refs)].tolist()
        oof_probs = oof_probability_matrix[oof_indices, :]
        oof_pred = oof_predictions[oof_indices].tolist()
        oof_weight = None if weights is None else [float(weights[index]) for index in oof_indices]
        oof_metric = classification_metric_bundle(
            actual=oof_actual,
            probabilities=oof_probs,
            predictions=oof_pred,
            positive_class=positive_raw,
            threshold=0.5,
            sample_scope="development_oof",
            evaluation_design="nested_development",
            numerical_method="sklearn_1.x",
            inference_basis="descriptive",
            validation_level="validated",
            sample_weight=oof_weight,
            class_order=class_order,
            averaging=averaging,
        )
        selection_score = _metric_score(oof_metric, task.primary_metric)
        fold_distribution = _fold_distribution(
            fold_primary_scores,
            structure_kind=task.structure.kind,
        )
        model_record = {
            "model_id": model_id,
            "model_family": model_id,
            "adapter_metadata": last_metadata,
            "development_oof": oof_metric,
            "primary_metric": task.primary_metric,
            "development_oof_score": selection_score,
            "fold_distribution": fold_distribution,
            "folds": fold_records,
            "oof_row_refs": list(oof_refs),
            "oof_probability_rows": [
                {
                    "row_ref": ref,
                    "probabilities": [float(value) for value in oof_probability_matrix[position[ref], :]],
                    "positive_probability": (
                        float(oof_probability_matrix[position[ref], positive_index])
                        if positive_raw is not None else None
                    ),
                    "prediction": _scalar_for_evidence(oof_predictions[position[ref]]),
                }
                for ref in oof_refs
            ],
            "explanations": {
                "status": "available" if positive_raw is not None else "unavailable",
                "causal_interpretation": "not_causal",
                "sample_scope": "outer_validation",
                "folds": fold_explanations,
            },
            "selection_score": selection_score,
            "status": "candidate",
        }
        model_outputs.append(model_record)
        is_better = selected_oof is not None and _score_is_better(
            model_record["selection_score"],
            selected_oof["selection_score"],
            selection_direction,
        )
        if selected_oof is None or is_better:
            selected_oof = model_record
            selected_adapter_id = model_id

    assert selected_oof is not None and selected_adapter_id is not None
    selected_score = float(selected_oof["selection_score"])
    tied_model_ids = [
        model["model_id"]
        for model in model_outputs
        if abs(float(model["selection_score"]) - selected_score) <= _SELECTION_TOLERANCE
    ]
    tie_policy = {
        "name": "absolute_score_tolerance",
        "tolerance": _SELECTION_TOLERANCE,
        "selection": "first_candidate_in_input_order",
        "rule": "abs(candidate_score - selected_score) <= tolerance",
    }
    tie_freeze_gate = {
        "status": "frozen" if len(tied_model_ids) > 1 else "passed",
        "selected_model_id": selected_adapter_id,
        "tied_model_ids": tied_model_ids,
        "requires_manual_review": len(tied_model_ids) > 1,
        "reason": (
            "primary metric tie is frozen; no unique winner is claimed"
            if len(tied_model_ids) > 1
            else "no primary metric tie was detected within the declared tolerance"
        ),
    }
    multiple_comparison_warning = {
        "status": "warning" if len(model_outputs) > 1 else "not_applicable",
        "candidate_count": len(model_outputs),
        "message": (
            "Comparison across multiple candidates is exploratory; it is not a multiplicity-adjusted "
            "inferential claim."
            if len(model_outputs) > 1
            else "A single candidate was evaluated; multiple-comparison warning is not applicable."
        ),
    }
    comparison_candidates: list[dict[str, Any]] = []
    for model in model_outputs:
        score = float(model["selection_score"])
        raw_difference = score - selected_score
        direction_aware_difference = (
            raw_difference
            if selection_direction == "higher_is_better"
            else -raw_difference
        )
        model["direction"] = selection_direction
        model["raw_difference_vs_selected"] = raw_difference
        model["direction_aware_difference_vs_selected"] = direction_aware_difference
        comparison_candidates.append(
            {
                "model_id": model["model_id"],
                "primary_metric": task.primary_metric,
                "development_oof_score": score,
                "selection_score": score,
                "fold_distribution": model["fold_distribution"],
                "direction": selection_direction,
                "raw_difference_vs_selected": raw_difference,
                "direction_aware_difference_vs_selected": direction_aware_difference,
                "status": (
                    "selected"
                    if model["model_id"] == selected_adapter_id
                    else ("tied" if model["model_id"] in tied_model_ids else "candidate")
                ),
            }
        )
    search_receipt = {
        "schema_version": "classification-search-receipt.v1",
        "candidate_model_ids": list(model_ids),
        "model_ids": list(model_ids),
        "candidate_count": len(model_ids),
        "max_trials": search_budget["max_trials"],
        "trials_executed": len(model_outputs),
        "seed": task.seed,
        "max_cpu_seconds": search_budget["max_cpu_seconds"],
        "candidate_space": {
            "kind": "model_adapters",
            "candidate_ids": list(model_ids),
            "count": len(model_ids),
        },
        "search_space": {
            "kind": "fixed_adapter_candidates",
            "model_ids": list(model_ids),
            "parameter_search": tuning_status,
        },
        "cancel_recovery_policy": {
            "cancel_mode": "cooperative_between_trials",
            "recovery_mode": "resume_from_last_completed_trial",
            "retry_policy": "no_automatic_retry",
        },
        "resource_enforcement": {
            "status": "cooperative_bounded",
            "cpu_hard_kill": False,
            "reason": "no process-level CPU hard kill is implemented",
        },
        "tuning_status": tuning_status,
        "parameter_source": parameter_source,
        "tuning": {"status": tuning_status, "parameter_source": parameter_source},
        "search_scope": "development_only",
        "holdout_access": "none",
        "holdout_labels_accessed": False,
        "trials": [
            {
                "trial_index": index,
                "model_id": model["model_id"],
                "status": "completed",
                "evaluation_scope": "development_oof",
                "primary_metric": task.primary_metric,
                "development_oof_score": float(model["selection_score"]),
                "parameter_source": _parameter_source(model["model_id"], model_parameters),
                "seed": task.seed,
                "max_cpu_seconds": search_budget["max_cpu_seconds"],
                "holdout_access": "none",
                "cancel_recovery_status": "completed_without_recovery",
            }
            for index, model in enumerate(model_outputs, start=1)
        ],
    }
    selected_oof_refs = tuple(development_refs)
    control = _run_iid_shuffle_control(
        frame=frame,
        target=target,
        split=split,
        feature_columns=feature_columns,
        weights=weights,
        position=position,
        task=task,
        model_id=selected_adapter_id,
        class_order=class_order,
        positive_raw=positive_raw,
        cv_folds=cv_folds,
        averaging=averaging,
        model_parameters=model_parameters,
    )
    # Refit the selected model on all development rows.  The fitted adapter is
    # intentionally not re-used from a fold: its fit scope must be visible in
    # the receipt and its threshold remains development-OOF derived.
    transform = _fit_fold_transform(frame, feature_columns, selected_oof_refs, weight_name=task.weights)
    development_features = transform.transform(frame.loc[list(selected_oof_refs), list(feature_columns)])
    selected_adapter = get_classification_adapter(
        selected_adapter_id,
        seed=task.seed,
        parameters=(model_parameters or {}).get(selected_adapter_id),
        class_order=class_order,
    )
    development_weight = None if weights is None else [float(weights[position[ref]]) for ref in selected_oof_refs]
    selected_adapter.fit(
        development_features,
        target.loc[list(selected_oof_refs)].tolist(),
        sample_weight=development_weight,
        class_order=class_order,
    )
    positive_index = class_order.index(positive_raw) if positive_raw is not None else len(class_order) - 1
    holdout_metric_names = (
        "accuracy",
        "precision",
        "recall",
        "f1",
        "balanced_accuracy",
        "roc_auc",
        "pr_auc",
        "log_loss",
        "brier_score",
    )
    seal = HoldoutSealV1(
        data_hash=dataset_hash,
        split_hash=split_hash,
        metric_release_plan={
            "metrics": list(holdout_metric_names),
            "sections": [
                "selected_model",
                "baseline",
                "baseline_majority_label",
                "baseline_probability_matrix",
            ] + (["diagnostics"] if diagnostics_plan is not None else []),
            "metrics_by_section": {
                "selected_model": list(holdout_metric_names),
                "baseline": list(holdout_metric_names),
            },
            **(
                {
                    "section_fields": {
                        "diagnostics": ["status", "plan_hash", "plan", "subgroups", "shift"]
                    }
                }
                if diagnostics_plan is not None
                else {}
            ),
            **(
                {
                    "diagnostics_plan": diagnostics_plan.to_dict(),
                    "diagnostic_columns": list(
                        dict.fromkeys(
                            (*diagnostics_plan.subgroup_columns, *diagnostics_plan.shift_columns)
                        )
                    ),
                    "diagnostic_minimum_support": diagnostics_plan.minimum_support,
                    "diagnostic_bins": diagnostics_plan.bins,
                    "diagnostic_statistics": list(diagnostics_plan.statistics),
                }
                if diagnostics_plan is not None
                else {}
            ),
            "subgroups": [],
            "shift": False,
            "multiplicity_policy": "predeclared_packet_v1",
        },
    )
    selected_oof_evaluation_refs = tuple(selected_oof["oof_row_refs"])
    oof_actual = target.loc[list(selected_oof_evaluation_refs)].tolist()
    oof_weight = None if weights is None else [float(weights[position[ref]]) for ref in selected_oof_evaluation_refs]
    # The selection record carries the complete OOF packet.  Binary
    # calibration is nevertheless fit on a disjoint development subset and
    # its curve/policy are evaluated on the complementary subset, avoiding
    # calibrator reuse optimism while keeping the final holdout sealed.
    if positive_raw is None:
        raw_oof_positive_probabilities = None
        calibration_fit_refs = selected_oof_evaluation_refs
        calibration_evaluation_refs = selected_oof_evaluation_refs
        calibration_fit_probabilities = np.asarray([], dtype=float)
        calibration_evaluation_probabilities = np.asarray([], dtype=float)
        calibration_fit_actual: list[Any] = []
        calibration_evaluation_actual: list[Any] = []
        calibration_fit_weight: list[float] | None = None
        calibration_evaluation_weight: list[float] | None = None
    else:
        raw_oof_by_ref = {
            str(row["row_ref"]): float(row["positive_probability"])
            for row in selected_oof.get("oof_probability_rows", [])
            if row.get("positive_probability") is not None
        }
        if len(raw_oof_by_ref) != len(selected_oof_evaluation_refs) or set(raw_oof_by_ref) != set(selected_oof_evaluation_refs):
            raise _error("CLASSIFICATION_OOF_PROBABILITY_RECEIPT_MISSING", "calibration requires complete OOF probability refs")
        raw_oof_positive_probabilities = np.asarray(
            [raw_oof_by_ref[ref] for ref in selected_oof_evaluation_refs],
            dtype=float,
        )
        if calibration_method == "none":
            calibration_fit_refs = selected_oof_evaluation_refs
            calibration_evaluation_refs = selected_oof_evaluation_refs
        else:
            calibration_fit_refs, calibration_evaluation_refs = _calibration_partition(
                selected_oof_evaluation_refs,
                oof_actual,
                structure_kind=task.structure.kind,
                seed=task.seed,
            )
        oof_position = {ref: index for index, ref in enumerate(selected_oof_evaluation_refs)}
        calibration_fit_indices = [oof_position[ref] for ref in calibration_fit_refs]
        calibration_evaluation_indices = [oof_position[ref] for ref in calibration_evaluation_refs]
        calibration_fit_probabilities = raw_oof_positive_probabilities[calibration_fit_indices]
        calibration_evaluation_probabilities = raw_oof_positive_probabilities[calibration_evaluation_indices]
        calibration_fit_actual = [oof_actual[index] for index in calibration_fit_indices]
        calibration_evaluation_actual = [oof_actual[index] for index in calibration_evaluation_indices]
        calibration_fit_weight = None if oof_weight is None else [oof_weight[index] for index in calibration_fit_indices]
        calibration_evaluation_weight = (
            None if oof_weight is None else [oof_weight[index] for index in calibration_evaluation_indices]
        )
    calibrator = None
    if positive_raw is not None:
        calibrator = fit_probability_calibrator(
            method=calibration_method,
            fit_probabilities=calibration_fit_probabilities,
            fit_labels=calibration_fit_actual,
            fit_scope="development_oof",
            fit_row_refs=calibration_fit_refs,
            seed=task.seed,
            recipe={
                "recipe_id": "classification.probability-calibration",
                "version": "1.0",
                "method": calibration_method,
            },
            evidence_receipt={
                "receipt_id": "receipt:calibration:" + _canonical_hash(calibration_fit_refs),
                "source_artifacts": ["artifact:development-oof:" + _canonical_hash(calibration_fit_refs)],
                "validation_level": "formal_packet_local",
            },
            class_order=class_order,
            positive_class=positive_raw,
            sample_weight=calibration_fit_weight,
        )
        oof_positive_probabilities = calibrator.transform(
            calibration_evaluation_probabilities,
            sample_scope="development_calibration_eval",
        )
        calibration_payload = calibrator.evidence()
        calibration_payload["status"] = "applied" if calibration_method != "none" else "not_applied"
        calibration_payload["scope"] = "development_calibration_fit_eval_outer_holdout_transform"
        calibration_payload["evaluation_scope"] = "development_calibration_eval"
        calibration_payload["evaluation_row_refs"] = list(calibration_evaluation_refs)
        calibration_payload["nested_calibration"] = calibration_method != "none"
        calibration_payload["oof_curve"] = compute_calibration_bins(
            actual=[int(label == positive_raw) for label in calibration_evaluation_actual],
            probabilities=oof_positive_probabilities,
            sample_scope="development_calibration_eval",
            positive_class=1,
            sample_weight=calibration_evaluation_weight,
            calibration_kind="calibrated_binary_positive_class",
        )
    else:
        oof_positive_probabilities = None
        calibration_payload = {
            "status": "unavailable",
            "method": calibration_method,
            "scope": "development_oof",
            "reason": "probability calibration is currently binary-only",
            "independent_oracle": False,
        }
    threshold_value: float | None = None
    threshold_receipt: dict[str, Any] = {"status": "scenarios_only", "scope": "development_oof"}
    if positive_raw is not None and decision_policy.selection_status == "SELECTABLE":
        # Recreate OOF probabilities from the fold records' row-level receipt
        # only when the protocol stored them.  If a caller requests a policy
        # without that receipt, fail closed instead of fitting a threshold on
        # the holdout or silently using a favorable default.
        if oof_positive_probabilities is None:
            raise _error("CLASSIFICATION_OOF_PROBABILITY_RECEIPT_MISSING", "threshold selection requires OOF probability refs")
        if decision_policy.threshold_method == "fixed":
            if decision_policy.selected_threshold is None:
                raise _error("CLASSIFICATION_POLICY_INVALID", "fixed threshold policy must declare selected_threshold")
            threshold_receipt = {
                "status": "frozen_predeclared_choice",
                "threshold": float(decision_policy.selected_threshold),
                "method": "fixed",
                "scope": "development_oof",
                "positive_class": positive_raw,
                "capacity_constraint": {
                    "status": "declared",
                    "unit": decision_policy.capacity_unit,
                    "limit": float(decision_policy.capacity) if decision_policy.capacity is not None else None,
                },
            }
        else:
            threshold_receipt = select_threshold_from_oof(
                actual=calibration_evaluation_actual,
                probabilities=oof_positive_probabilities,
                method=decision_policy.threshold_method,
                scope=(
                    "development_calibration_eval"
                    if calibration_method != "none"
                    else "development_oof"
                ),
                positive_class=positive_raw,
                cost_matrix=(
                    decision_policy.cost_matrix
                    if decision_policy.threshold_method == "expected_utility"
                    else None
                ),
                capacity=decision_policy.capacity,
                capacity_unit=decision_policy.capacity_unit,
                sample_weight=calibration_evaluation_weight,
            )
        if threshold_receipt.get("status") not in {
            "frozen_development_choice",
            "frozen_predeclared_choice",
        }:
            raise _error(
                "CLASSIFICATION_THRESHOLD_SELECTION_UNDEFINED",
                "selectable threshold policy did not produce a selected threshold",
            )
        threshold_receipt["input_scope"] = (
            "development_calibration_eval"
            if calibration_method != "none"
            else "development_oof"
        )
        threshold_receipt["input_row_refs"] = list(
            calibration_evaluation_refs if decision_policy.threshold_method != "fixed" else ()
        )
        if threshold_receipt.get("status") == "frozen_development_choice":
            threshold_value = float(threshold_receipt["threshold"])
        elif threshold_receipt.get("status") == "frozen_predeclared_choice":
            threshold_value = float(threshold_receipt["threshold"])
    elif positive_raw is not None:
        threshold_receipt["reason"] = "cost and capacity were not both declared; scenarios only"
    evaluation_threshold = 0.5 if threshold_value is None else threshold_value

    def _release_holdout_metrics() -> dict[str, Any]:
        """Compute the single predeclared holdout release behind the seal."""

        holdout_features = transform.transform(frame.loc[list(holdout_refs), list(feature_columns)])
        raw_holdout_probabilities_matrix = selected_adapter.predict_proba(holdout_features)
        holdout_probabilities_matrix = raw_holdout_probabilities_matrix.copy()
        if calibrator is not None and positive_raw is not None:
            calibrated_holdout_positive = calibrator.transform(
                raw_holdout_probabilities_matrix[:, positive_index],
                sample_scope="outer_holdout",
            )
            holdout_probabilities_matrix[:, positive_index] = calibrated_holdout_positive
            holdout_probabilities_matrix[:, 1 - positive_index] = 1.0 - calibrated_holdout_positive
        holdout_predictions = (
            selected_adapter.predict_at_threshold(
                holdout_features,
                threshold=evaluation_threshold,
                positive_class=positive_raw,
            )
            if positive_raw is not None
            else selected_adapter.predict(holdout_features)
        )
        holdout_weight = None if weights is None else [float(weights[position[ref]]) for ref in holdout_refs]
        evaluation = classification_metric_bundle(
            actual=target.loc[list(holdout_refs)].tolist(),
            probabilities=holdout_probabilities_matrix,
            predictions=holdout_predictions.tolist(),
            positive_class=positive_raw,
            threshold=evaluation_threshold,
            sample_scope="final_holdout",
            evaluation_design="sealed_holdout",
            numerical_method="sklearn_1.x",
            inference_basis="descriptive",
            validation_level="validated",
            sample_weight=holdout_weight,
            class_order=class_order,
            averaging=averaging,
        )
        majority = target.loc[list(development_refs)].mode(dropna=True)
        if majority.empty:
            raise _error("CLASSIFICATION_BASELINE_INVALID", "development majority baseline is undefined")
        majority_value = majority.iloc[0]
        majority_label = majority_value.item() if hasattr(majority_value, "item") else majority_value
        baseline_predictions = [majority_label] * len(holdout_refs)
        baseline_probability_matrix = np.zeros((len(holdout_refs), len(class_order)), dtype=float)
        majority_index = class_order.index(majority_label)
        if len(class_order) == 2:
            development_labels = np.asarray(target.loc[list(development_refs)]) == positive_raw
            development_weight_values = (
                np.ones(len(development_refs), dtype=float)
                if weights is None
                else np.asarray(
                    [float(weights[position[ref]]) for ref in development_refs],
                    dtype=float,
                )
            )
            prevalence = float(np.average(development_labels, weights=development_weight_values))
            baseline_probability_matrix[:, positive_index] = prevalence
            baseline_probability_matrix[:, 1 - positive_index] = 1.0 - prevalence
        else:
            baseline_probability_matrix[:, majority_index] = 1.0
        baseline = classification_metric_bundle(
            actual=target.loc[list(holdout_refs)].tolist(),
            probabilities=baseline_probability_matrix,
            predictions=baseline_predictions,
            positive_class=positive_raw,
            threshold=evaluation_threshold,
            sample_scope="final_holdout",
            evaluation_design="sealed_holdout_baseline",
            numerical_method="known_answer",
            inference_basis="descriptive",
            validation_level="validated",
            sample_weight=holdout_weight,
            class_order=class_order,
            averaging=averaging,
        )
        diagnostics: dict[str, Any] | None = None
        if diagnostics_plan is not None:
            subgroup_rows: list[dict[str, Any]] = []
            holdout_target = target.loc[list(holdout_refs)].to_numpy()
            holdout_weights_array = None if holdout_weight is None else np.asarray(holdout_weight, dtype=float)
            holdout_predictions_array = np.asarray(holdout_predictions)
            for column in diagnostics_plan.subgroup_columns:
                values = frame.loc[list(holdout_refs), column]
                unique_values = list(pd.unique(values))
                unique_values.sort(key=lambda value: (type(value).__name__, repr(value)))
                for value in unique_values:
                    if _diagnostic_is_missing(value):
                        mask = values.isna().to_numpy()
                    else:
                        mask = values.eq(value).fillna(False).to_numpy(dtype=bool)
                    group_indices = np.flatnonzero(mask)
                    group_refs = [holdout_refs[index] for index in group_indices]
                    group_value = _diagnostic_scalar(value)
                    support = len(group_indices)
                    if support < diagnostics_plan.minimum_support:
                        subgroup_rows.append(
                            {
                                "column": column,
                                "value": group_value,
                                "status": "insufficient_support",
                                "support": support,
                                "minimum_support": diagnostics_plan.minimum_support,
                                "row_refs": group_refs,
                                "sample_scope": "final_holdout_subgroup",
                                "evaluation_design": "sealed_holdout_subgroup",
                                "metrics": {},
                                "reason": "support below predeclared diagnostic minimum",
                            }
                        )
                        continue
                    group_weight = (
                        None
                        if holdout_weights_array is None
                        else holdout_weights_array[group_indices].tolist()
                    )
                    group_bundle = classification_metric_bundle(
                        actual=holdout_target[group_indices].tolist(),
                        probabilities=holdout_probabilities_matrix[group_indices, :],
                        predictions=holdout_predictions_array[group_indices].tolist(),
                        positive_class=positive_raw,
                        threshold=evaluation_threshold,
                        sample_scope="final_holdout_subgroup",
                        evaluation_design="sealed_holdout_subgroup",
                        numerical_method="sklearn_1.x",
                        inference_basis="descriptive",
                        validation_level="validated",
                        sample_weight=group_weight,
                        class_order=class_order,
                        averaging=averaging,
                        calibration_bins=diagnostics_plan.bins,
                    )
                    subgroup_rows.append(
                        {
                            "column": column,
                            "value": group_value,
                            "status": "computed",
                            "support": support,
                            "minimum_support": diagnostics_plan.minimum_support,
                            "row_refs": group_refs,
                            "sample_scope": "final_holdout_subgroup",
                            "evaluation_design": "sealed_holdout_subgroup",
                            "metrics": group_bundle,
                        }
                    )
            shift = summarize_shift(
                development=frame.loc[list(development_refs), list(diagnostics_plan.shift_columns)],
                validation=frame.loc[list(holdout_refs), list(diagnostics_plan.shift_columns)],
                minimum_support=diagnostics_plan.minimum_support,
                bins=diagnostics_plan.bins,
                statistics=diagnostics_plan.statistics,
            )
            diagnostics = {
                "status": "computed",
                "plan_hash": diagnostics_plan.content_hash,
                "plan": diagnostics_plan.to_dict(),
                "subgroups": subgroup_rows,
                "shift": shift,
            }
        return {
            "selected_model": evaluation,
            "baseline": baseline,
            "baseline_majority_label": majority_label,
            "baseline_probability_matrix": baseline_probability_matrix.tolist(),
            **({"diagnostics": diagnostics} if diagnostics is not None else {}),
        }

    policy_payload = _policy_with_threshold(decision_policy, threshold_value)
    availability_validated = task.availability_status == "VALIDATED"
    if availability_validated:
        released = seal.release(_release_holdout_metrics)
        evaluation = released["metric_bundle"]["selected_model"]
        baseline = released["metric_bundle"]["baseline"]
        baseline_majority_label = released["metric_bundle"]["baseline_majority_label"]
        baseline_probability_matrix = released["metric_bundle"]["baseline_probability_matrix"]
        diagnostics = released["metric_bundle"].get("diagnostics")
    else:
        # Unknown/exploration availability is not allowed to consume the outer
        # holdout.  Keep an explicit boundary receipt so consumers can explain
        # the block without mistaking it for a failed evaluation.
        released = {
            "status": "blocked",
            "data_hash": dataset_hash,
            "split_hash": split_hash,
            "metric_release_plan_hash": seal.metric_release_plan_hash,
            "access_count": 0,
            "metric_bundle": {},
        }
        evaluation = {"status": "unavailable", "metrics": {}}
        baseline = None
        baseline_majority_label = None
        baseline_probability_matrix = None
        diagnostics = None
    comparison = {
        "comparison_id": _canonical_hash(
            {
                "models": model_ids,
                "split_hash": split_hash,
                "primary_metric": task.primary_metric,
                "selection_tolerance": _SELECTION_TOLERANCE,
            }
        ),
        "selection_status": "selected",
        "selected_model_id": selected_adapter_id,
        "primary_metric": task.primary_metric,
        "direction": selection_direction,
        "selected_direction": selection_direction,
        "sample_scope": "development_oof",
        "resampling_unit": _resampling_unit(task.structure.kind),
        "models": model_outputs,
        "candidates": comparison_candidates,
        "metric_differences": {
            model["model_id"]: model["raw_difference_vs_selected"]
            for model in model_outputs
        },
        "direction_aware_differences": {
            model["model_id"]: model["direction_aware_difference_vs_selected"]
            for model in model_outputs
        },
        "tie_policy": tie_policy,
        "tied_model_ids": tied_model_ids,
        "tie_freeze_gate": tie_freeze_gate,
        "multiple_comparison_warning": multiple_comparison_warning,
        "warnings": (
            [multiple_comparison_warning["message"]]
            if len(model_outputs) > 1
            else []
        ),
        "search_receipt": search_receipt,
        "paired_prediction_refs": _paired_prediction_refs(
            model_outputs,
            oof_refs=oof_refs,
            resampling_unit=_resampling_unit(task.structure.kind),
        ),
        "uncertainty": {
            "status": "unavailable",
            "reason": "no predeclared independent interval method is available for paired model comparison",
        },
        "evidence_state": {
            "status": "sufficient",
            "insufficient_evidence": False,
            "reason": "paired development OOF row and fold prediction references are complete",
        },
        "insufficient_evidence_state": {
            "status": "not_present",
            "reason": "paired development OOF row and fold prediction references are complete",
        },
        "pareto_tradeoff": _pareto_tradeoff(
            model_outputs,
            task=task,
            selection_direction=selection_direction,
        ),
        "ranking_is_not_causal": True,
    }
    split_payload = split.to_dict()
    split_payload["content_hash"] = split_hash
    task_payload = task.to_dict()
    artifact_refs = {
        "dataset": f"artifact:dataset:{dataset_hash}",
        "task": f"artifact:task:{task.content_hash}",
        "split": f"artifact:split:{split_hash}",
        "preprocessing": f"artifact:preprocessing:{transform.recipe_hash}",
        "candidates": "artifact:candidates:" + _canonical_hash(model_ids),
        "comparison": "artifact:comparison:" + comparison["comparison_id"],
        "selected_model": f"artifact:model:{selected_adapter_id}",
        "decision_policy": "artifact:policy:" + _canonical_hash(policy_payload),
        "holdout": "artifact:holdout:" + _canonical_hash(released),
        "evidence": "artifact:evidence:" + _canonical_hash({"dataset": dataset_hash, "split": split_hash}),
        **(
            {
                "diagnostics_plan": "artifact:diagnostics-plan:" + diagnostics_plan.content_hash,
                "diagnostics": "artifact:diagnostics:" + _canonical_hash(diagnostics),
            }
            if diagnostics is not None
            else {}
        ),
    }
    baseline_payload = []
    if availability_validated:
        baseline_payload = [
            {
                "baseline_id": "development_majority",
                "majority_class": baseline_majority_label,
                "class_order": list(class_order),
                "probability_matrix": baseline_probability_matrix,
                "metrics": baseline,
            }
        ]
    warnings = ["Prediction explanations are descriptive, not causal."]
    if len(model_outputs) > 1:
        warnings.append(multiple_comparison_warning["message"])
    packet_identity = {
        "dataset": dataset_hash,
        "task": task.content_hash,
        "split": split_hash,
        "model_set": list(model_ids),
        "selected_model": selected_adapter_id,
        "comparison": comparison["comparison_id"],
        "decision_policy": policy_payload,
        "calibration_method": calibration_payload.get("method"),
        "diagnostics_plan": diagnostics_plan.content_hash if diagnostics_plan is not None else None,
    }
    packet_status = "validated"
    if task.availability_status != "VALIDATED":
        packet_status = "blocked"
        warnings.append(
            "Classification packet is exploration-only because feature availability is not validated."
        )
    models_payload = model_outputs if availability_validated else []
    selected_model_payload = (
        {"model_id": selected_adapter_id, "selection_artifact_ref": artifact_refs["comparison"]}
        if availability_validated
        else None
    )
    calibration_payload_for_packet = (
        {**calibration_payload, "threshold": threshold_receipt}
        if availability_validated
        else {"status": "unavailable", "reason": "feature availability is not validated"}
    )
    comparison_payload = comparison if availability_validated else {"status": "unavailable"}
    explanations_payload = selected_oof["explanations"] if availability_validated else {"status": "unavailable"}
    decision_policy_payload = (
        {**policy_payload, "threshold_receipt": threshold_receipt}
        if availability_validated
        else {"status": "unavailable"}
    )
    packet = build_classification_packet(
        packet_id="classification:" + _canonical_hash(packet_identity),
        status=packet_status,
        task=task_payload,
        split=split_payload,
        models=models_payload,
        selected_model=selected_model_payload,
        evaluation={
            **evaluation,
            "sample_scope": "final_holdout",
            "holdout_release": released,
            **({"diagnostics": diagnostics} if diagnostics is not None else {}),
        },
        calibration=calibration_payload_for_packet,
        baselines=baseline_payload,
        controls=[control] if availability_validated else [],
        comparison=comparison_payload,
        explanations=explanations_payload,
        decision_policy=decision_policy_payload,
        holdout_boundary={
            "status": released["status"],
            "metric_release_plan_hash": released["metric_release_plan_hash"],
            **({"authorization_ref": released["authorization_ref"]} if "authorization_ref" in released else {}),
            "access_count": released["access_count"],
        },
        availability={"status": task.availability_status, "deployment_safe": task.deployment_safe},
        warnings=warnings,
        artifact_refs=artifact_refs,
        evidence_receipt={
            "receipt_id": "receipt:" + _canonical_hash({"dataset": dataset_hash, "split": split_hash}),
            "source_artifacts": [
                artifact_refs["comparison"],
                artifact_refs["holdout"],
                *(
                    [artifact_refs["diagnostics_plan"]]
                    if "diagnostics_plan" in artifact_refs
                    else []
                ),
                *([artifact_refs["diagnostics"]] if "diagnostics" in artifact_refs else []),
            ],
            "validation_level": "formal_packet_local",
        },
    )
    packet["protocol"] = "classification_ml_v1"
    packet["packet_hash"] = classification_content_hash(packet)
    return packet


__all__ = ["HoldoutSealV1", "run_classification_protocol"]
