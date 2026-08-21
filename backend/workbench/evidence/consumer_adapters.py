"""Port-based, fail-closed projections of persisted evidence envelopes.

This module deliberately has no statistical implementation dependency.  A
projection may select, order, redact, or omit already persisted facts, but it
never derives a new value or fills a missing value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
import re
from threading import RLock
from typing import Any
import weakref

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.contracts.agent.context_egress import (
    ContextEgressGatewayV1,
    ContextEgressReceiptIssuerV1,
    ContextEgressReceiptV1,
    EgressContractError,
    SensitivityClassV1,
    require_context_egress_receipt,
)
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.foundation_status import (
    AvailabilityStatusV1,
    CompletenessStatusV1,
    ExecutionStatusV1,
    TransactionStatusV1,
)
from workbench.contracts.evidence.envelope import EvidenceEnvelopeV1, NumericFactV1
from workbench.contracts.evidence.persistence import (
    EvidenceCommitBindingV1,
)
from workbench.evidence.contracts import ArtifactAdmissionV1
from workbench.evidence.persistence import (
    EvidencePacketStoreV1,
    EvidencePersistenceAdmissionV1,
    EvidencePersistenceError,
)
from workbench.evidence.authority import (
    EvidenceHostAuthorityError,
    build_authority_request,
    issue_host_proof,
    validate_host_proof,
)
from workbench.evidence.registry import (
    EvidenceRegistryError,
    EvidenceRegistryV1,
    validate_registry_persistence_receipt,
)


class EvidenceProjectionError(ValueError):
    """A stable, caller-visible projection contract failure."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


class ProjectionStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    DEGRADED = "degraded"
    BLOCKED = "blocked"


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip() or "\x00" in value:
        raise EvidenceProjectionError("PROJECTION_TEXT_INVALID", f"{name} must be non-empty text")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise EvidenceProjectionError("PROJECTION_IDENTITY_INVALID", f"{name} must be a SHA-256 digest")
    return value


def _ref(value: object, name: str) -> ContractRefV1:
    if type(value) is not ContractRefV1:
        raise EvidenceProjectionError("PROJECTION_REF_INVALID", f"{name} must be ContractRefV1")
    return value


def _sensitivity(value: object, name: str) -> SensitivityClassV1:
    if isinstance(value, SensitivityClassV1):
        return value
    if type(value) is str:
        try:
            return SensitivityClassV1(value)
        except ValueError as exc:
            raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", f"{name} is invalid") from exc
    raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", f"{name} is invalid")


def _sensitivity_tuple(value: object, name: str) -> tuple[SensitivityClassV1, ...]:
    if not isinstance(value, (list, tuple)) or not value:
        raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", f"{name} must be non-empty")
    result = tuple(_sensitivity(item, f"{name}[]") for item in value)
    if len(result) != len(set(result)):
        raise EvidenceProjectionError("PROJECTION_SENSITIVITY_INVALID", f"{name} must be unique")
    return result


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise EvidenceProjectionError("PROJECTION_TEXT_INVALID", f"{name} must be an array")
    result = tuple(_text(item, f"{name}[]") for item in value)
    if len(result) != len(set(result)):
        raise EvidenceProjectionError("PROJECTION_TEXT_INVALID", f"{name} must be unique")
    return result


@dataclass(frozen=True)
class PersistedEvidenceEnvelopeV1:
    """The only input shape accepted by a consumer adapter.

    The binding and envelope digest are checked at construction time so a
    caller cannot turn an uncommitted or altered payload into a projection.
    """

    commit_id: str
    artifact_ref: str
    envelope_ref: str
    sensitivity: SensitivityClassV1 | str
    binding: EvidenceCommitBindingV1
    envelope: EvidenceEnvelopeV1
    evidence_contract_digest: str | None = None
    envelope_contract_digest: str | None = None

    def __post_init__(self) -> None:
        _text(self.commit_id, "commit_id")
        _text(self.artifact_ref, "artifact_ref")
        _text(self.envelope_ref, "envelope_ref")
        object.__setattr__(self, "sensitivity", _sensitivity(self.sensitivity, "sensitivity"))
        if type(self.binding) is not EvidenceCommitBindingV1:
            raise EvidenceProjectionError("PROJECTION_BINDING_INVALID", "binding is invalid")
        if type(self.envelope) is not EvidenceEnvelopeV1:
            raise EvidenceProjectionError("PROJECTION_ENVELOPE_INVALID", "envelope is invalid")
        if self.binding.commit_id != self.commit_id:
            raise EvidenceProjectionError("PROJECTION_COMMIT_MISMATCH", "binding commit_id differs")
        if self.binding.transaction_status is not TransactionStatusV1.COMMITTED:
            raise EvidenceProjectionError("PROJECTION_NOT_COMMITTED", "only committed evidence may be projected")
        if self.binding.envelope_digest != sha256_canonical(self.envelope.to_dict()):
            raise EvidenceProjectionError("PROJECTION_DIGEST_MISMATCH", "persisted envelope digest differs")
        input_provenance = self.envelope.input_provenance
        if (
            not isinstance(input_provenance, Mapping)
            or set(input_provenance) != {"artifact_ref", "artifact_digest"}
        ):
            raise EvidenceProjectionError(
                "PROJECTION_DATA_SNAPSHOT_IDENTITY_INVALID",
                "persisted envelope input provenance is not an exact data snapshot identity",
            )
        data_snapshot_ref = _text(input_provenance["artifact_ref"], "data_snapshot_ref")
        _digest(input_provenance["artifact_digest"], "data_snapshot_digest")
        dependency_refs = {
            dependency.get("artifact_ref")
            for dependency in self.envelope.dependencies
            if isinstance(dependency, Mapping) and type(dependency.get("artifact_ref")) is str
        }
        if dependency_refs and data_snapshot_ref not in dependency_refs:
            raise EvidenceProjectionError(
                "PROJECTION_DATA_SNAPSHOT_MISMATCH",
                "persisted envelope data snapshot is not one of its declared dependencies",
            )
        source_refs = {
            fact.source_selector.artifact_ref for fact in self.envelope.numeric_facts
        }
        if source_refs and source_refs != {self.artifact_ref}:
            raise EvidenceProjectionError(
                "PROJECTION_ARTIFACT_IDENTITY_MISMATCH",
                "persisted fact source selectors cross the projected artifact identity",
            )
        source_digests = {
            fact.source_selector.artifact_digest for fact in self.envelope.numeric_facts
        }
        if len(source_digests) > 1:
            raise EvidenceProjectionError(
                "PROJECTION_ARTIFACT_IDENTITY_MISMATCH",
                "persisted fact source selectors contain multiple artifact snapshots",
            )
        for name in ("evidence_contract_digest", "envelope_contract_digest"):
            value = getattr(self, name)
            if value is not None:
                _digest(value, name)

    @property
    def envelope_digest(self) -> str:
        return self.binding.envelope_digest

    @property
    def data_snapshot_ref(self) -> str:
        return self.envelope.input_provenance["artifact_ref"]  # type: ignore[return-value]

    @property
    def data_snapshot_digest(self) -> str:
        return self.envelope.input_provenance["artifact_digest"]  # type: ignore[return-value]


