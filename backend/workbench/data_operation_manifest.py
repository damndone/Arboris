"""Closed, declaration-only manifest for the v1 data-operation surface."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import importlib.util
import json
import re
from types import MappingProxyType
from typing import Any, Mapping

from workbench.agent.operations import OperationRecord, OperationRegistry
from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
from workbench.canonical import sha256_canonical
from workbench.contracts.agent.planning import (
    DraftAgentPlanV1,
    PlanEffectV1,
    PlanRiskLevelV1,
)
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.provider import (
    AdapterDeclarationV1,
    ExposurePathRefV1,
    ProviderContributionV1,
    is_opaque_executor_ref,
)


DATA_OPERATION_MANIFEST_VERSION = "data-operation-manifest.v1"
_DATA_OPERATION_IDS = (
    "data.aggregate",
    "data.append",
    "data.column.cast",
    "data.columns.cast",
    "data.feature_recipe",
    "data.merge",
    "data.metadata.update",
    "data.recode",
    "data.rename",
    "data.reshape",
    "data.sort",
    "data.split",
    "data.subset",
)
_LOCAL_OPERATION_IDS = frozenset(
    {"data.metadata.update", "data.sort", "data.split", "data.recode", "data.rename"}
)
_NATIVE_INTERCHANGE_IDS = ("data.interchange.sav", "data.interchange.zsav", "data.interchange.dta")
_METADATA_LOSS_UNAVAILABLE_ID = "data.metadata.loss"
_IDENTITY_FIELDS = ("source_run_id", "source_node_id", "source_artifact_id")
_SECONDARY_IDENTITY_FIELDS = (
    "secondary_run_id",
    "secondary_node_id",
    "secondary_artifact_id",
)
_DERIVED_IDENTITY_FIELDS = (
    "source_run_id",
    "child_node_id",
    "artifact_id",
    "recipe_artifact_id",
    "execution_key",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SERVER_OWNED_CAPABILITY = object()


def _registered_data_consumer_executor(
    record: OperationRecord, outputs: object
) -> object:
    return outputs


SERVER_OWNED_EXECUTOR_REGISTRY: dict[str, object] = {
    "executor:workbench.data_consumer.adapter": _registered_data_consumer_executor,
}
_OPERATION_ROUTES = {
    "data.aggregate": ("/data-operations/transform/preview", "/data-operations/transform/confirm"),
    "data.append": ("/data-operations/transform/preview", "/data-operations/transform/confirm"),
    "data.column.cast": ("/data-operations/column-cast/preview", "/data-operations/column-cast/confirm"),
    "data.columns.cast": ("/data-operations/columns-cast/preview", "/data-operations/columns-cast/confirm"),
    "data.feature_recipe": ("/data-operations/feature-recipe/preview", "/data-operations/feature-recipe/confirm"),
    "data.merge": ("/data-operations/transform/preview", "/data-operations/transform/confirm"),
    "data.metadata.update": ("/data-operations/metadata/preview", "/data-operations/metadata/confirm"),
    "data.recode": ("/data-operations/transform/preview", "/data-operations/transform/confirm"),
    "data.rename": ("/data-operations/transform/preview", "/data-operations/transform/confirm"),
    "data.reshape": ("/data-operations/transform/preview", "/data-operations/transform/confirm"),
    "data.sort": ("/data-operations/transform/preview", "/data-operations/transform/confirm"),
    "data.split": ("/data-operations/transform/preview", "/data-operations/transform/confirm"),
    "data.subset": ("/data-operations/transform/preview", "/data-operations/transform/confirm"),
}


class _FrozenList(tuple):
    """Tuple-backed JSON list that retains list equality for schema reuse."""

    def __eq__(self, other: object) -> bool:
        if isinstance(other, (list, tuple)):
            return tuple.__eq__(self, tuple(other))
        return NotImplemented


def _freeze(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int, float}:
        return value
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if type(value) in {list, tuple}:
        return _FrozenList(_freeze(item) for item in value)
    raise TypeError(f"unsupported manifest value: {type(value).__name__}")


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _text_tuple(value: object, name: str, *, required: bool = False) -> tuple[str, ...]:
    if type(value) not in {list, tuple}:
        raise ValueError(f"{name} must be a sequence")
    result = tuple(_text(item, f"{name}[]") for item in value)
    if required and not result:
        raise ValueError(f"{name} must not be empty")
    if len(set(result)) != len(result):
        raise ValueError(f"{name} must not contain duplicates")
    return result


@dataclass(frozen=True)
class DataPortV1:
    name: str
    port_type: str
    dataset_kind: str | None
    cardinality: str
    required: bool
    identity_fields: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.name, "name")
        if self.port_type not in {"dataset", "operation_record", "evidence"}:
            raise ValueError("port_type is not closed")
        if self.dataset_kind is not None:
            _text(self.dataset_kind, "dataset_kind")
        if self.cardinality not in {"one", "many"}:
            raise ValueError("cardinality is not closed")
        if type(self.required) is not bool:
            raise ValueError("required must be boolean")
        object.__setattr__(self, "identity_fields", _text_tuple(self.identity_fields, "identity_fields"))

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "port_type": self.port_type,
            "dataset_kind": self.dataset_kind,
            "cardinality": self.cardinality,
            "required": self.required,
            "identity_fields": list(self.identity_fields),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DataPortV1":
        fields = {"name", "port_type", "dataset_kind", "cardinality", "required", "identity_fields"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("data port fields are not exact")
        return cls(
            name=value["name"],  # type: ignore[arg-type]
            port_type=value["port_type"],  # type: ignore[arg-type]
            dataset_kind=value["dataset_kind"],  # type: ignore[arg-type]
            cardinality=value["cardinality"],  # type: ignore[arg-type]
            required=value["required"],  # type: ignore[arg-type]
            identity_fields=_text_tuple(value["identity_fields"], "identity_fields"),
        )


@dataclass(frozen=True)
class ReplayContractV1:
    recipe_kind: str
    request_identity_fields: tuple[str, ...]
    source_fingerprint_field: str
    request_digest_field: str = "request_sha256"

    def __post_init__(self) -> None:
        _text(self.recipe_kind, "recipe_kind")
        object.__setattr__(
            self,
            "request_identity_fields",
            _text_tuple(self.request_identity_fields, "request_identity_fields", required=True),
        )
        _text(self.source_fingerprint_field, "source_fingerprint_field")
        _text(self.request_digest_field, "request_digest_field")

    def to_dict(self) -> dict[str, object]:
        return {
            "recipe_kind": self.recipe_kind,
            "request_identity_fields": list(self.request_identity_fields),
            "source_fingerprint_field": self.source_fingerprint_field,
            "request_digest_field": self.request_digest_field,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "ReplayContractV1":
        fields = {
            "recipe_kind",
            "request_identity_fields",
            "source_fingerprint_field",
            "request_digest_field",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("replay contract fields are not exact")
        return cls(
            recipe_kind=value["recipe_kind"],  # type: ignore[arg-type]
            request_identity_fields=_text_tuple(
                value["request_identity_fields"], "request_identity_fields"
            ),
            source_fingerprint_field=value["source_fingerprint_field"],  # type: ignore[arg-type]
            request_digest_field=value["request_digest_field"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class DataOperationDescriptorV1:
    operation_id: str
    operation_version: str
    effect_level: str
    risk_level: str
    confirmation_policy: str
    executor_key: str
    reconciler_key: str
    validator_key: str
    request_schema: Mapping[str, Any]
    input_ports: tuple[DataPortV1, ...]
    output_ports: tuple[DataPortV1, ...]
    metadata_effect: str
    metadata_risk: str
    output_kind: str
    preview_ref: str
    confirm_ref: str
    confirm_requires: tuple[str, ...]
    replay: ReplayContractV1
    clarification_requirements: tuple[str, ...]
    request_schema_digest: str = ""

    def __post_init__(self) -> None:
        for name in (
            "operation_id",
            "operation_version",
            "effect_level",
            "risk_level",
            "confirmation_policy",
            "executor_key",
            "reconciler_key",
            "validator_key",
            "metadata_effect",
            "metadata_risk",
            "output_kind",
            "preview_ref",
            "confirm_ref",
        ):
            _text(getattr(self, name), name)
        if not isinstance(self.request_schema, Mapping):
            raise ValueError("request_schema must be a mapping")
        object.__setattr__(self, "request_schema", _freeze(deepcopy(dict(self.request_schema))))
        computed_schema_digest = sha256(
            json.dumps(
                _thaw(self.request_schema),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        if self.request_schema_digest:
            if _SHA256_RE.fullmatch(self.request_schema_digest) is None:
                raise ValueError("request_schema_digest must be a lowercase SHA-256 digest")
            if self.request_schema_digest != computed_schema_digest:
                raise ValueError("request_schema_digest does not match request_schema")
        object.__setattr__(self, "request_schema_digest", computed_schema_digest)
        for name in ("input_ports", "output_ports"):
            ports = getattr(self, name)
            if type(ports) is not tuple or not ports or any(type(port) is not DataPortV1 for port in ports):
                raise ValueError(f"{name} must contain DataPortV1 values")
        if type(self.replay) is not ReplayContractV1:
            raise ValueError("replay must be ReplayContractV1")
        object.__setattr__(self, "confirm_requires", _text_tuple(self.confirm_requires, "confirm_requires"))
        object.__setattr__(
            self,
            "clarification_requirements",
            _text_tuple(self.clarification_requirements, "clarification_requirements", required=True),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "effect_level": self.effect_level,
            "risk_level": self.risk_level,
            "confirmation_policy": self.confirmation_policy,
            "executor_key": self.executor_key,
            "reconciler_key": self.reconciler_key,
            "validator_key": self.validator_key,
            "request_schema": _thaw(self.request_schema),
            "input_ports": [port.to_dict() for port in self.input_ports],
            "output_ports": [port.to_dict() for port in self.output_ports],
            "metadata_effect": self.metadata_effect,
            "metadata_risk": self.metadata_risk,
            "output_kind": self.output_kind,
            "preview_ref": self.preview_ref,
            "confirm_ref": self.confirm_ref,
            "confirm_requires": list(self.confirm_requires),
            "replay": self.replay.to_dict(),
            "clarification_requirements": list(self.clarification_requirements),
            "request_schema_digest": self.request_schema_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DataOperationDescriptorV1":
        fields = {
            "operation_id",
            "operation_version",
            "effect_level",
            "risk_level",
            "confirmation_policy",
            "executor_key",
            "reconciler_key",
            "validator_key",
            "request_schema",
            "input_ports",
            "output_ports",
            "metadata_effect",
            "metadata_risk",
            "output_kind",
            "preview_ref",
            "confirm_ref",
            "confirm_requires",
            "replay",
            "clarification_requirements",
            "request_schema_digest",
        }
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("data operation descriptor fields are not exact")
        return cls(
            operation_id=value["operation_id"],  # type: ignore[arg-type]
            operation_version=value["operation_version"],  # type: ignore[arg-type]
            effect_level=value["effect_level"],  # type: ignore[arg-type]
            risk_level=value["risk_level"],  # type: ignore[arg-type]
            confirmation_policy=value["confirmation_policy"],  # type: ignore[arg-type]
            executor_key=value["executor_key"],  # type: ignore[arg-type]
            reconciler_key=value["reconciler_key"],  # type: ignore[arg-type]
            validator_key=value["validator_key"],  # type: ignore[arg-type]
            request_schema=value["request_schema"],  # type: ignore[arg-type]
            input_ports=tuple(DataPortV1.from_dict(item) for item in value["input_ports"]),  # type: ignore[arg-type]
            output_ports=tuple(DataPortV1.from_dict(item) for item in value["output_ports"]),  # type: ignore[arg-type]
            metadata_effect=value["metadata_effect"],  # type: ignore[arg-type]
            metadata_risk=value["metadata_risk"],  # type: ignore[arg-type]
            output_kind=value["output_kind"],  # type: ignore[arg-type]
            preview_ref=value["preview_ref"],  # type: ignore[arg-type]
            confirm_ref=value["confirm_ref"],  # type: ignore[arg-type]
            confirm_requires=_text_tuple(value["confirm_requires"], "confirm_requires"),
            replay=ReplayContractV1.from_dict(value["replay"]),  # type: ignore[arg-type]
            clarification_requirements=_text_tuple(
                value["clarification_requirements"], "clarification_requirements"
            ),
            request_schema_digest=value["request_schema_digest"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class DataOperationUnavailableV1:
    operation_id: str
    operation_version: str
    reason_code: str
    message: str
    status: str = "unavailable"

    def __post_init__(self) -> None:
        for name in ("operation_id", "operation_version", "reason_code", "message"):
            _text(getattr(self, name), name)
        if self.status != "unavailable":
            raise ValueError("unavailable operation status must be unavailable")

    def to_dict(self) -> dict[str, str]:
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "status": self.status,
            "reason_code": self.reason_code,
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DataOperationUnavailableV1":
        fields = {"operation_id", "operation_version", "status", "reason_code", "message"}
        if not isinstance(value, Mapping) or set(value) != fields:
            raise ValueError("unavailable operation fields are not exact")
        return cls(
            operation_id=value["operation_id"],  # type: ignore[arg-type]
            operation_version=value["operation_version"],  # type: ignore[arg-type]
            status=value["status"],  # type: ignore[arg-type]
            reason_code=value["reason_code"],  # type: ignore[arg-type]
            message=value["message"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class DataOperationManifestV1:
    schema_version: str
    operations: tuple[DataOperationDescriptorV1, ...]
    unavailable: tuple[DataOperationUnavailableV1, ...] = ()

    def __post_init__(self) -> None:
        if self.schema_version != DATA_OPERATION_MANIFEST_VERSION:
            raise ValueError("manifest schema_version is invalid")
        if type(self.operations) is not tuple or any(
            type(operation) is not DataOperationDescriptorV1 for operation in self.operations
        ):
            raise ValueError("manifest operations are invalid")
        operation_ids = tuple(operation.operation_id for operation in self.operations)
        if len(set(operation_ids)) != len(operation_ids):
            raise ValueError("manifest operation ids must be unique")
        if type(self.unavailable) is not tuple or any(
            type(item) is not DataOperationUnavailableV1 for item in self.unavailable
        ):
            raise ValueError("manifest unavailable operations are invalid")
        unavailable_ids = tuple(item.operation_id for item in self.unavailable)
        if len(set(unavailable_ids)) != len(unavailable_ids):
            raise ValueError("manifest unavailable operation ids must be unique")
        if set(operation_ids) & set(unavailable_ids):
            raise ValueError("manifest cannot advertise and mark an operation unavailable")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            # The manifest is the single read-only projection consumed by the
            # component/Agent planners.  Returning only IDs would force each
            # consumer to recreate request schemas and safety metadata.
            "operations": [operation.to_dict() for operation in self.operations],
            "unavailable": [item.to_dict() for item in self.unavailable],
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "DataOperationManifestV1":
        if not isinstance(value, Mapping) or set(value) not in (
            {"schema_version", "operations"},
            {"schema_version", "operations", "unavailable"},
        ):
            raise ValueError("manifest fields are not exact")
        if value["schema_version"] != DATA_OPERATION_MANIFEST_VERSION:
            raise ValueError("manifest schema_version is invalid")
        raw_operations = value["operations"]
        if type(raw_operations) is not list or not raw_operations:
            raise ValueError("manifest operations must be a non-empty descriptor list")
        try:
            operations = tuple(
                DataOperationDescriptorV1.from_dict(item) for item in raw_operations
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("manifest operations contain an invalid descriptor") from exc
        raw_unavailable = value.get("unavailable", [])
        if type(raw_unavailable) is not list:
            raise ValueError("manifest unavailable operations must be a list")
        try:
            unavailable = tuple(
                DataOperationUnavailableV1.from_dict(item) for item in raw_unavailable
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("manifest unavailable operations contain an invalid item") from exc

        live = build_data_operation_manifest()
        if operations != live.operations or unavailable != live.unavailable:
            raise ValueError("manifest descriptors do not match the live operation surface")
        return DataOperationManifestV1(DATA_OPERATION_MANIFEST_VERSION, operations, unavailable)


@dataclass(frozen=True)
class DraftAgentNotebookFixture:
    consumer: str
    mode: str
    execution_allowed: bool
    confirmation_ref: str | None
    plan: DraftAgentPlanV1

    def __post_init__(self) -> None:
        _text(self.consumer, "consumer")
        if self.mode != "draft":
            raise ValueError("fixture mode must be draft")
        if self.execution_allowed is not False:
            raise ValueError("draft fixture execution is disabled")
        if self.confirmation_ref is not None:
            raise ValueError("draft fixture cannot carry confirmation authority")
        if type(self.plan) is not DraftAgentPlanV1:
            raise ValueError("plan must be DraftAgentPlanV1")


def _local_request_schema(operation_id: str) -> dict[str, Any]:
    identity_properties = {
        field: {"type": "string", "minLength": 1, "description": "Bound source identity."}
        for field in _IDENTITY_FIELDS
    }
    if operation_id == "data.metadata.update":
        properties = {
            **identity_properties,
            "metadata": {
                "type": "object",
                "description": "Per-column typed variable/value-label and role declarations.",
                "additionalProperties": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {
                        "variable_label": {"type": "string"},
                        "value_labels": {"type": "object", "additionalProperties": {"type": "string"}},
                        "measurement_level": {"type": "string"},
                        "missing_policy": {"type": "string"},
                        "role": {"type": "string"},
                        "sensitivity": {"type": "string"},
                        "user_missing_values": {"type": "array", "items": {}},
                    },
                },
            },
            "weight": {"type": ["object", "null"]},
            "split": {"type": ["object", "null"]},
            "group": {"type": ["object", "null"]},
        }
        return {
            "type": "object",
            "required": list(_IDENTITY_FIELDS),
            "properties": properties,
            "additionalProperties": False,
        }

    parameter_properties: dict[str, Any]
    if operation_id == "data.sort":
        parameter_properties = {
            "keys": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "object"}]}},
            "by": {"type": "array", "items": {"type": "string"}},
        }
    elif operation_id == "data.split":
        parameter_properties = {
            "by": {"type": "array", "items": {"type": "string"}},
            "columns": {"type": "array", "items": {"type": "string"}},
            "mode": {"type": "string", "enum": ["split_file", "group"]},
        }
    else:
        parameter_properties = {
            "columns": {"type": "array", "items": {"type": "object"}},
            "column": {"type": "string"},
            "mapping": {"type": "object"},
            "other": {},
            "missing": {"type": "string", "enum": ["preserve", "missing"]},
        }
    return {
        "type": "object",
        "required": [*list(_IDENTITY_FIELDS), "operation"],
        "properties": {
            **identity_properties,
            "operation": {"type": "string", "enum": [operation_id.removeprefix("data.")]},
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": parameter_properties,
            },
        },
        "additionalProperties": False,
    }


def _request_schema(operation_id: str, registry: OperationRegistry) -> dict[str, Any]:
    if operation_id in _LOCAL_OPERATION_IDS:
        return _local_request_schema(operation_id)
    definition = registry.require(operation_id)
    contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id)
    if contract is not None:
        # Keep the workflow contract's field schemas byte-for-byte intact.  A
        # display description belongs in a renderer; adding one here would
        # silently create a second request-schema contract.
        schema = {
            "type": "object",
            "required": list(contract.required),
            "properties": deepcopy(dict(contract.field_schemas)),
            "additionalProperties": False,
        }
    else:
        schema = deepcopy(definition.editable_schema)
    if contract is not None:
        for field_schema in schema.get("properties", {}).values():
            field_schema.pop("description", None)
    properties = schema.setdefault("properties", {})
    properties.update(
        {
            field: {"type": "string", "minLength": 1, "description": "Bound source identity."}
            for field in _IDENTITY_FIELDS
        }
    )
    if operation_id == "data.columns.cast":
        properties["output_format"] = {
            "type": "string",
            "enum": ["csv", "xlsx"],
            "description": "Output format for the derived artifact.",
        }
    required = list(schema.get("required", []))
    schema["required"] = required + [field for field in _IDENTITY_FIELDS if field not in required]
    schema["additionalProperties"] = False
    return schema


def _ports(operation_id: str) -> tuple[tuple[DataPortV1, ...], tuple[DataPortV1, ...]]:
    inputs = [
        DataPortV1("source", "dataset", "source_data", "one", True, _IDENTITY_FIELDS)
    ]
    if operation_id in {"data.merge", "data.append"}:
        inputs.append(
            DataPortV1("secondary", "dataset", "source_data", "one", True, _SECONDARY_IDENTITY_FIELDS)
        )
    return tuple(inputs), (
        DataPortV1("derived", "dataset", "derived_data", "one", True, _DERIVED_IDENTITY_FIELDS),
        DataPortV1("operation_record", "operation_record", None, "one", True, ("record_id",)),
        DataPortV1("evidence", "evidence", None, "one", True, ("method",)),
    )


def _clarifications(operation_id: str) -> tuple[str, ...]:
    return {
        "data.aggregate": ("Declare bounded group keys, aggregation functions, and how confirmed weights are consumed.",),
        "data.append": ("Declare exact or union schema policy and an explicit row-growth bound.",),
        "data.column.cast": ("Declare the target dtype and review any lossy coercion.",),
        "data.columns.cast": ("Declare each target dtype and review any lossy coercion.",),
        "data.feature_recipe": ("Choose a registered recipe and provide its closed parameters.",),
        "data.merge": ("Declare join keys, join cardinality, and a row-growth policy.",),
        "data.metadata.update": (
            "Declare typed variable/value labels, measurement role, missing values, weight, and split/group semantics.",
        ),
        "data.recode": ("Declare bounded batch recode rules and an explicit unmatched-value policy.",),
        "data.rename": ("Declare a closed source-to-output column mapping without collisions.",),
        "data.reshape": ("Declare the reshape direction and its identity/value columns.",),
        "data.sort": ("Declare stable sort keys and direction for each key.",),
        "data.split": ("Declare split/group columns and whether the result is split-file or grouped.",),
        "data.subset": ("Declare output columns and closed filters; arbitrary expressions are unsupported.",),
    }[operation_id]


def _replay_identity_fields(operation_id: str) -> tuple[str, ...]:
    fields = ["operation_id", "operation_version", *_IDENTITY_FIELDS]
    if operation_id in {"data.merge", "data.append"}:
        fields.extend(_SECONDARY_IDENTITY_FIELDS)
    fields.append("request_sha256")
    return tuple(fields)


def _local_operation_surface(operation_id: str) -> dict[str, str]:
    if operation_id not in _LOCAL_OPERATION_IDS:
        raise ValueError(f"{operation_id} is not a local data-consumer operation")
    return {
        "operation_version": "v1",
        "effect_level": "mutation",
        "risk_level": "mutating",
        "confirmation_policy": "required",
        "executor_key": f"executor:workbench.data_consumer.{operation_id.removeprefix('data.')}",
        "reconciler_key": f"reconciler:workbench.data_consumer.{operation_id.removeprefix('data.')}",
    }


def build_data_operation_manifest() -> DataOperationManifestV1:
    registry = OperationRegistry()
    descriptors: list[DataOperationDescriptorV1] = []
    for operation_id in _DATA_OPERATION_IDS:
        local_surface = _local_operation_surface(operation_id) if operation_id in _LOCAL_OPERATION_IDS else None
        definition = None if local_surface is not None else registry.require(operation_id)
        contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id)
        input_ports, output_ports = _ports(operation_id)
        preview_ref, confirm_ref = _OPERATION_ROUTES[operation_id]
        descriptors.append(
            DataOperationDescriptorV1(
                operation_id=operation_id,
                operation_version=(
                    local_surface["operation_version"] if local_surface else definition.operation_version
                ),
                effect_level=(
                    local_surface["effect_level"] if local_surface else definition.effect_level
                ),
                risk_level=(
                    local_surface["risk_level"] if local_surface else definition.risk_level
                ),
                confirmation_policy=(
                    local_surface["confirmation_policy"] if local_surface else definition.confirmation_policy
                ),
                executor_key=(
                    local_surface["executor_key"] if local_surface else definition.executor_key
                ),
                reconciler_key=(
                    local_surface["reconciler_key"] if local_surface else definition.reconciler_key
                ),
                validator_key=(
                    contract.semantic_validator_key if contract is not None else operation_id
                ),
                request_schema=_request_schema(operation_id, registry),
                input_ports=input_ports,
                output_ports=output_ports,
                metadata_effect="preserve source metadata and append provenance",
                metadata_risk="metadata loss is blocked without an explicit manifest",
                output_kind="derived_data",
                preview_ref=preview_ref,
                confirm_ref=confirm_ref,
                confirm_requires=("preview_fingerprint",),
                replay=ReplayContractV1(
                    recipe_kind="typed_operation_request",
                    request_identity_fields=_replay_identity_fields(operation_id),
                    source_fingerprint_field="source_sha256",
                    request_digest_field="request_sha256",
                ),
                clarification_requirements=_clarifications(operation_id),
            )
        )
    unavailable: tuple[DataOperationUnavailableV1, ...]
    try:
        pyreadstat_available = importlib.util.find_spec("pyreadstat") is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        pyreadstat_available = False
    native_unavailable = () if pyreadstat_available else tuple(
            DataOperationUnavailableV1(
                operation_id=operation_id,
                operation_version="v1",
                reason_code="optional_dependency",
                message="pyreadstat is not installed; native statistical-file interchange is not advertised.",
            )
            for operation_id in _NATIVE_INTERCHANGE_IDS
        )
    unavailable = (
        DataOperationUnavailableV1(
            operation_id=_METADATA_LOSS_UNAVAILABLE_ID,
            operation_version="v1",
            reason_code="not_executable",
            message="Metadata-loss preview is read-only and is not an executable data operation.",
        ),
        *native_unavailable,
    )
    return DataOperationManifestV1(DATA_OPERATION_MANIFEST_VERSION, tuple(descriptors), unavailable)


@dataclass(frozen=True)
class DataConsumerDerivedPortV1:
    """A derived port that can only be created from a server-owned effect."""

    effect: object
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        from workbench.data_operations import (
            DataColumnCastEffect,
            DataColumnsCastEffect,
            FeatureRecipeEffect,
        )
        from workbench.metadata import MetadataMutationEffectV1

        allowed_effects = (
            DataColumnCastEffect,
            DataColumnsCastEffect,
            FeatureRecipeEffect,
            MetadataMutationEffectV1,
        )
        if type(self.effect) not in allowed_effects:
            raise TypeError("derived port requires a server-owned typed effect")
        payload = self.effect.to_dict()
        if type(payload) is not dict:
            raise TypeError("server-owned effect did not produce a typed payload")
        if not isinstance(payload.get("execution_key"), str) or not payload["execution_key"]:
            raise ValueError("derived port effect has no execution_key")
        if not isinstance(payload.get("child_node_id"), str) or not payload["child_node_id"]:
            raise ValueError("derived port effect has no child_node_id")
        if not any(
            isinstance(payload.get(field), str) and payload[field]
            for field in ("artifact_id", "metadata_artifact_id")
        ):
            raise ValueError("derived port effect has no artifact identity")
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("derived port can only be created by the server-owned factory")

    @classmethod
    def from_server(cls, effect: object) -> "DataConsumerDerivedPortV1":
        return cls(effect=effect, _capability=_SERVER_OWNED_CAPABILITY)

    @property
    def execution_key(self) -> str:
        return str(self.effect.to_dict()["execution_key"])

    def to_dict(self) -> dict[str, object]:
        return dict(self.effect.to_dict())


@dataclass(frozen=True)
class DataConsumerServerEvidenceV1:
    """Immutable evidence created by the package-owned execution boundary."""

    method: str
    payload: Mapping[str, object]
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.method) is not str or not self.method.strip():
            raise ValueError("server evidence method must be a non-empty string")
        if type(self.payload) is not dict:
            raise TypeError("server evidence payload must be a server-owned dict")
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("server evidence can only be created by the server-owned factory")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))

    @classmethod
    def from_server(
        cls,
        method: str,
        payload: Mapping[str, object],
        *,
        record_id: str,
        operation_id: str,
        execution_key: str,
        bindings: Mapping[str, object],
    ) -> "DataConsumerServerEvidenceV1":
        if type(payload) is not dict:
            raise TypeError("server evidence payload must be a server-owned dict")
        expected = {
            "record_id": record_id,
            "operation_id": operation_id,
            "execution_key": execution_key,
            **{str(key): str(value) for key, value in bindings.items()},
        }
        for key, value in expected.items():
            if key in payload and str(payload[key]) != str(value):
                raise ValueError(f"server evidence identity mismatch for {key}")
        materialized = dict(payload)
        materialized.update(expected)
        return cls(method=method, payload=materialized, _capability=_SERVER_OWNED_CAPABILITY)


@dataclass(frozen=True)
class DataConsumerEvidencePortV1:
    """Evidence port constructed from the server's bounded evidence object."""

    method: str
    evidence: Mapping[str, object]
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.method) is not str or not self.method.strip():
            raise ValueError("evidence port method must be a non-empty string")
        if not isinstance(self.evidence, Mapping):
            raise TypeError("evidence port requires a typed evidence mapping")
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("evidence port can only be created by the server-owned factory")
        object.__setattr__(self, "evidence", MappingProxyType(dict(self.evidence)))

    @classmethod
    def from_server(cls, method: str, evidence: DataConsumerServerEvidenceV1) -> "DataConsumerEvidencePortV1":
        if type(evidence) is not DataConsumerServerEvidenceV1:
            raise TypeError("server evidence must be a typed server-owned evidence object")
        if evidence.method != method:
            raise ValueError("server evidence method does not match the requested method")
        return cls(
            method=evidence.method,
            evidence=evidence.payload,
            _capability=_SERVER_OWNED_CAPABILITY,
        )

    def to_dict(self) -> dict[str, object]:
        return {"method": self.method, **dict(self.evidence)}


