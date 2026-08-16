"""Untrusted plan IR, server compilation records, confirmations and failures.

The objects here are intentionally separate from runtime execution.  A
client may serialize a draft or a parsed persistence record, but only a
``CompilationRecordStoreV1`` can issue the process-bound reference consumed by
the admission gate.  A field named ``trusted`` or a signature-looking string
is never used as authority.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from functools import wraps
from threading import Lock
from typing import Any

from workbench.canonical import CanonicalJSONError, canonical_json_v1, sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json


_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_JSON_SAFE_INTEGER = 9_007_199_254_740_991
_DRAFT_SCHEMA = "draft-agent-plan.v1"
_COMPILED_SCHEMA = "compiled-workflow.v1"
_RECORD_SCHEMA = "compilation-record.v1"
_SERVER_DRAFT_REF_SCHEMA = "server-draft-plan-ref.v1"
_REFERENCE_FIELDS = {"record_id", "record_digest", "semantic_plan_hash"}
_DRAFT_FIELDS = {
    "schema_version",
    "intent_ref",
    "capability_refs",
    "method_ref",
    "effect",
    "risk_level",
    "resource_budget",
    "data_impact",
    "output_contract_refs",
    "evidence_contract_refs",
    "contract_snapshot_refs",
    "catalog_snapshot_ref",
    "nodes",
    "connections",
    "config",
    "policy_snapshot_ref",
    "rationale",
    "semantic_plan_hash",
}
_COMPILED_FIELDS = {
    "schema_version",
    "intent_ref",
    "capability_refs",
    "method_ref",
    "effect",
    "risk_level",
    "resource_budget",
    "data_impact",
    "output_contract_refs",
    "evidence_contract_refs",
    "nodes",
    "connections",
    "config",
    "contract_snapshot_refs",
    "catalog_snapshot_ref",
    "policy_snapshot_ref",
    "compiler_version",
    "server_execution_identity",
    "preview_fingerprint",
    "plan_diff",
    "risk_level",
    "effect",
    "resource_budget",
    "semantic_plan_hash",
}
_RECORD_FIELDS = {
    "schema_version",
    "record_id",
    "principal_ref",
    "session_ref",
    "project_ref",
    "compiler_version",
    "contract_snapshot_refs",
    "catalog_snapshot_ref",
    "policy_snapshot_ref",
    "source_commitments",
    "compiled_workflow",
    "created_at",
    "expires_at",
    "semantic_plan_hash",
    "record_digest",
}
_DRAFT_FORBIDDEN_SERVER_FIELDS = frozenset(
    {
        "artifact_id",
        "artifact_ref",
        "artifact_digest",
        "node_ref",
        "run_id",
        "execution_key",
        "risk_authorization",
        "confirmation_id",
        "compiled_plan_hash",
        "server_execution_identity",
        "compilation_record_id",
    }
)
_DRAFT_FORBIDDEN_SENSITIVE_KEYS = frozenset(
    {
        "prompt",
        "raw_prompt",
        "secret",
        "raw_secret",
        "password",
        "api_key",
        "apikey",
        "access_token",
        "private_key",
        "credential",
    }
)
_DRAFT_FORBIDDEN_SENSITIVE_PREFIXES = ("raw:", "secret:", "prompt:", "token:")
_DRAFT_OPAQUE_REF_PREFIXES = ("prompt-ref:", "descriptor:", "symbol:", "rationale:", "intent:")
_DRAFT_TYPED_REF_PREFIXES = (
    "artifact:",
    "capability:",
    "catalog:",
    "column:",
    "connection:",
    "contract:",
    "dataset:",
    "descriptor:",
    "effect:",
    "evidence:",
    "metric:",
    "method:",
    "model:",
    "node:",
    "output:",
    "policy:",
    "port:",
    "prompt-ref:",
    "ref:",
    "rationale:",
    "run:",
    "schema:",
    "source:",
    "symbol:",
    "intent:",
)
_DRAFT_OPAQUE_REF_KEYS = frozenset(
    {
        "prompt_ref",
        "prompt_refs",
        "descriptor_ref",
        "descriptor_refs",
        "symbol_ref",
        "symbol_refs",
        "rationale_ref",
        "rationale_refs",
    }
)
_DRAFT_OPAQUE_REF_PREFIX_BY_KEY = {
    "prompt_ref": "prompt-ref:",
    "prompt_refs": "prompt-ref:",
    "descriptor_ref": "descriptor:",
    "descriptor_refs": "descriptor:",
    "symbol_ref": "symbol:",
    "symbol_refs": "symbol:",
    "rationale_ref": "rationale:",
    "rationale_refs": "rationale:",
}
_DRAFT_FREE_TEXT_KEYS = frozenset(
    {
        "body",
        "content",
        "description",
        "descriptions",
        "free_text",
        "instruction",
        "instructions",
        "message",
        "messages",
        "note",
        "notes",
        "rationale",
        "text",
    }
)
_DRAFT_TYPED_STRING_KEYS = frozenset(
    {
        "analysis_mode",
        "capability_ref",
        "column",
        "connection_id",
        "data_impact",
        "effect",
        "from_node",
        "kind",
        "method",
        "method_ref",
        "mode",
        "name",
        "node_id",
        "read_refs",
        "ref",
        "role",
        "scope",
        "solver",
        "source",
        "source_node",
        "source_port",
        "strategy",
        "target",
        "target_node",
        "target_port",
        "type",
        "value_kind",
        "write_refs",
        "write_mode",
        "to_node",
    }
)
_DRAFT_SENSITIVE_TEXT_MARKERS = (
    "prompt",
    "secret",
    "password",
    "credential",
    "api_key",
    "api key",
    "access_token",
    "private_key",
    "raw:",
)
_DRAFT_DURABLE_REF_KEYS = frozenset(
    {
        "actual",
        "artifact_ref",
        "capability_ref",
        "catalog_ref",
        "column",
        "column_ref",
        "connection_id",
        "connection_ref",
        "contract_ref",
        "dataset_ref",
        "descriptor_ref",
        "descriptor_refs",
        "evidence_ref",
        "evidence_refs",
        "feature",
        "from_node",
        "from_port",
        "group",
        "method_ref",
        "node_ref",
        "output_ref",
        "output_refs",
        "policy_ref",
        "port_ref",
        "prediction",
        "prompt_ref",
        "prompt_refs",
        "rationale_ref",
        "rationale_refs",
        "read_refs",
        "ref",
        "run_ref",
        "schema_ref",
        "source",
        "source_node",
        "source_port",
        "symbol_ref",
        "symbol_refs",
        "target",
        "target_node",
        "target_port",
        "to_node",
        "to_port",
        "weight",
        "write_refs",
    }
)
_DRAFT_DURABLE_REF_PREFIX_BY_KEY = {
    "actual": "column:",
    "artifact_ref": "artifact:",
    "capability_ref": "capability:",
    "catalog_ref": "catalog:",
    "column": "column:",
    "column_ref": "column:",
    "connection_id": "connection:",
    "connection_ref": "connection:",
    "contract_ref": "contract:",
    "dataset_ref": "dataset:",
    "descriptor_ref": "descriptor:",
    "descriptor_refs": "descriptor:",
    "evidence_ref": "evidence:",
    "evidence_refs": "evidence:",
    "feature": "column:",
    "from_node": "node:",
    "from_port": "port:",
    "group": "column:",
    "method_ref": "method:",
    "node_ref": "node:",
    "output_ref": "output:",
    "output_refs": "output:",
    "policy_ref": "policy:",
    "port_ref": "port:",
    "prediction": "column:",
    "prompt_ref": "prompt-ref:",
    "prompt_refs": "prompt-ref:",
    "rationale_ref": "rationale:",
    "rationale_refs": "rationale:",
    "read_refs": "dataset:",
    "ref": "ref:",
    "run_ref": "run:",
    "schema_ref": "schema:",
    "source": "source:",
    "source_node": "node:",
    "source_port": "port:",
    "symbol_ref": "symbol:",
    "symbol_refs": "symbol:",
    "target": "column:",
    "target_node": "node:",
    "target_port": "port:",
    "to_node": "node:",
    "to_port": "port:",
    "weight": "column:",
    "write_refs": "dataset:",
}
_DRAFT_DURABLE_ENUMS = {
    "analysis_mode": frozenset({"classification", "descriptive", "diagnostic", "inference", "predictive", "regression"}),
    "data_impact": frozenset({"none", "read_dataset", "read_model", "read_only", "write_dataset"}),
    "effect": frozenset({"model_evaluate", "model_fit", "model_predict", "none", "read", "report", "write"}),
    "kind": frozenset({"artifact", "dataset", "evidence", "metric", "model", "port", "schema"}),
    "mode": frozenset({"read", "read_only", "write"}),
    "role": frozenset({"actual", "feature", "group", "id", "prediction", "target", "time", "weight"}),
    "status": frozenset({"available", "complete", "completed", "ready", "validated"}),
    "type": frozenset({"boolean", "integer", "metric", "number", "reference", "scalar"}),
    "value_kind": frozenset({"boolean", "integer", "number", "reference", "scalar"}),
    "write_mode": frozenset({"append", "create", "none", "read_only", "replace"}),
}
_DRAFT_DURABLE_IDENTIFIER_KEYS = frozenset({"connection_name", "key", "name", "node_id", "port_name"})
_DRAFT_DURABLE_NUMBER_KEYS = frozenset(
    {"alpha", "cpu_ms", "limit", "max_rows", "max_tokens", "memory_mb", "probability", "seed", "threshold", "timeout_ms"}
)
_DRAFT_DURABLE_BOOLEAN_KEYS = frozenset({"allow_missing", "enabled", "include_intercept", "normalize", "strict"})
_DRAFT_DURABLE_MAPPING_KEYS = frozenset({"bounds", "constraints", "options", "parameters", "resource_budget", "roles"})
_DRAFT_DURABLE_ARRAY_NUMBER_KEYS = frozenset({"class_weights", "quantiles", "thresholds"})
_DRAFT_DURABLE_ALLOWED_KEYS = (
    _DRAFT_DURABLE_REF_KEYS
    | frozenset(_DRAFT_DURABLE_ENUMS)
    | _DRAFT_DURABLE_IDENTIFIER_KEYS
    | _DRAFT_DURABLE_NUMBER_KEYS
    | _DRAFT_DURABLE_BOOLEAN_KEYS
    | _DRAFT_DURABLE_MAPPING_KEYS
    | _DRAFT_DURABLE_ARRAY_NUMBER_KEYS
)
# The compiler capability and the exact record object are kept server-side.
# Neither appears on the wire or on ``CompilationRecordV1`` itself.  This is
# deliberately an identity registry rather than a client-controlled marker:
# parsing/constructing a record can never upgrade it to server authority.
_SERVER_COMPILER_CAPABILITIES: dict[int, object] = {}
_SERVER_COMPILER_ISSUER_CAPABILITIES: dict[int, object] = {}
_SERVER_DRAFT_REFERENCES: dict[int, tuple[object, object, object]] = {}
_SERVER_DRAFT_REGISTRATION_LOCK = Lock()
_SERVER_DRAFT_SEQUENCE = 0
_SERVER_COMPILATION_SEQUENCE = 0
_SERVER_COMPILER_VERSION = "compiler:1.8.9"
_SERVER_AUTHORIZED_COMPILED_WORKFLOWS: dict[int, tuple[object, object, str]] = {}
_SERVER_AUTHORIZED_RECORDS: dict[int, tuple[object, object]] = {}


def _is_server_authorized_record(value: object) -> bool:
    authority = _SERVER_AUTHORIZED_RECORDS.get(id(value))
    if authority is None or authority[0] is not value:
        return False
    capability = authority[1]
    return _SERVER_COMPILER_CAPABILITIES.get(id(capability)) is capability


def _is_server_authorized_compiled(value: object, capability: object) -> bool:
    authority = _SERVER_AUTHORIZED_COMPILED_WORKFLOWS.get(id(value))
    if (
        authority is None
        or authority[0] is not value
        or authority[1] is not capability
        or _SERVER_COMPILER_CAPABILITIES.get(id(capability)) is not capability
    ):
        return False
    try:
        return authority[2] == sha256_canonical(value.to_dict())
    except (AttributeError, CanonicalJSONError, ContractError, RecursionError, TypeError, ValueError):
        return False


class PlanningContractError(ContractError):
    """A planning contract failure with a stable public code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