def _sensitivity_policy_digest(
    *,
    scope_ref: str,
    artifact_id: str,
    commit_id: str,
    envelope_digest: str,
    sensitivity: SensitivityClassV1,
) -> str:
    return sha256_canonical(
        {
            "scope_ref": scope_ref,
            "artifact_id": artifact_id,
            "commit_id": commit_id,
            "envelope_digest": envelope_digest,
            "sensitivity": sensitivity.value,
        }
    )


_SOURCE_ADMISSIONS: "weakref.WeakKeyDictionary[ServerOwnedEvidenceProjectionSourceV1, ServerOwnedEvidenceProjectionSourceV1]" = weakref.WeakKeyDictionary()
_SOURCE_ADMISSIONS_LOCK = RLock()


class ServerOwnedEvidenceSensitivityPolicyV1:
    """Host-issued sensitivity policy bound to one committed evidence packet."""

    __slots__ = (
        "_scope_ref",
        "_artifact_id",
        "_commit_id",
        "_envelope_digest",
        "_sensitivity",
        "_authority_handle",
        "_authority_request",
        "_authority_proof",
        "_sealed",
    )

    def __init__(
        self,
        *,
        scope_ref: str,
        artifact_id: str,
        commit_id: str,
        envelope_digest: str,
        sensitivity: SensitivityClassV1 | str,
        authority_handle: object | None,
    ) -> None:
        object.__setattr__(self, "_sealed", False)
        if authority_handle is None:
            raise EvidenceProjectionError(
                "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                "sensitivity policy requires a host-issued evidence authority",
            )
        scope_ref = _text(scope_ref, "scope_ref")
        artifact_id = _text(artifact_id, "artifact_id")
        commit_id = _text(commit_id, "commit_id")
        envelope_digest = _digest(envelope_digest, "envelope_digest")
        sensitivity_value = _sensitivity(sensitivity, "sensitivity")
        object.__setattr__(self, "_scope_ref", scope_ref)
        object.__setattr__(self, "_artifact_id", artifact_id)
        object.__setattr__(self, "_commit_id", commit_id)
        object.__setattr__(self, "_envelope_digest", envelope_digest)
        object.__setattr__(self, "_sensitivity", sensitivity_value)
        object.__setattr__(self, "_authority_handle", authority_handle)
        try:
            request = build_authority_request(
                authority_handle,
                purpose="evidence.consumer.sensitivity",
                scope_ref=scope_ref,
                subject_id=id(self),
                payload_digest=self._payload_digest(),
            )
            proof = issue_host_proof(authority_handle, request)
            validate_host_proof(authority_handle, request, proof)
        except EvidenceHostAuthorityError as exc:
            raise EvidenceProjectionError(exc.code, str(exc)) from exc
        object.__setattr__(self, "_authority_request", request)
        object.__setattr__(self, "_authority_proof", proof)
        object.__setattr__(self, "_sealed", True)

    @classmethod
    def _from_host(
        cls,
        *,
        scope_ref: str,
        artifact_id: str,
        commit_id: str,
        envelope_digest: str,
        sensitivity: SensitivityClassV1 | str,
        authority_handle: object,
    ) -> "ServerOwnedEvidenceSensitivityPolicyV1":
        return cls(
            scope_ref=scope_ref,
            artifact_id=artifact_id,
            commit_id=commit_id,
            envelope_digest=envelope_digest,
            sensitivity=sensitivity,
            authority_handle=authority_handle,
        )

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise TypeError("server-owned evidence sensitivity policies are immutable")
        object.__setattr__(self, name, value)

    def __copy__(self):
        raise TypeError("server-owned evidence sensitivity policies cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("server-owned evidence sensitivity policies cannot be copied")

    def __reduce__(self):
        raise TypeError("server-owned evidence sensitivity policies cannot be serialized")

    @property
    def sensitivity(self) -> SensitivityClassV1:
        self._require_policy_authority()
        return self._sensitivity

    def _payload_digest(self) -> str:
        return _sensitivity_policy_digest(
            scope_ref=self._scope_ref,
            artifact_id=self._artifact_id,
            commit_id=self._commit_id,
            envelope_digest=self._envelope_digest,
            sensitivity=self._sensitivity,
        )

    def _require_policy_authority(self) -> None:
        try:
            request = self._authority_request
            if (
                request.subject_id != id(self)
                or request.scope_ref != self._scope_ref
                or request.payload_digest != self._payload_digest()
            ):
                raise ValueError("sensitivity policy binding changed")
            validate_host_proof(self._authority_handle, request, self._authority_proof)
        except EvidenceHostAuthorityError as exc:
            raise EvidenceProjectionError(exc.code, str(exc)) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise EvidenceProjectionError(
                "EVIDENCE_SENSITIVITY_POLICY_REQUIRED",
                "sensitivity policy is not a live server-issued capability",
            ) from exc


class ServerOwnedEvidenceProjectionSourceV1:
    """Live C0 source capability for production evidence consumers.

    ``PersistedEvidenceEnvelopeV1`` is a validated value object, not authority.
    This source revalidates the exact packet store, registry admission,
    registry receipt, host handle, scope, artifact and commit before every
    projection.
    """

    __slots__ = (
        "__weakref__",
        "_evidence_store",
        "_registry",
        "_receipt",
        "_scope_ref",
        "_artifact_id",
        "_commit_id",
        "_envelope_digest",
        "_sensitivity_policy",
        "_authority_handle",
        "_authority_request",
        "_authority_proof",
        "_sealed",
    )

    def __init__(
        self,
        evidence_store: EvidencePacketStoreV1,
        registry: EvidenceRegistryV1,
        receipt: object,
        *,
        scope_ref: str,
        artifact_id: str,
        commit_id: str,
        sensitivity_policy: ServerOwnedEvidenceSensitivityPolicyV1 | None = None,
        envelope_digest: str,
        authority_handle: object | None = None,
    ) -> None:
        object.__setattr__(self, "_sealed", False)
        admitted = False
        if authority_handle is None:
            raise EvidenceProjectionError(
                "EVIDENCE_HOST_AUTHORITY_REQUIRED",
                "consumer projection requires a host-issued evidence authority",
            )
        try:
            if type(evidence_store) is not EvidencePacketStoreV1:
                raise EvidenceProjectionError(
                    "EVIDENCE_SERVER_SOURCE_REQUIRED",
                    "consumer projection requires the server-owned EvidencePacketStoreV1",
                )
            if type(registry) is not EvidenceRegistryV1:
                raise EvidenceProjectionError(
                    "EVIDENCE_SERVER_SOURCE_REQUIRED",
                    "consumer projection requires the server-owned EvidenceRegistryV1",
                )
            object.__setattr__(self, "_evidence_store", evidence_store)
            object.__setattr__(self, "_registry", registry)
            object.__setattr__(self, "_receipt", receipt)
            object.__setattr__(self, "_scope_ref", _text(scope_ref, "scope_ref"))
            object.__setattr__(self, "_artifact_id", _text(artifact_id, "artifact_id"))
            object.__setattr__(self, "_commit_id", _text(commit_id, "commit_id"))
            object.__setattr__(self, "_envelope_digest", _digest(envelope_digest, "envelope_digest"))
            if type(sensitivity_policy) is not ServerOwnedEvidenceSensitivityPolicyV1:
                raise EvidenceProjectionError(
                    "EVIDENCE_SENSITIVITY_POLICY_REQUIRED",
                    "consumer projection requires a server-issued sensitivity policy",
                )
            object.__setattr__(self, "_sensitivity_policy", sensitivity_policy)
            object.__setattr__(self, "_authority_handle", authority_handle)
            try:
                request = build_authority_request(
                    authority_handle,
                    purpose="evidence.consumer.source",
                    scope_ref=self._scope_ref,
                    subject_id=id(self),
                    payload_digest=self._payload_digest(),
                )
                proof = issue_host_proof(authority_handle, request)
                validate_host_proof(authority_handle, request, proof)
            except EvidenceHostAuthorityError as exc:
                raise EvidenceProjectionError(exc.code, str(exc)) from exc
            object.__setattr__(self, "_authority_request", request)
            object.__setattr__(self, "_authority_proof", proof)
            with _SOURCE_ADMISSIONS_LOCK:
                _SOURCE_ADMISSIONS[self] = self
                admitted = True
            _load_server_record(self)
            object.__setattr__(self, "_sealed", True)
        except Exception:
            if admitted:
                with _SOURCE_ADMISSIONS_LOCK:
                    try:
                        del _SOURCE_ADMISSIONS[self]
                    except KeyError:
                        pass
            raise

    def __setattr__(self, name: str, value: object) -> None:
        if getattr(self, "_sealed", False):
            raise TypeError("server-owned evidence projection sources are immutable")
        object.__setattr__(self, name, value)

    def __copy__(self):
        raise TypeError("server-owned evidence projection sources cannot be copied")

    def __deepcopy__(self, _memo):
        raise TypeError("server-owned evidence projection sources cannot be copied")

    def __reduce__(self):
        raise TypeError("server-owned evidence projection sources cannot be serialized")

    @property
    def scope_ref(self) -> str:
        return self._scope_ref

    @property
    def artifact_id(self) -> str:
        return self._artifact_id

    @property
    def commit_id(self) -> str:
        return self._commit_id

    def _payload_digest(self) -> str:
        policy = self._sensitivity_policy
        return sha256_canonical(
            {
                "scope_ref": self._scope_ref,
                "artifact_id": self._artifact_id,
                "commit_id": self._commit_id,
                "envelope_digest": self._envelope_digest,
                "sensitivity_policy_digest": policy._payload_digest(),
                "evidence_store_id": id(self._evidence_store),
                "registry_id": id(self._registry),
                "receipt_id": id(self._receipt),
            }
        )

    def _require_source_authority(self) -> None:
        with _SOURCE_ADMISSIONS_LOCK:
            if _SOURCE_ADMISSIONS.get(self) is not self:
                raise EvidenceProjectionError(
                    "EVIDENCE_SERVER_SOURCE_REQUIRED",
                    "consumer projection source is not the exact server-issued capability",
                )
        try:
            request = self._authority_request
            if (
                request.subject_id != id(self)
                or request.scope_ref != self._scope_ref
                or request.payload_digest != self._payload_digest()
            ):
                raise ValueError("consumer projection source binding changed")
            validate_host_proof(self._authority_handle, request, self._authority_proof)
            policy = self._sensitivity_policy
            policy._require_policy_authority()
            if (
                policy._authority_handle is not self._authority_handle
                or policy._scope_ref != self._scope_ref
                or policy._artifact_id != self._artifact_id
                or policy._commit_id != self._commit_id
                or policy._envelope_digest != self._envelope_digest
            ):
                raise EvidenceProjectionError(
                    "EVIDENCE_SENSITIVITY_POLICY_REQUIRED",
                    "sensitivity policy is not bound to this evidence source",
                )
            admission = self._evidence_store.admission
            if type(admission) is not EvidencePersistenceAdmissionV1:
                raise ValueError("evidence store admission is not C0 persistence")
            if getattr(admission, "_authority_handle", None) is not self._authority_handle:
                raise ValueError("persistence authority handle differs")
            admission._validate_authority()
            if self._registry.scope_ref != self._scope_ref:
                raise ValueError("registry scope differs")
            if self._registry._host_authority_handle() is not self._authority_handle:
                raise ValueError("registry authority handle differs")
            admitted = self._registry.get(self._artifact_id, scope_ref=self._scope_ref)
            validate_registry_persistence_receipt(
                admitted,
                self._receipt,
                registry=self._registry,
            )
        except EvidenceProjectionError:
            raise
        except (EvidencePersistenceError, EvidenceRegistryError, AttributeError, TypeError, ValueError) as exc:
            raise EvidenceProjectionError(
                "EVIDENCE_SERVER_SOURCE_REQUIRED",
                "consumer projection source is not backed by a live server-owned registry receipt",
            ) from exc



def _load_server_record(source: ServerOwnedEvidenceProjectionSourceV1) -> PersistedEvidenceEnvelopeV1:
    """Load the raw envelope only inside the projection implementation seam.

    The source capability intentionally has no raw-record reader method.  This
    keeps a caller from turning a private source method into an alternate facts
    port; the registry is the only production boundary that consumes this
    module-private server reload.
    """

    source._require_source_authority()
    try:
        binding = source._evidence_store.load(
            source._commit_id,
            registry=source._registry,
            receipt=source._receipt,
        )
        artifact = source._evidence_store.load_packet(
            source._commit_id,
            registry=source._registry,
            receipt=source._receipt,
        )
        if type(artifact) is not ArtifactAdmissionV1:
            raise ValueError("stored packet is not an admitted artifact")
        admitted = source._registry.resolve(
            source._artifact_id,
            scope_ref=source._scope_ref,
        )
        validate_registry_persistence_receipt(
            admitted,
            source._receipt,
            registry=source._registry,
        )
        if (
            artifact.to_dict() != admitted.to_dict()
            or artifact.artifact_id != source._artifact_id
            or artifact.scope_ref != source._scope_ref
            or binding.commit_id != source._commit_id
            or binding.artifact_admission_ref != artifact.artifact_id
            or artifact.envelope_digest != binding.envelope_digest
            or binding.envelope_digest != source._envelope_digest
            or artifact.envelope_digest != source._envelope_digest
            or source._sensitivity_policy._envelope_digest != source._envelope_digest
        ):
            raise EvidenceProjectionError(
                "EVIDENCE_ADMISSION_NOT_FOUND",
                "consumer projection source identity differs from the server-owned packet",
            )
        record = PersistedEvidenceEnvelopeV1(
            commit_id=binding.commit_id,
            artifact_ref=artifact.artifact_id,
            envelope_ref=f"evidence-envelope:{artifact.envelope_digest}",
            sensitivity=source._sensitivity_policy.sensitivity,
            binding=binding,
            envelope=artifact.envelope.envelope,
            evidence_contract_digest=artifact.contract_digest,
        )
        if record.envelope_digest != source._envelope_digest:
            raise EvidenceProjectionError(
                "PROJECTION_DIGEST_MISMATCH",
                "consumer projection source envelope digest differs from the server commit",
            )
        return record
    except EvidenceProjectionError:
        raise
    except (EvidencePersistenceError, EvidenceRegistryError, AttributeError, TypeError, ValueError, KeyError) as exc:
        raise EvidenceProjectionError(
            "EVIDENCE_SERVER_SOURCE_REQUIRED",
            "consumer projection source could not reload the server-owned evidence packet",
        ) from exc


@dataclass(frozen=True)
class ConsumerProjectionSpecV1:
    consumer_id: str
    semantic_version: str
    projection_ref: ContractRefV1
    policy_ref: ContractRefV1
    renderer_key: str
    max_token_budget: int
    max_row_budget: int
    allowed_sensitivity: tuple[SensitivityClassV1 | str, ...]
    ordering: tuple[str, ...]
    accepted_evidence_refs: tuple[ContractRefV1, ...] = ()
    accepted_envelope_refs: tuple[ContractRefV1, ...] = ()
    fact_kinds: tuple[str, ...] = ()
    renderer_ref: ContractRefV1 | None = None

    def __post_init__(self) -> None:
        _text(self.consumer_id, "consumer_id")
        _text(self.semantic_version, "semantic_version")
        _ref(self.projection_ref, "projection_ref")
        _ref(self.policy_ref, "policy_ref")
        _text(self.renderer_key, "renderer_key")
        if type(self.max_token_budget) is not int or self.max_token_budget <= 0:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "max_token_budget must be positive")
        if type(self.max_row_budget) is not int or self.max_row_budget <= 0:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "max_row_budget must be positive")
        object.__setattr__(
            self,
            "allowed_sensitivity",
            _sensitivity_tuple(self.allowed_sensitivity, "allowed_sensitivity"),
        )
        object.__setattr__(self, "ordering", _string_tuple(self.ordering, "ordering"))
        for name in ("accepted_evidence_refs", "accepted_envelope_refs"):
            refs = getattr(self, name)
            if type(refs) not in {tuple, list} or any(type(ref) is not ContractRefV1 for ref in refs):
                raise EvidenceProjectionError("PROJECTION_REF_INVALID", f"{name} must contain ContractRefV1 values")
            if len(set((ref.kind, ref.logical_id, ref.semantic_version) for ref in refs)) != len(refs):
                raise EvidenceProjectionError("PROJECTION_REF_INVALID", f"{name} must be unique")
            object.__setattr__(self, name, tuple(refs))
        object.__setattr__(self, "fact_kinds", _string_tuple(self.fact_kinds, "fact_kinds"))
        if self.renderer_ref is not None:
            _ref(self.renderer_ref, "renderer_ref")

    def to_dict(self) -> dict[str, object]:
        return {
            "consumer_id": self.consumer_id,
            "semantic_version": self.semantic_version,
            "projection_ref": self.projection_ref.to_dict(),
            "policy_ref": self.policy_ref.to_dict(),
            "renderer_key": self.renderer_key,
            "max_token_budget": self.max_token_budget,
            "max_row_budget": self.max_row_budget,
            "allowed_sensitivity": [value.value for value in self.allowed_sensitivity],
            "ordering": list(self.ordering),
            "accepted_evidence_refs": [ref.to_dict() for ref in self.accepted_evidence_refs],
            "accepted_envelope_refs": [ref.to_dict() for ref in self.accepted_envelope_refs],
            "fact_kinds": list(self.fact_kinds),
            "renderer_ref": None if self.renderer_ref is None else self.renderer_ref.to_dict(),
        }


