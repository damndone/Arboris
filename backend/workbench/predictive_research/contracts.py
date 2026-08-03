"""Typed, deterministic contracts shared by predictive-research consumers."""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
from typing import Any, Mapping


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _canonical(value[key]) for key in sorted(value, key=str)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite values are not allowed in predictive contracts")
        return value
    return value


class ContractError(ValueError):
    """A stable, user-actionable predictive-research contract failure."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _require_text(value: Any, code: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContractError(code, f"{label} must be a non-empty string")
    return value


@dataclass(frozen=True)
class SamplingSpecV1:
    sampling_weight: str | None = None
    analysis_weight: str | None = None
    frequency_weight: str | None = None
    semantics_version: int = 1

    def validate(self) -> None:
        if self.semantics_version != 1:
            raise ContractError("PREDICTION_WEIGHT_SEMANTICS_UNSUPPORTED", "unknown weight semantics version")
        fields = {
            "sampling_weight": self.sampling_weight,
            "analysis_weight": self.analysis_weight,
            "frequency_weight": self.frequency_weight,
        }
        for label, value in fields.items():
            if value is not None:
                _require_text(value, "PREDICTION_WEIGHT_INVALID", label)
        declared = [value for value in fields.values() if value is not None]
        if len(declared) != len(set(declared)):
            raise ContractError(
                "PREDICTION_WEIGHT_SEMANTICS_CONFLICT",
                "sampling, analysis, and frequency weights must remain distinct",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "sampling_weight": self.sampling_weight,
            "analysis_weight": self.analysis_weight,
            "frequency_weight": self.frequency_weight,
            "semantics_version": self.semantics_version,
        }


@dataclass(frozen=True)
class StructureSpecV1:
    kind: str = "unknown"
    group_column: str | None = None
    time_column: str | None = None
    entity_column: str | None = None
    provenance: str = "user_confirmed"

    def validate(self) -> None:
        if self.kind not in {"unknown", "iid", "grouped", "temporal", "panel"}:
            raise ContractError("PREDICTION_DATA_STRUCTURE_INVALID", "unknown data structure kind")
        if self.kind == "unknown":
            raise ContractError("PREDICTION_DATA_STRUCTURE_UNKNOWN", "data structure must be explicitly declared")
        if self.provenance != "user_confirmed":
            raise ContractError(
                "PREDICTION_DATA_STRUCTURE_NOT_CONFIRMED",
                "data structure inference cannot authorize a prediction split",
            )
        if self.kind == "grouped" and not self.group_column:
            raise ContractError("PREDICTION_GROUP_COLUMN_REQUIRED", "grouped structure requires a group column")
        if self.kind == "temporal" and not self.time_column:
            raise ContractError("PREDICTION_TIME_COLUMN_REQUIRED", "temporal structure requires a time column")
        if self.kind == "panel" and (not self.entity_column or not self.time_column):
            raise ContractError("PREDICTION_PANEL_KEYS_REQUIRED", "panel structure requires entity and time columns")

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "group_column": self.group_column,
            "time_column": self.time_column,
            "entity_column": self.entity_column,
            "provenance": self.provenance,
        }


@dataclass(frozen=True)
class AvailabilitySpecV1:
    kind: str = "unspecified"
    feature_available_at: str | None = None
    label_available_at: str | None = None
    reservation_policy: str = "fail_closed"
    validation_status: str = "unverified"

    def validate(self) -> None:
        if self.kind not in {"declared", "unspecified", "validated"}:
            raise ContractError("PREDICTION_AVAILABILITY_INVALID", "unknown availability kind")
        if self.reservation_policy != "fail_closed":
            raise ContractError(
                "PREDICTION_AVAILABILITY_POLICY_INVALID",
                "availability reservation must be fail_closed",
            )
        if self.kind == "unspecified":
            raise ContractError(
                "PREDICTION_AVAILABILITY_UNSPECIFIED",
                "feature and label availability must be declared before fitting",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "feature_available_at": self.feature_available_at,
            "label_available_at": self.label_available_at,
            "reservation_policy": self.reservation_policy,
            "validation_status": self.validation_status,
        }


@dataclass(frozen=True)
class SplitPlanV1:
    strategy: str
    profile_id: str
    profile_version: int
    effective_parameters: Mapping[str, Any] = field(default_factory=dict)

    def validate(self, executable_profiles: set[str] | frozenset[str] | None = None) -> None:
        if self.strategy not in {"iid", "random", "grouped", "temporal", "panel"}:
            raise ContractError("PREDICTION_SPLIT_STRATEGY_INVALID", "unknown split strategy")
        _require_text(self.profile_id, "PREDICTION_SPLIT_PROFILE_INVALID", "profile_id")
        if not isinstance(self.profile_version, int) or self.profile_version < 1:
            raise ContractError("PREDICTION_SPLIT_PROFILE_INVALID", "profile_version must be positive")
        if not isinstance(self.effective_parameters, Mapping):
            raise ContractError("PREDICTION_SPLIT_PARAMETERS_INVALID", "effective split parameters must be an object")
        try:
            _canonical(self.effective_parameters)
        except ValueError as error:
            raise ContractError("PREDICTION_SPLIT_PARAMETERS_INVALID", str(error)) from error
        if executable_profiles is not None and self.profile_id not in executable_profiles:
            raise ContractError(
                "PREDICTION_SPLIT_PROFILE_NOT_SUPPORTED",
                f"split profile {self.profile_id!r} is not executable in this release",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "profile_id": self.profile_id,
            "profile_version": self.profile_version,
            "effective_parameters": _canonical(self.effective_parameters),
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class FeatureRecipeV1:
    recipe_id: str
    operation_id: str
    operation_version: int
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    output_types: tuple[str, ...]
    parameters: Mapping[str, Any]
    fit_scope: str
    source_artifact: str
    lineage_parent: str | None = None
    missing_policy: str = "fail_closed"
    outlier_policy: str = "preserve"

    ALLOWED_OPERATIONS = frozenset({"derived_variable", "recode", "interaction", "log", "ratio"})

    def validate(self) -> None:
        if self.operation_id not in self.ALLOWED_OPERATIONS:
            raise ContractError(
                "PREDICTION_FEATURE_RECIPE_UNKNOWN_OPERATION",
                f"feature operation {self.operation_id!r} is not registered",
            )
        if self.operation_version != 1:
            raise ContractError("PREDICTION_FEATURE_RECIPE_VERSION_UNSUPPORTED", "unknown feature operation version")
        if not self.inputs or not self.outputs or len(self.outputs) != len(self.output_types):
            raise ContractError("PREDICTION_FEATURE_RECIPE_SHAPE_INVALID", "recipe inputs and typed outputs are required")
        if self.fit_scope not in {"stateless", "date_local", "period_fitted"}:
            raise ContractError("PREDICTION_FEATURE_RECIPE_FIT_SCOPE_INVALID", "unknown recipe fit scope")
        _require_text(self.source_artifact, "PREDICTION_FEATURE_RECIPE_SOURCE_REQUIRED", "source_artifact")
        if self.missing_policy == "silent" or self.outlier_policy == "silent":
            raise ContractError("PREDICTION_FEATURE_RECIPE_POLICY_INVALID", "missing/outlier behavior cannot be silent")

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_schema": "workbench.prediction.feature-recipe",
            "schema_version": 1,
            "recipe_id": self.recipe_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "output_types": list(self.output_types),
            "parameters": _canonical(self.parameters),
            "fit_scope": self.fit_scope,
            "source_artifact": self.source_artifact,
            "lineage_parent": self.lineage_parent,
            "missing_policy": self.missing_policy,
            "outlier_policy": self.outlier_policy,
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(_canonical(self.to_dict()), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class SampleSpecV1:
    dataset_sha256: str
    sampling: SamplingSpecV1
    split_plan: SplitPlanV1
    structure: StructureSpecV1
    availability: AvailabilitySpecV1
    row_identity: str = "snapshot_ordinal_v1"
    feature_recipe_ref: str | None = None
    split_plan_ref: str | None = None

    def validate(self, executable_profiles: set[str] | frozenset[str] | None = None) -> None:
        if len(self.dataset_sha256) != 64 or any(char not in "0123456789abcdef" for char in self.dataset_sha256):
            raise ContractError("PREDICTION_DATASET_REF_INVALID", "dataset_sha256 must be lowercase hexadecimal")
        if self.row_identity != "snapshot_ordinal_v1":
            raise ContractError("PREDICTION_ROW_IDENTITY_UNSUPPORTED", "unknown row identity policy")
        self.sampling.validate()
        self.structure.validate()
        self.availability.validate()
        self.split_plan.validate(executable_profiles=executable_profiles)
        if self.structure.kind == "grouped" and self.split_plan.strategy != "grouped":
            raise ContractError("PREDICTION_SPLIT_STRUCTURE_MISMATCH", "grouped data requires a grouped split strategy")
        if self.structure.kind in {"temporal", "panel"} and self.split_plan.strategy not in {"temporal", "panel"}:
            raise ContractError("PREDICTION_SPLIT_STRUCTURE_MISMATCH", "temporal/panel data cannot use a random split")

    def to_dict(self) -> dict[str, Any]:
        return {
            "payload_schema": "workbench.prediction.sample-spec",
            "schema_version": 1,
            "dataset_ref": {"dataset_sha256": self.dataset_sha256, "row_identity": self.row_identity},
            "sampling": self.sampling.to_dict(),
            "split_plan": self.split_plan.to_dict(),
            "structure": self.structure.to_dict(),
            "availability": self.availability.to_dict(),
            "feature_recipe_ref": self.feature_recipe_ref,
            "split_plan_ref": self.split_plan_ref,
        }

    @property
    def content_hash(self) -> str:
        encoded = json.dumps(_canonical(self.to_dict()), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @property
    def transformation_hash(self) -> str:
        """Identity for the data-transformation layer, independent of splitting."""

        payload = {
            "payload_schema": "workbench.prediction.sample-transformation-identity",
            "schema_version": 1,
            "dataset_ref": {"dataset_sha256": self.dataset_sha256, "row_identity": self.row_identity},
            "sampling": self.sampling.to_dict(),
            "structure": self.structure.to_dict(),
            "availability": self.availability.to_dict(),
            "feature_recipe_ref": self.feature_recipe_ref,
        }
        encoded = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()

    @property
    def evaluation_hash(self) -> str:
        """Identity for evaluation, which must change with the effective split plan."""

        payload = {
            "payload_schema": "workbench.prediction.evaluation-identity",
            "schema_version": 1,
            "transformation_hash": self.transformation_hash,
            "split_plan": self.split_plan.to_dict(),
            "split_plan_ref": self.split_plan_ref,
        }
        encoded = json.dumps(_canonical(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return "sha256:" + hashlib.sha256(encoded).hexdigest()
