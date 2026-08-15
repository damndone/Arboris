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
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from workbench.canonical import CanonicalJSONError, canonical_json_v1, sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.envelope import ContractError, freeze_json, thaw_json


_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_JSON_SAFE_INTEGER = 9_007_199_254_740_991
_DRAFT_SCHEMA = "draft-agent-plan.v1"
_COMPILED_SCHEMA = "compiled-workflow.v1"
_RECORD_SCHEMA = "compilation-record.v1"
_REFERENCE_FIELDS = {"record_id", "record_digest", "semantic_plan_hash"}
_DRAFT_FIELDS = {
    "schema_version",
    "intent_ref",
    "capability_refs",
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
    except (CanonicalJSONError, ContractError, RecursionError, OverflowError, ValueError) as exc:
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
    if type(value) is dict:
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


def _plain(value: object) -> object:
    try:
        return thaw_json(value)
    except (RecursionError, ValueError, TypeError) as exc:
        raise _error("PLANNING_JSON_INVALID", "value must be finite, acyclic JSON") from exc


def _semantic_payload(
    *,
    schema_version: str,
    intent_ref: str,
    capability_refs: tuple[ContractRefV1, ...],
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
    nodes: tuple[Mapping[str, Any], ...]
    connections: tuple[Mapping[str, Any], ...]
    config: Mapping[str, Any]
    policy_snapshot_ref: str
    rationale: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != _DRAFT_SCHEMA:
            raise _error("PLANNING_SCHEMA_INVALID", "draft schema_version is invalid")
        _text(self.intent_ref, "intent_ref")
        if not isinstance(self.capability_refs, (tuple, list)):
            raise _error("PLANNING_ARRAY_INVALID", "capability_refs must be an array")
        refs = tuple(self.capability_refs)
        if any(type(ref) is not ContractRefV1 for ref in refs):
            raise _error("PLANNING_CONTRACT_REF_INVALID", "capability_refs contain an invalid ref")
        if len({(ref.kind, ref.logical_id, ref.semantic_version) for ref in refs}) != len(refs):
            raise _error("PLANNING_DUPLICATE_ID", "capability_refs contain duplicate identities")
        object.__setattr__(self, "capability_refs", refs)
        if not isinstance(self.nodes, (tuple, list)):
            raise _error("PLANNING_ARRAY_INVALID", "nodes must be an array")
        nodes = tuple(_frozen_mapping(_plain(node), "nodes[]") for node in self.nodes)
        for node in nodes:
            _reject_draft_server_fields(node, "node")
            if type(node.get("node_id")) is not str or not node["node_id"]:
                raise _error("PLANNING_NODE_INVALID", "each node must have a node_id")
        if len({node["node_id"] for node in nodes}) != len(nodes):
            raise _error("PLANNING_DUPLICATE_ID", "nodes contain duplicate node_id values")
        object.__setattr__(self, "nodes", nodes)
        if not isinstance(self.connections, (tuple, list)):
            raise _error("PLANNING_ARRAY_INVALID", "connections must be an array")
        connections = tuple(_frozen_mapping(_plain(connection), "connections[]") for connection in self.connections)
        object.__setattr__(self, "connections", connections)
        object.__setattr__(self, "config", _frozen_mapping(_plain(self.config), "config"))
        _text(self.policy_snapshot_ref, "policy_snapshot_ref")
        if not isinstance(self.rationale, (tuple, list)):
            raise _error("PLANNING_ARRAY_INVALID", "rationale must be an array")
        object.__setattr__(self, "rationale", tuple(_text(item, "rationale[]") for item in self.rationale))

    def semantic_hash_input(self) -> dict[str, object]:
        return _semantic_payload(
            schema_version=self.schema_version,
            intent_ref=self.intent_ref,
            capability_refs=self.capability_refs,
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
            "nodes": [_plain(node) for node in self.nodes],
            "connections": [_plain(connection) for connection in self.connections],
            "config": _plain(self.config),
            "policy_snapshot_ref": self.policy_snapshot_ref,
            "rationale": list(self.rationale),
            "semantic_plan_hash": self.semantic_plan_hash,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "DraftAgentPlanV1":
        value = _wire(value, _DRAFT_FIELDS, "draft_agent_plan")
        raw_nodes = value["nodes"]
        raw_connections = value["connections"]
        if type(raw_nodes) is not list or type(raw_connections) is not list:
            raise _error("PLANNING_ARRAY_INVALID", "nodes and connections must be built-in lists")
        if any(type(item) is not dict for item in raw_nodes + raw_connections):
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "plan nodes and connections must be built-in dicts")
        plan = cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            intent_ref=value["intent_ref"],  # type: ignore[arg-type]
            capability_refs=tuple(_ref_tuple(value["capability_refs"], "capability_refs")),
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
    risk_level: PlanRiskLevelV1
    effect: str
    resource_budget: Mapping[str, Any]
    semantic_plan_hash: str

    def __post_init__(self) -> None:
        if self.schema_version != _COMPILED_SCHEMA:
            raise _error("PLANNING_SCHEMA_INVALID", "compiled schema_version is invalid")
        _text(self.intent_ref, "intent_ref")
        for name, refs in (
            ("capability_refs", self.capability_refs),
            ("contract_snapshot_refs", self.contract_snapshot_refs),
        ):
            if not isinstance(refs, (tuple, list)) or any(type(ref) is not ContractRefV1 for ref in refs):
                raise _error("PLANNING_CONTRACT_REF_INVALID", f"{name} contains an invalid ref")
            object.__setattr__(self, name, tuple(refs))
        if not isinstance(self.nodes, (tuple, list)) or any(not isinstance(node, Mapping) for node in self.nodes):
            raise _error("PLANNING_NODE_INVALID", "nodes are invalid")
        object.__setattr__(self, "nodes", tuple(_frozen_mapping(_plain(node), "nodes[]") for node in self.nodes))
        if not isinstance(self.connections, (tuple, list)) or any(not isinstance(item, Mapping) for item in self.connections):
            raise _error("PLANNING_NODE_INVALID", "connections are invalid")
        object.__setattr__(self, "connections", tuple(_frozen_mapping(_plain(item), "connections[]") for item in self.connections))
        object.__setattr__(self, "config", _frozen_mapping(_plain(self.config), "config"))
        _text(self.catalog_snapshot_ref, "catalog_snapshot_ref")
        _text(self.policy_snapshot_ref, "policy_snapshot_ref")
        _text(self.compiler_version, "compiler_version")
        _text(self.server_execution_identity, "server_execution_identity")
        _digest(self.preview_fingerprint, "preview_fingerprint")
        object.__setattr__(self, "plan_diff", _frozen_mapping(_plain(self.plan_diff), "plan_diff"))
        if type(self.risk_level) is not PlanRiskLevelV1:
            raise _error("PLANNING_ENUM_INVALID", "risk_level is invalid")
        _text(self.effect, "effect")
        object.__setattr__(self, "resource_budget", _frozen_mapping(_plain(self.resource_budget), "resource_budget"))
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
        effect: str,
        resource_budget: Mapping[str, Any],
        contract_snapshot_refs: tuple[ContractRefV1, ...] | None = None,
        catalog_snapshot_ref: str = "catalog:snapshot:1",
    ) -> "CompiledWorkflowV1":
        if type(draft) is not DraftAgentPlanV1:
            raise _error("PLANNING_DRAFT_INVALID", "only DraftAgentPlanV1 can be compiled")
        return cls(
            schema_version=_COMPILED_SCHEMA,
            intent_ref=draft.intent_ref,
            capability_refs=draft.capability_refs,
            nodes=draft.nodes,
            connections=draft.connections,
            config=draft.config,
            contract_snapshot_refs=contract_snapshot_refs or draft.capability_refs,
            catalog_snapshot_ref=catalog_snapshot_ref,
            policy_snapshot_ref=draft.policy_snapshot_ref,
            compiler_version=compiler_version,
            server_execution_identity=server_execution_identity,
            preview_fingerprint=preview_fingerprint,
            plan_diff=plan_diff,
            risk_level=risk_level,
            effect=effect,
            resource_budget=resource_budget,
            semantic_plan_hash=draft.semantic_plan_hash,
        )

    def semantic_hash_input(self) -> dict[str, object]:
        return _semantic_payload(
            schema_version=self.schema_version,
            intent_ref=self.intent_ref,
            capability_refs=self.capability_refs,
            nodes=self.nodes,
            connections=self.connections,
            config=self.config,
            policy_snapshot_ref=self.policy_snapshot_ref,
        )

    def execution_instance_hash(self, resolved_artifact_digests: Mapping[str, str]) -> str:
        if type(resolved_artifact_digests) is not dict:
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "resolved_artifact_digests must be a built-in dict")
        normalized: dict[str, str] = {}
        for ref, digest in resolved_artifact_digests.items():
            _text(ref, "resolved_artifact_digests key")
            normalized[ref] = _digest(digest, "resolved_artifact_digests value") or digest
        if not normalized:
            raise _error("PLANNING_ARTIFACTS_REQUIRED", "execution hash requires resolved artifact digests")
        return sha256_canonical(
            {
                "semantic_plan_hash": self.semantic_plan_hash,
                "resolved_artifact_digests": normalized,
            }
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "intent_ref": self.intent_ref,
            "capability_refs": [ref.to_dict() for ref in self.capability_refs],
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
            "risk_level": self.risk_level.value,
            "effect": self.effect,
            "resource_budget": _plain(self.resource_budget),
            "semantic_plan_hash": self.semantic_plan_hash,
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "CompiledWorkflowV1":
        value = _wire(value, _COMPILED_FIELDS, "compiled_workflow")
        raw_nodes = value["nodes"]
        raw_connections = value["connections"]
        if type(raw_nodes) is not list or type(raw_connections) is not list:
            raise _error("PLANNING_ARRAY_INVALID", "nodes and connections must be built-in lists")
        if any(type(item) is not dict for item in raw_nodes + raw_connections):
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "nodes and connections must be built-in dicts")
        return cls(
            schema_version=value["schema_version"],  # type: ignore[arg-type]
            intent_ref=value["intent_ref"],  # type: ignore[arg-type]
            capability_refs=_ref_tuple(value["capability_refs"], "capability_refs"),
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
            risk_level=_enum(value["risk_level"], PlanRiskLevelV1, "risk_level"),
            effect=value["effect"],  # type: ignore[arg-type]
            resource_budget=_frozen_mapping(value["resource_budget"], "resource_budget"),  # type: ignore[arg-type]
            semantic_plan_hash=value["semantic_plan_hash"],  # type: ignore[arg-type]
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
        if type(record) is not CompilationRecordV1:
            raise _error("SERVER_RECORD_REQUIRED", "only a validated CompilationRecordV1 can be issued")
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
    def from_dict(cls, value: dict[str, object]) -> "ConfirmationBindingV1":
        required = {
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
        }
        value = _wire(value, required, "confirmation_binding")
        raw_ref = value["compilation_record_ref"]
        if type(raw_ref) is not dict:
            raise _error("PLANNING_NESTED_DICT_REQUIRED", "compilation_record_ref must be a built-in dict")
        binding = cls(
            confirmation_id=value["confirmation_id"],  # type: ignore[arg-type]
            compilation_record_ref=CompilationRecordReferenceV1.from_dict(raw_ref),
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
            raise _error("PLANNING_DIGEST_MISMATCH", "confirmation_digest does not match")
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
        for name, values in (("evidence_refs", self.evidence_refs), ("remediation_codes", self.remediation_codes), ("partial_output_refs", self.partial_output_refs)):
            if not isinstance(values, (tuple, list)):
                raise _error("PLANNING_ARRAY_INVALID", f"{name} must be an array")
            normalized = tuple(_text(item, f"{name}[]") for item in values)
            if len(set(normalized)) != len(normalized):
                raise _error("PLANNING_DUPLICATE_ID", f"{name} contains duplicates")
            object.__setattr__(self, name, normalized)
        if type(self.retryable) is not bool or type(self.confirmation_required) is not bool:
            raise _error("PLANNING_BOOLEAN_INVALID", "failure booleans must be exact booleans")
        if self.partial_output_trust not in {"trusted", "untrusted", "not_available"}:
            raise _error("PLANNING_ENUM_INVALID", "partial_output_trust is invalid")

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
    "DraftAgentPlanV1",
    "FailureEnvelopeV1",
    "PlanRiskLevelV1",
    "PlanningContractError",
    "ServerCompilationRecordReferenceV1",
]
