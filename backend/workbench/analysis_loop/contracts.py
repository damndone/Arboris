"""Packet contracts and logical identity helpers for the Agent Analysis Loop."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from .canonical import sha256_canonical

PacketStatus = Literal["pending", "complete", "blocked", "failed"]
CompareStatus = Literal["complete", "partial", "not_comparable", "blocked_by_integrity"]
TERMINAL_PACKET_STATUSES = frozenset({"complete", "blocked", "failed"})


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


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
            object.__setattr__(self, field_name, _freeze(getattr(self, field_name)))
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
        object.__setattr__(self, "payload", _freeze(self.payload))

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
    """Raised when a new packet would replace a different terminal packet."""


def ensure_packet_idempotent(
    existing: PacketEnvelope | None,
    incoming: PacketEnvelope,
) -> PacketEnvelope:
    """Return the idempotent packet or reject a terminal packet conflict.

    Storage is intentionally outside this foundation. A pending packet may be
    advanced by a later packet, while complete/blocked/failed packets are
    immutable once observed.
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