@dataclass(frozen=True)
class DataConsumerOutputPortsV1:
    """The complete typed output projection for one OperationRecord."""

    operation_record: OperationRecord
    derived: DataConsumerDerivedPortV1
    evidence: DataConsumerEvidencePortV1
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if type(self.operation_record) is not OperationRecord:
            raise TypeError("output ports require a server-owned typed OperationRecord")
        if type(self.derived) is not DataConsumerDerivedPortV1:
            raise TypeError("output ports require a typed derived port")
        if type(self.evidence) is not DataConsumerEvidencePortV1:
            raise TypeError("output ports require a typed evidence port")
        if self.derived.to_dict().get("execution_key") != self.operation_record.execution.get(
            "execution_key"
        ):
            raise ValueError("derived port execution key does not match OperationRecord claim")
        expected_bindings = {
            key: str(value)
            for key, value in self.derived.to_dict().items()
            if key.endswith("_id") and value is not None
        }
        actual_bindings = self.operation_record.execution.get("bindings")
        if not isinstance(actual_bindings, Mapping) or {
            str(key): str(value) for key, value in actual_bindings.items()
        } != expected_bindings:
            raise ValueError("derived effect identities do not exactly match OperationRecord bindings")
        evidence_payload = self.evidence.to_dict()
        for key, expected in {
            "record_id": self.operation_record.record_id,
            "operation_id": self.operation_record.operation_id,
            "execution_key": self.operation_record.execution.get("execution_key"),
            "child_node_id": self.derived.to_dict().get("child_node_id"),
        }.items():
            if evidence_payload.get(key) != expected:
                raise ValueError(f"evidence identity does not match OperationRecord for {key}")
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("output ports can only be created by the server-owned factory")

    @classmethod
    def from_server(
        cls,
        operation_record: OperationRecord,
        derived: DataConsumerDerivedPortV1,
        evidence: DataConsumerEvidencePortV1,
    ) -> "DataConsumerOutputPortsV1":
        return cls(
            operation_record=operation_record,
            derived=derived,
            evidence=evidence,
            _capability=_SERVER_OWNED_CAPABILITY,
        )

    def to_dict(self, *, catalog_digest: str) -> dict[str, object]:
        record = self.operation_record
        return {
            "ports": {
                "derived": self.derived.to_dict(),
                "operation_record": {
                    "record_id": record.record_id,
                    "operation_id": record.operation_id,
                    "operation_version": record.operation_version,
                },
                "evidence": self.evidence.to_dict(),
            },
            "consumer_slots": {
                "data.agent": {"record_id": record.record_id, "port": "derived"},
                "data.notebook": {"record_id": record.record_id, "port": "derived"},
                "data.report": {"record_id": record.record_id, "port": "evidence"},
            },
            "catalog_digest": catalog_digest,
        }


