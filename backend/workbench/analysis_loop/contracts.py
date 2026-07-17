"""Packet contracts and logical identity helpers for the Agent Analysis Loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping

from .canonical import sha256_canonical

PacketStatus = Literal["pending", "complete", "blocked", "failed"]
CompareStatus = Literal["complete", "partial", "not_comparable", "blocked_by_integrity"]
TERMINAL_PACKET_STATUSES = frozenset({"complete", "blocked", "failed"})


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
        if self.status not in {"pending", "complete", "blocked", "failed"}:
            raise ValueError(f"invalid packet status: {self.status}")
        object.__setattr__(self, "reasons", tuple(str(item) for item in self.reasons))

    def to_dict(self) -> dict[str, Any]:
        return {
            "packet_type": self.packet_type,
            "schema_version": self.schema_version,
            "status": self.status,
            "source": dict(self.source),
            "child": dict(self.child),
            "operation": dict(self.operation),
            "execution": dict(self.execution),
            "logical_key": self.logical_key,
            "input_fingerprints": dict(self.input_fingerprints),
            "policy_versions": dict(self.policy_versions),
            "timestamps": dict(self.timestamps),
            "reasons": list(self.reasons),
            "payload": dict(self.payload),
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

        for field in ("packet_type", "schema_version", "status", "logical_key"):
            if type(value[field]) is not str:
                raise TypeError(f"{field} must be a string")

        for field in (
            "source",
            "child",
            "operation",
            "execution",
            "input_fingerprints",
            "policy_versions",
            "timestamps",
            "payload",
        ):
            if not isinstance(value[field], Mapping):
                raise TypeError(f"{field} must be a mapping")

        for field in ("input_fingerprints", "policy_versions", "timestamps"):
            if any(type(item) is not str for item in value[field].values()):
                raise TypeError(f"{field} values must be strings")

        if not isinstance(value["reasons"], (list, tuple)):
            raise TypeError("reasons must be a list")
        if any(type(item) is not str for item in value["reasons"]):
            raise TypeError("reasons items must be strings")

        return cls(
            packet_type=value["packet_type"],
            schema_version=value["schema_version"],
            status=value["status"],
            source=dict(value["source"]),
            child=dict(value["child"]),
            operation=dict(value["operation"]),
            execution=dict(value["execution"]),
            logical_key=value["logical_key"],
            input_fingerprints=dict(value["input_fingerprints"]),
            policy_versions=dict(value["policy_versions"]),
            timestamps=dict(value["timestamps"]),
            reasons=tuple(value["reasons"]),
            payload=dict(value["payload"]),
        )


@dataclass(frozen=True)
class ComparePayload:
    compare_status: CompareStatus
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.payload, Mapping):
            raise TypeError("payload must be a mapping")
        if self.compare_status not in {
            "complete",
            "partial",
            "not_comparable",
            "blocked_by_integrity",
        }:
            raise ValueError(f"invalid compare_status: {self.compare_status}")
        if "compare_status" in self.payload:
            raise ValueError("payload reserves compare_status")

    def to_dict(self) -> dict[str, Any]:
        return {"compare_status": self.compare_status, **dict(self.payload)}

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ComparePayload":
        return cls(
            compare_status=str(value["compare_status"]),
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