@dataclass(frozen=True)
class ProjectionAuditV1:
    requested_fact_ids: tuple[str, ...]
    selected_fact_ids: tuple[str, ...]
    omitted_fact_ids: tuple[str, ...]
    redacted_fact_ids: tuple[str, ...]
    destination: str
    policy_ref: ContractRefV1
    token_budget: int
    row_budget: int
    raw_rows_rejected: bool
    restriction_reason: str | None = None
    egress_receipt_id: str | None = None
    egress_receipt_digest: str | None = None

    def __post_init__(self) -> None:
        for name in (
            "requested_fact_ids",
            "selected_fact_ids",
            "omitted_fact_ids",
            "redacted_fact_ids",
        ):
            object.__setattr__(self, name, _string_tuple(getattr(self, name), name))
        if self.destination not in {"local", "remote"}:
            raise EvidenceProjectionError("PROJECTION_DESTINATION_INVALID", "destination is invalid")
        _ref(self.policy_ref, "policy_ref")
        if type(self.token_budget) is not int or self.token_budget < 0:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "token_budget is invalid")
        if type(self.row_budget) is not int or self.row_budget < 0:
            raise EvidenceProjectionError("PROJECTION_BUDGET_INVALID", "row_budget is invalid")
        if type(self.raw_rows_rejected) is not bool:
            raise EvidenceProjectionError("PROJECTION_RAW_ROWS_INVALID", "raw_rows_rejected is invalid")
        if self.restriction_reason is not None:
            _text(self.restriction_reason, "restriction_reason")
        if (self.egress_receipt_id is None) != (self.egress_receipt_digest is None):
            raise EvidenceProjectionError(
                "PROJECTION_EGRESS_RECEIPT_INVALID",
                "egress receipt id and digest must be supplied together",
            )
        if self.egress_receipt_id is not None:
            _text(self.egress_receipt_id, "egress_receipt_id")
            _digest(self.egress_receipt_digest, "egress_receipt_digest")

    def to_dict(self) -> dict[str, object]:
        wire: dict[str, object] = {
            "requested_fact_ids": list(self.requested_fact_ids),
            "selected_fact_ids": list(self.selected_fact_ids),
            "omitted_fact_ids": list(self.omitted_fact_ids),
            "redacted_fact_ids": list(self.redacted_fact_ids),
            "destination": self.destination,
            "policy_ref": self.policy_ref.to_dict(),
            "token_budget": self.token_budget,
            "row_budget": self.row_budget,
            "raw_rows_rejected": self.raw_rows_rejected,
            "restriction_reason": self.restriction_reason,
        }
        if self.egress_receipt_id is not None:
            wire["egress_receipt_id"] = self.egress_receipt_id
            wire["egress_receipt_digest"] = self.egress_receipt_digest
        return wire