@dataclass(frozen=True)
class DataConsumerRuntimeAdapterV1:
    """Package-owned adapter joined only from the server's typed catalog."""

    provider_id: str
    adapter_id: str
    catalog_digest: str
    executor_ref: str
    consumer_slots: tuple[str, ...]
    output_ports: tuple[str, ...]
    operation_ids: tuple[str, ...]
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if self.provider_id != "workbench.data_consumer":
            raise ValueError("runtime adapter provider is not server-owned")
        if self.adapter_id != "workbench.data_consumer.adapter":
            raise ValueError("runtime adapter identity is not server-owned")
        if type(self.catalog_digest) is not str or _SHA256_RE.fullmatch(self.catalog_digest) is None:
            raise ValueError("catalog digest is not a canonical SHA-256 digest")
        if not is_opaque_executor_ref(self.executor_ref):
            raise ValueError("executor reference must be an opaque server-owned executor ID")
        if self.executor_ref != "executor:workbench.data_consumer.adapter":
            raise ValueError("executor reference is not the server-owned data-consumer executor")
        if self.consumer_slots != ("data.agent", "data.notebook", "data.report"):
            raise ValueError("consumer slots are not the server-owned typed slots")
        if self.output_ports != ("derived", "operation_record", "evidence"):
            raise ValueError("output ports are not the server-owned typed ports")
        if type(self.operation_ids) is not tuple or not self.operation_ids:
            raise ValueError("runtime adapter operation IDs are invalid")
        if any(type(operation_id) is not str or not operation_id for operation_id in self.operation_ids):
            raise ValueError("runtime adapter operation IDs are invalid")
        if len(set(self.operation_ids)) != len(self.operation_ids):
            raise ValueError("runtime adapter operation IDs are duplicated")
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("runtime adapter can only be created by the server-owned factory")

    def adapt_operation_record(
        self,
        record: object,
        outputs: object | None = None,
    ) -> DataConsumerOutputPortsV1:
        if type(record) is not OperationRecord:
            raise TypeError("server-owned typed OperationRecord is required")
        if type(outputs) is not DataConsumerOutputPortsV1:
            raise TypeError("server-owned typed output ports are required")
        if outputs.operation_record is not record:
            raise ValueError("output ports are bound to a different OperationRecord")
        if not record.record_id:
            raise ValueError("OperationRecord has no record_id")
        if record.operation_id not in self.operation_ids:
            raise ValueError(
                "OperationRecord operation is not in the live server manifest: "
                f"{record.operation_id!r}"
            )
        if outputs.derived.to_dict().get("execution_key") != record.execution.get("execution_key"):
            raise ValueError("derived output is not bound to the OperationRecord execution")
        executor = SERVER_OWNED_EXECUTOR_REGISTRY.get(self.executor_ref)
        if not callable(executor):
            raise RuntimeError("server-owned data-consumer executor is not registered")
        if executor(record, outputs) is not outputs:
            raise RuntimeError("server-owned data-consumer executor returned an invalid output")
        return outputs


