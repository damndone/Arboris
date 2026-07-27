"""Immutable preparation contracts for the Capability Factory dispatch seam."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, ClassVar, Mapping

from ..custom_capability.canonical import domain_digest
from .control import ControlSubjectCursor, ExecutionControlRecord


PREPARED_RUN_INTENT_CONTRACT_VERSION = "PreparedRunIntent@1.0"
_HEX = frozenset("0123456789abcdef")


class PreparedRunIntentError(ValueError):
    """Raised when an immutable prepared intent fails closed."""


def _text(value: Any, field: str, *, maximum: int = 512) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise PreparedRunIntentError(f"{field} must be a bounded non-empty string")
    if any(ord(char) < 0x20 for char in value):
        raise PreparedRunIntentError(f"{field} contains a control character")
    return value


def _identifier(value: Any, field: str) -> str:
    text = _text(value, field)
    if text in {".", ".."} or "/" in text or "\\" in text:
        raise PreparedRunIntentError(f"{field} must be path-safe")
    return text


def _digest(value: Any, field: str) -> str:
    text = _text(value, field, maximum=64)
    if len(text) != 64 or any(char not in _HEX for char in text):
        raise PreparedRunIntentError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _draft_hash(value: Any) -> str:
    text = _text(value, "draft_hash", maximum=71)
    if not text.startswith("sha256:") or len(text) != 71 or any(char not in _HEX for char in text[7:]):
        raise PreparedRunIntentError("draft_hash must be a sha256-prefixed digest")
    return text


def _revision(value: Any, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise PreparedRunIntentError(f"{field} must be a positive integer")
    return value


@dataclass(frozen=True, slots=True)
class PreparedRunIntent:
    """Content-addressed identity for a validated but not-yet-created Run.

    This object is deliberately a pure contract. Its construction does not
    inspect a project, create a Run directory, reserve a process, or call a
    dispatcher. A later trusted consumer must compare all pinned revisions in
    the durable control stream before doing any external work.
    """

    intent_id: str
    draft_id: str
    draft_hash: str
    binding_ref: str
    binding_revision: int
    capability_ref: str
    bundle_ref: str
    evidence_ref: str
    admission_ref: str
    runtime_policy_ref: str
    host_containment_ref: str
    operation_id: str
    run_id: str
    input_graph_fingerprint: str
    input_contract_ref: str
    output_contract_ref: str
    consumer_projection_ref: str
    host_validity_revision: int
    bundle_validity_revision: int
    evidence_validity_revision: int
    admission_validity_revision: int
    artifact_namespace: str
    graph_edge_namespace: str
    trace_event_namespace: str
    namespace_derivation_revision: int
    artifact_producer_revision: int
    graph_producer_revision: int
    trace_producer_revision: int
    slot_mapping_revision: int
    harness_abi_revision: int
    protocol_revision: int

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "intent_id",
        "draft_id",
        "draft_hash",
        "binding_ref",
        "binding_revision",
        "capability_ref",
        "bundle_ref",
        "evidence_ref",
        "admission_ref",
        "runtime_policy_ref",
        "host_containment_ref",
        "operation_id",
        "run_id",
        "input_graph_fingerprint",
        "input_contract_ref",
        "output_contract_ref",
        "consumer_projection_ref",
        "host_validity_revision",
        "bundle_validity_revision",
        "evidence_validity_revision",
        "admission_validity_revision",
        "artifact_namespace",
        "graph_edge_namespace",
        "trace_event_namespace",
        "namespace_derivation_revision",
        "artifact_producer_revision",
        "graph_producer_revision",
        "trace_producer_revision",
        "slot_mapping_revision",
        "harness_abi_revision",
        "protocol_revision",
    )

    def __post_init__(self) -> None:
        for field in (
            "intent_id",
            "draft_id",
            "operation_id",
            "run_id",
            "artifact_namespace",
            "graph_edge_namespace",
            "trace_event_namespace",
        ):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        object.__setattr__(self, "draft_hash", _draft_hash(self.draft_hash))
        for field in (
            "binding_ref",
            "capability_ref",
            "bundle_ref",
            "evidence_ref",
            "admission_ref",
            "runtime_policy_ref",
            "host_containment_ref",
            "input_contract_ref",
            "output_contract_ref",
            "consumer_projection_ref",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        object.__setattr__(
            self,
            "input_graph_fingerprint",
            _text(self.input_graph_fingerprint, "input_graph_fingerprint"),
        )
        for field in (
            "binding_revision",
            "host_validity_revision",
            "bundle_validity_revision",
            "evidence_validity_revision",
            "admission_validity_revision",
            "namespace_derivation_revision",
            "artifact_producer_revision",
            "graph_producer_revision",
            "trace_producer_revision",
            "slot_mapping_revision",
            "harness_abi_revision",
            "protocol_revision",
        ):
            object.__setattr__(self, field, _revision(getattr(self, field), field))

    def _payload(self) -> dict[str, Any]:
        return {field: getattr(self, field) for field in self._FIELDS}

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.prepared_run_intent/v1",
            {"contract_version": PREPARED_RUN_INTENT_CONTRACT_VERSION, **self._payload()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": PREPARED_RUN_INTENT_CONTRACT_VERSION,
            **self._payload(),
            "content_digest": self.content_digest,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "PreparedRunIntent":
        if not isinstance(value, Mapping):
            raise PreparedRunIntentError("prepared run intent must be an object")
        expected = {"contract_version", *cls._FIELDS, "content_digest"}
        if set(value) != expected:
            raise PreparedRunIntentError("prepared run intent has unknown or missing fields")
        if value["contract_version"] != PREPARED_RUN_INTENT_CONTRACT_VERSION:
            raise PreparedRunIntentError("prepared run intent contract version is unsupported")
        try:
            result = cls(**{field: value[field] for field in cls._FIELDS})
        except (TypeError, ValueError) as error:
            if isinstance(error, PreparedRunIntentError):
                raise
            raise PreparedRunIntentError("prepared run intent fields are invalid") from error
        if value["content_digest"] != result.content_digest:
            raise PreparedRunIntentError("prepared run intent content digest mismatch")
        return result


class DispatchReservationError(ValueError):
    """Raised when a reservation record is not bound to its control snapshot."""


@dataclass(frozen=True, slots=True)
class DispatchReservation:
    """Immutable unique-start record derived from one control append."""

    reservation_id: str
    authorization_id: str
    authorization_payload_digest: str
    intent_id: str
    intent_digest: str
    run_id: str
    attempt_id: str
    lease_epoch: int
    executor_idempotency_key: str
    control_sequence: int
    subject_snapshot: tuple[ControlSubjectCursor, ...]

    _FIELDS: ClassVar[tuple[str, ...]] = (
        "reservation_id",
        "authorization_id",
        "authorization_payload_digest",
        "intent_id",
        "intent_digest",
        "run_id",
        "attempt_id",
        "lease_epoch",
        "executor_idempotency_key",
        "control_sequence",
        "subject_snapshot",
    )

    def __post_init__(self) -> None:
        for field in (
            "reservation_id",
            "authorization_id",
            "intent_id",
            "run_id",
            "attempt_id",
            "executor_idempotency_key",
        ):
            object.__setattr__(self, field, _identifier(getattr(self, field), field))
        for field in ("authorization_payload_digest", "intent_digest"):
            object.__setattr__(self, field, _digest(getattr(self, field), field))
        if not isinstance(self.lease_epoch, int) or isinstance(self.lease_epoch, bool) or self.lease_epoch < 1:
            raise DispatchReservationError("lease_epoch must be a positive integer")
        if not isinstance(self.control_sequence, int) or isinstance(self.control_sequence, bool) or self.control_sequence < 1:
            raise DispatchReservationError("control_sequence must be a positive integer")
        if not isinstance(self.subject_snapshot, tuple) or not self.subject_snapshot:
            raise DispatchReservationError("subject_snapshot must be a non-empty tuple")
        if any(not isinstance(item, ControlSubjectCursor) for item in self.subject_snapshot):
            raise DispatchReservationError("subject_snapshot contains an invalid cursor")

    @classmethod
    def from_control_record(
        cls,
        *,
        intent: PreparedRunIntent,
        control_record: ExecutionControlRecord,
    ) -> "DispatchReservation":
        if not isinstance(intent, PreparedRunIntent):
            raise DispatchReservationError("intent must be a PreparedRunIntent")
        if not isinstance(control_record, ExecutionControlRecord):
            raise DispatchReservationError("control_record must be an ExecutionControlRecord")
        if control_record.request.record_type != "dispatch_reservation":
            raise DispatchReservationError("control record is not a dispatch reservation")
        value = control_record.request.value
        expected = {
            "authorization_id",
            "authorization_payload_digest",
            "intent_id",
            "intent_digest",
            "run_id",
            "attempt_id",
            "lease_epoch",
            "executor_idempotency_key",
        }
        if set(value) != expected:
            raise DispatchReservationError("dispatch reservation payload fields are invalid")
        if value["intent_id"] != intent.intent_id or value["intent_digest"] != intent.content_digest:
            raise DispatchReservationError("dispatch reservation is bound to another intent")
        if value["run_id"] != intent.run_id:
            raise DispatchReservationError("dispatch reservation run identity does not match intent")
        try:
            return cls(
                reservation_id=control_record.request.record_id,
                authorization_id=value["authorization_id"],
                authorization_payload_digest=value["authorization_payload_digest"],
                intent_id=value["intent_id"],
                intent_digest=value["intent_digest"],
                run_id=value["run_id"],
                attempt_id=value["attempt_id"],
                lease_epoch=value["lease_epoch"],
                executor_idempotency_key=value["executor_idempotency_key"],
                control_sequence=control_record.control_sequence,
                subject_snapshot=control_record.subject_snapshot,
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, DispatchReservationError):
                raise
            raise DispatchReservationError("dispatch reservation payload is invalid") from error

    def _payload(self) -> dict[str, Any]:
        return {
            "reservation_id": self.reservation_id,
            "authorization_id": self.authorization_id,
            "authorization_payload_digest": self.authorization_payload_digest,
            "intent_id": self.intent_id,
            "intent_digest": self.intent_digest,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "lease_epoch": self.lease_epoch,
            "executor_idempotency_key": self.executor_idempotency_key,
            "control_sequence": self.control_sequence,
            "subject_snapshot": [item.to_dict() for item in self.subject_snapshot],
        }

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.dispatch_reservation/v1",
            {"contract_version": "DispatchReservation@1.0", **self._payload()},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "DispatchReservation@1.0",
            **self._payload(),
            "content_digest": self.content_digest,
        }

    @staticmethod
    def _cursor_from_dict(value: Any) -> ControlSubjectCursor:
        if not isinstance(value, Mapping):
            raise DispatchReservationError("subject snapshot item is not an object")
        expected = {
            "subject_kind",
            "subject_ref",
            "validity_revision",
            "status",
            "effective_at",
            "expires_at",
            "authority",
            "reason",
            "source_record_ref",
            "control_sequence",
        }
        if set(value) != expected:
            raise DispatchReservationError("subject snapshot fields are invalid")
        try:
            def parse_time(item: Any, field: str) -> datetime:
                if not isinstance(item, str):
                    raise DispatchReservationError(f"{field} must be a timestamp")
                return datetime.fromisoformat(item.replace("Z", "+00:00")).astimezone(timezone.utc)

            return ControlSubjectCursor(
                subject_kind=value["subject_kind"],
                subject_ref=value["subject_ref"],
                validity_revision=value["validity_revision"],
                status=value["status"],
                effective_at=parse_time(value["effective_at"], "effective_at"),
                expires_at=(None if value["expires_at"] is None else parse_time(value["expires_at"], "expires_at")),
                authority=value["authority"],
                reason=value["reason"],
                source_record_ref=value["source_record_ref"],
                control_sequence=value["control_sequence"],
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, DispatchReservationError):
                raise
            raise DispatchReservationError("subject snapshot item is invalid") from error

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "DispatchReservation":
        if not isinstance(value, Mapping):
            raise DispatchReservationError("dispatch reservation must be an object")
        expected = {"contract_version", *cls._FIELDS, "content_digest"}
        if set(value) != expected or value["contract_version"] != "DispatchReservation@1.0":
            raise DispatchReservationError("dispatch reservation fields or version are invalid")
        snapshot = value["subject_snapshot"]
        if not isinstance(snapshot, list) or not snapshot:
            raise DispatchReservationError("dispatch reservation subject snapshot is invalid")
        try:
            result = cls(
                reservation_id=value["reservation_id"],
                authorization_id=value["authorization_id"],
                authorization_payload_digest=value["authorization_payload_digest"],
                intent_id=value["intent_id"],
                intent_digest=value["intent_digest"],
                run_id=value["run_id"],
                attempt_id=value["attempt_id"],
                lease_epoch=value["lease_epoch"],
                executor_idempotency_key=value["executor_idempotency_key"],
                control_sequence=value["control_sequence"],
                subject_snapshot=tuple(cls._cursor_from_dict(item) for item in snapshot),
            )
        except (TypeError, ValueError) as error:
            if isinstance(error, DispatchReservationError):
                raise
            raise DispatchReservationError("dispatch reservation fields are invalid") from error
        if value["content_digest"] != result.content_digest:
            raise DispatchReservationError("dispatch reservation content digest mismatch")
        return result


__all__ = [
    "DispatchReservation",
    "DispatchReservationError",
    "PREPARED_RUN_INTENT_CONTRACT_VERSION",
    "PreparedRunIntent",
    "PreparedRunIntentError",
]