@dataclass(frozen=True)
class EvidenceProjectionV1:
    consumer_id: str
    consumer_version: str
    projection_ref: ContractRefV1
    artifact_ref: str
    commit_id: str
    envelope_ref: str
    envelope_digest: str
    result_identity: Mapping[str, Any]
    execution_status: str
    availability: str
    completeness_status: str
    numerical_method: str
    inference_basis: str
    evaluation_design: str
    validation_summary: Mapping[str, Any]
    facts: tuple[NumericFactV1, ...]
    status: ProjectionStatus
    audit: ProjectionAuditV1
    lineage_refs: tuple[str, ...]
    data_snapshot_ref: str | None = None
    data_snapshot_digest: str | None = None
    renderer_key: str | None = None

    def __post_init__(self) -> None:
        _text(self.consumer_id, "consumer_id")
        _text(self.consumer_version, "consumer_version")
        _ref(self.projection_ref, "projection_ref")
        for name in ("artifact_ref", "commit_id", "envelope_ref", "envelope_digest"):
            _text(getattr(self, name), name)
        if not isinstance(self.result_identity, Mapping):
            raise EvidenceProjectionError("PROJECTION_IDENTITY_INVALID", "result_identity is invalid")
        if not isinstance(self.validation_summary, Mapping):
            raise EvidenceProjectionError("PROJECTION_VALIDATION_INVALID", "validation_summary is invalid")
        if not isinstance(self.facts, (list, tuple)) or any(type(fact) is not NumericFactV1 for fact in self.facts):
            raise EvidenceProjectionError("PROJECTION_FACTS_INVALID", "facts must be persisted NumericFactV1 values")
        object.__setattr__(self, "facts", tuple(self.facts))
        if type(self.status) is not ProjectionStatus:
            raise EvidenceProjectionError("PROJECTION_STATUS_INVALID", "status is invalid")
        if type(self.audit) is not ProjectionAuditV1:
            raise EvidenceProjectionError("PROJECTION_AUDIT_INVALID", "audit is invalid")
        object.__setattr__(self, "lineage_refs", _string_tuple(self.lineage_refs, "lineage_refs"))
        if (self.data_snapshot_ref is None) != (self.data_snapshot_digest is None):
            raise EvidenceProjectionError(
                "PROJECTION_DATA_SNAPSHOT_IDENTITY_INVALID",
                "data snapshot ref and digest must be supplied together",
            )
        if self.data_snapshot_ref is not None:
            _text(self.data_snapshot_ref, "data_snapshot_ref")
            _digest(self.data_snapshot_digest, "data_snapshot_digest")
        if self.renderer_key is not None:
            _text(self.renderer_key, "renderer_key")

    @property
    def fact_ids(self) -> tuple[str, ...]:
        return tuple(fact.fact_id for fact in self.facts)

    def to_dict(self) -> dict[str, object]:
        return {
            "consumer_id": self.consumer_id,
            "consumer_version": self.consumer_version,
            "projection_ref": self.projection_ref.to_dict(),
            "artifact_ref": self.artifact_ref,
            "commit_id": self.commit_id,
            "envelope_ref": self.envelope_ref,
            "envelope_digest": self.envelope_digest,
            "data_snapshot_ref": self.data_snapshot_ref,
            "data_snapshot_digest": self.data_snapshot_digest,
            "result_identity": dict(self.result_identity),
            "execution_status": self.execution_status,
            "availability": self.availability,
            "completeness_status": self.completeness_status,
            "numerical_method": self.numerical_method,
            "inference_basis": self.inference_basis,
            "evaluation_design": self.evaluation_design,
            "validation_summary": dict(self.validation_summary),
            "facts": [fact.to_dict() for fact in self.facts],
            "status": self.status.value,
            "audit": self.audit.to_dict(),
            "lineage_refs": list(self.lineage_refs),
            "renderer_key": self.renderer_key,
        }


