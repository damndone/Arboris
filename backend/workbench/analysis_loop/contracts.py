"""Packet contracts and logical identity helpers for the Agent Analysis Loop."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from .canonical import sha256_canonical

PacketStatus = Literal["pending", "complete", "blocked", "failed"]
CompareStatus = Literal["complete", "partial", "not_comparable", "blocked_by_integrity"]
ValidationStatus = Literal["pass", "warning", "fail"]
TERMINAL_PACKET_STATUSES = frozenset({"complete", "blocked", "failed"})


def _freeze(value: Any, path: str = "value") -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{path} must contain only finite numbers")
        return value
    if isinstance(value, Mapping):
        frozen = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"{path} mapping keys must be strings")
            frozen[key] = _freeze(item, f"{path}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item, f"{path}[]") for item in value)
    raise TypeError(
        f"{path} contains unsupported JSON-compatible leaf "
        f"{type(value).__name__}"
    )


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def _require_string(value: Any, field_name: str) -> None:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be a string")


def _require_mapping(value: Any, field_name: str) -> None:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")


def _require_non_empty_string(value: Any, field_name: str) -> None:
    _require_string(value, field_name)
    if not value:
        raise ValueError(f"{field_name} must not be empty")


@dataclass(frozen=True)
class SourceRunContract:
    """The immutable source facts accepted by the v1.7.2 golden flow.

    This is deliberately a value object rather than a view over a run directory.  A
    caller must provide the persisted facts explicitly; validation never fills in
    missing contract fields from legacy artifacts.
    """

    run_id: str
    status: str
    model: str
    covariance: str
    result_artifact: Mapping[str, Any] | None
    run_inputs: Mapping[str, Any] | None
    lineage: Mapping[str, Any] | None
    contract_version: str | None
    result_ids: tuple[str, ...]
    primary_estimand: Mapping[str, Any] | None = None
    result_labels: Mapping[str, str] = field(default_factory=dict)
    dataset_schema: Mapping[str, Any] = field(default_factory=dict)
    analysis_row_ids: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        for field_name in ("run_id", "status", "model", "covariance"):
            _require_non_empty_string(getattr(self, field_name), field_name)
        if self.contract_version is not None:
            _require_non_empty_string(self.contract_version, "contract_version")
        for field_name in ("result_artifact", "run_inputs", "lineage"):
            value = getattr(self, field_name)
            if value is not None:
                _require_mapping(value, field_name)
                object.__setattr__(self, field_name, _freeze(value, field_name))
        if self.primary_estimand is not None:
            _require_mapping(self.primary_estimand, "primary_estimand")
            object.__setattr__(
                self,
                "primary_estimand",
                _freeze(self.primary_estimand, "primary_estimand"),
            )
        for field_name in ("result_labels", "dataset_schema"):
            value = getattr(self, field_name)
            _require_mapping(value, field_name)
            object.__setattr__(self, field_name, _freeze(value, field_name))
        for field_name in ("result_ids", "analysis_row_ids"):
            value = getattr(self, field_name)
            if not isinstance(value, (tuple, list)):
                raise TypeError(f"{field_name} must be a tuple or list")
            if any(type(item) is not str for item in value):
                raise TypeError(f"{field_name} items must be strings")
            object.__setattr__(self, field_name, tuple(value))
        if any(type(key) is not str or type(value) is not str for key, value in self.result_labels.items()):
            raise TypeError("result_labels must map strings to strings")

    @property
    def model_type(self) -> str:
        """Compatibility spelling for callers that use the result contract term."""

        return self.model

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "model": self.model,
            "covariance": self.covariance,
            "result_artifact": _thaw(self.result_artifact),
            "run_inputs": _thaw(self.run_inputs),
            "lineage": _thaw(self.lineage),
            "contract_version": self.contract_version,
            "result_ids": list(self.result_ids),
            "primary_estimand": _thaw(self.primary_estimand),
            "result_labels": _thaw(self.result_labels),
            "dataset_schema": _thaw(self.dataset_schema),
            "analysis_row_ids": list(self.analysis_row_ids),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceRunContract":
        if not isinstance(value, Mapping):
            raise TypeError("source run contract must be a mapping")
        required = {
            "run_id",
            "status",
            "model",
            "covariance",
            "result_artifact",
            "run_inputs",
            "lineage",
            "contract_version",
            "result_ids",
        }
        optional = {"primary_estimand", "result_labels", "dataset_schema", "analysis_row_ids"}
        extra = set(value) - required - optional
        if extra:
            raise ValueError("extra source contract field(s): " + ", ".join(sorted(extra)))
        missing = required - set(value)
        if missing:
            raise KeyError("missing source contract field(s): " + ", ".join(sorted(missing)))
        return cls(
            run_id=value["run_id"],
            status=value["status"],
            model=value["model"],
            covariance=value["covariance"],
            result_artifact=value["result_artifact"],
            run_inputs=value["run_inputs"],
            lineage=value["lineage"],
            contract_version=value["contract_version"],
            result_ids=tuple(value["result_ids"]),
            primary_estimand=value.get("primary_estimand"),
            result_labels=value.get("result_labels", {}),
            dataset_schema=value.get("dataset_schema", {}),
            analysis_row_ids=tuple(value.get("analysis_row_ids", ())),
        )


@dataclass(frozen=True)
class ComparisonTarget:
    """One exact, stable result identity used for a comparison conclusion."""

    result_id: str
    role: str
    resolution_source: str
    label: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("result_id", "role", "resolution_source"):
            _require_non_empty_string(getattr(self, field_name), field_name)
        if self.label is not None:
            _require_string(self.label, "label")

    def _hash_payload(self) -> dict[str, Any]:
        return {
            "result_id": self.result_id,
            "role": self.role,
            "label": self.label,
            "resolution_source": self.resolution_source,
        }

    @property
    def target_hash(self) -> str:
        return sha256_canonical(self._hash_payload())

    @property
    def selection_source(self) -> str:
        """Spec spelling retained as a read-only alias for resolution_source."""

        return self.resolution_source

    def to_dict(self) -> dict[str, Any]:
        return {**self._hash_payload(), "target_hash": self.target_hash}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComparisonTarget":
        if not isinstance(value, Mapping):
            raise TypeError("comparison target must be a mapping")
        required = {"result_id", "role", "resolution_source"}
        allowed = required | {"label", "target_hash"}
        extra = set(value) - allowed
        if extra:
            raise ValueError("extra comparison target field(s): " + ", ".join(sorted(extra)))
        missing = required - set(value)
        if missing:
            raise KeyError("missing comparison target field(s): " + ", ".join(sorted(missing)))
        target = cls(
            result_id=value["result_id"],
            role=value["role"],
            resolution_source=value["resolution_source"],
            label=value.get("label"),
        )
        if "target_hash" in value and value["target_hash"] != target.target_hash:
            raise ValueError("comparison target hash does not match canonical target")
        return target


@dataclass(frozen=True)
class SourceValidationResult:
    valid: bool
    status: ValidationStatus
    severity: str
    code: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if type(self.valid) is not bool:
            raise TypeError("valid must be a bool")
        if self.status not in {"pass", "warning", "fail"}:
            raise ValueError(f"invalid source validation status: {self.status}")
        _require_non_empty_string(self.severity, "severity")
        _require_non_empty_string(self.code, "code")
        _require_mapping(self.evidence, "evidence")
        object.__setattr__(self, "evidence", _freeze(self.evidence, "evidence"))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status,
            "severity": self.severity,
            "code": self.code,
            "evidence": _thaw(self.evidence),
            "reason_codes": list(self.reason_codes),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "SourceValidationResult":
        if not isinstance(value, Mapping):
            raise TypeError("source validation result must be a mapping")
        required = {"valid", "status", "severity", "code", "evidence", "reason_codes"}
        extra = set(value) - required
        missing = required - set(value)
        if extra:
            raise ValueError("extra source validation field(s): " + ", ".join(sorted(extra)))
        if missing:
            raise KeyError("missing source validation field(s): " + ", ".join(sorted(missing)))
        return cls(
            valid=value["valid"],
            status=value["status"],
            severity=value["severity"],
            code=value["code"],
            evidence=value.get("evidence", {}),
            reason_codes=tuple(value.get("reason_codes", ())),
        )


@dataclass(frozen=True)
class ClusterPreflightResult:
    valid: bool
    status: ValidationStatus
    severity: str
    code: str
    cluster_variable: str
    wire_field: str = "entity_col"
    cluster_count: int = 0
    row_count: int = 0
    missing_count: int = 0
    singleton_cluster_count: int = 0
    all_singleton_clusters: bool = False
    value_type: str | None = None
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    evidence: Mapping[str, Any] = field(default_factory=dict)
    invariants: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.valid) is not bool:
            raise TypeError("valid must be a bool")
        if self.status not in {"pass", "warning", "fail"}:
            raise ValueError(f"invalid cluster preflight status: {self.status}")
        _require_non_empty_string(self.severity, "severity")
        _require_non_empty_string(self.code, "code")
        _require_non_empty_string(self.cluster_variable, "cluster_variable")
        _require_non_empty_string(self.wire_field, "wire_field")
        for field_name in (
            "cluster_count",
            "row_count",
            "missing_count",
            "singleton_cluster_count",
        ):
            if type(getattr(self, field_name)) is not int or getattr(self, field_name) < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.value_type is not None:
            _require_string(self.value_type, "value_type")
        _require_mapping(self.evidence, "evidence")
        _require_mapping(self.invariants, "invariants")
        object.__setattr__(self, "evidence", _freeze(self.evidence, "evidence"))
        object.__setattr__(self, "invariants", _freeze(self.invariants, "invariants"))
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status,
            "severity": self.severity,
            "code": self.code,
            "cluster_variable": self.cluster_variable,
            "wire_field": self.wire_field,
            "cluster_count": self.cluster_count,
            "row_count": self.row_count,
            "missing_count": self.missing_count,
            "singleton_cluster_count": self.singleton_cluster_count,
            "all_singleton_clusters": self.all_singleton_clusters,
            "value_type": self.value_type,
            "reason_codes": list(self.reason_codes),
            "evidence": _thaw(self.evidence),
            "invariants": _thaw(self.invariants),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ClusterPreflightResult":
        if not isinstance(value, Mapping):
            raise TypeError("cluster preflight result must be a mapping")
        required = {
            "valid",
            "status",
            "severity",
            "code",
            "cluster_variable",
            "wire_field",
            "cluster_count",
            "row_count",
            "missing_count",
            "singleton_cluster_count",
            "all_singleton_clusters",
            "value_type",
            "reason_codes",
            "evidence",
            "invariants",
        }
        extra = set(value) - required
        missing = required - set(value)
        if extra:
            raise ValueError("extra cluster preflight field(s): " + ", ".join(sorted(extra)))
        if missing:
            raise KeyError("missing cluster preflight field(s): " + ", ".join(sorted(missing)))
        return cls(
            valid=value["valid"],
            status=value["status"],
            severity=value["severity"],
            code=value["code"],
            cluster_variable=value["cluster_variable"],
            wire_field=value.get("wire_field", "entity_col"),
            cluster_count=value.get("cluster_count", 0),
            row_count=value.get("row_count", 0),
            missing_count=value.get("missing_count", 0),
            singleton_cluster_count=value.get("singleton_cluster_count", 0),
            all_singleton_clusters=value.get("all_singleton_clusters", False),
            value_type=value.get("value_type"),
            reason_codes=tuple(value.get("reason_codes", ())),
            evidence=value.get("evidence", {}),
            invariants=value.get("invariants", {}),
        )


@dataclass(frozen=True)
class IntentValidationResult:
    valid: bool
    status: ValidationStatus
    severity: str
    code: str
    action_id: str
    operation_id: str
    canonical_patch: Mapping[str, Any] = field(default_factory=dict)
    wire_patch: Mapping[str, Any] = field(default_factory=dict)
    comparison_target: ComparisonTarget | None = None
    source_validation: SourceValidationResult | None = None
    cluster_preflight: ClusterPreflightResult | None = None
    evidence: Mapping[str, Any] = field(default_factory=dict)
    invariants: Mapping[str, Any] = field(default_factory=dict)
    side_effects: Mapping[str, bool] = field(default_factory=dict)
    reason_codes: tuple[str, ...] = field(default_factory=tuple)
    message: str = ""

    def __post_init__(self) -> None:
        if type(self.valid) is not bool:
            raise TypeError("valid must be a bool")
        if self.status not in {"pass", "warning", "fail"}:
            raise ValueError(f"invalid intent validation status: {self.status}")
        _require_non_empty_string(self.severity, "severity")
        _require_non_empty_string(self.code, "code")
        _require_non_empty_string(self.action_id, "action_id")
        _require_non_empty_string(self.operation_id, "operation_id")
        for field_name in ("canonical_patch", "wire_patch", "evidence", "invariants", "side_effects"):
            value = getattr(self, field_name)
            _require_mapping(value, field_name)
            object.__setattr__(self, field_name, _freeze(value, field_name))
        if any(type(key) is not str or type(value) is not bool for key, value in self.side_effects.items()):
            raise TypeError("side_effects must map strings to booleans")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status,
            "severity": self.severity,
            "code": self.code,
            "action_id": self.action_id,
            "operation_id": self.operation_id,
            "canonical_patch": _thaw(self.canonical_patch),
            "wire_patch": _thaw(self.wire_patch),
            "comparison_target": self.comparison_target.to_dict() if self.comparison_target else None,
            "source_validation": self.source_validation.to_dict() if self.source_validation else None,
            "cluster_preflight": self.cluster_preflight.to_dict() if self.cluster_preflight else None,
            "evidence": _thaw(self.evidence),
            "invariants": _thaw(self.invariants),
            "side_effects": _thaw(self.side_effects),
            "reason_codes": list(self.reason_codes),
            "message": self.message,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "IntentValidationResult":
        if not isinstance(value, Mapping):
            raise TypeError("intent validation result must be a mapping")
        required = {
            "valid",
            "status",
            "severity",
            "code",
            "action_id",
            "operation_id",
            "canonical_patch",
            "wire_patch",
            "comparison_target",
            "source_validation",
            "cluster_preflight",
            "evidence",
            "invariants",
            "side_effects",
            "reason_codes",
            "message",
        }
        extra = set(value) - required
        missing = required - set(value)
        if extra:
            raise ValueError("extra intent validation field(s): " + ", ".join(sorted(extra)))
        if missing:
            raise KeyError("missing intent validation field(s): " + ", ".join(sorted(missing)))
        return cls(
            valid=value["valid"],
            status=value["status"],
            severity=value["severity"],
            code=value["code"],
            action_id=value["action_id"],
            operation_id=value["operation_id"],
            canonical_patch=value.get("canonical_patch", {}),
            wire_patch=value.get("wire_patch", {}),
            comparison_target=(
                ComparisonTarget.from_dict(value["comparison_target"])
                if value.get("comparison_target") is not None
                else None
            ),
            source_validation=(
                SourceValidationResult.from_dict(value["source_validation"])
                if value.get("source_validation") is not None
                else None
            ),
            cluster_preflight=(
                ClusterPreflightResult.from_dict(value["cluster_preflight"])
                if value.get("cluster_preflight") is not None
                else None
            ),
            evidence=value.get("evidence", {}),
            invariants=value.get("invariants", {}),
            side_effects=value.get("side_effects", {}),
            reason_codes=tuple(value.get("reason_codes", ())),
            message=value.get("message", ""),
        )


ProposalRejection = IntentValidationResult


def _validate_envelope(
    *,
    packet_type: Any,
    schema_version: Any,
    status: Any,
    source: Any,
    child: Any,
    operation: Any,
    execution: Any,
    logical_key: Any,
    input_fingerprints: Any,
    policy_versions: Any,
    timestamps: Any,
    reasons: Any,
    payload: Any,
) -> None:
    for field_name, value in (
        ("packet_type", packet_type),
        ("schema_version", schema_version),
        ("status", status),
        ("logical_key", logical_key),
    ):
        _require_string(value, field_name)
    if status not in {"pending", "complete", "blocked", "failed"}:
        raise ValueError(f"invalid packet status: {status}")

    mapping_fields = {
        "source": source,
        "child": child,
        "operation": operation,
        "execution": execution,
        "input_fingerprints": input_fingerprints,
        "policy_versions": policy_versions,
        "timestamps": timestamps,
        "payload": payload,
    }
    for field_name, value in mapping_fields.items():
        _require_mapping(value, field_name)
        if any(type(key) is not str for key in value):
            raise TypeError(f"{field_name} keys must be strings")
    for field_name, value in (
        ("input_fingerprints", input_fingerprints),
        ("policy_versions", policy_versions),
        ("timestamps", timestamps),
    ):
        if any(type(item) is not str for item in value.values()):
            raise TypeError(f"{field_name} values must be strings")
    if not isinstance(reasons, (list, tuple)):
        raise TypeError("reasons must be a list")
    if any(type(item) is not str for item in reasons):
        raise TypeError("reasons items must be strings")


@dataclass(frozen=True)
class PacketEnvelope:
    packet_type: str
    schema_version: str
    status: PacketStatus
    source: Mapping[str, Any]
    child: Mapping[str, Any]
    operation: Mapping[str, Any]
    execution: Mapping[str, Any]
    logical_key: str
    input_fingerprints: Mapping[str, str]
    policy_versions: Mapping[str, str]
    timestamps: Mapping[str, str]
    reasons: tuple[str, ...] = field(default_factory=tuple)
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_envelope(
            packet_type=self.packet_type,
            schema_version=self.schema_version,
            status=self.status,
            source=self.source,
            child=self.child,
            operation=self.operation,
            execution=self.execution,
            logical_key=self.logical_key,
            input_fingerprints=self.input_fingerprints,
            policy_versions=self.policy_versions,
            timestamps=self.timestamps,
            reasons=self.reasons,
            payload=self.payload,
        )
        for field_name in (
            "source",
            "child",
            "operation",
            "execution",
            "input_fingerprints",
            "policy_versions",
            "timestamps",
            "payload",
        ):
            object.__setattr__(
                self,
                field_name,
                _freeze(getattr(self, field_name), field_name),
            )
        object.__setattr__(self, "reasons", tuple(self.reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_type": self.packet_type,
            "schema_version": self.schema_version,
            "status": self.status,
            "source": _thaw(self.source),
            "child": _thaw(self.child),
            "operation": _thaw(self.operation),
            "execution": _thaw(self.execution),
            "logical_key": self.logical_key,
            "input_fingerprints": _thaw(self.input_fingerprints),
            "policy_versions": _thaw(self.policy_versions),
            "timestamps": _thaw(self.timestamps),
            "reasons": list(self.reasons),
            "payload": _thaw(self.payload),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PacketEnvelope":
        if not isinstance(value, Mapping):
            raise TypeError("envelope must be a mapping")
        required = (
            "packet_type",
            "schema_version",
            "status",
            "source",
            "child",
            "operation",
            "execution",
            "logical_key",
            "input_fingerprints",
            "policy_versions",
            "timestamps",
            "reasons",
            "payload",
        )
        allowed = set(required)
        extra = [key for key in value if key not in allowed]
        if extra:
            rendered = ", ".join(repr(key) for key in extra)
            raise ValueError(f"extra envelope field(s): {rendered}")
        missing = [field for field in required if field not in value]
        if missing:
            raise KeyError(f"missing envelope field(s): {', '.join(missing)}")

        return cls(
            packet_type=value["packet_type"],
            schema_version=value["schema_version"],
            status=value["status"],
            source=value["source"],
            child=value["child"],
            operation=value["operation"],
            execution=value["execution"],
            logical_key=value["logical_key"],
            input_fingerprints=value["input_fingerprints"],
            policy_versions=value["policy_versions"],
            timestamps=value["timestamps"],
            reasons=value["reasons"],
            payload=value["payload"],
        )


@dataclass(frozen=True)
class ComparePayload:
    compare_status: CompareStatus
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _require_string(self.compare_status, "compare_status")
        _require_mapping(self.payload, "payload")
        if self.compare_status not in {
            "complete",
            "partial",
            "not_comparable",
            "blocked_by_integrity",
        }:
            raise ValueError(f"invalid compare_status: {self.compare_status}")
        if "compare_status" in self.payload:
            raise ValueError("payload reserves compare_status")
        object.__setattr__(self, "payload", _freeze(self.payload, "payload"))

    def to_dict(self) -> dict[str, Any]:
        return {"compare_status": self.compare_status, **_thaw(self.payload)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComparePayload":
        if not isinstance(value, Mapping):
            raise TypeError("compare payload must be a mapping")
        if "compare_status" not in value:
            raise KeyError("missing compare_status")
        return cls(
            compare_status=value["compare_status"],
            payload={
                key: item
                for key, item in value.items()
                if key != "compare_status"
            },
        )


class PacketConflictError(ValueError):
    """Raised for identity mismatch or forbidden packet replacement.

    Same-identity pending packets with different content cannot replace one
    another; terminal packets cannot be replaced. A same-identity
    pending-to-terminal advancement remains allowed.
    """


def ensure_packet_idempotent(
    existing: PacketEnvelope | None,
    incoming: PacketEnvelope,
) -> PacketEnvelope:
    """Reconcile packets without replacing a conflicting packet silently.

    Raises :class:`PacketConflictError` for identity mismatch, different
    same-identity pending content, or any replacement of a terminal packet.
    A same-identity pending packet may advance to a terminal packet; storage
    is intentionally outside this foundation.
    """

    if existing is None:
        return incoming
    if (
        existing.packet_type,
        existing.schema_version,
        existing.logical_key,
    ) != (
        incoming.packet_type,
        incoming.schema_version,
        incoming.logical_key,
    ):
        raise PacketConflictError("packet identity does not match")
    if existing.status == "pending":
        if incoming.status == "pending":
            if existing.to_dict() == incoming.to_dict():
                return existing
            raise PacketConflictError("pending packet content conflicts")
        return incoming
    if existing.to_dict() == incoming.to_dict():
        return existing
    if existing.status in TERMINAL_PACKET_STATUSES:
        raise PacketConflictError(
            f"cannot replace terminal packet {existing.logical_key!r}"
        )
    return incoming


def _logical_key(values: tuple[Any, ...]) -> str:
    return sha256_canonical(list(values))


def plan_diff_logical_key(
    *,
    source_run_id: str,
    source_context_fingerprint: str,
    action_id: str,
    canonical_patch_hash: str,
    comparison_target_hash: str,
    schema_version: str,
) -> str:
    return _logical_key(
        (
            source_run_id,
            source_context_fingerprint,
            action_id,
            canonical_patch_hash,
            comparison_target_hash,
            schema_version,
        ),
    )


def validation_packet_logical_key(
    *,
    child_run_id: str,
    executed_payload_hash: str,
    artifact_manifest_hash: str,
    validation_policy_version: str,
    schema_version: str,
) -> str:
    return _logical_key(
        (
            child_run_id,
            executed_payload_hash,
            artifact_manifest_hash,
            validation_policy_version,
            schema_version,
        ),
    )


def compare_packet_logical_key(
    *,
    source_run_id: str,
    child_run_id: str,
    comparison_target_set_hash: str,
    strategy_version: str,
    schema_version: str,
) -> str:
    return _logical_key(
        (
            source_run_id,
            child_run_id,
            comparison_target_set_hash,
            strategy_version,
            schema_version,
        ),
    )


AnalysisPacketEnvelope = PacketEnvelope
ComparePacketPayload = ComparePayload
make_plan_diff_logical_key = plan_diff_logical_key
make_validation_packet_logical_key = validation_packet_logical_key
make_compare_packet_logical_key = compare_packet_logical_key
