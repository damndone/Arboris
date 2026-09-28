"""Typed, fail-closed contracts for v1.8.9 classification research.

The classification lane deliberately keeps the task contract independent from
the estimator implementation.  In particular, availability and decision
policy facts are not inferred from a dataframe or a model adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Mapping

from .contracts import ContractError, StructureSpecV1


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractError("CLASSIFICATION_CONTRACT_INVALID", "non-finite values are not allowed")
        return value
    return value


def _text(value: Any, code: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(code, f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True)
class FeatureAvailabilityContractV1:
    """Server-bound availability facts for one feature column."""

    feature_name: str
    observed_at: str | None
    available_at: str | None
    prediction_origin: str | None
    source_recipe: str | None
    leakage_status: str = "unknown"

    def validate(self, *, structure_kind: str, allow_exploration: bool = False) -> None:
        _text(self.feature_name, "CLASSIFICATION_FEATURE_INVALID", "feature_name")
        if self.leakage_status not in {"unknown", "declared", "validated", "blocked"}:
            raise ContractError("CLASSIFICATION_AVAILABILITY_INVALID", "unknown leakage status")
        if self.leakage_status == "blocked":
            raise ContractError("CLASSIFICATION_INFORMATION_SET_BLOCKED", self.feature_name)
        required = {
            "observed_at": self.observed_at,
            "available_at": self.available_at,
            "prediction_origin": self.prediction_origin,
            "source_recipe": self.source_recipe,
        }
        if structure_kind in {"temporal", "panel"}:
            if any(not isinstance(value, str) or not value.strip() for value in required.values()):
                raise ContractError(
                    "CLASSIFICATION_INFORMATION_SET_INCOMPLETE",
                    f"{self.feature_name} lacks an information-set binding",
                )
            if self.leakage_status != "validated":
                raise ContractError(
                    "CLASSIFICATION_INFORMATION_SET_INCOMPLETE",
                    f"{self.feature_name} availability is not validated",
                )
        elif not allow_exploration and any(value is None for value in required.values()):
            raise ContractError(
                "CLASSIFICATION_INFORMATION_SET_INCOMPLETE",
                f"{self.feature_name} availability is not declared",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "feature_name": self.feature_name,
            "observed_at": self.observed_at,
            "available_at": self.available_at,
            "prediction_origin": self.prediction_origin,
            "source_recipe": self.source_recipe,
            "leakage_status": self.leakage_status,
        }


@dataclass(frozen=True)
class LabelDefinitionV1:
    target_construction: str
    event_time: str | None
    horizon: str | None
    purge_gap: str | None
    revision_policy: str

    def validate(self, *, structure_kind: str) -> None:
        _text(self.target_construction, "CLASSIFICATION_LABEL_INVALID", "target_construction")
        _text(self.revision_policy, "CLASSIFICATION_LABEL_INVALID", "revision_policy")
        if structure_kind in {"temporal", "panel"}:
            if any(not isinstance(value, str) or not value.strip() for value in (self.event_time, self.horizon)):
                raise ContractError("CLASSIFICATION_LABEL_TIME_REQUIRED", "event time and horizon are required")
            if self.purge_gap is not None and (not isinstance(self.purge_gap, str) or not self.purge_gap.strip()):
                raise ContractError("CLASSIFICATION_LABEL_PURGE_INVALID", "purge_gap must be non-empty when declared")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_construction": self.target_construction,
            "event_time": self.event_time,
            "horizon": self.horizon,
            "purge_gap": self.purge_gap,
            "revision_policy": self.revision_policy,
        }


@dataclass(frozen=True)
class DecisionPolicyV1:
    cost_matrix: Mapping[str, Any] | None
    capacity: int | float | None
    abstain_allowed: bool
    manual_review_allowed: bool
    threshold_scope: str
    threshold_method: str
    policy_version: str
    population: str
    time_validity: str
    selected_threshold: float | None = None

    @property
    def selection_status(self) -> str:
        return "SELECTABLE" if self.cost_matrix is not None and self.capacity is not None else "SCENARIOS_ONLY"

    def validate(self) -> None:
        _text(self.threshold_scope, "CLASSIFICATION_POLICY_INVALID", "threshold_scope")
        _text(self.threshold_method, "CLASSIFICATION_POLICY_INVALID", "threshold_method")
        _text(self.policy_version, "CLASSIFICATION_POLICY_INVALID", "policy_version")
        _text(self.population, "CLASSIFICATION_POLICY_INVALID", "population")
        _text(self.time_validity, "CLASSIFICATION_POLICY_INVALID", "time_validity")
        if not isinstance(self.abstain_allowed, bool) or not isinstance(self.manual_review_allowed, bool):
            raise ContractError("CLASSIFICATION_POLICY_INVALID", "abstain/manual-review flags must be booleans")
        if self.selected_threshold is not None and not 0 <= self.selected_threshold <= 1:
            raise ContractError("CLASSIFICATION_THRESHOLD_INVALID", "selected threshold must be in [0, 1]")
        if self.selection_status == "SCENARIOS_ONLY" and self.selected_threshold is not None:
            raise ContractError("CLASSIFICATION_POLICY_COSTS_REQUIRED", "unknown costs cannot produce a selected threshold")
        if self.cost_matrix is not None and not isinstance(self.cost_matrix, Mapping):
            raise ContractError("CLASSIFICATION_POLICY_INVALID", "cost_matrix must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "cost_matrix": _canonical(self.cost_matrix) if self.cost_matrix is not None else None,
            "capacity": self.capacity,
            "abstain_allowed": self.abstain_allowed,
            "manual_review_allowed": self.manual_review_allowed,
            "threshold_scope": self.threshold_scope,
            "threshold_method": self.threshold_method,
            "policy_version": self.policy_version,
            "population": self.population,
            "time_validity": self.time_validity,
            "selected_threshold": self.selected_threshold,
            "selection_status": self.selection_status,
        }


@dataclass(frozen=True)
class StageCapabilityV1:
    stage_id: str
    stage_kind: str
    supports_weight: bool
    contract_version: str = "1.0"

    def validate(self) -> None:
        _text(self.stage_id, "CLASSIFICATION_STAGE_INVALID", "stage_id")
        _text(self.stage_kind, "CLASSIFICATION_STAGE_INVALID", "stage_kind")
        if not isinstance(self.supports_weight, bool):
            raise ContractError("CLASSIFICATION_STAGE_INVALID", "supports_weight must be boolean")


def validate_weight_support(
    stages: tuple[StageCapabilityV1, ...] | list[StageCapabilityV1],
    *,
    declared_weight: str | None,
) -> None:
    if declared_weight is None:
        return
    _text(declared_weight, "CLASSIFICATION_WEIGHT_INVALID", "declared_weight")
    for stage in stages:
        stage.validate()
        if not stage.supports_weight:
            raise ContractError(
                "CLASSIFICATION_WEIGHT_UNSUPPORTED",
                f"stage {stage.stage_id!r} does not support declared weight {declared_weight!r}",
            )


@dataclass(frozen=True)
class ClassificationTaskSpecV1:
    target_column: str
    task_type: str
    class_mapping: Mapping[Any, str]
    positive_class: str | None
    feature_columns: tuple[str, ...]
    feature_availability: tuple[FeatureAvailabilityContractV1, ...]
    label_definition: LabelDefinitionV1
    structure: StructureSpecV1
    primary_metric: str
    secondary_metrics: tuple[str, ...]
    split_profile: str
    seed: int
    resource_budget: Mapping[str, Any]
    weights: str | None = None
    allow_exploration: bool = False
    task_version: str = "1.0"

    @property
    def availability_status(self) -> str:
        values = self.feature_availability
        complete = all(
            item.observed_at and item.available_at and item.prediction_origin and item.source_recipe
            and item.leakage_status == "validated"
            for item in values
        )
        return "VALIDATED" if complete else "UNKNOWN_EXPLORATION_ONLY"

    @property
    def deployment_safe(self) -> bool:
        return self.availability_status == "VALIDATED" and self.structure.kind in {"iid", "grouped", "temporal", "panel"}

    def validate(self) -> None:
        _text(self.target_column, "CLASSIFICATION_TARGET_INVALID", "target_column")
        if self.task_type not in {"binary", "multiclass"}:
            raise ContractError("CLASSIFICATION_TASK_TYPE_INVALID", "task_type must be binary or multiclass")
        if not self.feature_columns or len(set(self.feature_columns)) != len(self.feature_columns):
            raise ContractError("CLASSIFICATION_FEATURE_INVALID", "feature_columns must be unique and non-empty")
        if self.target_column in self.feature_columns:
            raise ContractError("CLASSIFICATION_TARGET_FEATURE_OVERLAP", "target column cannot be a feature")
        if not isinstance(self.class_mapping, Mapping) or len(self.class_mapping) < 2:
            raise ContractError("CLASSIFICATION_CLASS_MAPPING_INVALID", "class_mapping must contain at least two classes")
        mapped = tuple(self.class_mapping.values())
        if any(not isinstance(item, str) or not item.strip() for item in mapped) or len(set(mapped)) != len(mapped):
            raise ContractError("CLASSIFICATION_CLASS_MAPPING_INVALID", "class labels must be unique non-empty strings")
        if self.task_type == "binary":
            if len(mapped) != 2:
                raise ContractError("CLASSIFICATION_CLASS_MAPPING_INVALID", "binary tasks require exactly two classes")
            if self.positive_class is None or self.positive_class not in mapped:
                raise ContractError("CLASSIFICATION_POSITIVE_CLASS_REQUIRED", "binary tasks require a mapped positive class")
        elif self.positive_class is not None and self.positive_class not in mapped:
            raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in class_mapping")
        if len(self.feature_availability) != len(self.feature_columns):
            raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "each feature needs one availability contract")
        names = tuple(item.feature_name for item in self.feature_availability)
        if set(names) != set(self.feature_columns) or len(names) != len(set(names)):
            raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "availability contracts must cover features exactly")
        self.structure.validate()
        self.label_definition.validate(structure_kind=self.structure.kind)
        for item in self.feature_availability:
            item.validate(structure_kind=self.structure.kind, allow_exploration=self.allow_exploration)
        if self.structure.kind in {"temporal", "panel"} and self.availability_status != "VALIDATED":
            raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "temporal/panel availability is not deployment-safe")
        if self.structure.kind == "iid" and self.availability_status != "VALIDATED" and not self.allow_exploration:
            raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "unknown IID availability requires exploration mode")
        _text(self.primary_metric, "CLASSIFICATION_METRIC_INVALID", "primary_metric")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ContractError("CLASSIFICATION_SEED_INVALID", "seed must be a non-negative integer")
        if not isinstance(self.resource_budget, Mapping):
            raise ContractError("CLASSIFICATION_RESOURCE_BUDGET_INVALID", "resource_budget must be an object")

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_schema": "workbench.prediction.classification-task-spec",
            "schema_version": 1,
            "task_version": self.task_version,
            "target_column": self.target_column,
            "task_type": self.task_type,
            "class_mapping": _canonical(self.class_mapping),
            "positive_class": self.positive_class,
            "feature_columns": list(self.feature_columns),
            "feature_availability": [item.to_dict() for item in self.feature_availability],
            "label_definition": self.label_definition.to_dict(),
            "structure": self.structure.to_dict(),
            "primary_metric": self.primary_metric,
            "secondary_metrics": list(self.secondary_metrics),
            "split_profile": self.split_profile,
            "seed": self.seed,
            "resource_budget": _canonical(self.resource_budget),
            "weights": self.weights,
            "allow_exploration": self.allow_exploration,
            "availability_status": self.availability_status,
            "deployment_safe": self.deployment_safe,
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class ClassificationClarificationV1:
    """Package-local clarification record for an incomplete classification ask."""

    provider_id: str
    provider_digest: str
    contract_digests: tuple[str, ...]
    missing_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.provider_id, "CLASSIFICATION_CLARIFICATION_INVALID", "provider_id")
        if not isinstance(self.provider_digest, str) or len(self.provider_digest) != 64:
            raise ContractError("CLASSIFICATION_CLARIFICATION_INVALID", "provider_digest must be a SHA-256 digest")
        if not self.contract_digests or any(not isinstance(item, str) or len(item) != 64 for item in self.contract_digests):
            raise ContractError("CLASSIFICATION_CLARIFICATION_INVALID", "contract_digests must contain SHA-256 digests")
        if any(not isinstance(item, str) or not item.strip() for item in self.missing_fields):
            raise ContractError("CLASSIFICATION_CLARIFICATION_INVALID", "missing_fields must contain non-empty names")

    @property
    def status(self) -> str:
        return "clarification_required" if self.missing_fields else "ready_for_compile"

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "provider_id": self.provider_id,
            "provider_digest": self.provider_digest,
            "contract_digests": list(self.contract_digests),
            "missing_fields": list(self.missing_fields),
        }


_CLARIFICATION_FIELDS = (
    "target",
    "positive_class",
    "time_horizon",
    "availability",
    "primary_metric",
    "cost_policy",
)


def build_classification_clarification(
    request: Mapping[str, Any],
    *,
    provider_id: str,
    provider_digest: str,
    contract_digests: tuple[str, ...],
) -> ClassificationClarificationV1:
    """Return a typed missing-information record without choosing defaults."""

    if not isinstance(request, Mapping):
        raise ContractError("CLASSIFICATION_CLARIFICATION_INVALID", "request must be an object")

    def missing(value: Any) -> bool:
        return value is None or (isinstance(value, str) and not value.strip()) or (
            isinstance(value, (Mapping, list, tuple)) and not value
        )

    return ClassificationClarificationV1(
        provider_id=provider_id,
        provider_digest=provider_digest,
        contract_digests=tuple(contract_digests),
        missing_fields=tuple(field for field in _CLARIFICATION_FIELDS if missing(request.get(field))),
    )


__all__ = [
    "ClassificationClarificationV1",
    "ClassificationTaskSpecV1",
    "DecisionPolicyV1",
    "FeatureAvailabilityContractV1",
    "LabelDefinitionV1",
    "StageCapabilityV1",
    "validate_weight_support",
    "build_classification_clarification",
]