class PlanRiskLevelV1(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    RESTRICTED = "restricted"


class PlanEffectV1(str, Enum):
    """The finite effect vocabulary allowed to cross the planning seam."""

    MODEL_EVALUATE = "model_evaluate"
    MODEL_FIT = "model_fit"
    MODEL_PREDICT = "model_predict"
    NONE = "none"
    READ = "read"
    REPORT = "report"
    WRITE = "write"


def _error(code: str, message: str) -> PlanningContractError:
    return PlanningContractError(code, message)


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise _error("PLANNING_TEXT_INVALID", f"{name} must be an exact non-empty string")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _error("PLANNING_DIGEST_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _enum(value: object, enum_type: type[Enum], name: str) -> Any:
    if type(value) is not str:
        raise _error("PLANNING_ENUM_INVALID", f"{name} is invalid")
    try:
        return enum_type(value)
    except ValueError as exc:
        raise _error("PLANNING_ENUM_INVALID", f"{name} is invalid") from exc


def _contract_ref(value: object, name: str) -> ContractRefV1:
    if type(value) is not dict:
        raise _error("PLANNING_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    try:
        return ContractRefV1.from_dict(value)
    except (ContractError, ValueError) as exc:
        raise _error("PLANNING_CONTRACT_REF_INVALID", f"{name} is invalid") from exc


def _ref_tuple(value: object, name: str) -> tuple[ContractRefV1, ...]:
    if type(value) is not list:
        raise _error("PLANNING_ARRAY_INVALID", f"{name} must be a built-in list")
    refs = tuple(_contract_ref(item, f"{name}[]") for item in value)
    identities = [(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs]
    if len(set(identities)) != len(identities):
        raise _error("PLANNING_DUPLICATE_ID", f"{name} contains duplicate identities")
    return refs


def _typed_ref_tuple(value: object, name: str) -> tuple[ContractRefV1, ...]:
    if not isinstance(value, (tuple, list)):
        raise _error("PLANNING_ARRAY_INVALID", f"{name} must be an array")
    refs = tuple(value)
    if any(type(ref) is not ContractRefV1 for ref in refs):
        raise _error("PLANNING_CONTRACT_REF_INVALID", f"{name} contains an invalid ref")
    identities = [(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs]
    if len(set(identities)) != len(identities):
        raise _error("PLANNING_DUPLICATE_ID", f"{name} contains duplicate identities")
    if not refs:
        raise _error("PLANNING_CONTRACT_REF_REQUIRED", f"{name} must not be empty")
    return refs


def _text_tuple(value: object, name: str) -> tuple[str, ...]:
    if type(value) is not list:
        raise _error("PLANNING_ARRAY_INVALID", f"{name} must be a built-in list")
    values = tuple(_text(item, f"{name}[]") for item in value)
    if len(set(values)) != len(values):
        raise _error("PLANNING_DUPLICATE_ID", f"{name} contains duplicate values")
    return values


def _validate_json(value: object, name: str, active: set[int] | None = None) -> None:
    if value is None or type(value) in {str, bool}:
        return
    if type(value) is int:
        if not -_MAX_JSON_SAFE_INTEGER <= value <= _MAX_JSON_SAFE_INTEGER:
            raise _error("PLANNING_JSON_INVALID", f"{name} contains a nonportable integer")
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise _error("PLANNING_JSON_INVALID", f"{name} contains a non-finite number")
        return
    if type(value) not in {dict, list, tuple}:
        raise _error("PLANNING_JSON_INVALID", f"{name} contains an unsupported value")
    active_ids = active if active is not None else set()
    value_id = id(value)
    if value_id in active_ids:
        raise _error("PLANNING_JSON_INVALID", f"{name} must be acyclic JSON")
    active_ids.add(value_id)
    try:
        children = value.values() if type(value) is dict else value
        if type(value) is dict and any(type(key) is not str for key in value):
            raise _error("PLANNING_JSON_INVALID", f"{name} keys must be strings")
        for child in children:
            _validate_json(child, f"{name}[]", active_ids)
    finally:
        active_ids.remove(value_id)


def _frozen_mapping(value: object, name: str) -> Mapping[str, Any]:
    if type(value) is not dict:
        raise _error("PLANNING_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    _validate_json(value, name)
    try:
        canonical_json_v1(value)
        frozen = freeze_json(value, name)
    except (
        AttributeError,
        CanonicalJSONError,
        ContractError,
        RecursionError,
        OverflowError,
        TypeError,
        ValueError,
    ) as exc:
        raise _error("PLANNING_JSON_INVALID", f"{name} must be canonical JSON") from exc
    if not isinstance(frozen, Mapping):  # pragma: no cover
        raise _error("PLANNING_JSON_INVALID", f"{name} must be an object")
    return frozen


def _frozen_nodes(value: object, name: str) -> tuple[Mapping[str, Any], ...]:
    if type(value) is not list:
        raise _error("PLANNING_ARRAY_INVALID", f"{name} must be a built-in list")
    nodes = tuple(_frozen_mapping(node, f"{name}[]") for node in value)
    identifiers: list[str] = []
    for node in nodes:
        node_id = node.get("node_id")
        if type(node_id) is not str or not node_id:
            raise _error("PLANNING_NODE_INVALID", "each node must have a node_id")
        identifiers.append(node_id)
        _reject_draft_server_fields(node, "node")
    if len(set(identifiers)) != len(identifiers):
        raise _error("PLANNING_DUPLICATE_ID", "nodes contain duplicate node_id values")
    return nodes


def _frozen_mappings(value: object, name: str) -> tuple[Mapping[str, Any], ...]:
    if type(value) is not list:
        raise _error("PLANNING_ARRAY_INVALID", f"{name} must be a built-in list")
    return tuple(_frozen_mapping(item, f"{name}[]") for item in value)


def _reject_draft_server_fields(value: object, name: str) -> None:
    if isinstance(value, Mapping):
        forbidden = _DRAFT_FORBIDDEN_SERVER_FIELDS.intersection(value)
        if forbidden:
            raise _error(
                "DRAFT_PLAN_SERVER_FIELD_FORBIDDEN",
                f"{name} contains a server-only field: {sorted(forbidden)[0]}",
            )
        for child in value.values():
            _reject_draft_server_fields(child, name)
    elif type(value) in {list, tuple}:
        for child in value:
            _reject_draft_server_fields(child, name)

def _reject_draft_sensitive_content(value: object, name: str, *, opaque_ref: bool = False) -> None:
    if opaque_ref and type(value) not in {str, list, tuple}:
        raise _error("DRAFT_OPAQUE_REF_REQUIRED", f"{name} must contain an opaque reference")
    if isinstance(value, Mapping):
        for key, child in value.items():
            lowered = key.casefold()
            if lowered in _DRAFT_OPAQUE_REF_KEYS:
                _reject_draft_sensitive_content(child, name, opaque_ref=True)
                continue
            if lowered in _DRAFT_FREE_TEXT_KEYS or lowered in _DRAFT_FORBIDDEN_SENSITIVE_KEYS or any(
                marker in lowered for marker in ("prompt", "secret", "password", "credential")
            ):
                raise _error(
                    "DRAFT_SENSITIVE_CONTENT_FORBIDDEN",
                    f"{name} contains a raw prompt or secret field",
                )
            _reject_draft_sensitive_content(child, name, opaque_ref=False)
    elif type(value) in {list, tuple}:
        for child in value:
            _reject_draft_sensitive_content(child, name, opaque_ref=opaque_ref)
    elif type(value) is str:
        if opaque_ref:
            _require_opaque_ref(value, name)
            return
        lowered = value.casefold()
        if lowered.startswith(_DRAFT_FORBIDDEN_SENSITIVE_PREFIXES) or any(
            marker in lowered for marker in _DRAFT_SENSITIVE_TEXT_MARKERS
        ):
            raise _error("DRAFT_SENSITIVE_CONTENT_FORBIDDEN", f"{name} contains raw sensitive content")


def _require_opaque_ref(
    value: object,
    name: str,
    prefixes: tuple[str, ...] = _DRAFT_OPAQUE_REF_PREFIXES,
) -> None:
    if type(value) is not str or not value or value != value.strip() or not value.startswith(prefixes):
        raise _error("DRAFT_OPAQUE_REF_REQUIRED", f"{name} must contain an explicit opaque reference")
    prefix = next(prefix for prefix in prefixes if value.startswith(prefix))
    suffix = value[len(prefix) :]
    if not suffix.strip() or any(char.isspace() for char in suffix):
        raise _error("DRAFT_OPAQUE_REF_REQUIRED", f"{name} must contain a non-empty opaque reference")


def _require_contract_ref_kind(value: object, expected_kind: str, name: str) -> ContractRefV1:
    if type(value) is not ContractRefV1 or value.kind != expected_kind:
        raise _error(
            "DRAFT_REF_KIND_INVALID",
            f"{name} must be a {expected_kind} contract reference",
        )
    return value


def _require_contract_ref_kinds(
    values: tuple[ContractRefV1, ...],
    expected_kind: str,
    name: str,
) -> None:
    for index, value in enumerate(values):
        _require_contract_ref_kind(value, expected_kind, f"{name}[{index}]")


def _durable_ref_prefixes(field_name: str | None) -> tuple[str, ...]:
    if field_name in _DRAFT_DURABLE_REF_PREFIX_BY_KEY:
        return (_DRAFT_DURABLE_REF_PREFIX_BY_KEY[field_name],)
    return _DRAFT_TYPED_REF_PREFIXES


def _validate_durable_option_value(value: object, name: str, field_name: str | None = None) -> None:
    """Allow only typed scalar/enum/ref shapes in durable plan maps."""

    if isinstance(value, Mapping):
        for key, child in value.items():
            if type(key) is not str:
                raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name} option keys must be strings")
            lowered = key.casefold()
            if lowered not in _DRAFT_DURABLE_ALLOWED_KEYS:
                raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name}.{key} is not an allowlisted durable field")
            if lowered in _DRAFT_DURABLE_REF_KEYS:
                prefixes = _durable_ref_prefixes(lowered)
                if type(child) is str:
                    _require_opaque_ref(child, f"{name}.{key}", prefixes)
                elif type(child) in {list, tuple}:
                    for index, item in enumerate(child):
                        _require_opaque_ref(item, f"{name}.{key}[{index}]", prefixes)
                else:
                    raise _error("DRAFT_OPAQUE_REF_REQUIRED", f"{name}.{key} must contain typed opaque references")
                continue
            if lowered in _DRAFT_DURABLE_ENUMS:
                if type(child) is not str or child not in _DRAFT_DURABLE_ENUMS[lowered]:
                    raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name}.{key} must contain an allowlisted enum")
                continue
            if lowered in _DRAFT_DURABLE_IDENTIFIER_KEYS:
                if type(child) is not str or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", child):
                    raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name}.{key} must contain a typed identifier")
                continue
            if lowered in _DRAFT_DURABLE_NUMBER_KEYS:
                if type(child) not in {int, float} or isinstance(child, bool) or not math.isfinite(child):
                    raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name}.{key} must contain a finite number")
                continue
            if lowered in _DRAFT_DURABLE_BOOLEAN_KEYS:
                if type(child) is not bool:
                    raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name}.{key} must contain a boolean")
                continue
            if lowered in _DRAFT_DURABLE_ARRAY_NUMBER_KEYS:
                if type(child) not in {list, tuple} or any(
                    type(item) not in {int, float} or isinstance(item, bool) or not math.isfinite(item)
                    for item in child
                ):
                    raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name}.{key} must contain numeric values")
                continue
            if lowered in _DRAFT_DURABLE_MAPPING_KEYS:
                if not isinstance(child, Mapping):
                    raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name}.{key} must contain a typed mapping")
                _validate_durable_option_value(child, f"{name}.{key}", lowered)
                continue
            raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name}.{key} is not a durable typed option")
        return
    if type(value) in {list, tuple}:
        if field_name in _DRAFT_DURABLE_REF_KEYS:
            prefixes = _durable_ref_prefixes(field_name)
            for index, child in enumerate(value):
                _require_opaque_ref(child, f"{name}[{index}]", prefixes)
            return
        if field_name in _DRAFT_DURABLE_ARRAY_NUMBER_KEYS:
            if any(type(child) not in {int, float} or isinstance(child, bool) or not math.isfinite(child) for child in value):
                raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name} must contain numeric values")
            return
        for index, child in enumerate(value):
            _validate_durable_option_value(child, f"{name}[{index}]", field_name)
        return
    if type(value) is str:
        if field_name in _DRAFT_DURABLE_ENUMS and value in _DRAFT_DURABLE_ENUMS[field_name]:
            return
        if field_name in _DRAFT_DURABLE_REF_KEYS:
            _require_opaque_ref(value, name, _durable_ref_prefixes(field_name))
            return
        if field_name in _DRAFT_DURABLE_IDENTIFIER_KEYS and re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}", value):
            return
        raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name} requires an allowlisted enum, number, boolean or opaque ref")
    if value is None or type(value) in {bool, int, float}:
        return
    raise _error("DRAFT_TYPED_OPTION_REQUIRED", f"{name} contains an unsupported durable option")