def build_data_consumer_runtime_adapter() -> DataConsumerRuntimeAdapterV1:
    """Join the package executor with the server-loaded provider catalog."""

    from workbench.providers.catalog import ProviderCatalogV1, load_builtin_catalog

    catalog = load_builtin_catalog()
    if type(catalog) is not ProviderCatalogV1:
        raise TypeError("runtime adapter requires the server-owned typed provider catalog")
    if catalog.catalog_digest != sha256_canonical(catalog.digest_payload()):
        raise ValueError("server provider catalog digest does not match its typed contents")
    providers = [
        item
        for item in catalog.providers
        if type(item) is ProviderContributionV1
        and item.provider_id == "workbench.data_consumer"
    ]
    if len(providers) != 1:
        raise RuntimeError("workbench.data_consumer is absent or duplicated in the live provider catalog")
    provider = providers[0]
    declarations = [
        item
        for item in provider.adapter_declarations
        if type(item) is AdapterDeclarationV1
        and item.adapter_id == "workbench.data_consumer.adapter"
    ]
    if len(declarations) != 1:
        raise RuntimeError("workbench.data_consumer is absent from the live provider catalog")
    declaration = declarations[0]
    if declaration.executor_ref != "executor:workbench.data_consumer.adapter":
        raise ValueError("live provider catalog points at an invalid data-consumer executor")
    if not callable(SERVER_OWNED_EXECUTOR_REGISTRY.get(declaration.executor_ref)):
        raise RuntimeError("live data-consumer executor is not registered")
    manifest = build_data_operation_manifest()
    return DataConsumerRuntimeAdapterV1(
        provider_id=provider.provider_id,
        adapter_id=declaration.adapter_id,
        catalog_digest=catalog.catalog_digest,
        executor_ref=declaration.executor_ref,
        consumer_slots=("data.agent", "data.notebook", "data.report"),
        output_ports=("derived", "operation_record", "evidence"),
        operation_ids=tuple(item.operation_id for item in manifest.operations),
        _capability=_SERVER_OWNED_CAPABILITY,
    )