def _fact_token_cost(fact: NumericFactV1) -> int:
    """Use a deterministic serialization bound; never transform a statistic."""

    return max(1, (len(canonical_json_v1(fact.to_dict())) + 3) // 4)


class ConsumerProjectionRegistryV1:
    def __init__(self, specs: Sequence[ConsumerProjectionSpecV1] = ()) -> None:
        self._specs: dict[str, ConsumerProjectionSpecV1] = {}
        self._scoped_specs: dict[tuple[str, str, str], ConsumerProjectionSpecV1] = {}
        for spec in specs:
            self.register(spec)

    def register(self, spec: ConsumerProjectionSpecV1) -> None:
        if type(spec) is not ConsumerProjectionSpecV1:
            raise EvidenceProjectionError("PROJECTION_SPEC_INVALID", "spec is invalid")
        if spec.consumer_id in self._specs:
            raise EvidenceProjectionError("PROJECTION_DUPLICATE", spec.consumer_id)
        self._specs[spec.consumer_id] = spec

    def resolve(self, consumer_id: str) -> ConsumerProjectionSpecV1 | None:
        return self._specs.get(consumer_id)

    def register_for(
        self,
        provider_id: str,
        exposure_path: str,
        consumer_id: str,
        spec: ConsumerProjectionSpecV1,
    ) -> None:
        if type(spec) is not ConsumerProjectionSpecV1:
            raise EvidenceProjectionError("PROJECTION_SPEC_INVALID", "spec is invalid")
        key = (provider_id, exposure_path, consumer_id)
        if key in self._scoped_specs:
            raise EvidenceProjectionError("PROJECTION_DUPLICATE", str(key))
        if spec.consumer_id != consumer_id:
            raise EvidenceProjectionError("PROJECTION_DECLARATION_IDENTITY_MISMATCH", str(key))
        self._scoped_specs[key] = spec

    def resolve_for(
        self,
        provider_id: str,
        exposure_path: str,
        consumer_id: str,
    ) -> ConsumerProjectionSpecV1 | None:
        return self._scoped_specs.get((provider_id, exposure_path, consumer_id))

    @property
    def consumer_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._specs))

    def without(self, consumer_id: str) -> "ConsumerProjectionRegistryV1":
        registry = ConsumerProjectionRegistryV1(
            tuple(spec for key, spec in self._specs.items() if key != consumer_id)
        )
        for (provider_id, exposure_path, scoped_consumer_id), spec in self._scoped_specs.items():
            if scoped_consumer_id != consumer_id:
                registry.register_for(provider_id, exposure_path, scoped_consumer_id, spec)
        return registry

    def project(
        self,
        source: ServerOwnedEvidenceProjectionSourceV1,
        *,
        consumer_id: str,
        destination: str,
        requested_fact_ids: Sequence[str] | None = None,
        raw_rows: object | None = None,
        gateway: ContextEgressGatewayV1 | None = None,
        receipt: ContextEgressReceiptV1 | None = None,
        issuer: ContextEgressReceiptIssuerV1 | None = None,
    ) -> EvidenceProjectionV1:
        if type(source) is not ServerOwnedEvidenceProjectionSourceV1:
            raise EvidenceProjectionError(
                "EVIDENCE_SERVER_SOURCE_REQUIRED",
                "consumer projections require a live server-owned evidence source",
            )
        record = _load_server_record(source)
        spec = self.resolve(consumer_id)
        if spec is None:
            raise EvidenceProjectionError("PROJECTION_CONSUMER_UNKNOWN", f"unknown consumer {consumer_id}")
        if destination not in {"local", "remote"}:
            raise EvidenceProjectionError("PROJECTION_DESTINATION_INVALID", "destination is invalid")
        if record.binding.artifact_admission_ref != record.artifact_ref:
            raise EvidenceProjectionError(
                "PROJECTION_ARTIFACT_ADMISSION_MISMATCH",
                "binding artifact admission differs from the projected artifact",
            )
        requested = (
            tuple(fact.fact_id for fact in record.envelope.numeric_facts)
            if requested_fact_ids is None
            else _string_tuple(requested_fact_ids, "requested_fact_ids")
        )
        all_fact_ids = tuple(fact.fact_id for fact in record.envelope.numeric_facts)
        requested_set = set(requested)
        missing_requested = tuple(fact_id for fact_id in requested if fact_id not in set(all_fact_ids))
        redacted = tuple()
        restriction_reason: str | None = None
        egress_receipt_id: str | None = None
        egress_receipt_digest: str | None = None

        if spec.accepted_evidence_refs:
            accepted_digests = {ref.contract_digest for ref in spec.accepted_evidence_refs}
            if record.evidence_contract_digest is None:
                restriction_reason = "evidence_contract_identity_unavailable"
            elif record.evidence_contract_digest not in accepted_digests:
                restriction_reason = "evidence_contract_not_allowed"
        if spec.accepted_envelope_refs:
            accepted_digests = {ref.contract_digest for ref in spec.accepted_envelope_refs}
            if record.envelope_contract_digest is None:
                restriction_reason = restriction_reason or "envelope_contract_identity_unavailable"
            elif record.envelope_contract_digest not in accepted_digests:
                restriction_reason = restriction_reason or "envelope_contract_not_allowed"
        if spec.fact_kinds and "numeric_fact" not in spec.fact_kinds:
            restriction_reason = restriction_reason or "fact_kind_not_allowed"

        if record.sensitivity not in spec.allowed_sensitivity:
            redacted = all_fact_ids
            restriction_reason = "sensitivity_not_allowed"
        elif destination == "remote":
            if gateway is None or receipt is None or issuer is None:
                redacted = all_fact_ids
                restriction_reason = "egress_receipt_required"
            else:
                try:
                    require_context_egress_receipt(gateway, receipt, issuer=issuer)
                    egress_receipt_id = receipt.receipt_id
                    egress_receipt_digest = receipt.receipt_digest
                except EgressContractError as exc:
                    redacted = all_fact_ids
                    restriction_reason = exc.code

        raw_rows_rejected = raw_rows is not None
        if raw_rows_rejected and restriction_reason is None:
            restriction_reason = "raw_rows_rejected"
        if missing_requested and restriction_reason is None:
            restriction_reason = "unknown_fact_identity"
        if (
            restriction_reason is not None
            or redacted
            or raw_rows_rejected
            or missing_requested
            or record.envelope.availability is not AvailabilityStatusV1.AVAILABLE
        ):
            selected: tuple[NumericFactV1, ...] = tuple()
            omitted = tuple(dict.fromkeys((*missing_requested, *all_fact_ids)))
            if redacted:
                omitted = missing_requested
        else:
            selected_list: list[NumericFactV1] = []
            omitted_list: list[str] = list(missing_requested)
            used_tokens = 0
            # Preserve the envelope's persisted sequence.  ``ordering`` is a
            # declaration for the consumer contract, not permission to sort or
            # otherwise rewrite source evidence.
            for fact in (fact for fact in record.envelope.numeric_facts if fact.fact_id in requested_set):
                cost = _fact_token_cost(fact)
                if len(selected_list) >= spec.max_row_budget or used_tokens + cost > spec.max_token_budget:
                    omitted_list.append(fact.fact_id)
                    continue
                selected_list.append(fact)
                used_tokens += cost
            selected = tuple(selected_list)
            omitted = tuple(dict.fromkeys(omitted_list))

        if record.envelope.availability is not AvailabilityStatusV1.AVAILABLE:
            status = ProjectionStatus.UNAVAILABLE
        elif restriction_reason is not None:
            status = ProjectionStatus.BLOCKED
        elif redacted:
            status = ProjectionStatus.BLOCKED
        elif raw_rows_rejected:
            status = ProjectionStatus.BLOCKED
        elif missing_requested:
            status = ProjectionStatus.BLOCKED
        elif (
            omitted
            or record.envelope.completeness_status is CompletenessStatusV1.DEGRADED
            or record.envelope.execution_status is ExecutionStatusV1.PARTIAL
        ):
            status = ProjectionStatus.DEGRADED
        else:
            status = ProjectionStatus.AVAILABLE

        audit = ProjectionAuditV1(
            requested_fact_ids=requested,
            selected_fact_ids=tuple(fact.fact_id for fact in selected),
            omitted_fact_ids=omitted,
            redacted_fact_ids=redacted,
            destination=destination,
            policy_ref=spec.policy_ref,
            token_budget=sum(_fact_token_cost(fact) for fact in selected),
            row_budget=len(selected),
            raw_rows_rejected=raw_rows_rejected,
            restriction_reason=restriction_reason,
            egress_receipt_id=egress_receipt_id,
            egress_receipt_digest=egress_receipt_digest,
        )
        return EvidenceProjectionV1(
            consumer_id=spec.consumer_id,
            consumer_version=spec.semantic_version,
            projection_ref=spec.projection_ref,
            artifact_ref=record.artifact_ref,
            commit_id=record.commit_id,
            envelope_ref=record.envelope_ref,
            envelope_digest=record.envelope_digest,
            result_identity=record.envelope.result_identity,
            execution_status=record.envelope.execution_status.value,
            availability=record.envelope.availability.value,
            completeness_status=record.envelope.completeness_status.value,
            numerical_method=record.envelope.numerical_method.value,
            inference_basis=record.envelope.inference_basis.value,
            evaluation_design=record.envelope.evaluation_design.value,
            validation_summary=record.envelope.validation_summary.to_dict(),
            facts=selected,
            status=status,
            audit=audit,
            lineage_refs=record.envelope.lineage_refs,
            data_snapshot_ref=record.data_snapshot_ref,
            data_snapshot_digest=record.data_snapshot_digest,
            renderer_key=spec.renderer_key,
        )