def _plain(value: object) -> object:
    try:
        return thaw_json(value)
    except (AttributeError, CanonicalJSONError, RecursionError, ValueError, TypeError) as exc:
        raise _error("PLANNING_JSON_INVALID", "value must be finite, acyclic JSON") from exc


def _wire_boundary(function):
    @wraps(function)
    def wrapped(cls, value):
        try:
            return function(cls, value)
        except PlanningContractError:
            raise
        except (
            AttributeError,
            CanonicalJSONError,
            ContractError,
            RecursionError,
            TypeError,
            ValueError,
        ) as exc:
            raise _error("PLANNING_WIRE_INVALID", "planning wire value is invalid") from exc

    return wrapped


def _semantic_payload(
    *,
    intent_ref: str,
    capability_refs: tuple[ContractRefV1, ...],
    method_ref: str,
    effect: PlanEffectV1,
    risk_level: PlanRiskLevelV1,
    resource_budget: Mapping[str, Any],
    data_impact: Mapping[str, Any],
    output_contract_refs: tuple[ContractRefV1, ...],
    evidence_contract_refs: tuple[ContractRefV1, ...],
    contract_snapshot_refs: tuple[ContractRefV1, ...],
    catalog_snapshot_ref: str,
    nodes: tuple[Mapping[str, Any], ...],
    connections: tuple[Mapping[str, Any], ...],
    config: Mapping[str, Any],
    policy_snapshot_ref: str,
) -> dict[str, object]:
    """Explicit semantic whitelist; server identity never enters this value."""

    return {
        # Draft and compiled envelopes are different trust phases, but they
        # intentionally share one semantic identity.  Phase/server identity
        # must never perturb a user-confirmed plan hash.
        "semantic_schema_version": "agent-plan-semantic.v1",
        "intent_ref": intent_ref,
        "capability_refs": [ref.to_dict() for ref in capability_refs],
        "method_ref": method_ref,
        "effect": effect.value,
        "risk_level": risk_level.value,
        "resource_budget": _plain(resource_budget),
        "data_impact": _plain(data_impact),
        "output_contract_refs": [ref.to_dict() for ref in output_contract_refs],
        "evidence_contract_refs": [ref.to_dict() for ref in evidence_contract_refs],
        "contract_snapshot_refs": [ref.to_dict() for ref in contract_snapshot_refs],
        "catalog_snapshot_ref": catalog_snapshot_ref,
        "nodes": [_plain(node) for node in nodes],
        "connections": [_plain(connection) for connection in connections],
        "config": _plain(config),
        "policy_snapshot_ref": policy_snapshot_ref,
    }