_PROVIDER_KINDS = (
    "capability",
    "operation",
    "step",
    "schema",
    "validator",
    "adapter",
    "output",
    "evidence",
    "projection",
    "renderer",
    "policy",
)


def _provider_binding_payload(kind: str) -> dict[str, object]:
    """Bind each provider ref to the live descriptor surface.

    The provider JSON is a discovery contribution, not an executor.  Its
    digests must nevertheless change when the live request schemas, routes, or
    validators change; repeated fixture digests made that boundary impossible
    to audit.
    """

    manifest = build_data_operation_manifest().to_dict()
    registry = OperationRegistry()
    registry_surface = []
    for index, operation_id in enumerate(_DATA_OPERATION_IDS):
        local_surface = (
            _local_operation_surface(operation_id)
            if operation_id in _LOCAL_OPERATION_IDS
            else None
        )
        definition = None if local_surface is not None else registry.require(operation_id)
        registry_surface.append(
            {
                "operation_id": operation_id,
                "operation_version": (
                    local_surface["operation_version"] if local_surface else definition.operation_version
                ),
                "executor_key": (
                    local_surface["executor_key"] if local_surface else definition.executor_key
                ),
                "reconciler_key": (
                    local_surface["reconciler_key"] if local_surface else definition.reconciler_key
                ),
                "validator_key": manifest["operations"][index]["validator_key"],
                "request_schema_digest": manifest["operations"][index]["request_schema_digest"],
            }
        )
    return {
        "provider_id": "workbench.data_consumer",
        "semantic_version": "1.0",
        "binding_kind": kind,
        "manifest": manifest,
        "registry_surface": registry_surface,
    }


