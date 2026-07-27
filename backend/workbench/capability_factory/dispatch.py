"""Immutable preparation contracts for the Capability Factory dispatch seam."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Mapping

from ..custom_capability.canonical import domain_digest


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


__all__ = [
    "PREPARED_RUN_INTENT_CONTRACT_VERSION",
    "PreparedRunIntent",
    "PreparedRunIntentError",
]