def _parse_timestamp(value: object, name: str) -> datetime:
    if type(value) is not str or not value or value != value.strip():
        raise _error("PLANNING_TIMESTAMP_INVALID", f"{name} must be an aware RFC3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise _error("PLANNING_TIMESTAMP_INVALID", f"{name} must be an aware RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _error("PLANNING_TIMESTAMP_INVALID", f"{name} must be timezone-aware")
    return parsed.astimezone(UTC)


def _wire(value: object, required: set[str], name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise _error("PLANNING_NESTED_DICT_REQUIRED", f"{name} must be a built-in dict")
    if any(type(key) is not str for key in value):
        raise _error("PLANNING_SCHEMA_INVALID", f"{name} keys must be strings")
    if set(value) != required:
        raise _error("PLANNING_SCHEMA_INVALID", f"{name} fields are not exact")
    return value


@dataclass(frozen=True)
class DraftAgentPlanV1:
    schema_version: str
    intent_ref: str
    capability_refs: tuple[ContractRefV1, ...]
    method_ref: str
    effect: PlanEffectV1
    risk_level: PlanRiskLevelV1
    resource_budget: Mapping[str, Any]
    data_impact: Mapping[str, Any]
    output_contract_refs: tuple[ContractRefV1, ...]
    evidence_contract_refs: tuple[ContractRefV1, ...]
    contract_snapshot_refs: tuple[ContractRefV1, ...]
    catalog_snapshot_ref: str
    nodes: tuple[Mapping[str, Any], ...]
    connections: tuple[Mapping[str, Any], ...]
    config: Mapping[str, Any]
    policy_snapshot_ref: str
    rationale: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _DRAFT_SCHEMA:
            raise _error("PLANNING_SCHEMA_INVALID", "draft schema_version is invalid")
        _require_opaque_ref(self.intent_ref, "intent_ref", ("intent:",))
        if not isinstance(self.capability_refs, (tuple, list)):
            raise _error("PLANNING_ARRAY_INVALID", "capability_refs must be an array")
        refs = tuple(self.capability_refs)
        if any(type(ref) is not ContractRefV1 for ref in refs):
            raise _error("PLANNING_CONTRACT_REF_INVALID", "capability_refs contain an invalid ref")
        if len({(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs}) != len(refs):
            raise _error("PLANNING_DUPLICATE_ID", "capability_refs contain duplicate identities")
        object.__setattr__(self, "capability_refs", refs)
        _text(self.method_ref, "method_ref")
        if type(self.effect) is not PlanEffectV1:
            raise _error("PLANNING_ENUM_INVALID", "effect is invalid")
        if type(self.risk_level) is not PlanRiskLevelV1:
            raise _error("PLANNING_ENUM_INVALID", "risk_level is invalid")
        object.__setattr__(self, "resource_budget", _frozen_mapping(_plain(self.resource_budget), "resource_budget"))
        _validate_durable_option_value(self.resource_budget, "resource_budget")
        object.__setattr__(self, "data_impact", _frozen_mapping(_plain(self.data_impact), "data_impact"))
        _validate_durable_option_value(self.data_impact, "data_impact")
        for name in ("output_contract_refs", "evidence_contract_refs", "contract_snapshot_refs"):
            object.__setattr__(self, name, _typed_ref_tuple(getattr(self, name), name))
        _require_contract_ref_kinds(self.capability_refs, "capability", "capability_refs")
        _require_contract_ref_kinds(self.output_contract_refs, "output-contract", "output_contract_refs")
        _require_contract_ref_kinds(self.evidence_contract_refs, "evidence-contract", "evidence_contract_refs")
        _require_contract_ref_kinds(self.contract_snapshot_refs, "contract", "contract_snapshot_refs")
        _require_opaque_ref(self.method_ref, "method_ref", ("method:",))
        _require_opaque_ref(self.catalog_snapshot_ref, "catalog_snapshot_ref", ("catalog:",))
        if not isinstance(self.nodes, (tuple, list)):
            raise _error("PLANNING_ARRAY_INVALID", "nodes must be an array")
        nodes = tuple(_frozen_mapping(_plain(node), "nodes[]") for node in self.nodes)
        for node in nodes:
            _reject_draft_server_fields(node, "node")
            _reject_draft_sensitive_content(node, "node")
            _validate_durable_option_value(node, "node")
            if type(node.get("node_id")) is not str or not node["node_id"]:
                raise _error("PLANNING_NODE_INVALID", "each node must have a node_id")
        if len({node["node_id"] for node in nodes}) != len(nodes):
            raise _error("PLANNING_DUPLICATE_ID", "nodes contain duplicate node_id values")
        object.__setattr__(self, "nodes", nodes)
        if not isinstance(self.connections, (tuple, list)):
            raise _error("PLANNING_ARRAY_INVALID", "connections must be an array")
        connections = tuple(_frozen_mapping(_plain(connection), "connections[]") for connection in self.connections)
        for connection in connections:
            _reject_draft_server_fields(connection, "connection")
            _reject_draft_sensitive_content(connection, "connection")
            _validate_durable_option_value(connection, "connection")
        object.__setattr__(self, "connections", connections)
        object.__setattr__(self, "config", _frozen_mapping(_plain(self.config), "config"))
        _reject_draft_server_fields(self.config, "config")
        _validate_durable_option_value(self.config, "config")
        _reject_draft_server_fields(self.data_impact, "data_impact")
        _reject_draft_sensitive_content(self.data_impact, "data_impact")
        _require_opaque_ref(self.policy_snapshot_ref, "policy_snapshot_ref", ("policy:",))
        if not isinstance(self.rationale, (tuple, list)):
            raise _error("PLANNING_ARRAY_INVALID", "rationale must be an array")
        rationale = tuple(_text(item, "rationale[]") for item in self.rationale)
        for item in rationale:
            try:
                _require_opaque_ref(item, "rationale[]", ("rationale:",))
            except PlanningContractError as exc:
                raise _error(
                    "DRAFT_RATIONALE_OPAQUE_REQUIRED",
                    "rationale must contain opaque rationale refs, not free text",
                ) from exc
        object.__setattr__(self, "rationale", rationale)

    def semantic_hash_input(self) -> dict[str, object]:
        return _semantic_payload(
            intent_ref=self.intent_ref,
            capability_refs=self.capability_refs,
            method_ref=self.method_ref,
            effect=self.effect,
            risk_level=self.risk_level,
            resource_budget=self.resource_budget,
            data_impact=self.data_impact,
            output_contract_refs=self.output_contract_refs,
            evidence_contract_refs=self.evidence_contract_refs,
            contract_snapshot_refs=self.contract_snapshot_refs,
            catalog_snapshot_ref=self.catalog_snapshot_ref,
            nodes=self.nodes,
            connections=self.connections,
            config=self.config,
            policy_snapshot_ref=self.policy_snapshot_ref,
        )

    @property
    def semantic_plan_hash(self) -> str:
        return sha256_canonical(self.semantic_hash_input())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intent_ref": self.intent_ref,
            "capability_refs": [ref.to_dict() for ref in self.capability_refs],
            "method_ref": self.method_ref,
            "effect": self.effect.value,
            "risk_level": self.risk_level.value,
            "resource_budget": _plain(self.resource_budget),
            "data_impact": _plain(self.data_impact),
            "output_contract_refs": [ref.to_dict() for ref in self.output_contract_refs],
            "evidence_contract_refs": [ref.to_dict() for ref in self.evidence_contract_refs],
            "contract_snapshot_refs": [ref.to_dict() for ref in self.contract_snapshot_refs],
            "catalog_snapshot_ref": self.catalog_snapshot_ref,
            "nodes": [_plain(node) for node in self.nodes],
            "connections": [_plain(connection) for connection in self.connections],
            "config": _plain(self.config),
            "policy_snapshot_ref": self.policy_snapshot_ref,
            "rationale": list(self.rationale),
            "semantic_plan_hash": self.semantic_plan_hash,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "DraftAgentPlanV1":
        value = _wire(value, _DRAFT_FIELDS, "draft_agent_plan")
        raw_nodes = value["nodes"]
        raw_connections = value["connections"]
        raw_resource_budget = value["resource_budget"]
        raw_data_impact = value["data_impact"]
        if type(raw_nodes) is not list or type(raw_connections) is not list:
            raise _error("PLANNING_ARRAY_INVALID", "nodes and connections must be built-in lists")
        if type(raw_resource_budget) is not dict or type(raw_data_impact) is not dict:
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "plan budgets and data impact must be built-in dicts")
        if any(type(item) is not dict for item in raw_nodes + raw_connections):
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "plan nodes and connections must be built-in dicts")
        plan = cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            intent_ref=value["intent_ref"],  # type: ignore[arg-type]
            capability_refs=tuple(_ref_tuple(value["capability_refs"], "capability_refs")),
            method_ref=value["method_ref"],  # type: ignore[arg-type]
            effect=_enum(value["effect"], PlanEffectV1, "effect"),
            risk_level=_enum(value["risk_level"], PlanRiskLevelV1, "risk_level"),
            resource_budget=_frozen_mapping(raw_resource_budget, "resource_budget"),
            data_impact=_frozen_mapping(raw_data_impact, "data_impact"),
            output_contract_refs=_ref_tuple(value["output_contract_refs"], "output_contract_refs"),
            evidence_contract_refs=_ref_tuple(value["evidence_contract_refs"], "evidence_contract_refs"),
            contract_snapshot_refs=_ref_tuple(value["contract_snapshot_refs"], "contract_snapshot_refs"),
            catalog_snapshot_ref=value["catalog_snapshot_ref"],  # type: ignore[arg-type]
            nodes=tuple(_frozen_nodes(raw_nodes, "nodes")),  # type: ignore[arg-type]
            connections=_frozen_mappings(raw_connections, "connections"),  # type: ignore[arg-type]
            config=_frozen_mapping(value["config"], "config"),  # type: ignore[arg-type]
            policy_snapshot_ref=value["policy_snapshot_ref"],  # type: ignore[arg-type]
            rationale=tuple(_text_tuple(value["rationale"], "rationale")),
        )
        if value["semantic_plan_hash"] != plan.semantic_plan_hash:
            raise _error("PLANNING_HASH_MISMATCH", "semantic_plan_hash does not match semantic fields")
        return plan