def _provider_ref(kind: str) -> ContractRefV1:
    if kind not in _PROVIDER_KINDS:
        raise ValueError(f"unknown data-consumer provider ref kind: {kind}")
    digest = sha256(
        json.dumps(
            _provider_binding_payload(kind),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return ContractRefV1(
        kind=kind,
        logical_id=f"workbench.data_consumer.{kind}",
        semantic_version="1.0",
        contract_digest=digest,
    )


def build_builtin_provider_payload() -> dict[str, object]:
    refs = {name: _provider_ref(name) for name in _PROVIDER_KINDS}
    contribution = ProviderContributionV1(
        provider_id="workbench.data_consumer",
        semantic_version="1.0",
        contract_refs=tuple(refs.values()),
        exposure_paths=(
            ExposurePathRefV1(
                path_id="workbench.data_consumer.operations",
                semantic_version="1.0",
                exposure="composition",
                capability_ref=refs["capability"],
                operation_ref=refs["operation"],
                step_contract_ref=refs["step"],
                family_contract_ref=None,
                execution_adapter_ref=refs["adapter"],
                result_contract_refs=(refs["output"],),
                evidence_contract_refs=(refs["evidence"],),
                projection_refs=MappingProxyType({"agent": refs["projection"]}),
            ),
        ),
        adapter_declarations=(
            AdapterDeclarationV1(
                adapter_id="workbench.data_consumer.adapter",
                semantic_version="1.0",
                request_schema_ref=refs["schema"],
                executor_ref="executor:workbench.data_consumer.adapter",
                result_validator_ref=refs["validator"],
                output_refs=(refs["output"], refs["evidence"]),
            ),
        ),
        projection_refs=(refs["projection"],),
        renderer_refs=(refs["renderer"],),
        policy_refs=(refs["policy"],),
    )
    return contribution.to_dict()


def _draft_ref(kind: str, logical_id: str) -> ContractRefV1:
    digest = sha256(f"draft-data-consumer:{kind}:{logical_id}:1.0".encode()).hexdigest()
    return ContractRefV1(kind, logical_id, "1.0", digest)


def _draft_plan(consumer: str) -> DraftAgentPlanV1:
    operation_id = "data.subset" if consumer == "agent" else "data.feature_recipe"
    return DraftAgentPlanV1(
        schema_version="draft-agent-plan.v1",
        intent_ref=f"intent:data-consumer:{consumer}",
        capability_refs=(_draft_ref("capability", f"data.{consumer}"),),
        method_ref="method:data-operation-manifest:1",
        effect=PlanEffectV1.WRITE,
        risk_level=PlanRiskLevelV1.MEDIUM,
        resource_budget={"cpu_ms": 1000, "memory_mb": 128},
        data_impact={"read_refs": ["dataset:source"], "write_mode": "create"},
        output_contract_refs=(_draft_ref("output-contract", f"data.{consumer}.output"),),
        evidence_contract_refs=(_draft_ref("evidence-contract", f"data.{consumer}.evidence"),),
        contract_snapshot_refs=(_draft_ref("contract", "data-operation-manifest"),),
        catalog_snapshot_ref="catalog:data-consumer:1",
        nodes=(
            {
                "node_id": f"{consumer}-draft-operation",
                # DraftAgentPlanV1 exposes only its durable, allowlisted node
                # vocabulary.  The operation identity is a typed identifier,
                # not an execution authority.
                "name": operation_id,
                "type": "reference",
                "ref": "ref:bound-dataset",
            },
        ),
        connections=(),
        config={},
        policy_snapshot_ref="policy:data-consumer:draft",
        rationale=(f"rationale:data-consumer:{consumer}",),
    )


def draft_agent_notebook_composition_fixtures() -> tuple[DraftAgentNotebookFixture, ...]:
    return tuple(
        DraftAgentNotebookFixture(
            consumer=consumer,
            mode="draft",
            execution_allowed=False,
            confirmation_ref=None,
            plan=_draft_plan(consumer),
        )
        for consumer in ("agent", "notebook")
    )


__all__ = [
    "DATA_OPERATION_MANIFEST_VERSION",
    "DataOperationDescriptorV1",
    "DataOperationManifestV1",
    "DataOperationUnavailableV1",
    "DataPortV1",
    "DataConsumerDerivedPortV1",
    "DataConsumerEvidencePortV1",
    "DataConsumerServerEvidenceV1",
    "DataConsumerOutputPortsV1",
    "DataConsumerRuntimeAdapterV1",
    "DraftAgentNotebookFixture",
    "ReplayContractV1",
    "build_builtin_provider_payload",
    "build_data_operation_manifest",
    "build_data_consumer_runtime_adapter",
    "draft_agent_notebook_composition_fixtures",
]
