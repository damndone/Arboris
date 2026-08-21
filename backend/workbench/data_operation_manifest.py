"""Closed, declaration-only manifest for the v1 data-operation surface."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
import re
from types import MappingProxyType
from typing import Any, Callable, Mapping

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
    ConsumerProjectionDeclarationV1,
    ExposurePathRefV1,
    ProviderContributionV1,
    is_opaque_executor_ref,
)
from workbench.data_interchange import interchange_capability


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
_SERVER_OWNED_ISSUER = object()


def _validate_opaque_identity(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or "/" in value
        or "\\" in value
        or ".." in value
    ):
        raise ValueError(f"{name} must be an opaque identity")
    return value


def _registered_data_consumer_executor(
    record: OperationRecord, outputs: object
) -> object:
    return outputs


_SERVER_OWNED_EXECUTOR_REGISTRY = MappingProxyType(
    {
    "executor:workbench.data_consumer.adapter": _registered_data_consumer_executor,
    }
)
# Read-only compatibility projection. Runtime joins use the private mapping so
# rebinding this public name cannot replace the executor authority.
SERVER_OWNED_EXECUTOR_REGISTRY: Mapping[str, object] = _SERVER_OWNED_EXECUTOR_REGISTRY
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
    native_unavailable_items: list[DataOperationUnavailableV1] = []
    for operation_id in _NATIVE_INTERCHANGE_IDS:
        capability = interchange_capability(operation_id.rsplit(".", 1)[-1])
        if capability.status == "available":
            continue
        native_unavailable_items.append(
            DataOperationUnavailableV1(
                operation_id=operation_id,
                operation_version="v1",
                reason_code=capability.reason_code or "optional_dependency",
                message=capability.message or "native statistical-file interchange is unavailable.",
            )
        )
    native_unavailable = tuple(native_unavailable_items)
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
    def from_server(
        cls,
        effect: object,
        *,
        _issuer: object | None = None,
    ) -> "DataConsumerDerivedPortV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("derived port requires the server-owned issuer")
        from workbench.data_operations import _is_server_owned_effect

        if not _is_server_owned_effect(effect):
            raise TypeError("derived port effect was not issued by the server-owned factory")
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
        _issuer: object | None = None,
    ) -> "DataConsumerServerEvidenceV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("server evidence requires the server-owned issuer")
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
    def from_server(
        cls,
        method: str,
        evidence: DataConsumerServerEvidenceV1,
        *,
        _issuer: object | None = None,
    ) -> "DataConsumerEvidencePortV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("evidence port requires the server-owned issuer")
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
        *,
        _issuer: object | None = None,
    ) -> "DataConsumerOutputPortsV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("output ports require the server-owned issuer")
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
class DataConsumerRuntimeOutputV1:
    """Safe runtime projection of server-issued data output ports.

    The Agent/Notebook runtime must not carry rows or filesystem paths.  The
    package-owned data route may still use ``DataConsumerOutputPortsV1``
    internally, but this projection carries only durable identities and an
    evidence digest across the generic provider boundary.
    """

    record_id: str
    operation_id: str
    operation_version: str
    execution_key: str
    child_node_id: str
    artifact_ids: tuple[str, ...]
    evidence_digest: str
    catalog_digest: str
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        for name in (
            "record_id",
            "operation_id",
            "operation_version",
            "execution_key",
            "child_node_id",
            "catalog_digest",
        ):
            value = getattr(self, name)
            if (
                type(value) is not str
                or not value
                or value != value.strip()
                or "/" in value
                or "\\" in value
                or ".." in value
            ):
                raise ValueError(f"{name} must be a non-empty string")
        if self.operation_id not in _DATA_OPERATION_IDS:
            raise ValueError("runtime output operation_id is not a declared data operation")
        if type(self.artifact_ids) is not tuple or not self.artifact_ids:
            raise ValueError("runtime output artifact identities are required")
        if any(
            type(value) is not str
            or not value
            or value != value.strip()
            or "/" in value
            or "\\" in value
            or ".." in value
            for value in self.artifact_ids
        ):
            raise ValueError("runtime output artifact identities must not be paths")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("runtime output artifact identities are duplicated")
        if _SHA256_RE.fullmatch(self.evidence_digest) is None:
            raise ValueError("runtime output evidence_digest must be a SHA-256 digest")
        if _SHA256_RE.fullmatch(self.catalog_digest) is None:
            raise ValueError("runtime output catalog_digest must be a SHA-256 digest")
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("runtime output can only be created by the server-owned factory")

    @classmethod
    def from_server(
        cls,
        *,
        record_id: str,
        operation_id: str,
        operation_version: str,
        execution_key: str,
        child_node_id: str,
        artifact_ids: tuple[str, ...],
        evidence_digest: str,
        catalog_digest: str,
        _issuer: object | None = None,
    ) -> "DataConsumerRuntimeOutputV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("runtime output requires the server-owned issuer")
        return cls(
            record_id=record_id,
            operation_id=operation_id,
            operation_version=operation_version,
            execution_key=execution_key,
            child_node_id=child_node_id,
            artifact_ids=artifact_ids,
            evidence_digest=evidence_digest,
            catalog_digest=catalog_digest,
            _capability=_SERVER_OWNED_CAPABILITY,
        )

    @classmethod
    def from_output_ports(
        cls,
        output_ports: object,
        *,
        catalog_digest: str,
        _issuer: object | None = None,
    ) -> "DataConsumerRuntimeOutputV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("runtime output requires the server-owned issuer")
        if type(output_ports) is not DataConsumerOutputPortsV1:
            raise TypeError("server-owned DataConsumerOutputPortsV1 is required")
        payload = output_ports.to_dict(catalog_digest=catalog_digest)
        record = payload["ports"]["operation_record"]
        derived = payload["ports"]["derived"]
        evidence = payload["ports"]["evidence"]
        artifact_ids = tuple(
            sorted(
                str(value)
                for key, value in derived.items()
                if key in {
                    "artifact_id",
                    "metadata_artifact_id",
                    "recipe_artifact_id",
                    "group_manifest_id",
                }
                and value is not None
            )
        )
        return cls(
            record_id=str(record["record_id"]),
            operation_id=str(record["operation_id"]),
            operation_version=str(record["operation_version"]),
            execution_key=str(derived["execution_key"]),
            child_node_id=str(derived["child_node_id"]),
            artifact_ids=artifact_ids,
            evidence_digest=sha256_canonical(evidence),
            catalog_digest=str(payload["catalog_digest"]),
            _capability=_SERVER_OWNED_CAPABILITY,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "record_id": self.record_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "execution_key": self.execution_key,
            "child_node_id": self.child_node_id,
            "artifact_ids": list(self.artifact_ids),
            "evidence_digest": self.evidence_digest,
            "catalog_digest": self.catalog_digest,
        }


@dataclass(frozen=True)
class DataConsumerHostOperationRequestV1:
    """Opaque identity-only input accepted by the server host-operation port."""

    project_ref: str
    session_ref: str
    snapshot_ref: str
    snapshot_digest: str
    operation_id: str
    operation_version: str
    source_run_id: str
    source_node_id: str
    source_artifact_id: str

    def __post_init__(self) -> None:
        for name in (
            "project_ref",
            "session_ref",
            "snapshot_ref",
            "operation_id",
            "operation_version",
            "source_run_id",
            "source_node_id",
            "source_artifact_id",
        ):
            _validate_opaque_identity(getattr(self, name), name)
        if _SHA256_RE.fullmatch(self.snapshot_digest) is None:
            raise ValueError("snapshot_digest must be a SHA-256 digest")
        if self.operation_id not in _DATA_OPERATION_IDS:
            raise ValueError("operation_id is not a declared data operation")
        if self.operation_version != "v1":
            raise ValueError("operation_version is not supported")


@dataclass(frozen=True)
class DataConsumerRecordAuthorityV1:
    """Closed server-issued authority for the records a host port may consume."""

    _records: Mapping[str, OperationRecord]
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not isinstance(self._records, Mapping):
            raise TypeError("record authority requires a server record mapping")
        copied = dict(self._records)
        for record_id, record in copied.items():
            if type(record_id) is not str or not record_id:
                raise ValueError("record authority contains an invalid record_id")
            if type(record) is not OperationRecord or record.record_id != record_id:
                raise ValueError("record authority contains a non-server OperationRecord")
        object.__setattr__(self, "_records", MappingProxyType(copied))
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("record authority can only be created by the server-owned factory")

    @classmethod
    def from_server(
        cls,
        records: Mapping[str, OperationRecord],
        *,
        _issuer: object | None = None,
    ) -> "DataConsumerRecordAuthorityV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("record authority requires the server-owned issuer")
        return cls(records, _capability=_SERVER_OWNED_CAPABILITY)

    def get(self, record_id: str) -> OperationRecord | None:
        return self._records.get(record_id)


_DATA_HOST_RAW_KEYS = frozenset(
    {"frame", "frames", "rows", "path", "paths", "features", "target", "raw", "data"}
)


def _reject_data_host_raw_payload(value: object, *, path: str = "request") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if type(key) is not str:
                raise ValueError(f"{path} contains a non-string field name")
            if key.lower() in _DATA_HOST_RAW_KEYS:
                raise ValueError(f"{path}.{key} is a raw data field")
            _reject_data_host_raw_payload(child, path=f"{path}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _reject_data_host_raw_payload(child, path=f"{path}[{index}]")


@dataclass(frozen=True)
class DataConsumerHostOperationPortV1:
    """Server-owned resolver from opaque identities to typed data output ports."""

    _resolve: Callable[[DataConsumerHostOperationRequestV1], object]
    _record_authority: DataConsumerRecordAuthorityV1
    catalog_digest: str
    project_ref: str
    session_ref: str
    snapshot_ref: str
    snapshot_digest: str
    operation_id: str
    operation_version: str
    source_run_id: str
    source_node_id: str
    source_artifact_id: str
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not callable(self._resolve):
            raise TypeError("host-operation port requires a server resolver")
        if type(self._record_authority) is not DataConsumerRecordAuthorityV1:
            raise TypeError("host-operation port requires a server record authority")
        if _SHA256_RE.fullmatch(self.catalog_digest) is None:
            raise ValueError("host-operation port catalog_digest must be a SHA-256 digest")
        for name in (
            "project_ref",
            "session_ref",
            "snapshot_ref",
            "operation_id",
            "operation_version",
            "source_run_id",
            "source_node_id",
            "source_artifact_id",
        ):
            _validate_opaque_identity(getattr(self, name), name)
        if self.operation_id not in _DATA_OPERATION_IDS:
            raise ValueError("host-operation port operation_id is not declared")
        if self.operation_version != "v1":
            raise ValueError("host-operation port operation_version is not supported")
        if _SHA256_RE.fullmatch(self.snapshot_digest) is None:
            raise ValueError("host-operation port snapshot_digest must be a SHA-256 digest")
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("host-operation port can only be created by the server-owned factory")

    @classmethod
    def from_server(
        cls,
        resolve: Callable[[DataConsumerHostOperationRequestV1], object],
        *,
        record_authority: DataConsumerRecordAuthorityV1,
        catalog_digest: str,
        project_ref: str,
        session_ref: str,
        snapshot_ref: str,
        snapshot_digest: str,
        operation_id: str,
        operation_version: str,
        source_run_id: str,
        source_node_id: str,
        source_artifact_id: str,
        _issuer: object | None = None,
    ) -> "DataConsumerHostOperationPortV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("host-operation port requires the server-owned issuer")
        return cls(
            _resolve=resolve,
            _record_authority=record_authority,
            catalog_digest=catalog_digest,
            project_ref=project_ref,
            session_ref=session_ref,
            snapshot_ref=snapshot_ref,
            snapshot_digest=snapshot_digest,
            operation_id=operation_id,
            operation_version=operation_version,
            source_run_id=source_run_id,
            source_node_id=source_node_id,
            source_artifact_id=source_artifact_id,
            _capability=_SERVER_OWNED_CAPABILITY,
        )

    def resolve(self, request: DataConsumerHostOperationRequestV1) -> DataConsumerRuntimeOutputV1:
        if type(request) is not DataConsumerHostOperationRequestV1:
            raise TypeError("host-operation port accepts only a typed identity request")
        if request.project_ref != self.project_ref or request.session_ref != self.session_ref:
            raise ValueError("host-operation request has a foreign scope")
        if (
            request.snapshot_ref != self.snapshot_ref
            or request.snapshot_digest != self.snapshot_digest
        ):
            raise ValueError("host-operation request has a stale snapshot")
        if (
            request.operation_id != self.operation_id
            or request.operation_version != self.operation_version
            or request.source_run_id != self.source_run_id
            or request.source_node_id != self.source_node_id
            or request.source_artifact_id != self.source_artifact_id
        ):
            raise ValueError("host-operation request has a foreign operation or source identity")
        result = self._resolve(request)
        if type(result) is not DataConsumerOutputPortsV1:
            raise TypeError("host resolver must return typed server-owned output ports")
        record = result.operation_record
        authoritative_record = self._record_authority.get(record.record_id)
        if type(authoritative_record) is not OperationRecord or authoritative_record is not record:
            raise ValueError(
                "host resolver returned an OperationRecord that is not the exact server-issued record"
            )
        if record.status != "completed" or record.effect_status != "committed":
            raise ValueError("host resolver returned an incomplete OperationRecord")
        if (
            record.operation_id != request.operation_id
            or record.operation_version != request.operation_version
            or record.agent_session_id != self.session_ref
        ):
            raise ValueError("OperationRecord does not match the host-operation identity")
        required_claims = {
            "project_ref": self.project_ref,
            "session_ref": self.session_ref,
            "data_snapshot_ref": self.snapshot_ref,
            "data_snapshot_digest": self.snapshot_digest,
            "source_run_id": self.source_run_id,
            "source_node_id": self.source_node_id,
            "source_artifact_id": self.source_artifact_id,
        }
        claims = (record.target, record.preconditions)
        if any(not isinstance(claim, Mapping) for claim in claims):
            raise ValueError("OperationRecord identity claims are not mappings")
        for key, expected in required_claims.items():
            values = [claim[key] for claim in claims if key in claim]
            if not values:
                raise ValueError(f"OperationRecord is missing required identity claim {key}")
            if any(type(value) is not str or value != expected for value in values):
                raise ValueError(f"OperationRecord has a foreign {key}")
        adapter = build_data_consumer_runtime_adapter()
        if adapter.catalog_digest != self.catalog_digest:
            raise ValueError("host-operation port catalog digest is not the live server catalog")
        adapter.adapt_operation_record(record, result)
        return DataConsumerRuntimeOutputV1.from_output_ports(
            result,
            catalog_digest=self.catalog_digest,
            _issuer=_SERVER_OWNED_ISSUER,
        )

    def as_execution_port(self) -> "DataConsumerExecutionPortV1":
        def execute(context: object, request: Mapping[str, object]) -> object:
            from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1

            if type(context) is not ProviderRuntimeContextV1:
                raise TypeError("host-operation port requires a server runtime context")
            if context.project_ref != self.project_ref or context.session_ref != self.session_ref:
                raise ValueError("host runtime context has a foreign scope")
            if not isinstance(request, Mapping):
                raise TypeError("host-operation port requires a shared runtime request mapping")
            _reject_data_host_raw_payload(request)
            allowed = {
                "capability_id",
                "target_ref",
                "data_snapshot_ref",
                "source_text_digest",
                "operation_id",
                "source_run_id",
                "source_node_id",
                "source_artifact_id",
                "operation",
                "options",
            }
            unknown = sorted(set(request) - allowed)
            if unknown:
                raise ValueError(
                    "host-operation shared runtime request contains unsupported field(s): "
                    + ", ".join(unknown)
                )
            if request.get("data_snapshot_ref") != self.snapshot_ref:
                raise ValueError("host-operation shared runtime request has a stale snapshot")
            if request.get("target_ref") != self.source_run_id:
                raise ValueError("host-operation shared runtime request has a foreign source run")
            options = request.get("options")
            if options is not None and not isinstance(options, Mapping):
                raise ValueError("host-operation shared runtime options must be a mapping")
            operation_id = request.get("operation_id")
            if operation_id is None and isinstance(options, Mapping):
                operation_id = options.get("operation_id")
            if operation_id != self.operation_id:
                raise ValueError("host-operation shared runtime request has a foreign operation")
            for name in ("source_run_id", "source_node_id", "source_artifact_id"):
                value = request.get(name)
                if value is not None and value != getattr(self, name):
                    raise ValueError(f"host-operation shared runtime request has a foreign {name}")
            typed_request = DataConsumerHostOperationRequestV1(
                project_ref=self.project_ref,
                session_ref=self.session_ref,
                snapshot_ref=self.snapshot_ref,
                snapshot_digest=self.snapshot_digest,
                operation_id=self.operation_id,
                operation_version=self.operation_version,
                source_run_id=self.source_run_id,
                source_node_id=self.source_node_id,
                source_artifact_id=self.source_artifact_id,
            )
            return self.resolve(typed_request)

        return DataConsumerExecutionPortV1.from_server(
            execute,
            catalog_digest=self.catalog_digest,
            _issuer=_SERVER_OWNED_ISSUER,
        )


@dataclass(frozen=True)
class DataConsumerExecutionPortV1:
    """Server-issued host port for executing one data operation.

    The host implementation is intentionally hidden behind this typed port.
    A generic provider contribution can only receive a validated
    ``DataConsumerRuntimeOutputV1``; it cannot receive a project path, a raw
    dataframe, or a caller-created evidence packet.
    """

    _execute: Callable[[object, Mapping[str, object]], object]
    catalog_digest: str
    _capability: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        if not callable(self._execute):
            raise TypeError("execution port requires a callable host implementation")
        if _SHA256_RE.fullmatch(self.catalog_digest) is None:
            raise ValueError("execution port catalog_digest must be a SHA-256 digest")
        if self._capability is not _SERVER_OWNED_CAPABILITY:
            raise TypeError("execution port can only be created by the server-owned factory")

    @classmethod
    def from_server(
        cls,
        execute: Callable[[object, Mapping[str, object]], object],
        *,
        catalog_digest: str,
        _issuer: object | None = None,
    ) -> "DataConsumerExecutionPortV1":
        if _issuer is not _SERVER_OWNED_ISSUER:
            raise TypeError("execution port requires the server-owned issuer")
        return cls(
            _execute=execute,
            catalog_digest=catalog_digest,
            _capability=_SERVER_OWNED_CAPABILITY,
        )

    def execute(
        self,
        context: object,
        request: Mapping[str, object],
    ) -> DataConsumerRuntimeOutputV1:
        from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1

        if type(context) is not ProviderRuntimeContextV1:
            raise TypeError("execution port requires a server runtime context")
        if not isinstance(request, Mapping):
            raise TypeError("execution port requires a typed request mapping")
        result = self._execute(context, dict(request))
        if type(result) is DataConsumerRuntimeOutputV1:
            output = result
        else:
            output = DataConsumerRuntimeOutputV1.from_output_ports(
                result,
                catalog_digest=self.catalog_digest,
                _issuer=_SERVER_OWNED_ISSUER,
            )
        if output.catalog_digest != self.catalog_digest:
            raise ValueError("execution port output catalog digest does not match the port")
        return output


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
        executor = _SERVER_OWNED_EXECUTOR_REGISTRY.get(self.executor_ref)
        if executor is not _registered_data_consumer_executor:
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
    if _SERVER_OWNED_EXECUTOR_REGISTRY.get(declaration.executor_ref) is not _registered_data_consumer_executor:
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


def _validate_data_consumer_runtime_request(request: Mapping[str, object]) -> dict[str, object]:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    if not isinstance(request, Mapping):
        raise TrustedExecutorRegistryError(
            "DATA_CONSUMER_RUNTIME_REQUEST_INVALID",
            "data-consumer runtime request must be an object",
        )
    allowed = {
        "capability_id", "target_ref", "data_snapshot_ref", "source_text_digest",
        "operation_id", "source_run_id", "source_node_id", "source_artifact_id",
        "operation", "options",
    }
    unknown = sorted(set(request) - allowed)
    if unknown:
        raise TrustedExecutorRegistryError(
            "DATA_CONSUMER_RUNTIME_REQUEST_INVALID",
            f"unsupported data-consumer runtime field(s): {', '.join(unknown)}",
        )
    normalized = dict(request)
    operation_id = normalized.get("operation_id")
    if operation_id is None and isinstance(normalized.get("options"), Mapping):
        operation_id = normalized["options"].get("operation_id")  # type: ignore[union-attr]
    if type(operation_id) is not str or operation_id not in _DATA_OPERATION_IDS:
        raise TrustedExecutorRegistryError(
            "DATA_CONSUMER_RUNTIME_OPERATION_INVALID",
            "data-consumer runtime requires a declared operation_id",
        )
    normalized["operation_id"] = operation_id
    for field_name in (
        "capability_id", "target_ref", "data_snapshot_ref", "source_text_digest",
        "source_run_id", "source_node_id", "source_artifact_id", "operation",
    ):
        value = normalized.get(field_name)
        if value is not None and (type(value) is not str or not value or value != value.strip()):
            raise TrustedExecutorRegistryError(
                "DATA_CONSUMER_RUNTIME_REQUEST_INVALID",
                f"{field_name} must be a non-empty string when present",
            )
    return normalized


def _execute_data_consumer_runtime_unavailable(
    context: object,
    request: Mapping[str, object],
) -> Mapping[str, object]:
    from workbench.agent.trusted_executor_registry import ProviderRuntimeContextV1

    if type(context) is not ProviderRuntimeContextV1:
        raise TypeError("data-consumer runtime requires a server runtime context")
    return {
        "status": "unavailable",
        "reason_code": "DATA_CONSUMER_HOST_DATA_STORE_UNAVAILABLE",
        "provider_id": "workbench.data_consumer",
        "adapter_id": "workbench.data_consumer.adapter",
        "executor_ref": "executor:workbench.data_consumer.adapter",
        "operation_id": str(request["operation_id"]),
        "execution_instance_hash": context.execution_instance_hash,
        "typed_authority": "DataConsumerOutputPortsV1",
    }


def _execute_data_consumer_runtime_with_port(
    context: object,
    request: Mapping[str, object],
    execution_port: DataConsumerExecutionPortV1,
) -> Mapping[str, object]:
    output = execution_port.execute(context, request)
    operation_id = str(request["operation_id"])
    if output.operation_id != operation_id:
        raise ValueError("data-consumer execution output operation does not match the request")
    return {
        "status": "completed",
        "reason_code": "DATA_CONSUMER_EXECUTED",
        "provider_id": "workbench.data_consumer",
        "adapter_id": "workbench.data_consumer.adapter",
        "executor_ref": "executor:workbench.data_consumer.adapter",
        "operation_id": operation_id,
        "execution_instance_hash": context.execution_instance_hash,
        "typed_authority": "DataConsumerOutputPortsV1",
        "output": output.to_dict(),
    }


def _validate_data_consumer_runtime_result(result: Mapping[str, object]) -> None:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistryError

    if not isinstance(result, Mapping) or result.get("status") not in {"unavailable", "completed"}:
        raise TrustedExecutorRegistryError(
            "DATA_CONSUMER_RUNTIME_RESULT_INVALID",
            "data-consumer runtime cannot claim completed without typed output ports",
        )
    expected = {
        "provider_id": "workbench.data_consumer",
        "adapter_id": "workbench.data_consumer.adapter",
        "executor_ref": "executor:workbench.data_consumer.adapter",
        "typed_authority": "DataConsumerOutputPortsV1",
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise TrustedExecutorRegistryError("DATA_CONSUMER_RUNTIME_RESULT_INVALID")
    operation_id = result.get("operation_id")
    if type(operation_id) is not str or operation_id not in _DATA_OPERATION_IDS:
        raise TrustedExecutorRegistryError("DATA_CONSUMER_RUNTIME_RESULT_INVALID")
    if any(key in result for key in ("rows", "path", "evidence")):
        raise TrustedExecutorRegistryError(
            "DATA_CONSUMER_RUNTIME_RESULT_INVALID",
            "unavailable data-consumer results cannot contain raw rows, paths or evidence",
        )
    if result.get("status") == "unavailable":
        if result.get("reason_code") != "DATA_CONSUMER_HOST_DATA_STORE_UNAVAILABLE":
            raise TrustedExecutorRegistryError("DATA_CONSUMER_RUNTIME_RESULT_INVALID")
        return
    if result.get("reason_code") != "DATA_CONSUMER_EXECUTED":
        raise TrustedExecutorRegistryError("DATA_CONSUMER_RUNTIME_RESULT_INVALID")
    output = result.get("output")
    if not isinstance(output, Mapping):
        raise TrustedExecutorRegistryError(
            "DATA_CONSUMER_RUNTIME_RESULT_INVALID",
            "completed data-consumer results require a typed output projection",
        )
    expected_output = {
        "record_id",
        "operation_id",
        "operation_version",
        "execution_key",
        "child_node_id",
        "artifact_ids",
        "evidence_digest",
        "catalog_digest",
    }
    if set(output) != expected_output:
        raise TrustedExecutorRegistryError(
            "DATA_CONSUMER_RUNTIME_RESULT_INVALID",
            "completed data-consumer output contains fields outside the typed projection",
        )
    if output.get("operation_id") != operation_id:
        raise TrustedExecutorRegistryError("DATA_CONSUMER_RUNTIME_RESULT_INVALID")
    for field_name in (
        "record_id",
        "operation_id",
        "operation_version",
        "execution_key",
        "child_node_id",
    ):
        value = output.get(field_name)
        if (
            type(value) is not str
            or not value
            or value != value.strip()
            or "/" in value
            or "\\" in value
            or ".." in value
        ):
            raise TrustedExecutorRegistryError("DATA_CONSUMER_RUNTIME_RESULT_INVALID")
    if type(output.get("artifact_ids")) is not list or not output["artifact_ids"]:
        raise TrustedExecutorRegistryError("DATA_CONSUMER_RUNTIME_RESULT_INVALID")
    if any(
        type(value) is not str
        or not value
        or "/" in value
        or "\\" in value
        or ".." in value
        for value in output["artifact_ids"]
    ):
        raise TrustedExecutorRegistryError(
            "DATA_CONSUMER_RUNTIME_RESULT_INVALID",
            "completed data-consumer output contains a path-like artifact identity",
        )
    if _SHA256_RE.fullmatch(str(output.get("evidence_digest"))) is None:
        raise TrustedExecutorRegistryError("DATA_CONSUMER_RUNTIME_RESULT_INVALID")
    if _SHA256_RE.fullmatch(str(output.get("catalog_digest"))) is None:
        raise TrustedExecutorRegistryError("DATA_CONSUMER_RUNTIME_RESULT_INVALID")


def build_data_consumer_runtime_contribution(
    catalog: object,
    *,
    execution_port: DataConsumerExecutionPortV1 | None = None,
) -> object:
    """Build the data contribution from an optional server-owned host port.

    Without a port the contribution remains explicitly unavailable.  A port
    can only enable execution when it is server-issued and bound to the exact
    catalog digest being composed.
    """

    from workbench.agent.trusted_executor_registry import ProviderRuntimeContributionV1
    from workbench.providers.catalog import ProviderCatalogV1, is_server_owned_catalog

    if type(catalog) is not ProviderCatalogV1 or not is_server_owned_catalog(catalog):
        raise ValueError("data-consumer runtime requires the exact server-loaded provider catalog")
    if execution_port is not None and type(execution_port) is not DataConsumerExecutionPortV1:
        raise TypeError("data-consumer runtime requires a server-issued execution port")
    if execution_port is not None and execution_port.catalog_digest != catalog.catalog_digest:
        raise ValueError("data-consumer execution port catalog digest does not match the catalog")
    providers = [provider for provider in catalog.providers if provider.provider_id == "workbench.data_consumer"]
    if len(providers) != 1:
        raise ValueError("workbench.data_consumer provider must be unique")
    provider = providers[0]
    declarations = [
        declaration
        for declaration in provider.adapter_declarations
        if declaration.adapter_id == "workbench.data_consumer.adapter"
    ]
    if len(declarations) != 1:
        raise ValueError("workbench.data_consumer adapter declaration must be unique")
    declaration = declarations[0]
    adapter = build_data_consumer_runtime_adapter()
    if execution_port is None:
        executor = _execute_data_consumer_runtime_unavailable
        execution_allowed = False
        metadata = {
            "status": "unavailable",
            "reason_code": "DATA_CONSUMER_HOST_DATA_STORE_UNAVAILABLE",
            "catalog_digest": catalog.catalog_digest,
            "output_ports": list(adapter.output_ports),
            "typed_authority": "DataConsumerOutputPortsV1",
        }
    else:
        def executor(context: object, request: Mapping[str, object]) -> Mapping[str, object]:
            return _execute_data_consumer_runtime_with_port(context, request, execution_port)

        execution_allowed = True
        metadata = {
            "status": "available",
            "reason_code": "DATA_CONSUMER_EXECUTED",
            "catalog_digest": catalog.catalog_digest,
            "output_ports": list(adapter.output_ports),
            "typed_authority": "DataConsumerOutputPortsV1",
        }
    return ProviderRuntimeContributionV1(
        provider_id=provider.provider_id,
        adapter_id=declaration.adapter_id,
        executor_ref=declaration.executor_ref,
        owner="workbench.server.data_consumer",
        signature="workbench.data_consumer.runtime.v1",
        effect="read_only",
        request_contract_ref=declaration.request_schema_ref,
        result_contract_refs=declaration.output_refs,
        executor=executor,
        request_validator=_validate_data_consumer_runtime_request,
        result_validator=_validate_data_consumer_runtime_result,
        execution_allowed=execution_allowed,
        metadata=metadata,
    )


def _issue_data_consumer_derived_port(effect: object) -> DataConsumerDerivedPortV1:
    return DataConsumerDerivedPortV1.from_server(effect, _issuer=_SERVER_OWNED_ISSUER)


def _issue_data_consumer_server_evidence(
    method: str,
    payload: Mapping[str, object],
    *,
    record_id: str,
    operation_id: str,
    execution_key: str,
    bindings: Mapping[str, object],
) -> DataConsumerServerEvidenceV1:
    return DataConsumerServerEvidenceV1.from_server(
        method,
        payload,
        record_id=record_id,
        operation_id=operation_id,
        execution_key=execution_key,
        bindings=bindings,
        _issuer=_SERVER_OWNED_ISSUER,
    )


def _issue_data_consumer_evidence_port(
    method: str,
    evidence: DataConsumerServerEvidenceV1,
) -> DataConsumerEvidencePortV1:
    return DataConsumerEvidencePortV1.from_server(method, evidence, _issuer=_SERVER_OWNED_ISSUER)


def _issue_data_consumer_output_ports(
    operation_record: OperationRecord,
    derived: DataConsumerDerivedPortV1,
    evidence: DataConsumerEvidencePortV1,
) -> DataConsumerOutputPortsV1:
    return DataConsumerOutputPortsV1.from_server(
        operation_record,
        derived,
        evidence,
        _issuer=_SERVER_OWNED_ISSUER,
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
    # Optional dependency admission is runtime state, not a provider
    # contract change. Keep the contract digest compatible with the
    # server-owned fixture while the live manifest still carries the typed
    # capability reason/message returned by data_interchange.
    unavailable = manifest.get("unavailable")
    if isinstance(unavailable, list):
        for item in unavailable:
            if (
                isinstance(item, dict)
                and item.get("operation_id") in _NATIVE_INTERCHANGE_IDS
                and item.get("reason_code") == "optional_dependency"
            ):
                item["message"] = (
                    "pyreadstat is not installed; native statistical-file "
                    "interchange is not advertised."
                )
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
                projection_refs=MappingProxyType(
                    {
                        "agent": refs["projection"],
                        "notebook": refs["projection"],
                        "report": refs["projection"],
                    }
                ),
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
        projection_declarations=(
            ConsumerProjectionDeclarationV1(
                path_id="workbench.data_consumer.operations",
                consumer_id="agent",
                projection_ref=refs["projection"],
                evidence_contract_refs=(refs["evidence"],),
                envelope_contract_refs=(),
                fact_kinds=("data_operation", "metadata"),
                policy_ref=refs["policy"],
                renderer_ref=refs["renderer"],
                max_token_budget=4096,
                max_row_budget=64,
                allowed_sensitivity=("public", "internal"),
                ordering=("fact_id",),
                coverage_status="required",
                exemption_reason=None,
            ),
            ConsumerProjectionDeclarationV1(
                path_id="workbench.data_consumer.operations",
                consumer_id="notebook",
                projection_ref=refs["projection"],
                evidence_contract_refs=(refs["evidence"],),
                envelope_contract_refs=(),
                fact_kinds=("data_operation", "metadata"),
                policy_ref=refs["policy"],
                renderer_ref=refs["renderer"],
                max_token_budget=4096,
                max_row_budget=64,
                allowed_sensitivity=("public", "internal"),
                ordering=("fact_id",),
                coverage_status="required",
                exemption_reason=None,
            ),
            ConsumerProjectionDeclarationV1(
                path_id="workbench.data_consumer.operations",
                consumer_id="report",
                projection_ref=refs["projection"],
                evidence_contract_refs=(refs["evidence"],),
                envelope_contract_refs=(),
                fact_kinds=("data_operation", "metadata"),
                policy_ref=refs["policy"],
                renderer_ref=refs["renderer"],
                max_token_budget=4096,
                max_row_budget=64,
                allowed_sensitivity=("public", "internal"),
                ordering=("fact_id",),
                coverage_status="required",
                exemption_reason=None,
            ),
        ),
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
    "DataConsumerHostOperationRequestV1",
    "DataConsumerHostOperationPortV1",
    "DataConsumerRuntimeAdapterV1",
    "DraftAgentNotebookFixture",
    "ReplayContractV1",
    "build_builtin_provider_payload",
    "build_data_operation_manifest",
    "build_data_consumer_runtime_contribution",
    "build_data_consumer_runtime_adapter",
    "draft_agent_notebook_composition_fixtures",
]