@dataclass(frozen=True)
class CompiledWorkflowV1:
    schema_version: str
    intent_ref: str
    capability_refs: tuple[ContractRefV1, ...]
    method_ref: str
    effect: PlanEffectV1
    risk_level: PlanRiskLevelV1
    resource_budget: Mapping[str, Any]
    data_impact: Mapping[str, Any]
    output_contract_refs: tuple[ContractRefV1, ...]
    evidence_contract_refs: tuple[ContractRefV1, ...]
    nodes: tuple[Mapping[str, Any], ...]
    connections: tuple[Mapping[str, Any], ...]
    config: Mapping[str, Any]
    contract_snapshot_refs: tuple[ContractRefV1, ...]
    catalog_snapshot_ref: str
    policy_snapshot_ref: str
    compiler_version: str
    server_execution_identity: str
    preview_fingerprint: str
    plan_diff: Mapping[str, Any]
    semantic_plan_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != _COMPILED_SCHEMA:
            raise _error("PLANNING_SCHEMA_INVALID", "compiled schema_version is invalid")
        _require_opaque_ref(self.intent_ref, "intent_ref", ("intent:",))
        for name, refs in (
            ("capability_refs", self.capability_refs),
            ("contract_snapshot_refs", self.contract_snapshot_refs),
            ("output_contract_refs", self.output_contract_refs),
            ("evidence_contract_refs", self.evidence_contract_refs),
        ):
            if not isinstance(refs, (tuple, list)) or any(type(ref) is not ContractRefV1 for ref in refs):
                raise _error("PLANNING_CONTRACT_REF_INVALID", f"{name} contains an invalid ref")
            object.__setattr__(self, name, tuple(refs))
        _require_contract_ref_kinds(self.capability_refs, "capability", "capability_refs")
        _require_contract_ref_kinds(self.output_contract_refs, "output-contract", "output_contract_refs")
        _require_contract_ref_kinds(self.evidence_contract_refs, "evidence-contract", "evidence_contract_refs")
        _require_contract_ref_kinds(self.contract_snapshot_refs, "contract", "contract_snapshot_refs")
        _text(self.method_ref, "method_ref")
        _require_opaque_ref(self.method_ref, "method_ref", ("method:",))
        if type(self.effect) is not PlanEffectV1:
            raise _error("PLANNING_ENUM_INVALID", "effect is invalid")
        if type(self.risk_level) is not PlanRiskLevelV1:
            raise _error("PLANNING_ENUM_INVALID", "risk_level is invalid")
        object.__setattr__(self, "resource_budget", _frozen_mapping(_plain(self.resource_budget), "resource_budget"))
        _validate_durable_option_value(self.resource_budget, "compiled resource_budget")
        object.__setattr__(self, "data_impact", _frozen_mapping(_plain(self.data_impact), "data_impact"))
        _validate_durable_option_value(self.data_impact, "compiled data_impact")
        if not isinstance(self.nodes, (tuple, list)) or any(not isinstance(node, Mapping) for node in self.nodes):
            raise _error("PLANNING_NODE_INVALID", "nodes are invalid")
        object.__setattr__(self, "nodes", tuple(_frozen_mapping(_plain(node), "nodes[]") for node in self.nodes))
        for node in self.nodes:
            _reject_draft_server_fields(node, "compiled node")
            _reject_draft_sensitive_content(node, "compiled node")
            _validate_durable_option_value(node, "compiled node")
        if not isinstance(self.connections, (tuple, list)) or any(not isinstance(item, Mapping) for item in self.connections):
            raise _error("PLANNING_NODE_INVALID", "connections are invalid")
        object.__setattr__(self, "connections", tuple(_frozen_mapping(_plain(item), "connections[]") for item in self.connections))
        for connection in self.connections:
            _reject_draft_server_fields(connection, "compiled connection")
            _reject_draft_sensitive_content(connection, "compiled connection")
            _validate_durable_option_value(connection, "compiled connection")
        object.__setattr__(self, "config", _frozen_mapping(_plain(self.config), "config"))
        _reject_draft_server_fields(self.config, "compiled config")
        _validate_durable_option_value(self.config, "compiled config")
        _reject_draft_server_fields(self.data_impact, "compiled data_impact")
        _reject_draft_sensitive_content(self.data_impact, "compiled data_impact")
        _require_opaque_ref(self.catalog_snapshot_ref, "catalog_snapshot_ref", ("catalog:",))
        _require_opaque_ref(self.policy_snapshot_ref, "policy_snapshot_ref", ("policy:",))
        _text(self.compiler_version, "compiler_version")
        _text(self.server_execution_identity, "server_execution_identity")
        _digest(self.preview_fingerprint, "preview_fingerprint")
        object.__setattr__(self, "plan_diff", _frozen_mapping(_plain(self.plan_diff), "plan_diff"))
        _reject_draft_server_fields(self.plan_diff, "compiled plan_diff")
        _validate_durable_option_value(self.plan_diff, "compiled plan_diff")
        _digest(self.semantic_plan_hash, "semantic_plan_hash")
        if self.semantic_plan_hash != sha256_canonical(self.semantic_hash_input()):
            raise _error("PLANNING_HASH_MISMATCH", "semantic_plan_hash does not match semantic fields")

    @classmethod
    def from_draft(
        cls,
        draft: DraftAgentPlanV1,
        *,
        compiler_version: str,
        server_execution_identity: str,
        preview_fingerprint: str,
        plan_diff: Mapping[str, Any],
        risk_level: PlanRiskLevelV1,
        effect: PlanEffectV1,
        resource_budget: Mapping[str, Any],
        contract_snapshot_refs: tuple[ContractRefV1, ...],
        catalog_snapshot_ref: str,
    ) -> "CompiledWorkflowV1":
        if type(draft) is not DraftAgentPlanV1:
            raise _error("PLANNING_DRAFT_INVALID", "only DraftAgentPlanV1 can be compiled")
        if effect != draft.effect or risk_level is not draft.risk_level or _plain(resource_budget) != _plain(draft.resource_budget):
            raise _error("PLANNING_SEMANTIC_MISMATCH", "compiled semantics must match the draft plan")
        if tuple(contract_snapshot_refs) != draft.contract_snapshot_refs or catalog_snapshot_ref != draft.catalog_snapshot_ref:
            raise _error("PLANNING_SNAPSHOT_MISMATCH", "compiled snapshots must be explicit and match the draft")
        return cls(
            schema_version=_COMPILED_SCHEMA,
            intent_ref=draft.intent_ref,
            capability_refs=draft.capability_refs,
            method_ref=draft.method_ref,
            effect=draft.effect,
            risk_level=draft.risk_level,
            resource_budget=draft.resource_budget,
            data_impact=draft.data_impact,
            output_contract_refs=draft.output_contract_refs,
            evidence_contract_refs=draft.evidence_contract_refs,
            nodes=draft.nodes,
            connections=draft.connections,
            config=draft.config,
            contract_snapshot_refs=contract_snapshot_refs,
            catalog_snapshot_ref=catalog_snapshot_ref,
            policy_snapshot_ref=draft.policy_snapshot_ref,
            compiler_version=compiler_version,
            server_execution_identity=server_execution_identity,
            preview_fingerprint=preview_fingerprint,
            plan_diff=plan_diff,
            semantic_plan_hash=draft.semantic_plan_hash,
        )

    def semantic_hash_input(self) -> dict[str, object]:
        return _semantic_payload(
            intent_ref=self.intent_ref,
            capability_refs=self.capability_refs,
            method_ref=self.method_ref,
            effect=self.effect,
            risk_level=self.risk_level,
            resource_budget=self.resource_budget,
            data_impact=self.data_impact,
            output_contract_refs=self.output_contract_refs,
            evidence_contract_refs=self.evidence_contract_refs,
            contract_snapshot_refs=self.contract_snapshot_refs,
            catalog_snapshot_ref=self.catalog_snapshot_ref,
            nodes=self.nodes,
            connections=self.connections,
            config=self.config,
            policy_snapshot_ref=self.policy_snapshot_ref,
        )

    def execution_instance_hash(
        self,
        resolved_artifact_digests: Mapping[str, str],
        *,
        resolved_run_identity: str,
        resolved_node_identities: Mapping[str, str],
    ) -> str:
        if type(resolved_artifact_digests) is not dict:
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "resolved_artifact_digests must be a built-in dict")
        normalized: dict[str, str] = {}
        for ref, digest in resolved_artifact_digests.items():
            _text(ref, "resolved_artifact_digests key")
            normalized[ref] = _digest(digest, "resolved_artifact_digests value") or digest
        if not normalized:
            raise _error("PLANNING_ARTIFACTS_REQUIRED", "execution hash requires resolved artifact digests")
        _text(resolved_run_identity, "resolved_run_identity")
        if type(resolved_node_identities) is not dict or not resolved_node_identities:
            raise _error("PLANNING_NODE_IDENTITY_REQUIRED", "execution hash requires resolved node identities")
        normalized_nodes = {
            _text(node_ref, "resolved_node_identities key"): _text(node_id, "resolved_node_identities value")
            for node_ref, node_id in resolved_node_identities.items()
        }
        return sha256_canonical(
            {
                "semantic_plan_hash": self.semantic_plan_hash,
                "server_execution_identity": self.server_execution_identity,
                "resolved_run_identity": resolved_run_identity,
                "resolved_node_identities": normalized_nodes,
                "resolved_artifact_digests": normalized,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intent_ref": self.intent_ref,
            "capability_refs": [ref.to_dict() for ref in self.capability_refs],
            "method_ref": self.method_ref,
            "effect": self.effect.value,
            "risk_level": self.risk_level.value,
            "resource_budget": _plain(self.resource_budget),
            "data_impact": _plain(self.data_impact),
            "output_contract_refs": [ref.to_dict() for ref in self.output_contract_refs],
            "evidence_contract_refs": [ref.to_dict() for ref in self.evidence_contract_refs],
            "nodes": [_plain(node) for node in self.nodes],
            "connections": [_plain(connection) for connection in self.connections],
            "config": _plain(self.config),
            "contract_snapshot_refs": [ref.to_dict() for ref in self.contract_snapshot_refs],
            "catalog_snapshot_ref": self.catalog_snapshot_ref,
            "policy_snapshot_ref": self.policy_snapshot_ref,
            "compiler_version": self.compiler_version,
            "server_execution_identity": self.server_execution_identity,
            "preview_fingerprint": self.preview_fingerprint,
            "plan_diff": _plain(self.plan_diff),
            "semantic_plan_hash": self.semantic_plan_hash,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "CompiledWorkflowV1":
        value = _wire(value, _COMPILED_FIELDS, "compiled_workflow")
        raw_nodes = value["nodes"]
        raw_connections = value["connections"]
        raw_resource_budget = value["resource_budget"]
        raw_data_impact = value["data_impact"]
        if type(raw_nodes) is not list or type(raw_connections) is not list:
            raise _error("PLANNING_ARRAY_INVALID", "nodes and connections must be built-in lists")
        if type(raw_resource_budget) is not dict or type(raw_data_impact) is not dict:
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "compiled budgets and data impact must be built-in dicts")
        if any(type(item) is not dict for item in raw_nodes + raw_connections):
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "nodes and connections must be built-in dicts")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            intent_ref=value["intent_ref"],  # type: ignore[arg-type]
            capability_refs=_ref_tuple(value["capability_refs"], "capability_refs"),
            method_ref=value["method_ref"],  # type: ignore[arg-type]
            effect=_enum(value["effect"], PlanEffectV1, "effect"),
            risk_level=_enum(value["risk_level"], PlanRiskLevelV1, "risk_level"),
            resource_budget=_frozen_mapping(raw_resource_budget, "resource_budget"),
            data_impact=_frozen_mapping(raw_data_impact, "data_impact"),
            output_contract_refs=_ref_tuple(value["output_contract_refs"], "output_contract_refs"),
            evidence_contract_refs=_ref_tuple(value["evidence_contract_refs"], "evidence_contract_refs"),
            nodes=tuple(_frozen_nodes(raw_nodes, "nodes")),  # type: ignore[arg-type]
            connections=_frozen_mappings(raw_connections, "connections"),  # type: ignore[arg-type]
            config=_frozen_mapping(value["config"], "config"),  # type: ignore[arg-type]
            contract_snapshot_refs=_ref_tuple(value["contract_snapshot_refs"], "contract_snapshot_refs"),
            catalog_snapshot_ref=value["catalog_snapshot_ref"],  # type: ignore[arg-type]
            policy_snapshot_ref=value["policy_snapshot_ref"],  # type: ignore[arg-type]
            compiler_version=value["compiler_version"],  # type: ignore[arg-type]
            server_execution_identity=value["server_execution_identity"],  # type: ignore[arg-type]
            preview_fingerprint=value["preview_fingerprint"],  # type: ignore[arg-type]
            plan_diff=_frozen_mapping(value["plan_diff"], "plan_diff"),  # type: ignore[arg-type]
            semantic_plan_hash=value["semantic_plan_hash"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, init=False)