def _builtin_ref(kind: str, consumer_id: str) -> ContractRefV1:
    logical_id = f"workbench.consumer_projection.{consumer_id}"
    return ContractRefV1(
        kind=kind,
        logical_id=logical_id,
        semantic_version="1.0",
        contract_digest=sha256_canonical({"kind": kind, "logical_id": logical_id, "semantic_version": "1.0"}),
    )


_CENTRAL_MAX_TOKEN_BUDGET = 4_096
_CENTRAL_MAX_ROW_BUDGET = 64
_CENTRAL_ALLOWED_SENSITIVITIES = frozenset({"public", "internal"})
_CENTRAL_ALLOWED_ORDERING = frozenset({"fact_id"})


def projection_registry_from_catalog(catalog: object | None = None) -> ConsumerProjectionRegistryV1:
    """Build the local adapter registry from the provider contribution refs."""

    if catalog is None:
        from workbench.providers.catalog import load_builtin_catalog

        catalog = load_builtin_catalog()
    from workbench.providers.catalog import ProviderCatalogV1, is_server_owned_catalog

    if type(catalog) is not ProviderCatalogV1 or not is_server_owned_catalog(catalog):
        raise EvidenceProjectionError(
            "PROJECTION_CATALOG_UNTRUSTED",
            "projection registry requires a server-issued catalog capability",
        )
    providers = catalog.providers
    provider = next(
        (candidate for candidate in providers if getattr(candidate, "provider_id", None) == "workbench.consumer_projection"),
        None,
    )
    if provider is None:
        raise EvidenceProjectionError("PROJECTION_PROVIDER_MISSING", "consumer projection provider is not declared")
    declarations = tuple(getattr(provider, "projection_declarations", ()))
    if not declarations:
        raise EvidenceProjectionError(
            "PROJECTION_DECLARATION_REQUIRED",
            "consumer projection provider has no projection declarations",
        )
    paths = {path.path_id: path for path in provider.exposure_paths}
    specs: list[ConsumerProjectionSpecV1] = []
    declared_keys: set[tuple[str, str]] = set()
    for declaration in declarations:
        path = paths.get(declaration.path_id)
        if path is None or path.projection_refs.get(declaration.consumer_id) != declaration.projection_ref:
            raise EvidenceProjectionError(
                "PROJECTION_DECLARATION_IDENTITY_MISMATCH",
                f"declaration {declaration.path_id}:{declaration.consumer_id} is not bound to its exposure path",
            )
        key = (declaration.path_id, declaration.consumer_id)
        if key in declared_keys:
            raise EvidenceProjectionError("PROJECTION_DECLARATION_DUPLICATE", str(key))
        declared_keys.add(key)
        if declaration.coverage_status == "exempt":
            continue
        if declaration.coverage_status != "required":
            raise EvidenceProjectionError("PROJECTION_DECLARATION_INCOMPLETE", str(key))
        if not declaration.fact_kinds:
            raise EvidenceProjectionError("PROJECTION_DECLARATION_INCOMPLETE", f"{key} has no fact kinds")
        if declaration.projection_ref not in path.projection_refs.values():
            raise EvidenceProjectionError("PROJECTION_DECLARATION_IDENTITY_MISMATCH", str(key))
        if (
            declaration.max_token_budget > _CENTRAL_MAX_TOKEN_BUDGET
            or declaration.max_row_budget > _CENTRAL_MAX_ROW_BUDGET
            or not set(declaration.allowed_sensitivity).issubset(_CENTRAL_ALLOWED_SENSITIVITIES)
            or not set(declaration.ordering).issubset(_CENTRAL_ALLOWED_ORDERING)
        ):
            raise EvidenceProjectionError(
                "PROJECTION_CATALOG_POLICY_INVALID",
                f"central projection authority rejected declaration {key}",
            )
        expected_ref = f"workbench.consumer_projection.{declaration.consumer_id}"
        if (
            declaration.policy_ref.logical_id != expected_ref
            or declaration.renderer_ref.logical_id != expected_ref
        ):
            raise EvidenceProjectionError(
                "PROJECTION_CATALOG_POLICY_INVALID",
                f"central policy/renderer allowlist rejected declaration {key}",
            )
        specs.append(
            ConsumerProjectionSpecV1(
                consumer_id=declaration.consumer_id,
                semantic_version=declaration.projection_ref.semantic_version,
                projection_ref=declaration.projection_ref,
                policy_ref=declaration.policy_ref,
                renderer_key=declaration.renderer_ref.logical_id,
                max_token_budget=declaration.max_token_budget,
                max_row_budget=declaration.max_row_budget,
                allowed_sensitivity=declaration.allowed_sensitivity,
                ordering=declaration.ordering,
                accepted_evidence_refs=declaration.evidence_contract_refs,
                accepted_envelope_refs=declaration.envelope_contract_refs,
                fact_kinds=declaration.fact_kinds,
                renderer_ref=declaration.renderer_ref,
            )
        )
    required_path_rows = {
        (path.path_id, consumer_id)
        for path in provider.exposure_paths
        for consumer_id in path.projection_refs
    }
    declared_required_or_exempt = declared_keys
    if required_path_rows - declared_required_or_exempt:
        missing = sorted(required_path_rows - declared_required_or_exempt)
        raise EvidenceProjectionError("PROJECTION_DECLARATION_REQUIRED", str(missing))
    return ConsumerProjectionRegistryV1(tuple(specs))


def default_projection_registry() -> ConsumerProjectionRegistryV1:
    """Return the package-local declarations for the minimum consumer slice."""

    registry = projection_registry_from_catalog()
    from workbench.evidence.provider_projection_adapters import (
        provider_projection_registry_from_catalog,
    )

    for binding in provider_projection_registry_from_catalog().bindings:
        registry.register_for(
            binding.provider_id,
            binding.exposure_path,
            binding.consumer_id,
            binding.to_consumer_spec(),
        )
    return registry


__all__ = [
    "ConsumerProjectionRegistryV1",
    "ConsumerProjectionSpecV1",
    "EvidenceProjectionError",
    "EvidenceProjectionV1",
    "PersistedEvidenceEnvelopeV1",
    "ProjectionAuditV1",
    "ProjectionStatus",
    "ServerOwnedEvidenceProjectionSourceV1",
    "ServerOwnedEvidenceSensitivityPolicyV1",
    "default_projection_registry",
    "projection_registry_from_catalog",
]
