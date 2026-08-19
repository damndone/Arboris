"""Deterministic, registry-derived capability authority for agent planning."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from ..canonical import canonical_json_v1, sha256_canonical
from ..contracts.common.contract_ref import ContractRefV1
from ..contracts.common.envelope import ContractError, freeze_json, thaw_json
from .failure_contract import CompilationFailure, failure
from .operations import OperationRegistry
from .port_types import PortTypeV1


def _identity(value: object, *, max_length: int = 160) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > max_length
        or "\x00" in value
        or any(token in value for token in ("/", "\\", "..", "://"))
    ):
        raise ValueError("invalid capability identity")
    return value


def _digest(value: object) -> str:
    return sha256_canonical(value)


_SHA256 = re.compile(r"[0-9a-f]{64}")

_DECLARED_EFFECT_BY_OPERATION = {
    "model.custom": "model_fit",
    "model.genesis": "model_fit",
    "model.rerun": "model_fit",
}


def _declared_effect(definition: Mapping[str, Any]) -> str:
    explicit = definition.get("declared_effect")
    if explicit is not None:
        return _identity(explicit)
    operation_id = _identity(definition["operation_id"])
    if definition["effect_level"] == "read_only":
        return "read"
    if operation_id in _DECLARED_EFFECT_BY_OPERATION:
        return _DECLARED_EFFECT_BY_OPERATION[operation_id]
    if operation_id.startswith("prediction."):
        return "model_predict"
    if operation_id.startswith("model."):
        return "model_fit"
    if operation_id.startswith(("statistical.", "test.")):
        return "read"
    return "write"


def _semantic_version(value: str) -> str:
    if value.startswith("v") and value[1:].isdigit():
        return f"{value[1:]}.0"
    return value


def _label(value: object) -> str:
    if type(value) is not str or not value or value != value.strip() or len(value) > 256 or "\x00" in value:
        raise ValueError("invalid capability label")
    return value


@dataclass(frozen=True)
class CapabilityManifestLimitsV1:
    max_entries: int = 256
    max_manifest_bytes: int = 256_000
    max_summary_bytes: int = 512

    def __post_init__(self) -> None:
        if type(self.max_entries) is not int or not 1 <= self.max_entries <= 4096:
            raise ValueError("max_entries is invalid")
        if type(self.max_manifest_bytes) is not int or not 1024 <= self.max_manifest_bytes <= 4_000_000:
            raise ValueError("max_manifest_bytes is invalid")
        if type(self.max_summary_bytes) is not int or not 32 <= self.max_summary_bytes <= 16_384:
            raise ValueError("max_summary_bytes is invalid")


@dataclass(frozen=True)
class CapabilityManifestEntryV1:
    capability_id: str
    operation_id: str
    operation_version: str
    kind: str
    summary: str
    scope: str
    scope_requirements: tuple[str, ...]
    effect_level: str
    declared_effect: str
    risk_level: str
    confirmation_policy: str
    natural_language_enabled: bool
    capability_ref: ContractRefV1
    contract_ref: ContractRefV1
    input_ports: tuple[PortTypeV1, ...]
    output_ports: tuple[PortTypeV1, ...]
    source_digest: str
    input_port_refs: tuple[str, ...] = ()
    output_port_refs: tuple[str, ...] = ()
    resource_budget: Mapping[str, int | float] = field(default_factory=dict)
    risk_authorization_policy: str = ""
    policy_snapshot_ref: str = ""
    precondition_digest: str = ""
    operation_contract_digest: str = ""
    executor_identity: str = ""
    reconciler_identity: str = ""
    runtime_identity: str = ""

    def __post_init__(self) -> None:
        for value in (
            self.capability_id,
            self.operation_id,
            self.operation_version,
            self.kind,
            self.effect_level,
            self.declared_effect,
            self.risk_level,
            self.confirmation_policy,
        ):
            _identity(value)
        _label(self.scope)
        for name in ("executor_identity", "reconciler_identity"):
            _identity(getattr(self, name))
        if type(self.summary) is not str or not self.summary or len(self.summary.encode("utf-8")) > 16_384:
            raise ValueError("capability summary is invalid")
        if not isinstance(self.scope_requirements, (tuple, list)):
            raise ValueError("scope_requirements are invalid")
        requirements = tuple(_identity(item, max_length=64) for item in self.scope_requirements)
        if len(set(requirements)) != len(requirements):
            raise ValueError("scope_requirements contain duplicates")
        object.__setattr__(self, "scope_requirements", requirements)
        if type(self.natural_language_enabled) is not bool:
            raise ValueError("natural_language_enabled is invalid")
        if type(self.capability_ref) is not ContractRefV1 or self.capability_ref.kind != "capability":
            raise ValueError("capability_ref is invalid")
        if type(self.contract_ref) is not ContractRefV1 or self.contract_ref.kind != "contract":
            raise ValueError("contract_ref is invalid")
        for name in ("input_ports", "output_ports"):
            ports = getattr(self, name)
            if not isinstance(ports, (tuple, list)) or any(type(port) is not PortTypeV1 for port in ports):
                raise ValueError(f"{name} are invalid")
            object.__setattr__(self, name, tuple(ports))
        for name, direction, count in (
            ("input_port_refs", "input", len(self.input_ports)),
            ("output_port_refs", "output", len(self.output_ports)),
        ):
            refs = getattr(self, name)
            if not isinstance(refs, (tuple, list)):
                raise ValueError(f"{name} are invalid")
            refs = tuple(refs)
            if not refs:
                refs = tuple(
                    f"port:{self.operation_id}:{self.operation_version}:{direction}:{index}"
                    for index in range(count)
                )
            if len(refs) != count or len(set(refs)) != len(refs):
                raise ValueError(f"{name} do not match ports")
            for ref in refs:
                if (
                    type(ref) is not str
                    or not ref.startswith("port:")
                    or any(token in ref for token in ("/", "\\", "..", "://"))
                ):
                    raise ValueError(f"{name} contain an invalid opaque port reference")
            object.__setattr__(self, name, refs)
        try:
            frozen_budget = freeze_json(self.resource_budget, "resource_budget")
        except ContractError as exc:
            raise ValueError("resource_budget is invalid") from exc
        if not isinstance(frozen_budget, Mapping) or not frozen_budget:
            raise ValueError("resource_budget is required")
        for key, value in frozen_budget.items():
            if type(key) is not str or type(value) not in {int, float} or isinstance(value, bool) or value < 0:
                raise ValueError("resource_budget contains an invalid value")
        object.__setattr__(self, "resource_budget", frozen_budget)
        if not self.risk_authorization_policy:
            object.__setattr__(
                self,
                "risk_authorization_policy",
                "explicit_single_use" if self.risk_level == "high" else "none",
            )
        _identity(self.risk_authorization_policy)
        if (
            type(self.policy_snapshot_ref) is not str
            or not self.policy_snapshot_ref.startswith("policy:")
            or any(token in self.policy_snapshot_ref for token in ("/", "\\", "..", "://"))
        ):
            raise ValueError("policy_snapshot_ref is invalid")
        object.__setattr__(
            self,
            "precondition_digest",
            self.precondition_digest or _digest({"scope_requirements": list(self.scope_requirements)}),
        )
        object.__setattr__(
            self,
            "operation_contract_digest",
            self.operation_contract_digest or _digest(
                {
                    "operation_id": self.operation_id,
                    "operation_version": self.operation_version,
                    "input_ports": [port.to_dict() for port in self.input_ports],
                    "output_ports": [port.to_dict() for port in self.output_ports],
                }
            ),
        )
        for name in ("precondition_digest", "operation_contract_digest"):
            if type(getattr(self, name)) is not str or _SHA256.fullmatch(getattr(self, name)) is None:
                raise ValueError(f"{name} is invalid")
        if type(self.runtime_identity) is not str or not self.runtime_identity.startswith("runtime:"):
            raise ValueError("runtime_identity is invalid")
        if any(token in self.runtime_identity for token in ("/", "\\", "..", "://")):
            raise ValueError("runtime_identity is invalid")
        if type(self.source_digest) is not str or _SHA256.fullmatch(self.source_digest) is None:
            raise ValueError("source_digest is invalid")

    def to_dict(self) -> dict[str, object]:
        """Return typed contract metadata and opaque runtime identities."""

        return {
            "schema_version": "capability-manifest-entry.v1",
            "capability_id": self.capability_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "kind": self.kind,
            "summary": self.summary,
            "scope": self.scope,
            "scope_requirements": list(self.scope_requirements),
            "effect_level": self.effect_level,
            "declared_effect": self.declared_effect,
            "risk_level": self.risk_level,
            "confirmation_policy": self.confirmation_policy,
            "natural_language_enabled": self.natural_language_enabled,
            "capability_ref": self.capability_ref.to_dict(),
            "contract_ref": self.contract_ref.to_dict(),
            "input_ports": [port.to_dict() for port in self.input_ports],
            "output_ports": [port.to_dict() for port in self.output_ports],
            "input_port_refs": list(self.input_port_refs),
            "output_port_refs": list(self.output_port_refs),
            "resource_budget": thaw_json(self.resource_budget),
            "risk_authorization_policy": self.risk_authorization_policy,
            "policy_snapshot_ref": self.policy_snapshot_ref,
            "precondition_digest": self.precondition_digest,
            "operation_contract_digest": self.operation_contract_digest,
            "executor_identity": self.executor_identity,
            "reconciler_identity": self.reconciler_identity,
            "runtime_identity": self.runtime_identity,
            "source_digest": self.source_digest,
        }


@dataclass(frozen=True)
class CapabilityManifestV1:
    entries: tuple[CapabilityManifestEntryV1, ...]
    manifest_digest: str
    schema_version: str = "capability-manifest.v1"

    def __post_init__(self) -> None:
        if self.schema_version != "capability-manifest.v1":
            raise ValueError("manifest schema_version is invalid")
        if not isinstance(self.entries, (tuple, list)) or not self.entries:
            raise ValueError("manifest entries are required")
        entries = tuple(self.entries)
        if any(type(entry) is not CapabilityManifestEntryV1 for entry in entries):
            raise ValueError("manifest entry is invalid")
        if tuple(sorted(entries, key=lambda entry: entry.capability_id)) != entries:
            raise ValueError("manifest entries must be deterministically ordered")
        if len({entry.capability_id for entry in entries}) != len(entries):
            raise ValueError("manifest contains duplicate capability identity")
        object.__setattr__(self, "entries", entries)
        expected = _manifest_digest(entries)
        if self.manifest_digest != expected:
            raise ValueError("manifest digest does not match entries")

    @property
    def capability_ids(self) -> tuple[str, ...]:
        return tuple(entry.capability_id for entry in self.entries)

    def require(self, capability_id: str) -> CapabilityManifestEntryV1:
        try:
            _identity(capability_id)
        except ValueError as exc:
            raise KeyError("UNKNOWN_CAPABILITY") from exc
        for entry in self.entries:
            if entry.capability_id == capability_id:
                return entry
        raise KeyError("UNKNOWN_CAPABILITY")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "entries": [entry.to_dict() for entry in self.entries],
            "manifest_digest": self.manifest_digest,
        }


def _ports_for(
    definition: Mapping[str, Any],
) -> tuple[tuple[PortTypeV1, ...], tuple[PortTypeV1, ...], tuple[str, ...], tuple[str, ...], str]:
    """Project port declarations from the exact registry contract payload.

    The registry currently publishes proposal/editable schemas rather than a
    separate port table. The schema digest is therefore the source identity;
    operation-name prefixes are never used to guess a dataset/model schema.
    A future registry projection can provide explicit ``input_ports`` and
    ``output_ports`` without changing this boundary.
    """

    operation_id = _identity(definition["operation_id"])
    operation_version = _identity(definition["operation_version"])
    operation_contract = {
        "operation_id": operation_id,
        "operation_version": operation_version,
        "proposal_schema": definition.get("proposal_schema", {}),
        "editable_schema": definition.get("editable_schema", {}),
    }
    operation_contract_digest = _digest(operation_contract)

    def parse_ports(raw: object) -> tuple[PortTypeV1, ...]:
        if raw in (None, ()):
            schema_ref = f"schema:operation-contract-{operation_contract_digest}:artifact"
            return (PortTypeV1("artifact", schema_ref),)
        if not isinstance(raw, (tuple, list)) or not raw:
            raise ValueError("registry port declaration is invalid")
        ports: list[PortTypeV1] = []
        for item in raw:
            if type(item) is PortTypeV1:
                ports.append(item)
            elif type(item) is dict:
                ports.append(PortTypeV1(**item))
            else:
                raise ValueError("registry port declaration is invalid")
        return tuple(ports)

    input_ports = parse_ports(definition.get("input_ports"))
    output_ports = parse_ports(definition.get("output_ports"))

    def refs(raw: object, direction: str, count: int) -> tuple[str, ...]:
        values = raw
        if values in (None, ()):
            values = tuple(
                f"port:{operation_id}:{operation_version}:{direction}:{index}"
                for index in range(count)
            )
        if not isinstance(values, (tuple, list)) or len(values) != count:
            raise ValueError("registry port references do not match declarations")
        return tuple(_identity(item) for item in values)

    return (
        input_ports,
        output_ports,
        refs(definition.get("input_port_refs"), "input", len(input_ports)),
        refs(definition.get("output_port_refs"), "output", len(output_ports)),
        operation_contract_digest,
    )


def _manifest_digest(entries: tuple[CapabilityManifestEntryV1, ...]) -> str:
    return _digest(
        {
            "schema_version": "capability-manifest.v1",
            "entries": [entry.to_dict() for entry in entries],
        }
    )


def _entry_from_definition(definition: dict[str, Any]) -> CapabilityManifestEntryV1:
    operation_id = _identity(definition["operation_id"])
    operation_version = _identity(definition["operation_version"])
    if type(definition) is not dict:
        raise ValueError("registry definition is invalid")
    input_ports, output_ports, input_port_refs, output_port_refs, operation_contract_digest = _ports_for(definition)
    resource_budget = definition.get("resource_budget")
    if resource_budget is None:
        resource_budget = {
            "cpu_ms": 500 if definition["risk_level"] == "high" else 1_000,
            "memory_mb": 64 if definition["risk_level"] == "high" else 128,
        }
    if type(resource_budget) is not dict:
        raise ValueError("registry resource budget is invalid")
    precondition_schema = (
        definition.get("proposal_schema", {})
        .get("properties", {})
        .get("preconditions", {})
    )
    precondition_digest = _digest(precondition_schema)
    declared_effect = _declared_effect(definition)
    executor_identity = _identity(definition.get("executor", "") or operation_id)
    reconciler_identity = _identity(definition.get("reconciler", "") or operation_id)
    runtime_identity = "runtime:" + _digest(
        {
            "executor_identity": executor_identity,
            "reconciler_identity": reconciler_identity,
            "diff_builder_identity": _identity(definition.get("diff_builder", "") or "none"),
            "verification_builder_identity": _identity(
                definition.get("verification_builder", "") or "none"
            ),
        }
    )
    risk_authorization_policy = _identity(
        definition.get(
            "risk_authorization_policy",
            "explicit_single_use" if definition["risk_level"] == "high" else "none",
        )
    )
    policy_snapshot_ref = "policy:agent-compiler:" + _digest(
        {
            "operation_id": operation_id,
            "operation_version": operation_version,
            "effect_level": definition["effect_level"],
            "declared_effect": declared_effect,
            "risk_level": definition["risk_level"],
            "confirmation_policy": definition["confirmation_policy"],
            "risk_authorization_policy": risk_authorization_policy,
            "resource_budget": resource_budget,
            "precondition_digest": precondition_digest,
        }
    )
    public = {
        "operation_id": operation_id,
        "operation_version": operation_version,
        "effect_level": _identity(definition["effect_level"]),
        "declared_effect": declared_effect,
        "scope": _label(definition.get("scope", "") or "scope:unspecified"),
        "scope_requirements": tuple(_identity(item, max_length=64) for item in definition.get("scope_requirements", ())),
        "risk_level": _identity(definition["risk_level"]),
        "confirmation_policy": _identity(definition["confirmation_policy"]),
        "ui_description": definition.get("ui_description", "") or operation_id,
        "proposal_schema": definition.get("proposal_schema", {}),
        "editable_schema": definition.get("editable_schema", {}),
        "input_ports": [port.to_dict() for port in input_ports],
        "output_ports": [port.to_dict() for port in output_ports],
        "input_port_refs": list(input_port_refs),
        "output_port_refs": list(output_port_refs),
        "resource_budget": resource_budget,
        "risk_authorization_policy": risk_authorization_policy,
        "policy_snapshot_ref": policy_snapshot_ref,
        "precondition_digest": precondition_digest,
        "operation_contract_digest": operation_contract_digest,
        "executor_identity": executor_identity,
        "reconciler_identity": reconciler_identity,
        "runtime_identity": runtime_identity,
    }
    summary = str(public["ui_description"])
    if len(summary.encode("utf-8")) > 16_384:
        raise ValueError("capability summary is oversized")
    source_digest = _digest(public)
    capability_ref = ContractRefV1(
        kind="capability",
        logical_id=operation_id,
        semantic_version=_semantic_version(operation_version),
        contract_digest=_digest({"kind": "capability", **public}),
    )
    contract_ref = ContractRefV1(
        kind="contract",
        logical_id=f"agent-capability.{operation_id}",
        semantic_version="1.0",
        contract_digest=_digest({"kind": "operation-contract", **public}),
    )
    return CapabilityManifestEntryV1(
        capability_id=operation_id,
        operation_id=operation_id,
        operation_version=operation_version,
        kind="registered-operation",
        summary=summary,
        scope=public["scope"],
        scope_requirements=public["scope_requirements"],
        effect_level=public["effect_level"],
        declared_effect=declared_effect,
        risk_level=public["risk_level"],
        confirmation_policy=public["confirmation_policy"],
        natural_language_enabled=bool(definition.get("natural_language_enabled", False)),
        capability_ref=capability_ref,
        contract_ref=contract_ref,
        input_ports=input_ports,
        output_ports=output_ports,
        source_digest=source_digest,
        input_port_refs=input_port_refs,
        output_port_refs=output_port_refs,
        resource_budget=resource_budget,
        risk_authorization_policy=risk_authorization_policy,
        policy_snapshot_ref=policy_snapshot_ref,
        precondition_digest=precondition_digest,
        operation_contract_digest=operation_contract_digest,
        executor_identity=executor_identity,
        reconciler_identity=reconciler_identity,
        runtime_identity=runtime_identity,
    )


def build_capability_manifest(
    limits: CapabilityManifestLimitsV1 | None = None,
    *,
    registry: OperationRegistry | None = None,
) -> CapabilityManifestV1:
    limits = limits or CapabilityManifestLimitsV1()
    if type(limits) is not CapabilityManifestLimitsV1:
        raise TypeError("limits must be CapabilityManifestLimitsV1")
    authority = registry or OperationRegistry()
    if type(authority) is not OperationRegistry:
        raise TypeError("registry must be OperationRegistry")
    try:
        definitions = authority.capabilities()
        entries = tuple(sorted((_entry_from_definition(item) for item in definitions), key=lambda item: item.capability_id))
        if len(entries) > limits.max_entries:
            raise failure("MANIFEST_LIMIT_EXCEEDED", stage="manifest")
        manifest = CapabilityManifestV1(entries=entries, manifest_digest=_manifest_digest(entries))
        if len(canonical_json_v1(manifest.to_dict()).encode("utf-8")) > limits.max_manifest_bytes:
            raise failure("MANIFEST_LIMIT_EXCEEDED", stage="manifest")
        if any(len(entry.summary.encode("utf-8")) > limits.max_summary_bytes for entry in entries):
            raise failure("MANIFEST_LIMIT_EXCEEDED", stage="manifest")
        return manifest
    except CompilationFailure:
        raise
    except (RecursionError, TypeError, ValueError):
        raise failure("DRAFT_INVALID", stage="manifest")


CapabilityManifest = CapabilityManifestV1
CapabilityManifestEntry = CapabilityManifestEntryV1
CapabilityManifestLimits = CapabilityManifestLimitsV1


__all__ = [
    "CapabilityManifest",
    "CapabilityManifestEntry",
    "CapabilityManifestEntryV1",
    "CapabilityManifestLimits",
    "CapabilityManifestLimitsV1",
    "CapabilityManifestV1",
    "build_capability_manifest",
]