class ServerDraftPlanReferenceV1:
    """Opaque server registration for a server-created draft plan copy."""

    draft_ref: str
    semantic_plan_hash: str
    draft_digest: str

    @classmethod
    def _new(
        cls,
        *,
        draft_ref: str,
        semantic_plan_hash: str,
        draft_digest: str,
    ) -> "ServerDraftPlanReferenceV1":
        _require_opaque_ref(draft_ref, "draft_ref", ("draft-plan:",))
        _digest(semantic_plan_hash, "semantic_plan_hash")
        _digest(draft_digest, "draft_digest")
        value = object.__new__(cls)
        object.__setattr__(value, "draft_ref", draft_ref)
        object.__setattr__(value, "semantic_plan_hash", semantic_plan_hash)
        object.__setattr__(value, "draft_digest", draft_digest)
        return value

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": _SERVER_DRAFT_REF_SCHEMA,
            "draft_ref": self.draft_ref,
            "semantic_plan_hash": self.semantic_plan_hash,
            "draft_digest": self.draft_digest,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "ServerDraftPlanReferenceV1":
        value = _wire(
            value,
            {"schema_version", "draft_ref", "semantic_plan_hash", "draft_digest"},
            "server_draft_plan_reference",
        )
        if value["schema_version"] != _SERVER_DRAFT_REF_SCHEMA:
            raise _error("PLANNING_SCHEMA_INVALID", "server draft reference schema_version is invalid")
        return cls._new(
            draft_ref=value["draft_ref"],  # type: ignore[arg-type]
            semantic_plan_hash=value["semantic_plan_hash"],  # type: ignore[arg-type]
            draft_digest=value["draft_digest"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class CompilationRecordReferenceV1:
    record_id: str
    record_digest: str
    semantic_plan_hash: str

    def __post_init__(self) -> None:
        _text(self.record_id, "record_id")
        _digest(self.record_digest, "record_digest")
        _digest(self.semantic_plan_hash, "semantic_plan_hash")

    def to_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "record_digest": self.record_digest,
            "semantic_plan_hash": self.semantic_plan_hash,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "CompilationRecordReferenceV1":
        value = _wire(value, _REFERENCE_FIELDS, "compilation_record_reference")
        return cls(
            record_id=value["record_id"],  # type: ignore[arg-type]
            record_digest=value["record_digest"],  # type: ignore[arg-type]
            semantic_plan_hash=value["semantic_plan_hash"],  # type: ignore[arg-type]
        )


@dataclass(frozen=True, init=False)
class ServerCompilationRecordReferenceV1:
    record_id: str
    record_digest: str
    semantic_plan_hash: str
    _issuer_token: object

    @classmethod
    def _issue(
        cls,
        reference: CompilationRecordReferenceV1,
        issuer_token: object,
    ) -> "ServerCompilationRecordReferenceV1":
        value = object.__new__(cls)
        object.__setattr__(value, "record_id", reference.record_id)
        object.__setattr__(value, "record_digest", reference.record_digest)
        object.__setattr__(value, "semantic_plan_hash", reference.semantic_plan_hash)
        object.__setattr__(value, "_issuer_token", issuer_token)
        return value

    def to_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "record_digest": self.record_digest,
            "semantic_plan_hash": self.semantic_plan_hash,
        }

    def as_untrusted_reference(self) -> CompilationRecordReferenceV1:
        return CompilationRecordReferenceV1(
            record_id=self.record_id,
            record_digest=self.record_digest,
            semantic_plan_hash=self.semantic_plan_hash,
        )


@dataclass(frozen=True)
class CompilationRecordV1:
    schema_version: str
    record_id: str
    principal_ref: str
    session_ref: str
    project_ref: str
    compiler_version: str
    contract_snapshot_refs: tuple[ContractRefV1, ...]
    catalog_snapshot_ref: str
    policy_snapshot_ref: str
    source_commitments: Mapping[str, Any]
    compiled_workflow: CompiledWorkflowV1
    created_at: str
    expires_at: str
    semantic_plan_hash: str
    record_digest: str

    def __post_init__(self) -> None:
        if self.schema_version != _RECORD_SCHEMA:
            raise _error("PLANNING_SCHEMA_INVALID", "compilation record schema_version is invalid")
        _text(self.record_id, "record_id")
        for name, value in (
            ("principal_ref", self.principal_ref),
            ("session_ref", self.session_ref),
            ("project_ref", self.project_ref),
            ("compiler_version", self.compiler_version),
            ("catalog_snapshot_ref", self.catalog_snapshot_ref),
            ("policy_snapshot_ref", self.policy_snapshot_ref),
        ):
            _text(value, name)
        if not isinstance(self.contract_snapshot_refs, (tuple, list)) or any(
            type(ref) is not ContractRefV1 for ref in self.contract_snapshot_refs
        ):
            raise _error("PLANNING_CONTRACT_REF_INVALID", "contract_snapshot_refs are invalid")
        object.__setattr__(self, "contract_snapshot_refs", tuple(self.contract_snapshot_refs))
        _require_contract_ref_kinds(self.contract_snapshot_refs, "contract", "contract_snapshot_refs")
        _require_opaque_ref(self.catalog_snapshot_ref, "catalog_snapshot_ref", ("catalog:",))
        _require_opaque_ref(self.policy_snapshot_ref, "policy_snapshot_ref", ("policy:",))
        object.__setattr__(self, "source_commitments", _frozen_mapping(_plain(self.source_commitments), "source_commitments"))
        if type(self.compiled_workflow) is not CompiledWorkflowV1:
            raise _error("PLANNING_COMPILED_INVALID", "compiled_workflow is invalid")
        _parse_timestamp(self.created_at, "created_at")
        created = _parse_timestamp(self.created_at, "created_at")
        expires = _parse_timestamp(self.expires_at, "expires_at")
        if expires <= created:
            raise _error("PLANNING_EXPIRY_INVALID", "expires_at must be after created_at")
        _digest(self.semantic_plan_hash, "semantic_plan_hash")
        if self.semantic_plan_hash != self.compiled_workflow.semantic_plan_hash:
            raise _error("PLANNING_HASH_MISMATCH", "record semantic_plan_hash mismatches compiled workflow")
        _digest(self.record_digest, "record_digest")
        if self.record_digest != self._computed_record_digest():
            raise _error("PLANNING_DIGEST_MISMATCH", "record_digest does not match record fields")

    @classmethod
    def from_compiled(
        cls,
        compiled: CompiledWorkflowV1,
        *,
        record_id: str,
        principal_ref: str,
        session_ref: str,
        project_ref: str,
        source_commitments: Mapping[str, Any],
        created_at: str,
        expires_at: str,
    ) -> "CompilationRecordV1":
        payload = {
            "schema_version": _RECORD_SCHEMA,
            "record_id": record_id,
            "principal_ref": principal_ref,
            "session_ref": session_ref,
            "project_ref": project_ref,
            "compiler_version": compiled.compiler_version,
            "contract_snapshot_refs": [ref.to_dict() for ref in compiled.contract_snapshot_refs],
            "catalog_snapshot_ref": compiled.catalog_snapshot_ref,
            "policy_snapshot_ref": compiled.policy_snapshot_ref,
            "source_commitments": _plain(_frozen_mapping(_plain(source_commitments), "source_commitments")),
            "compiled_workflow": compiled.to_dict(),
            "created_at": created_at,
            "expires_at": expires_at,
            "semantic_plan_hash": compiled.semantic_plan_hash,
        }
        return cls(
            schema_version=_RECORD_SCHEMA,
            record_id=record_id,
            principal_ref=principal_ref,
            session_ref=session_ref,
            project_ref=project_ref,
            compiler_version=compiled.compiler_version,
            contract_snapshot_refs=compiled.contract_snapshot_refs,
            catalog_snapshot_ref=compiled.catalog_snapshot_ref,
            policy_snapshot_ref=compiled.policy_snapshot_ref,
            source_commitments=_frozen_mapping(_plain(source_commitments), "source_commitments"),
            compiled_workflow=compiled,
            created_at=created_at,
            expires_at=expires_at,
            semantic_plan_hash=compiled.semantic_plan_hash,
            record_digest=sha256_canonical(payload),
        )

    @classmethod
    def _from_server_compiled(
        cls,
        compiled: CompiledWorkflowV1,
        *,
        _compiler_capability: object | None = None,
        **kwargs: Any,
    ) -> "CompilationRecordV1":
        """Private server seam requiring a registered compiler capability."""

        if (
            type(compiled) is not CompiledWorkflowV1
            or _compiler_capability is None
            or not _is_server_authorized_compiled(compiled, _compiler_capability)
        ):
            raise _error(
                "SERVER_COMPILER_AUTHORITY_REQUIRED",
                "private record construction requires a registered server compiler capability",
            )
        record = cls.from_compiled(compiled, **kwargs)
        _SERVER_AUTHORIZED_RECORDS[id(record)] = (record, _compiler_capability)
        return record

    def _record_payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "record_id": self.record_id,
            "principal_ref": self.principal_ref,
            "session_ref": self.session_ref,
            "project_ref": self.project_ref,
            "compiler_version": self.compiler_version,
            "contract_snapshot_refs": [ref.to_dict() for ref in self.contract_snapshot_refs],
            "catalog_snapshot_ref": self.catalog_snapshot_ref,
            "policy_snapshot_ref": self.policy_snapshot_ref,
            "source_commitments": _plain(self.source_commitments),
            "compiled_workflow": self.compiled_workflow.to_dict(),
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "semantic_plan_hash": self.semantic_plan_hash,
        }

    def _computed_record_digest(self) -> str:
        return sha256_canonical(self._record_payload())

    @property
    def reference(self) -> CompilationRecordReferenceV1:
        return CompilationRecordReferenceV1(
            record_id=self.record_id,
            record_digest=self.record_digest,
            semantic_plan_hash=self.semantic_plan_hash,
        )

    def to_dict(self) -> dict[str, object]:
        return {**self._record_payload(), "record_digest": self.record_digest}

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "CompilationRecordV1":
        value = _wire(value, _RECORD_FIELDS, "compilation_record")
        raw_refs = value["contract_snapshot_refs"]
        if type(raw_refs) is not list:
            raise _error("PLANNING_ARRAY_INVALID", "contract_snapshot_refs must be a built-in list")
        raw_source = value["source_commitments"]
        raw_compiled = value["compiled_workflow"]
        if type(raw_source) is not dict or type(raw_compiled) is not dict:
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "record nested objects must be built-in dicts")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            record_id=value["record_id"],  # type: ignore[arg-type]
            principal_ref=value["principal_ref"],  # type: ignore[arg-type]
            session_ref=value["session_ref"],  # type: ignore[arg-type]
            project_ref=value["project_ref"],  # type: ignore[arg-type]
            compiler_version=value["compiler_version"],  # type: ignore[arg-type]
            contract_snapshot_refs=_ref_tuple(raw_refs, "contract_snapshot_refs"),
            catalog_snapshot_ref=value["catalog_snapshot_ref"],  # type: ignore[arg-type]
            policy_snapshot_ref=value["policy_snapshot_ref"],  # type: ignore[arg-type]
            source_commitments=_frozen_mapping(raw_source, "source_commitments"),  # type: ignore[arg-type]
            compiled_workflow=CompiledWorkflowV1.from_dict(raw_compiled),
            created_at=value["created_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
            semantic_plan_hash=value["semantic_plan_hash"],  # type: ignore[arg-type]
            record_digest=value["record_digest"],  # type: ignore[arg-type]
        )


