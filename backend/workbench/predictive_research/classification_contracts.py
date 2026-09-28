"""Typed, fail-closed contracts for the v1.8.9 classification kernel.

The classification line deliberately keeps task facts separate from estimator
implementation.  In particular, availability, label timing, weights and
decision costs are declarations that must be validated; they are never
inferred from a dataframe or silently defaulted.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping, Sequence

from .contracts import ContractError, StructureSpecV1


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in sorted(value, key=lambda item: str(item)):
            canonical_key = str(key)
            if canonical_key in result:
                raise ContractError(
                    "CLASSIFICATION_CONTRACT_INVALID",
                    "mapping keys collide after canonical serialization",
                )
            result[canonical_key] = _canonical(value[key])
        return result
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractError("CLASSIFICATION_CONTRACT_INVALID", "non-finite values are not allowed")
    return value


def _text(value: Any, code: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(code, f"{label} must be a non-empty string")
    return value


def _hash_payload(payload: Any) -> str:
    encoded = json.dumps(
        _canonical(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FeatureAvailabilityContractV1:
    """The declared information-set binding for one feature."""

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

        fields = (self.observed_at, self.available_at, self.prediction_origin, self.source_recipe)
        if structure_kind in {"temporal", "panel"}:
            if any(not isinstance(value, str) or not value.strip() for value in fields):
                raise ContractError(
                    "CLASSIFICATION_INFORMATION_SET_INCOMPLETE",
                    f"{self.feature_name} lacks an information-set binding",
                )
            if self.leakage_status != "validated":
                raise ContractError(
                    "CLASSIFICATION_INFORMATION_SET_INCOMPLETE",
                    f"{self.feature_name} availability is not validated",
                )
            return

        # IID/group exploration may carry an intentionally unknown information
        # set, but it is never deployment-safe.  Partial declarations remain a
        # contract error rather than being upgraded to validated.
        present = [value is not None for value in fields]
        if any(present) and not all(present) and not allow_exploration:
            raise ContractError(
                "CLASSIFICATION_INFORMATION_SET_INCOMPLETE",
                f"{self.feature_name} availability is only partially declared",
            )
        if not allow_exploration and (not all(present) or self.leakage_status != "validated"):
            raise ContractError(
                "CLASSIFICATION_INFORMATION_SET_INCOMPLETE",
                f"{self.feature_name} availability is not deployment-safe",
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
    """How a target was constructed and when its information becomes known."""

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
                raise ContractError(
                    "CLASSIFICATION_LABEL_TIME_REQUIRED",
                    "temporal/panel labels require event time and horizon",
                )
        if self.purge_gap is not None and (
            not isinstance(self.purge_gap, str) or not self.purge_gap.strip()
        ):
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
class ClassificationSplitSpecV1:
    """Typed executable split parameters; no implicit random fallback exists."""

    profile: str
    final_holdout_fraction: float
    cv_folds: int
    random_seed: int
    purge_gap: Any | None = None
    embargo: Any | None = None
    embargo_basis: str | None = None

    ALLOWED_PROFILES = frozenset(
        {
            "iid_stratified",
            "group_holdout",
            "temporal_rolling",
            "panel_known_entity_future",
            "panel_new_entity",
        }
    )

    def validate(self) -> None:
        if self.profile not in self.ALLOWED_PROFILES:
            raise ContractError("CLASSIFICATION_SPLIT_PROFILE_INVALID", f"unknown profile {self.profile!r}")
        if not isinstance(self.final_holdout_fraction, (int, float)) or isinstance(
            self.final_holdout_fraction, bool
        ) or not 0 < float(self.final_holdout_fraction) < 1:
            raise ContractError("CLASSIFICATION_SPLIT_PARAMETERS_INVALID", "holdout fraction must be between zero and one")
        if not isinstance(self.cv_folds, int) or isinstance(self.cv_folds, bool) or self.cv_folds < 2:
            raise ContractError("CLASSIFICATION_SPLIT_PARAMETERS_INVALID", "cv_folds must be at least two")
        if not isinstance(self.random_seed, int) or isinstance(self.random_seed, bool) or self.random_seed < 0:
            raise ContractError("CLASSIFICATION_SEED_INVALID", "random_seed must be a non-negative integer")
        if self.embargo is not None and not isinstance(self.embargo_basis, str):
            raise ContractError("CLASSIFICATION_EMBARGO_BASIS_REQUIRED", "embargo requires an explicit basis")
        if self.embargo_basis is not None and not self.embargo_basis.strip():
            raise ContractError("CLASSIFICATION_EMBARGO_BASIS_REQUIRED", "embargo basis must be non-empty")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "profile": self.profile,
            "profile_version": 1,
            "final_holdout_fraction": self.final_holdout_fraction,
            "cv_folds": self.cv_folds,
            "random_seed": self.random_seed,
            "purge_gap": self.purge_gap,
            "embargo": self.embargo,
            "embargo_basis": self.embargo_basis,
        }

    @property
    def content_hash(self) -> str:
        return _hash_payload(self.to_dict())


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
    capacity_unit: str = "rate"

    @property
    def has_known_costs(self) -> bool:
        return isinstance(self.cost_matrix, Mapping) and bool(self.cost_matrix)

    @property
    def selection_status(self) -> str:
        return "SELECTABLE" if self.has_known_costs and self.capacity is not None else "SCENARIOS_ONLY"

    def validate(self) -> None:
        for value, label in (
            (self.threshold_scope, "threshold_scope"),
            (self.threshold_method, "threshold_method"),
            (self.policy_version, "policy_version"),
            (self.population, "population"),
            (self.time_validity, "time_validity"),
        ):
            _text(value, "CLASSIFICATION_POLICY_INVALID", label)
        if not isinstance(self.abstain_allowed, bool) or not isinstance(self.manual_review_allowed, bool):
            raise ContractError("CLASSIFICATION_POLICY_INVALID", "abstain/manual-review flags must be booleans")
        if self.capacity_unit not in {"rate", "count"}:
            raise ContractError(
                "CLASSIFICATION_POLICY_CAPACITY_INVALID",
                "capacity_unit must be either rate or count",
            )
        if self.capacity is not None:
            if isinstance(self.capacity, bool) or not isinstance(self.capacity, (int, float)):
                raise ContractError("CLASSIFICATION_POLICY_INVALID", "capacity must be numeric")
            if not math.isfinite(float(self.capacity)) or self.capacity < 0:
                raise ContractError("CLASSIFICATION_POLICY_INVALID", "capacity must be finite and non-negative")
        if self.cost_matrix is not None:
            if not isinstance(self.cost_matrix, Mapping):
                raise ContractError("CLASSIFICATION_POLICY_COSTS_INVALID", "cost_matrix must be an object")
            try:
                canonical_costs = _canonical(self.cost_matrix)
            except ContractError as exc:
                raise ContractError("CLASSIFICATION_POLICY_COSTS_INVALID", str(exc)) from exc
            if not isinstance(canonical_costs, Mapping):
                raise ContractError("CLASSIFICATION_POLICY_COSTS_INVALID", "cost_matrix must be an object")
            for name, value in canonical_costs.items():
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                    raise ContractError(
                        "CLASSIFICATION_POLICY_COSTS_INVALID",
                        f"cost_matrix entry {name!r} must be finite numeric",
                    )
            if self.threshold_method == "expected_utility" and canonical_costs:
                missing = {"false_positive", "false_negative"} - set(canonical_costs)
                if missing:
                    raise ContractError(
                        "CLASSIFICATION_POLICY_COSTS_INVALID",
                        "expected_utility requires false_positive and false_negative costs",
                    )
        if self.selected_threshold is not None:
            if not isinstance(self.selected_threshold, (int, float)) or isinstance(self.selected_threshold, bool):
                raise ContractError("CLASSIFICATION_THRESHOLD_INVALID", "selected threshold must be numeric")
            if not math.isfinite(float(self.selected_threshold)) or not 0 <= self.selected_threshold <= 1:
                raise ContractError("CLASSIFICATION_THRESHOLD_INVALID", "selected threshold must be in [0, 1]")
        if self.selection_status == "SCENARIOS_ONLY" and self.selected_threshold is not None:
            raise ContractError(
                "CLASSIFICATION_POLICY_COSTS_REQUIRED",
                "unknown costs/capacity cannot produce a selected threshold",
            )
        if self.threshold_method == "fixed" and self.selection_status == "SELECTABLE" and self.selected_threshold is None:
            raise ContractError(
                "CLASSIFICATION_POLICY_INVALID",
                "fixed threshold policy must declare selected_threshold",
            )

    def to_dict(self) -> dict[str, Any]:
        self.validate()
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
            "capacity_unit": self.capacity_unit,
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
        _text(self.contract_version, "CLASSIFICATION_STAGE_INVALID", "contract_version")
        if not isinstance(self.supports_weight, bool):
            raise ContractError("CLASSIFICATION_STAGE_INVALID", "supports_weight must be boolean")


@dataclass(frozen=True)
class ClassificationPreprocessingStepV1:
    """A declared preprocessing stage; learned state is produced per fold."""

    step_id: str
    kind: str
    columns: tuple[str, ...]
    supports_weight: bool
    seed: int = 0
    recipe_version: str = "1.0"
    recipe: str | Mapping[str, Any] | None = None

    def validate(self) -> None:
        _text(self.step_id, "CLASSIFICATION_PREPROCESSING_CONTRACT_INVALID", "step_id")
        _text(self.kind, "CLASSIFICATION_PREPROCESSING_CONTRACT_INVALID", "kind")
        if not self.columns or any(not isinstance(column, str) or not column.strip() for column in self.columns):
            raise ContractError("CLASSIFICATION_PREPROCESSING_CONTRACT_INVALID", "columns are required")
        if len(set(self.columns)) != len(self.columns):
            raise ContractError("CLASSIFICATION_PREPROCESSING_CONTRACT_INVALID", "columns must be unique")
        if not isinstance(self.supports_weight, bool):
            raise ContractError("CLASSIFICATION_PREPROCESSING_CONTRACT_INVALID", "supports_weight must be boolean")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ContractError("CLASSIFICATION_PREPROCESSING_CONTRACT_INVALID", "seed must be non-negative")
        _text(self.recipe_version, "CLASSIFICATION_PREPROCESSING_CONTRACT_INVALID", "recipe_version")
        if self.recipe is not None and not isinstance(self.recipe, (str, Mapping)):
            raise ContractError("CLASSIFICATION_PREPROCESSING_RECIPE_INVALID", "recipe must be text or an object")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "step_id": self.step_id,
            "kind": self.kind,
            "columns": list(self.columns),
            "supports_weight": self.supports_weight,
            "seed": self.seed,
            "recipe_version": self.recipe_version,
            "recipe": _canonical(self.recipe) if self.recipe is not None else None,
        }


def validate_weight_support(
    stages: tuple[StageCapabilityV1, ...] | list[StageCapabilityV1],
    *,
    declared_weight: str | None,
) -> None:
    """Reject a weighted task when any learned stage would ignore its weight."""

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
        complete = bool(self.feature_availability) and all(
            isinstance(item.observed_at, str)
            and bool(item.observed_at.strip())
            and isinstance(item.available_at, str)
            and bool(item.available_at.strip())
            and isinstance(item.prediction_origin, str)
            and bool(item.prediction_origin.strip())
            and isinstance(item.source_recipe, str)
            and bool(item.source_recipe.strip())
            and item.leakage_status == "validated"
            for item in self.feature_availability
        )
        return "VALIDATED" if complete else "UNKNOWN_EXPLORATION_ONLY"

    @property
    def deployment_safe(self) -> bool:
        return self.availability_status == "VALIDATED" and self.structure.kind in {
            "iid",
            "grouped",
            "temporal",
            "panel",
        }

    def validate(self) -> None:
        _text(self.target_column, "CLASSIFICATION_TARGET_INVALID", "target_column")
        if self.task_type not in {"binary", "multiclass"}:
            raise ContractError("CLASSIFICATION_TASK_TYPE_INVALID", "task_type must be binary or multiclass")
        if not self.feature_columns or any(not isinstance(column, str) or not column.strip() for column in self.feature_columns):
            raise ContractError("CLASSIFICATION_FEATURE_INVALID", "feature_columns must be non-empty text")
        if len(set(self.feature_columns)) != len(self.feature_columns):
            raise ContractError("CLASSIFICATION_FEATURE_INVALID", "feature_columns must be unique")
        if self.target_column in self.feature_columns:
            raise ContractError("CLASSIFICATION_TARGET_FEATURE_OVERLAP", "target column cannot be a feature")
        if not isinstance(self.class_mapping, Mapping) or len(self.class_mapping) < 2:
            raise ContractError("CLASSIFICATION_CLASS_MAPPING_INVALID", "class_mapping must contain at least two classes")
        if len({str(key) for key in self.class_mapping}) != len(self.class_mapping):
            raise ContractError("CLASSIFICATION_CLASS_MAPPING_INVALID", "class mapping keys must be canonicalizable uniquely")
        mapped = tuple(self.class_mapping.values())
        if any(not isinstance(item, str) or not item.strip() for item in mapped) or len(set(mapped)) != len(mapped):
            raise ContractError("CLASSIFICATION_CLASS_MAPPING_INVALID", "class labels must be unique non-empty strings")
        if self.task_type == "binary":
            if len(mapped) != 2:
                raise ContractError("CLASSIFICATION_CLASS_MAPPING_INVALID", "binary tasks require exactly two classes")
            if self.positive_class is None:
                raise ContractError("CLASSIFICATION_POSITIVE_CLASS_REQUIRED", "binary tasks require a positive class")
            if self.positive_class not in mapped:
                raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in class_mapping")
        elif self.positive_class is not None and self.positive_class not in mapped:
            raise ContractError("CLASSIFICATION_POSITIVE_CLASS_INVALID", "positive class is not in class_mapping")
        if len(self.feature_availability) != len(self.feature_columns):
            raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "each feature needs one availability contract")
        if any(not isinstance(item, FeatureAvailabilityContractV1) for item in self.feature_availability):
            raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "availability contracts are typed")
        names = tuple(item.feature_name for item in self.feature_availability)
        if set(names) != set(self.feature_columns) or len(names) != len(set(names)):
            raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "availability contracts must cover features exactly")
        if not isinstance(self.structure, StructureSpecV1):
            raise ContractError("CLASSIFICATION_DATA_STRUCTURE_INVALID", "structure must be a typed StructureSpecV1")
        self.structure.validate()
        self.label_definition.validate(structure_kind=self.structure.kind)
        for item in self.feature_availability:
            item.validate(structure_kind=self.structure.kind, allow_exploration=self.allow_exploration)
        if self.structure.kind in {"temporal", "panel"} and self.availability_status != "VALIDATED":
            raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "temporal/panel availability is not deployment-safe")
        if self.availability_status != "VALIDATED" and not self.allow_exploration:
            raise ContractError("CLASSIFICATION_INFORMATION_SET_INCOMPLETE", "unknown availability requires exploration mode")
        _text(self.primary_metric, "CLASSIFICATION_METRIC_INVALID", "primary_metric")
        if any(not isinstance(metric, str) or not metric.strip() for metric in self.secondary_metrics):
            raise ContractError("CLASSIFICATION_METRIC_INVALID", "secondary metrics must be non-empty text")
        _text(self.split_profile, "CLASSIFICATION_SPLIT_PROFILE_INVALID", "split_profile")
        expected_profiles = {
            "iid": {"iid_stratified"},
            "grouped": {"group_holdout"},
            "temporal": {"temporal_rolling"},
            "panel": {"panel_known_entity_future", "panel_new_entity"},
        }
        if self.split_profile not in expected_profiles.get(self.structure.kind, set()):
            raise ContractError("CLASSIFICATION_SPLIT_STRUCTURE_MISMATCH", "split profile does not match data structure")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool) or self.seed < 0:
            raise ContractError("CLASSIFICATION_SEED_INVALID", "seed must be a non-negative integer")
        if not isinstance(self.resource_budget, Mapping):
            raise ContractError("CLASSIFICATION_RESOURCE_BUDGET_INVALID", "resource_budget must be an object")
        _canonical(self.resource_budget)
        if self.weights is not None:
            _text(self.weights, "CLASSIFICATION_WEIGHT_INVALID", "weights")
        if not isinstance(self.allow_exploration, bool):
            raise ContractError("CLASSIFICATION_CONTRACT_INVALID", "allow_exploration must be boolean")
        _text(self.task_version, "CLASSIFICATION_CONTRACT_INVALID", "task_version")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
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
        return _hash_payload(self.to_dict())


@dataclass(frozen=True)
class ClassificationDiagnosticsPlanV1:
    """Predeclared descriptive subgroup/shift facts for one holdout release."""

    subgroup_columns: tuple[str, ...] = ()
    shift_columns: tuple[str, ...] = ()
    minimum_support: int = 20
    bins: int = 10
    statistics: tuple[str, ...] = ("mean", "distribution")
    multiplicity_policy: str = "descriptive_no_adjustment"
    plan_version: str = "1.0"

    def __post_init__(self) -> None:
        for field_name in ("subgroup_columns", "shift_columns", "statistics"):
            value = getattr(self, field_name)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                object.__setattr__(self, field_name, tuple(value))

    def validate(self) -> None:
        for values, label in (
            (self.subgroup_columns, "subgroup_columns"),
            (self.shift_columns, "shift_columns"),
        ):
            if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
                raise ContractError("CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID", f"{label} must be a sequence")
            if any(not isinstance(value, str) or not value.strip() for value in values):
                raise ContractError("CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID", f"{label} must contain non-empty strings")
            if len(set(values)) != len(values):
                raise ContractError("CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID", f"{label} must be unique")
        if not isinstance(self.minimum_support, int) or isinstance(self.minimum_support, bool) or self.minimum_support < 2:
            raise ContractError("CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID", "minimum_support must be at least two")
        if not isinstance(self.bins, int) or isinstance(self.bins, bool) or not 1 <= self.bins <= 100:
            raise ContractError("CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID", "bins must be an integer in [1, 100]")
        if (
            isinstance(self.statistics, (str, bytes))
            or not isinstance(self.statistics, Sequence)
            or not self.statistics
            or any(
                not isinstance(statistic, str) or statistic not in {"mean", "distribution"}
                for statistic in self.statistics
            )
            or len(set(self.statistics)) != len(self.statistics)
        ):
            raise ContractError(
                "CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID",
                "statistics must be a unique non-empty subset of mean and distribution",
            )
        _text(self.multiplicity_policy, "CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID", "multiplicity_policy")
        if self.multiplicity_policy not in {"descriptive_no_adjustment"}:
            raise ContractError(
                "CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID",
                "unsupported multiplicity policy would overstate diagnostic evidence",
            )
        _text(self.plan_version, "CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID", "plan_version")

    def to_dict(self) -> dict[str, Any]:
        self.validate()
        return {
            "payload_schema": "workbench.classification.diagnostics-plan",
            "schema_version": 1,
            "plan_version": self.plan_version,
            "subgroup_columns": list(self.subgroup_columns),
            "shift_columns": list(self.shift_columns),
            "minimum_support": self.minimum_support,
            "bins": self.bins,
            "statistics": list(self.statistics),
            "multiplicity_policy": self.multiplicity_policy,
        }

    @property
    def content_hash(self) -> str:
        return _hash_payload(self.to_dict())


# Short aliases make the public seam easier to extend without duplicating
# contracts or creating family-specific compiler branches.
FeatureAvailabilityV1 = FeatureAvailabilityContractV1
ClassificationSplitProfileV1 = ClassificationSplitSpecV1


__all__ = [
    "ClassificationPreprocessingStepV1",
    "ClassificationSplitProfileV1",
    "ClassificationSplitSpecV1",
    "ClassificationTaskSpecV1",
    "ClassificationDiagnosticsPlanV1",
    "DecisionPolicyV1",
    "FeatureAvailabilityContractV1",
    "FeatureAvailabilityV1",
    "LabelDefinitionV1",
    "StageCapabilityV1",
    "StructureSpecV1",
    "validate_weight_support",
]