class CompilationRecordStoreV1:
    """The only issuer/verifier seam for server compilation references."""

    def __init__(self) -> None:
        self._issuer_token = object()
        self._records: dict[tuple[str, str], CompilationRecordV1] = {}

    def issue(self, record: CompilationRecordV1) -> ServerCompilationRecordReferenceV1:
        raise _error(
            "SERVER_COMPILER_AUTHORITY_REQUIRED",
            "client records cannot be issued; server compiler authority is required",
        )

    def _issue_server(self, record: CompilationRecordV1) -> ServerCompilationRecordReferenceV1:
        if type(record) is not CompilationRecordV1 or not _is_server_authorized_record(record):
            raise _error("SERVER_COMPILER_AUTHORITY_REQUIRED", "record was not produced by the server compiler")
        self._records[(record.record_id, record.record_digest)] = record
        return ServerCompilationRecordReferenceV1._issue(record.reference, self._issuer_token)

    def resolve_client_reference(
        self,
        reference: CompilationRecordReferenceV1,
    ) -> tuple[CompilationRecordV1, ServerCompilationRecordReferenceV1]:
        if type(reference) is not CompilationRecordReferenceV1:
            raise _error("SERVER_RECORD_REFERENCE_REQUIRED", "client input must be an untrusted record reference")
        record = self._records.get((reference.record_id, reference.record_digest))
        if record is None or record.semantic_plan_hash != reference.semantic_plan_hash:
            raise _error("SERVER_RECORD_UNRESOLVED", "compilation record reference is not server-resolved")
        return record, ServerCompilationRecordReferenceV1._issue(record.reference, self._issuer_token)

    def resolve(self, reference: ServerCompilationRecordReferenceV1) -> CompilationRecordV1:
        if type(reference) is not ServerCompilationRecordReferenceV1:
            raise _error("SERVER_RECORD_REFERENCE_REQUIRED", "runtime requires a server-owned record reference")
        if reference._issuer_token is not self._issuer_token:
            raise _error("SERVER_RECORD_REFERENCE_REQUIRED", "record reference was not issued by this server store")
        record = self._records.get((reference.record_id, reference.record_digest))
        if record is None or record.semantic_plan_hash != reference.semantic_plan_hash:
            raise _error("SERVER_RECORD_UNRESOLVED", "server compilation record is unavailable")
        return record


class ServerCompilationRecordIssuerV1:
    """Server-owned compiler/issuer seam; persistence parsing is never authority."""

    def __init__(self, store: CompilationRecordStoreV1 | None = None) -> None:
        if store is not None and type(store) is not CompilationRecordStoreV1:
            raise _error("SERVER_RECORD_STORE_REQUIRED", "server compiler requires a compilation record store")
        self.store = store
        capability = object()
        _SERVER_COMPILER_CAPABILITIES[id(capability)] = capability
        _SERVER_COMPILER_ISSUER_CAPABILITIES[id(self)] = capability

    def register_draft(self, draft: DraftAgentPlanV1) -> ServerDraftPlanReferenceV1:
        """Create a server-owned draft copy and return its opaque registration."""

        if type(draft) is not DraftAgentPlanV1:
            raise _error("SERVER_DRAFT_REQUIRED", "server compiler requires a typed draft plan")
        capability = _SERVER_COMPILER_ISSUER_CAPABILITIES.get(id(self))
        if capability is None or _SERVER_COMPILER_CAPABILITIES.get(id(capability)) is not capability:
            raise _error("SERVER_COMPILER_AUTHORITY_REQUIRED", "server compiler capability is unavailable")
        try:
            server_draft = DraftAgentPlanV1.from_dict(draft.to_dict())
        except (AttributeError, PlanningContractError, TypeError, ValueError) as exc:
            raise _error("SERVER_DRAFT_INVALID", "server compiler could not register the draft plan") from exc
        global _SERVER_DRAFT_SEQUENCE
        with _SERVER_DRAFT_REGISTRATION_LOCK:
            _SERVER_DRAFT_SEQUENCE += 1
            draft_ref = f"draft-plan:{_SERVER_DRAFT_SEQUENCE}"
            value = ServerDraftPlanReferenceV1._new(
                draft_ref=draft_ref,
                semantic_plan_hash=server_draft.semantic_plan_hash,
                draft_digest=sha256_canonical(server_draft.to_dict()),
            )
            _SERVER_DRAFT_REFERENCES[id(value)] = (value, capability, server_draft)
            return value

    def compile_workflow(
        self,
        draft_reference: object,
        compiled: object | None = None,
        *,
        compiler_version: object = None,
        server_execution_identity: object = None,
        preview_fingerprint: object = None,
        plan_diff: object = None,
    ) -> CompiledWorkflowV1:
        """Compile only from a live server-registered draft reference.

        ``compiled`` is retained as a positional compatibility trap so an old
        caller gets a stable contract error rather than Python's ``TypeError``.
        A client/wire compiled object is never promoted; this seam constructs
        the compiled workflow from the server-owned draft copy itself. Compiler
        provenance is generated inside this seam, so caller-supplied compiler
        versions, execution identities, previews, or diffs are rejected.
        """

        if type(draft_reference) is not ServerDraftPlanReferenceV1:
            raise _error(
                "SERVER_DRAFT_REGISTRATION_REQUIRED",
                "server compiler requires a live registered draft reference",
            )
        if compiled is not None:
            raise _error(
                "SERVER_COMPILED_INPUT_FORBIDDEN",
                "server compiler constructs compiled workflows; client compiled input is not accepted",
            )
        if any(
            value is not None
            for value in (compiler_version, server_execution_identity, preview_fingerprint, plan_diff)
        ):
            raise _error(
                "SERVER_COMPILER_PROVENANCE_FORBIDDEN",
                "compiler provenance is generated by the server compiler",
            )
        reference_entry = _SERVER_DRAFT_REFERENCES.get(id(draft_reference))
        if reference_entry is None or reference_entry[0] is not draft_reference:
            raise _error("SERVER_DRAFT_REGISTRATION_REQUIRED", "draft reference was not issued by this server compiler")
        capability = _SERVER_COMPILER_ISSUER_CAPABILITIES.get(id(self))
        if capability is None or reference_entry[1] is not capability:
            raise _error("SERVER_COMPILER_AUTHORITY_REQUIRED", "draft reference is outside this server compiler scope")
        server_draft = reference_entry[2]
        if type(server_draft) is not DraftAgentPlanV1:
            raise _error("SERVER_DRAFT_INVALID", "registered server draft is invalid")
        if (
            draft_reference.semantic_plan_hash != server_draft.semantic_plan_hash
            or draft_reference.draft_digest != sha256_canonical(server_draft.to_dict())
        ):
            raise _error("SERVER_DRAFT_HASH_MISMATCH", "compiled workflow does not match the registered server draft")
        global _SERVER_COMPILATION_SEQUENCE
        with _SERVER_DRAFT_REGISTRATION_LOCK:
            _SERVER_COMPILATION_SEQUENCE += 1
            server_execution_identity = f"compile:server:{_SERVER_COMPILATION_SEQUENCE}"
        compiler_version = _SERVER_COMPILER_VERSION
        preview_fingerprint = sha256_canonical(
            {
                "semantic_plan_hash": server_draft.semantic_plan_hash,
                "compiler_version": compiler_version,
                "draft_ref": draft_reference.draft_ref,
            }
        )
        plan_diff = {
            "effect": server_draft.effect.value,
            "data_impact": "read_dataset" if "read_refs" in server_draft.data_impact else "none",
        }
        try:
            server_compiled = CompiledWorkflowV1.from_draft(
                server_draft,
                compiler_version=compiler_version,
                server_execution_identity=server_execution_identity,
                preview_fingerprint=preview_fingerprint,
                plan_diff=plan_diff,
                risk_level=server_draft.risk_level,
                effect=server_draft.effect,
                resource_budget=server_draft.resource_budget,
                contract_snapshot_refs=server_draft.contract_snapshot_refs,
                catalog_snapshot_ref=server_draft.catalog_snapshot_ref,
            )
        except (AttributeError, CanonicalJSONError, RecursionError, PlanningContractError, TypeError, ValueError) as exc:
            raise _error("SERVER_COMPILE_INVALID", "server compiler could not compile the registered draft") from exc
        _SERVER_AUTHORIZED_COMPILED_WORKFLOWS[id(server_compiled)] = (
            server_compiled,
            capability,
            sha256_canonical(server_compiled.to_dict()),
        )
        return server_compiled

    def compile_record(self, compiled: CompiledWorkflowV1, **kwargs: Any) -> CompilationRecordV1:
        if type(compiled) is not CompiledWorkflowV1:
            raise _error("SERVER_COMPILED_REQUIRED", "server compiler requires a compiled workflow")
        capability = _SERVER_COMPILER_ISSUER_CAPABILITIES.get(id(self))
        if capability is None or not _is_server_authorized_compiled(compiled, capability):
            raise _error("SERVER_COMPILER_AUTHORITY_REQUIRED", "workflow was not produced by this server compiler seam")
        return CompilationRecordV1._from_server_compiled(
            compiled,
            _compiler_capability=capability,
            **kwargs,
        )

    def issue(self, record: CompilationRecordV1) -> ServerCompilationRecordReferenceV1:
        if self.store is None:
            raise _error("SERVER_RECORD_STORE_REQUIRED", "server issuer requires a record store")
        if type(record) is not CompilationRecordV1 or not _is_server_authorized_record(record):
            raise _error("SERVER_COMPILER_AUTHORITY_REQUIRED", "record was not produced by this server compiler seam")
        return self.store._issue_server(record)


@dataclass(frozen=True)
class ConfirmationBindingV1:
    confirmation_id: str
    compilation_record_ref: CompilationRecordReferenceV1
    actor_ref: str
    session_ref: str
    project_ref: str
    semantic_plan_hash: str
    method_snapshot_ref: str
    risk_snapshot_ref: str
    policy_snapshot_ref: str
    confirmed_at: str
    expires_at: str
    _issuer_token: object | None = field(default=None, repr=False, compare=False)

    def __post_init__(self) -> None:
        _text(self.confirmation_id, "confirmation_id")
        if type(self.compilation_record_ref) is ServerCompilationRecordReferenceV1:
            object.__setattr__(self, "compilation_record_ref", self.compilation_record_ref.as_untrusted_reference())
        if type(self.compilation_record_ref) is not CompilationRecordReferenceV1:
            raise _error("PLANNING_RECORD_REFERENCE_INVALID", "compilation_record_ref is invalid")
        for name, value in (
            ("actor_ref", self.actor_ref),
            ("session_ref", self.session_ref),
            ("project_ref", self.project_ref),
            ("method_snapshot_ref", self.method_snapshot_ref),
            ("risk_snapshot_ref", self.risk_snapshot_ref),
            ("policy_snapshot_ref", self.policy_snapshot_ref),
        ):
            _text(value, name)
        _require_opaque_ref(self.method_snapshot_ref, "method_snapshot_ref", ("method:",))
        _require_opaque_ref(self.risk_snapshot_ref, "risk_snapshot_ref", ("risk:",))
        _require_opaque_ref(self.policy_snapshot_ref, "policy_snapshot_ref", ("policy:",))
        _digest(self.semantic_plan_hash, "semantic_plan_hash")
        if self.semantic_plan_hash != self.compilation_record_ref.semantic_plan_hash:
            raise _error("PLANNING_HASH_MISMATCH", "confirmation semantic hash mismatches record reference")
        confirmed = _parse_timestamp(self.confirmed_at, "confirmed_at")
        expires = _parse_timestamp(self.expires_at, "expires_at")
        if expires <= confirmed:
            raise _error("PLANNING_EXPIRY_INVALID", "expires_at must be after confirmed_at")

    @property
    def confirmation_digest(self) -> str:
        return sha256_canonical(
            {
                "confirmation_id": self.confirmation_id,
                "compilation_record_ref": self.compilation_record_ref.to_dict(),
                "actor_ref": self.actor_ref,
                "session_ref": self.session_ref,
                "project_ref": self.project_ref,
                "semantic_plan_hash": self.semantic_plan_hash,
                "method_snapshot_ref": self.method_snapshot_ref,
                "risk_snapshot_ref": self.risk_snapshot_ref,
                "policy_snapshot_ref": self.policy_snapshot_ref,
                "confirmed_at": self.confirmed_at,
                "expires_at": self.expires_at,
            }
        )

    def is_valid(
        self,
        *,
        actor_ref: str,
        session_ref: str,
        project_ref: str,
        semantic_plan_hash: str,
        method_snapshot_ref: str,
        risk_snapshot_ref: str,
        policy_snapshot_ref: str,
        at: str,
    ) -> bool:
        try:
            current = _parse_timestamp(at, "at")
            expires = _parse_timestamp(self.expires_at, "expires_at")
        except PlanningContractError:
            return False
        return (
            current < expires
            and actor_ref == self.actor_ref
            and session_ref == self.session_ref
            and project_ref == self.project_ref
            and semantic_plan_hash == self.semantic_plan_hash
            and method_snapshot_ref == self.method_snapshot_ref
            and risk_snapshot_ref == self.risk_snapshot_ref
            and policy_snapshot_ref == self.policy_snapshot_ref
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "confirmation_id": self.confirmation_id,
            "compilation_record_ref": self.compilation_record_ref.to_dict(),
            "actor_ref": self.actor_ref,
            "session_ref": self.session_ref,
            "project_ref": self.project_ref,
            "semantic_plan_hash": self.semantic_plan_hash,
            "method_snapshot_ref": self.method_snapshot_ref,
            "risk_snapshot_ref": self.risk_snapshot_ref,
            "policy_snapshot_ref": self.policy_snapshot_ref,
            "confirmed_at": self.confirmed_at,
            "expires_at": self.expires_at,
            "confirmation_digest": self.confirmation_digest,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "ConfirmationBindingV1":
        value = _wire(
            value,
            {
                "confirmation_id",
                "compilation_record_ref",
                "actor_ref",
                "session_ref",
                "project_ref",
                "semantic_plan_hash",
                "method_snapshot_ref",
                "risk_snapshot_ref",
                "policy_snapshot_ref",
                "confirmed_at",
                "expires_at",
                "confirmation_digest",
            },
            "confirmation_binding",
        )
        raw_reference = value["compilation_record_ref"]
        if type(raw_reference) is not dict:
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "compilation_record_ref must be a built-in dict")
        binding = cls(
            confirmation_id=value["confirmation_id"],  # type: ignore[arg-type]
            compilation_record_ref=CompilationRecordReferenceV1.from_dict(raw_reference),
            actor_ref=value["actor_ref"],  # type: ignore[arg-type]
            session_ref=value["session_ref"],  # type: ignore[arg-type]
            project_ref=value["project_ref"],  # type: ignore[arg-type]
            semantic_plan_hash=value["semantic_plan_hash"],  # type: ignore[arg-type]
            method_snapshot_ref=value["method_snapshot_ref"],  # type: ignore[arg-type]
            risk_snapshot_ref=value["risk_snapshot_ref"],  # type: ignore[arg-type]
            policy_snapshot_ref=value["policy_snapshot_ref"],  # type: ignore[arg-type]
            confirmed_at=value["confirmed_at"],  # type: ignore[arg-type]
            expires_at=value["expires_at"],  # type: ignore[arg-type]
        )
        if value["confirmation_digest"] != binding.confirmation_digest:
            raise _error("PLANNING_DIGEST_MISMATCH", "confirmation_digest does not match binding fields")
        return binding


class ConfirmationBindingStoreV1:
    """Server-owned confirmation authority used by the admission gate."""

    def __init__(self) -> None:
        self._issuer_token = object()
        self._bindings: dict[str, ConfirmationBindingV1] = {}

    def issue(self, binding: ConfirmationBindingV1) -> ConfirmationBindingV1:
        if type(binding) is not ConfirmationBindingV1:
            raise _error("PLANNING_CONFIRMATION_REQUIRED", "confirmation store accepts a typed binding")
        if binding._issuer_token is not None and binding._issuer_token is not self._issuer_token:
            raise _error(
                "PLANNING_CONFIRMATION_ISSUER_MISMATCH",
                "confirmation belongs to another server confirmation store",
            )
        existing = self._bindings.get(binding.confirmation_digest)
        if existing is not None and existing is not binding:
            raise _error("PLANNING_CONFIRMATION_DUPLICATE", "confirmation digest is already issued")
        object.__setattr__(binding, "_issuer_token", self._issuer_token)
        self._bindings[binding.confirmation_digest] = binding
        return binding

    def require(self, binding: ConfirmationBindingV1) -> ConfirmationBindingV1:
        if type(binding) is not ConfirmationBindingV1:
            raise _error(
                "PLANNING_CONFIRMATION_AUTHORITY_REQUIRED",
                "a server-issued confirmation binding is required",
            )
        if binding._issuer_token is not self._issuer_token:
            raise _error(
                "PLANNING_CONFIRMATION_AUTHORITY_REQUIRED",
                "confirmation was not issued by the current server confirmation store",
            )
        if self._bindings.get(binding.confirmation_digest) is not binding:
            raise _error(
                "PLANNING_CONFIRMATION_INVALID",
                "confirmation is not current store state",
            )
        return binding

@dataclass(frozen=True)
class FailureEnvelopeV1:
    failure_class: str
    reason_code: str
    capability_ref: str
    step_ref: str
    evidence_refs: tuple[str, ...]
    retryable: bool
    remediation_codes: tuple[str, ...]
    confirmation_required: bool
    partial_output_refs: tuple[str, ...]
    partial_output_trust: str

    def __post_init__(self) -> None:
        for name, value in (("failure_class", self.failure_class), ("reason_code", self.reason_code), ("capability_ref", self.capability_ref), ("step_ref", self.step_ref)):
            _text(value, name)
        _require_opaque_ref(self.capability_ref, "capability_ref", ("capability:",))
        _require_opaque_ref(self.step_ref, "step_ref", ("step:",))
        for name, values in (("evidence_refs", self.evidence_refs), ("remediation_codes", self.remediation_codes), ("partial_output_refs", self.partial_output_refs)):
            if not isinstance(values, (tuple, list)):
                raise _error("PLANNING_ARRAY_INVALID", f"{name} must be an array")
            normalized = tuple(_text(item, f"{name}[]") for item in values)
            if len(set(normalized)) != len(normalized):
                raise _error("PLANNING_DUPLICATE_ID", f"{name} contains duplicates")
            object.__setattr__(self, name, normalized)
        for index, value in enumerate(self.evidence_refs):
            _require_opaque_ref(value, f"evidence_refs[{index}]", ("evidence:",))
        for index, value in enumerate(self.partial_output_refs):
            _require_opaque_ref(value, f"partial_output_refs[{index}]", ("output:",))
        if type(self.retryable) is not bool or type(self.confirmation_required) is not bool:
            raise _error("PLANNING_BOOLEAN_INVALID", "failure booleans must be exact booleans")
        if self.partial_output_trust not in {"not_available"}:
            raise _error("PLANNING_ENUM_INVALID", "trusted partial output markers are not accepted")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "failure-envelope.v1",
            "failure_class": self.failure_class,
            "reason_code": self.reason_code,
            "capability_ref": self.capability_ref,
            "step_ref": self.step_ref,
            "evidence_refs": list(self.evidence_refs),
            "retryable": self.retryable,
            "remediation_codes": list(self.remediation_codes),
            "confirmation_required": self.confirmation_required,
            "partial_output_refs": list(self.partial_output_refs),
            "partial_output_trust": self.partial_output_trust,
        }

    @classmethod
    @_wire_boundary
    def from_dict(cls, value: dict[str, object]) -> "FailureEnvelopeV1":
        required = {
            "schema_version",
            "failure_class",
            "reason_code",
            "capability_ref",
            "step_ref",
            "evidence_refs",
            "retryable",
            "remediation_codes",
            "confirmation_required",
            "partial_output_refs",
            "partial_output_trust",
        }
        value = _wire(value, required, "failure_envelope")
        if value["schema_version"] != "failure-envelope.v1":
            raise _error("PLANNING_SCHEMA_INVALID", "failure envelope schema_version is invalid")
        return cls(
            failure_class=value["failure_class"],  # type: ignore[arg-type]
            reason_code=value["reason_code"],  # type: ignore[arg-type]
            capability_ref=value["capability_ref"],  # type: ignore[arg-type]
            step_ref=value["step_ref"],  # type: ignore[arg-type]
            evidence_refs=tuple(_text_tuple(value["evidence_refs"], "evidence_refs")),
            retryable=value["retryable"],  # type: ignore[arg-type]
            remediation_codes=tuple(_text_tuple(value["remediation_codes"], "remediation_codes")),
            confirmation_required=value["confirmation_required"],  # type: ignore[arg-type]
            partial_output_refs=tuple(_text_tuple(value["partial_output_refs"], "partial_output_refs")),
            partial_output_trust=value["partial_output_trust"],  # type: ignore[arg-type]
        )


__all__ = [
    "CompilationRecordReferenceV1",
    "CompilationRecordStoreV1",
    "CompilationRecordV1",
    "CompiledWorkflowV1",
    "ConfirmationBindingV1",
    "ConfirmationBindingStoreV1",
    "DraftAgentPlanV1",
    "FailureEnvelopeV1",
    "PlanEffectV1",
    "PlanRiskLevelV1",
    "PlanningContractError",
    "ServerDraftPlanReferenceV1",
    "ServerCompilationRecordReferenceV1",
    "ServerCompilationRecordIssuerV1",
]
