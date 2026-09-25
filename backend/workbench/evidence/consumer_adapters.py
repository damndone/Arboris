"""Port-based, fail-closed projections of persisted evidence envelopes.

This module deliberately has no statistical implementation dependency.  A
projection may select, order, redact, or omit already persisted facts, but it
never derives a new value or fills a missing value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
import re
import json
import unicodedata
from threading import RLock
from types import MappingProxyType
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
from workbench.contracts.common.envelope import freeze_json, thaw_json
from workbench.contracts.evidence.result_sections import (
    MAX_TEXT_BYTES, RESULT_SECTIONS_CONTRACT_DIGEST, ResultSectionV1, StructuredResultsV1,
)
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


# This is the evidence contract declared by the built-in consumer-projection
# provider.  Producers that want to be consumable by Agent, Notebook, Report,
# or Results must bind to this contract; the envelope-core digest alone is not
# a consumer admission.
CONSUMER_PROJECTION_EVIDENCE_CONTRACT_DIGEST = (
    "a80048ec382239a8e8050f1219322201591816828f1ccf8f12570f38a45c7361"
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
        has_dependency_extension = "result_dependencies" in self.envelope.family_evidence
        if not has_dependency_extension and source_refs and source_refs != {self.artifact_ref}:
            raise EvidenceProjectionError(
                "PROJECTION_ARTIFACT_IDENTITY_MISMATCH",
                "persisted fact source selectors cross the projected artifact identity",
            )
        source_digests = {
            fact.source_selector.artifact_digest for fact in self.envelope.numeric_facts
        }
        if not has_dependency_extension and len(source_digests) > 1:
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
        "_project_file_store",
        "_project_ref",
        "_run_id",
        "_canonical_project_root",
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
        project_file_store: object | None = None,
        project_ref: str | None = None,
        run_id: str | None = None,
        canonical_project_root: Path | str | None = None,
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
            object.__setattr__(self, "_project_file_store", project_file_store)
            object.__setattr__(self, "_project_ref", project_ref)
            object.__setattr__(self, "_run_id", run_id)
            object.__setattr__(self, "_canonical_project_root", (
                None if canonical_project_root is None else
                Path(canonical_project_root).expanduser().resolve(strict=False)
            ))
            self._require_host_context()
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
                "project_file_store_id": id(self._project_file_store),
                "project_file_admission_id": id(getattr(self._project_file_store, "_admission", None)),
                "project_ref": self._project_ref,
                "run_id": self._run_id,
                "canonical_project_root": (
                    None if self._canonical_project_root is None else str(self._canonical_project_root)
                ),
            }
        )

    def _require_host_context(self, *, required: bool = False) -> None:
        """Check exact FD store and the server context, never a verifier callback."""
        from workbench.services.report_evidence_owner_factory import HostBoundProjectFileStoreV1

        store = self._project_file_store
        if store is None and not required:
            return  # Numeric-only legacy sources have no dependency file capability.
        if type(store) is not HostBoundProjectFileStoreV1:
            raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_STORE_REQUIRED", "exact host file store required")
        try:
            _text(self._project_ref, "project_ref")
            _text(self._run_id, "run_id")
            if self._run_id in {".", ".."} or "/" in self._run_id or "\\" in self._run_id:
                raise ValueError("invalid run identity")
            admission = store._admission
            if (type(admission) is not EvidencePersistenceAdmissionV1
                    or admission._authority_handle is not self._authority_handle
                    or admission._scope_ref != self._scope_ref
                    or self._canonical_project_root is None
                    or store._root != self._canonical_project_root):
                raise ValueError("host store authority, scope or root differs")
            admission._require_open()
            root_stat = self._canonical_project_root.stat()
            if (root_stat.st_dev, root_stat.st_ino) != (admission._root_dev, admission._root_ino):
                raise ValueError("host store root identity differs")
        except (AttributeError, OSError, TypeError, ValueError, EvidencePersistenceError) as exc:
            raise EvidenceProjectionError("EVIDENCE_OWNER_CONTEXT_MISMATCH", "host store context differs") from exc

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
            self._require_host_context()
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
        for key, expected in (("project_ref", source._project_ref), ("run_id", source._run_id)):
            actual = record.envelope.result_identity.get(key)
            if expected is not None and actual is not None and actual != expected:
                raise EvidenceProjectionError("EVIDENCE_OWNER_CONTEXT_MISMATCH", "packet and host context differ")
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
    requested_section_ids: tuple[str, ...] = ()
    selected_section_ids: tuple[str, ...] = ()
    omitted_section_ids: tuple[str, ...] = ()
    redacted_section_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in (
            "requested_fact_ids",
            "selected_fact_ids",
            "omitted_fact_ids",
            "redacted_fact_ids",
            "requested_section_ids",
            "selected_section_ids",
            "omitted_section_ids",
            "redacted_section_ids",
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
            "requested_section_ids": list(self.requested_section_ids),
            "selected_section_ids": list(self.selected_section_ids),
            "omitted_section_ids": list(self.omitted_section_ids),
            "redacted_section_ids": list(self.redacted_section_ids),
        }
        if self.egress_receipt_id is not None:
            wire["egress_receipt_id"] = self.egress_receipt_id
            wire["egress_receipt_digest"] = self.egress_receipt_digest
        return wire


COEFFICIENT_ROLE_PATHS_V1 = MappingProxyType({
    "estimate": ("estimate",), "std_error": ("std_error",), "p_value": ("p_value",),
    "statistic": ("statistic",), "confidence_level": ("confidence_level",),
    "lower": ("confidence_interval", 0), "upper": ("confidence_interval", 1),
})
COEFFICIENT_SELECTION_CONTRACT_DIGEST = sha256_canonical({
    "schema_version": 1, "section_contract_digest": RESULT_SECTIONS_CONTRACT_DIGEST,
    "roles": dict(COEFFICIENT_ROLE_PATHS_V1), "source": "regression_table.rows.term.models",
    "dependency_closure": "provenance_section_declared_refs_and_selected_fact_sources",
    "terms": "NFC-exact-display-text",
})


def _exact_coefficient_terms(value: object) -> tuple[str, ...]:
    """Match admitted display text, including whitespace and empty labels."""
    if not isinstance(value, (list, tuple)) or not 1 <= len(value) <= 1024:
        raise EvidenceProjectionError("semantic_selector_invalid", "terms must be a bounded nonempty array")
    terms = []
    for term in value:
        if type(term) is not str or len(term) > MAX_TEXT_BYTES or "\x00" in term:
            raise EvidenceProjectionError("semantic_selector_invalid", "invalid display term")
        try:
            normalized = unicodedata.normalize("NFC", term)
            if max(len(term.encode("utf-8")), len(normalized.encode("utf-8"))) > MAX_TEXT_BYTES:
                raise ValueError("display term exceeds byte bound")
        except (UnicodeError, ValueError) as exc:
            raise EvidenceProjectionError("semantic_selector_invalid", "invalid bounded display term") from exc
        terms.append(normalized)
    if len(terms) != len(set(terms)):
        raise EvidenceProjectionError("semantic_selector_invalid", "duplicate canonical display term")
    return tuple(terms)


@dataclass(frozen=True)
class ModelCoefficientSelectionV1:
    """A query over admitted tree references, never an authority or ID heuristic."""
    model_id: str
    terms: tuple[str, ...] | None = None
    roles: tuple[str, ...] = ("estimate",)

    def __post_init__(self):
        _text(self.model_id, "model_id")
        if len(self.model_id.encode("utf-8")) > 4096:
            raise EvidenceProjectionError("semantic_selector_invalid", "model identity is too long")
        for field in ("terms", "roles"):
            value = getattr(self, field)
            if field == "terms" and value is None:
                continue
            value = _exact_coefficient_terms(value) if field == "terms" else _string_tuple(value, field)
            if not value or len(value) > 1024 or any(len(v.encode("utf-8")) > 4096 for v in value):
                raise EvidenceProjectionError("semantic_selector_invalid", "selector must be bounded and nonempty")
            object.__setattr__(self, field, value)
        if set(self.roles) - set(COEFFICIENT_ROLE_PATHS_V1):
            raise EvidenceProjectionError("semantic_role_unknown", "undeclared coefficient role")


PROVENANCE_ROLE_PATHS_V1 = MappingProxyType({
    **{f"survey_{field}": ("survey_design", field) for field in (
        "variance_method", "degf", "design_effect", "effective_sample_size",
        "replicates_attempted", "replicates_succeeded", "replicates_failed",
        "replicate_failure_reasons", "warnings")},
    **{f"coefficient_{field}": ("regression_table", field) for field in (
        "variance_source", "source_id", "warnings")},
})
PROVENANCE_SELECTION_CONTRACT_DIGEST = sha256_canonical({
    "schema_version": 1, "section_contract_digest": RESULT_SECTIONS_CONTRACT_DIGEST,
    "roles": dict(PROVENANCE_ROLE_PATHS_V1), "scope": "selected_only",
    "dependency_closure": "provenance_section_declared_refs_and_selected_fact_sources",
    "warnings": "complete_requested_typed_list", "terms": "NFC-exact-display-text",
})


@dataclass(frozen=True)
class ModelProvenanceSelectionV1:
    """Explicit bounded qualifications, not a whole-section or run read."""
    model_id: str
    terms: tuple[str, ...] | None = field(default=None, kw_only=True)
    roles: tuple[str, ...] = field(kw_only=True)

    def __post_init__(self):
        _text(self.model_id, "model_id")
        if len(self.model_id.encode("utf-8")) > 4096:
            raise EvidenceProjectionError("semantic_selector_invalid", "model identity is too long")
        roles = _string_tuple(self.roles, "roles")
        if not roles or set(roles) - set(PROVENANCE_ROLE_PATHS_V1):
            raise EvidenceProjectionError("semantic_role_unknown", "undeclared provenance role")
        object.__setattr__(self, "roles", roles)
        if self.terms is not None:
            object.__setattr__(self, "terms", _exact_coefficient_terms(self.terms))
        if any(role.startswith("coefficient_") for role in roles) and self.terms is None:
            raise EvidenceProjectionError("semantic_selector_invalid", "coefficient provenance requires explicit terms")
        if self.terms is not None and not any(role.startswith("coefficient_") for role in roles):
            raise EvidenceProjectionError("semantic_selector_invalid", "survey-only selection cannot use terms")


def _resolve_provenance_selection(sections, selection):
    bindings = []
    for role in sorted(selection.roles):
        section_type, field_name = PROVENANCE_ROLE_PATHS_V1[role]
        candidates = []
        for section in sections:
            wire = section.to_dict()
            if wire["section_type"] != section_type or wire["status"] != "available":
                continue
            fields = wire["content"]["fields"]
            models = fields.get("models", {}).get("items", [])
            ids = [m.get("value") if section_type == "survey_design" else
                   m.get("fields", {}).get("id", {}).get("value") for m in models]
            if selection.model_id in ids:
                if ids.count(selection.model_id) != 1:
                    raise EvidenceProjectionError("semantic_selection_ambiguous", "duplicate model declaration")
                candidates.append((section, fields))
        if not candidates:
            raise EvidenceProjectionError("semantic_model_unavailable", "model has no admitted qualification section")
        if len(candidates) != 1:
            raise EvidenceProjectionError("semantic_selection_ambiguous", "multiple qualification sections")
        section, fields = candidates[0]
        if section_type == "survey_design":
            cells = {None: fields.get("design", {}).get("fields", {}).get(selection.model_id, {}).get("fields", {})}
        else:
            cells = {}
            for row in fields.get("rows", {}).get("items", []):
                row_fields = row.get("fields", {})
                cell = row_fields.get("models", {}).get("fields", {}).get(selection.model_id)
                if cell is None:
                    continue
                term = row_fields.get("term", {})
                if term.get("kind") != "text":
                    raise EvidenceProjectionError("semantic_term_unavailable", "term is not declared text")
                name = term["value"]
                if name in cells:
                    raise EvidenceProjectionError("semantic_selection_ambiguous", "duplicate coefficient term")
                cells[name] = cell.get("fields", {})
            if set(selection.terms) - set(cells):
                raise EvidenceProjectionError("semantic_term_unavailable", "requested term is absent")
            cells = {term: cells[term] for term in sorted(selection.terms)}
        for term, cell in cells.items():
            value = cell.get(field_name, {})
            expected = ("list" if field_name == "warnings" else "object" if field_name == "replicate_failure_reasons"
                        else "text" if field_name in ("variance_method", "variance_source", "source_id") else "fact")
            if value.get("kind") != expected:
                raise EvidenceProjectionError("semantic_role_unavailable", "requested qualification is absent")
            children = (value.get("items", []) if expected == "list" else
                        list(value.get("fields", {}).values()) if expected == "object" else [value])
            for child in children:
                kind = "text" if expected == "list" else "fact" if expected == "object" else expected
                if child.get("kind") != kind or (kind == "fact" and child.get("fact_id") not in section.fact_refs):
                    raise EvidenceProjectionError("semantic_role_unavailable", "qualification is not fully admitted")
            binding = dict(section_id=section.section_id, model_id=selection.model_id, term=term, role=role, value=value)
            if expected == "fact":
                binding["fact_id"] = value["fact_id"]
            bindings.append(binding)
    return {"schema_version": 1, "contract_digest": PROVENANCE_SELECTION_CONTRACT_DIGEST,
            "scope": "selected_only", "whole_result_read": False,
            "model_id": selection.model_id, "terms": sorted(selection.terms or ()),
            "roles": sorted(selection.roles), "bindings": bindings}


def _semantic_fact_ids(semantic):
    def refs(node):
        if node.get("kind") == "fact":
            return [node["fact_id"]]
        if node.get("kind") == "object":
            return [ref for child in node["fields"].values() for ref in refs(child)]
        if node.get("kind") == "list":
            return [ref for child in node["items"] for ref in refs(child)]
        return []
    return tuple(dict.fromkeys(ref for binding in semantic["bindings"] for ref in
        (refs(binding["value"]) if "value" in binding else [binding["fact_id"]])))


def _resolve_coefficient_selection(sections, selection):
    if type(selection) is ModelProvenanceSelectionV1:
        return _resolve_provenance_selection(sections, selection)
    if type(selection) is not ModelCoefficientSelectionV1:
        raise EvidenceProjectionError("semantic_selector_invalid", "typed selector required")
    candidates = []
    for section in sections:
        wire = section.to_dict()
        if wire["section_type"] != "regression_table" or wire["status"] != "available":
            continue
        fields = wire["content"]["fields"]
        models = fields["models"]
        declared = [m.get("fields", {}).get("id", {}).get("value") for m in models.get("items", [])]
        if selection.model_id in declared:
            if declared.count(selection.model_id) != 1:
                raise EvidenceProjectionError("semantic_selection_ambiguous", "duplicate model identity")
            candidates.append((section, fields))
    if not candidates:
        raise EvidenceProjectionError("semantic_model_unavailable", "model is not declared")
    if len(candidates) != 1:
        raise EvidenceProjectionError("semantic_selection_ambiguous", "model occurs in multiple tables")
    section, fields = candidates[0]
    cells = {}
    for row in fields["rows"].get("items", []):
        row_fields = row.get("fields", {})
        term = row_fields.get("term", {})
        cell = row_fields.get("models", {}).get("fields", {}).get(selection.model_id)
        if cell is None:
            continue
        if term.get("kind") != "text":
            raise EvidenceProjectionError("semantic_term_unavailable", "term is not declared text")
        name = term["value"]
        if name in cells:
            raise EvidenceProjectionError("semantic_selection_ambiguous", "duplicate model term")
        cells[name] = cell.get("fields", {})
    terms = tuple(cells) if selection.terms is None else selection.terms
    if not terms or set(terms) - set(cells):
        raise EvidenceProjectionError("semantic_term_unavailable", "requested term is absent")
    bindings = []
    for term in sorted(terms):
        for role in sorted(selection.roles):
            path = COEFFICIENT_ROLE_PATHS_V1[role]
            ref = cells[term].get(path[0], {})
            if len(path) == 2:
                items = ref.get("items", ())
                ref = items[path[1]] if ref.get("kind") == "list" and len(items) == 2 else {}
            if ref.get("kind") != "fact" or ref.get("fact_id") not in section.fact_refs:
                raise EvidenceProjectionError("semantic_role_unavailable", "requested role has no admitted fact")
            bindings.append(dict(section_id=section.section_id, model_id=selection.model_id,
                                 term=term, role=role, fact_id=ref["fact_id"]))
    return {"schema_version": 1, "contract_digest": COEFFICIENT_SELECTION_CONTRACT_DIGEST,
            "model_id": selection.model_id, "terms": sorted(terms), "roles": sorted(selection.roles),
            "bindings": bindings}


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
    sections: tuple[ResultSectionV1, ...] = ()
    result_dependencies: Mapping[str, Any] | None = None
    semantic_selection: Mapping[str, Any] | None = None

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
        if not isinstance(self.sections, (list, tuple)) or any(type(s) is not ResultSectionV1 for s in self.sections):
            raise EvidenceProjectionError("PROJECTION_SECTIONS_INVALID", "sections must be typed values")
        object.__setattr__(self, "sections", tuple(self.sections))
        if self.result_dependencies is not None:
            object.__setattr__(self, "result_dependencies", freeze_json(self.result_dependencies))
        if self.semantic_selection is not None:
            object.__setattr__(self, "semantic_selection", freeze_json(self.semantic_selection))
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

    def egress_payload(self) -> dict[str, object]:
        """Exact content to materialize under ``evidence:projection`` remotely.

        Exclude only circular receipt/transport budgets; all selection metadata,
        section trees, facts, identities and sealed bindings remain covered.
        """
        wire = self.to_dict()
        wire["audit"] = {key: value for key, value in wire["audit"].items()
                         if key not in {"destination", "egress_receipt_id", "egress_receipt_digest",
                                        "token_budget", "row_budget"}}
        return wire

    def to_dict(self) -> dict[str, object]:
        return {
            **({"semantic_selection": thaw_json(self.semantic_selection)} if self.semantic_selection is not None else {}),
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
            "sections": [section.to_dict() for section in self.sections],
            "result_dependencies": None if self.result_dependencies is None else thaw_json(self.result_dependencies),
            "status": self.status.value,
            "audit": self.audit.to_dict(),
            "lineage_refs": list(self.lineage_refs),
            "renderer_key": self.renderer_key,
        }


def _fact_token_cost(fact: NumericFactV1) -> int:
    """Use a deterministic serialization bound; never transform a statistic."""

    return max(1, (len(canonical_json_v1(fact.to_dict())) + 3) // 4)


def _without_structured_content(projection: EvidenceProjectionV1, reason: str) -> EvidenceProjectionV1:
    return replace(projection, facts=(), sections=(), result_dependencies=None, semantic_selection=None,
        status=ProjectionStatus.UNAVAILABLE,
        audit=replace(projection.audit, restriction_reason=reason, token_budget=0, row_budget=0,
            selected_fact_ids=(), selected_section_ids=(),
            omitted_fact_ids=tuple(dict.fromkeys((*projection.audit.omitted_fact_ids, *projection.fact_ids))),
            omitted_section_ids=tuple(dict.fromkeys((*projection.audit.omitted_section_ids,
                                                     *(s.section_id for s in projection.sections))))))


def _structured_row_count(facts, sections, dependencies, semantic=None):
    """Same conservative row charge for ordinary projections and every page."""
    def rows(node):
        if node["kind"] == "list":
            return len(node["items"]) + sum(rows(child) for child in node["items"])
        if node["kind"] == "object":
            return sum(rows(child) for child in node["fields"].values())
        return int(node["kind"] == "fact")

    return (len(facts) + len(sections) + (len(semantic["bindings"]) if semantic is not None else 0)
            + (sum(rows(b["value"]) for b in semantic["bindings"] if "value" in b) if semantic is not None else 0)
            + (len(dependencies["records"]) if dependencies is not None else 0)
            + sum(rows(s.to_dict()["content"]) for s in sections))


def _budget_structured_projection(projection: EvidenceProjectionV1,
                                 spec: ConsumerProjectionSpecV1) -> EvidenceProjectionV1:
    """Charge complete UTF-8 wire and full structured row/reference semantics."""
    row_count = _structured_row_count(projection.facts, projection.sections,
                                     projection.result_dependencies, projection.semantic_selection)
    projection = replace(projection, audit=replace(projection.audit, row_budget=row_count))
    # Token count itself is serialized; settle its bounded decimal-width change.
    while True:
        tokens = (len(canonical_json_v1(projection.to_dict()).encode("utf-8")) + 3) // 4
        if tokens == projection.audit.token_budget:
            break
        projection = replace(projection, audit=replace(projection.audit, token_budget=tokens))
    if tokens > spec.max_token_budget or row_count > spec.max_row_budget:
        return _without_structured_content(projection, "structured_projection_budget_exceeded")
    return projection


LOCAL_STRUCTURED_PROJECTION_PROFILE_V1 = MappingProxyType({
    "profile_id": "workbench.consumer_projection.local_structured_v1",
    "schema_version": 1,
    "destination": "local",
    "consumer_ids": ("report", "results"),
    "max_token_budget": 65_536,
    "max_row_budget": 1_024,
    "section_contract_digest": RESULT_SECTIONS_CONTRACT_DIGEST,
})


def _local_structured_spec(spec: ConsumerProjectionSpecV1, destination: str) -> ConsumerProjectionSpecV1:
    """Apply the explicit server profile only to an unchanged catalog spec.

    This is not a global-cap change, a caller flag, or an override of a caller's
    narrower/custom declaration. Remote and conversational consumers never opt in.
    """
    profile = LOCAL_STRUCTURED_PROJECTION_PROFILE_V1
    if destination != profile["destination"] or spec.consumer_id not in profile["consumer_ids"]:
        return spec
    if spec != projection_registry_from_catalog().resolve(spec.consumer_id):
        return spec
    policy = ContractRefV1(kind=spec.policy_ref.kind,
        logical_id=f"{profile['profile_id']}.{spec.consumer_id}", semantic_version="1.0",
        contract_digest=sha256_canonical({"profile": dict(profile), "base_policy_ref": spec.policy_ref.to_dict()}))
    return replace(spec, max_token_budget=profile["max_token_budget"],
                   max_row_budget=profile["max_row_budget"], policy_ref=policy)


LOCAL_UNKNOWN_READ_PROFILE_V1 = MappingProxyType({
    "profile_id": "workbench.consumer_projection.local_unknown_read_v1",
    "schema_version": 1,
    "destination": "local",
    "consumer_ids": ("agent", "notebook", "report", "results"),
    "additional_sensitivity": "unknown",
    "source_admission": "live_host_committed_evidence",
})


def _local_read_spec(spec: ConsumerProjectionSpecV1, destination: str) -> ConsumerProjectionSpecV1:
    """Allow admitted UNKNOWN local reads without reclassification or new budgets."""
    profile = LOCAL_UNKNOWN_READ_PROFILE_V1
    if destination != profile["destination"] or spec.consumer_id not in profile["consumer_ids"]:
        return spec
    declared = projection_registry_from_catalog().resolve(spec.consumer_id)
    if declared is None or spec not in (declared, _local_structured_spec(declared, destination)):
        return spec
    policy = ContractRefV1(kind=spec.policy_ref.kind,
        logical_id=f"{profile['profile_id']}.{spec.consumer_id}", semantic_version="1.0",
        contract_digest=sha256_canonical({"profile": dict(profile), "base_spec": spec.to_dict()}))
    return replace(spec, allowed_sensitivity=(*spec.allowed_sensitivity, SensitivityClassV1.UNKNOWN),
                   policy_ref=policy)


def _spec_for_audit_policy(spec: ConsumerProjectionSpecV1, destination: str,
                           policy_ref: ContractRefV1) -> ConsumerProjectionSpecV1:
    """Match the complete declared profile identity at the final owner/parser."""
    for candidate in (spec, _local_structured_spec(spec, destination)):
        if policy_ref == candidate.policy_ref:
            return candidate
        local = _local_read_spec(candidate, destination)
        if policy_ref == local.policy_ref:
            return local
    raise EvidenceProjectionError("PROJECTION_CATALOG_POLICY_INVALID", "delivery policy is not declared")


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
        requested_section_ids: Sequence[str] | None = None,
        coefficient_selection: ModelCoefficientSelectionV1 | None = None,
        provenance_selection: ModelProvenanceSelectionV1 | None = None,
        requested_section_types: Sequence[str] | None = None,
        raw_rows: object | None = None,
        gateway: ContextEgressGatewayV1 | None = None,
        receipt: ContextEgressReceiptV1 | None = None,
        issuer: ContextEgressReceiptIssuerV1 | None = None,
    ) -> EvidenceProjectionV1:
        """Deliver only after the existing egress issuer authorizes remote use."""
        egress_failure = None
        validated_egress = None
        if destination == "remote":
            if gateway is None or receipt is None or issuer is None:
                egress_failure = "egress_receipt_required"
            else:
                try:
                    require_context_egress_receipt(gateway, receipt, issuer=issuer)
                    validated_egress = (receipt.receipt_id, receipt.receipt_digest)
                except EgressContractError as exc:
                    egress_failure = exc.code
        projection, observed, _spec, extended = self._build_projection(
            source, consumer_id=consumer_id, destination=destination,
            requested_fact_ids=requested_fact_ids, requested_section_ids=requested_section_ids,
            coefficient_selection=coefficient_selection, requested_section_types=requested_section_types,
            provenance_selection=provenance_selection,
            raw_rows=raw_rows, egress_failure=egress_failure, validated_egress=validated_egress)
        if extended and destination == "remote" and projection.status in {ProjectionStatus.AVAILABLE, ProjectionStatus.DEGRADED}:
            materialized = issuer.materializer_store.resolve(gateway.materialization_result_ref)
            expected = {"evidence:projection": projection.egress_payload()}
            if (gateway.destination != "remote" or gateway.sensitivity != observed
                    or canonical_json_v1(thaw_json(materialized.materialized_context)) != canonical_json_v1(expected)
                    or gateway.token_budget < projection.audit.token_budget
                    or gateway.row_budget < projection.audit.row_budget):
                projection = _without_structured_content(projection, "structured_egress_payload_mismatch")
        return projection

    def _build_projection(
        self, source: ServerOwnedEvidenceProjectionSourceV1, **kwargs,
    ) -> tuple[EvidenceProjectionV1, SensitivityClassV1, ConsumerProjectionSpecV1, bool]:
        fields, observed, spec, extended, deliver = self._prepare_selection(source, **kwargs)
        projection = EvidenceProjectionV1(**fields)
        if extended and deliver:
            projection = _budget_structured_projection(projection, spec)
        return projection, observed, spec, extended

    def _prepare_selection(
        self,
        source: ServerOwnedEvidenceProjectionSourceV1,
        *,
        consumer_id: str,
        destination: str,
        requested_fact_ids: Sequence[str] | None = None,
        requested_section_ids: Sequence[str] | None = None,
        coefficient_selection: ModelCoefficientSelectionV1 | None = None,
        provenance_selection: ModelProvenanceSelectionV1 | None = None,
        requested_section_types: Sequence[str] | None = None,
        raw_rows: object | None = None,
        egress_failure: str | None = None,
        validated_egress: tuple[str, str] | None = None,
    ) -> tuple[dict, SensitivityClassV1, ConsumerProjectionSpecV1, bool, bool]:
        """Private admission fields only; neither delivery nor egress authority."""
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
        family = record.envelope.family_evidence
        selector_error = None
        if provenance_selection is not None:
            if type(provenance_selection) is not ModelProvenanceSelectionV1:
                selector_error = "semantic_selector_invalid"
            elif any(value is not None for value in (coefficient_selection, requested_fact_ids,
                                                      requested_section_ids, requested_section_types)):
                selector_error = "semantic_selection_mixed"
            coefficient_selection = provenance_selection
        elif coefficient_selection is not None and type(coefficient_selection) is not ModelCoefficientSelectionV1:
            selector_error = "semantic_selector_invalid"
        extended = ("structured_results" in family or "result_dependencies" in family
                    or bool(requested_section_ids) or coefficient_selection is not None or requested_section_types is not None)
        if "structured_results" in family and coefficient_selection is None and requested_section_types is None:
            spec = _local_structured_spec(spec, destination)
        if record.sensitivity is SensitivityClassV1.UNKNOWN:
            spec = _local_read_spec(spec, destination)
        section_selection: tuple[ResultSectionV1, ...] = ()
        section_ids: tuple[str, ...] = ()
        requested_sections: tuple[str, ...] = ()
        dependency_wire = None
        extension_reason = None
        semantic_wire = None
        semantic_fact_ids = ()
        if extended:
            try:
                if selector_error:
                    raise EvidenceProjectionError(selector_error, "invalid or mixed semantic selector")
                dependency_ids = {item["artifact_ref"] for item in record.envelope.dependencies}
                structured = family.get("structured_results")
                parsed = (() if structured is None else StructuredResultsV1.from_dict(
                    structured, facts={f.fact_id: f for f in record.envelope.numeric_facts},
                    dependency_ids=dependency_ids).sections)
                section_ids = tuple(s.section_id for s in parsed)
                if coefficient_selection is not None or requested_section_types is not None:
                    if requested_fact_ids is not None or requested_section_ids is not None or (
                        coefficient_selection is not None and requested_section_types is not None
                    ):
                        raise EvidenceProjectionError("semantic_selection_mixed", "selectors are mutually exclusive")
                    if coefficient_selection is not None:
                        semantic_wire = _resolve_coefficient_selection(parsed, coefficient_selection)
                        semantic_fact_ids = _semantic_fact_ids(semantic_wire)
                        requested_section_ids = ()
                    else:
                        from workbench.contracts.evidence.result_sections import SECTION_FIELDS
                        types = _string_tuple(requested_section_types, "requested_section_types")
                        if not types or set(types) - set(SECTION_FIELDS):
                            raise EvidenceProjectionError("section_type_unknown", "undeclared section type")
                        if set(types) - {s.to_dict()["section_type"] for s in parsed}:
                            raise EvidenceProjectionError("section_type_unavailable", "section type missing")
                        requested_section_ids = tuple(s.section_id for s in parsed if s.to_dict()["section_type"] in types)
                requested_sections = (
                    section_ids if requested_section_ids is None and requested_fact_ids is None
                    else () if requested_section_ids is None
                    else _string_tuple(requested_section_ids, "requested_section_ids")
                )
                if requested_sections and structured is None:
                    raise EvidenceProjectionError("structured_results_unavailable", "no section extension")
                if set(requested_sections) - set(section_ids):
                    raise EvidenceProjectionError("unknown_section_identity", "unknown section requested")
                section_selection = tuple(s for s in parsed if s.section_id in requested_sections)
            except (ValueError, KeyError, TypeError) as exc:
                extension_reason = getattr(exc, "code", "structured_results_invalid")
        requested = (
            tuple(fact.fact_id for fact in record.envelope.numeric_facts)
            if requested_fact_ids is None and requested_section_ids is None
            else () if requested_fact_ids is None
            else _string_tuple(requested_fact_ids, "requested_fact_ids")
        )
        requested = tuple(dict.fromkeys((*requested, *semantic_fact_ids, *(ref for s in section_selection for ref in s.fact_refs))))
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

        if (record.sensitivity not in spec.allowed_sensitivity
                or destination == "remote" and record.sensitivity is SensitivityClassV1.UNKNOWN):
            redacted = all_fact_ids
            restriction_reason = "sensitivity_not_allowed"
        elif destination == "remote":
            if egress_failure is not None:
                redacted = all_fact_ids
                restriction_reason = egress_failure
            elif validated_egress is not None:
                egress_receipt_id, egress_receipt_digest = validated_egress

        raw_rows_rejected = raw_rows is not None
        if raw_rows_rejected and restriction_reason is None:
            restriction_reason = "raw_rows_rejected"
        if missing_requested and restriction_reason is None:
            restriction_reason = "unknown_fact_identity"
        if extended and restriction_reason is None:
            try:
                if extension_reason:
                    raise EvidenceProjectionError(extension_reason, "section selection unavailable")
                source._require_host_context(required=True)
                from workbench.evidence.result_dependencies import (
                    validate_result_dependency_manifest, verify_result_dependencies,
                )
                manifest = validate_result_dependency_manifest(family.get("result_dependencies"),
                    project_ref=source._project_ref, run_id=source._run_id)
                records = {row["artifact_id"]: row for row in manifest.records}
                closure = {ref for section in section_selection for ref in section.dependency_refs}
                if semantic_wire is not None:
                    # No admitted per-cell dependency map exists. Preserve the
                    # entire provenance section's declared closure; logical
                    # model IDs are not artifact identities.
                    parent_ids = {binding["section_id"] for binding in semantic_wire["bindings"]}
                    closure.update(ref for section in parsed if section.section_id in parent_ids
                                   for ref in section.dependency_refs)
                # Even a facts-only selection must check every selected source.
                for fact in record.envelope.numeric_facts:
                    if fact.fact_id not in requested_set:
                        continue
                    selector = fact.source_selector
                    dependency = records.get(selector.artifact_ref)
                    if (dependency is None or selector.artifact_ref not in dependency_ids
                            or dependency["sha256"] != selector.artifact_digest):
                        raise EvidenceProjectionError("EVIDENCE_DEPENDENCY_MISMATCH", "fact source is not sealed")
                    closure.add(selector.artifact_ref)
                verify_result_dependencies(source._project_file_store, manifest,
                    project_ref=source._project_ref, run_id=source._run_id,
                    dependency_ids=sorted(closure))
                dependency_wire = manifest.to_dict()
                dependency_wire["records"] = [row for row in dependency_wire["records"] if row["artifact_id"] in closure]
            except (ValueError, KeyError, TypeError) as exc:
                extension_reason = getattr(exc, "code", "structured_results_invalid")
                restriction_reason = extension_reason
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
        elif extended:
            selected = tuple(f for f in record.envelope.numeric_facts if f.fact_id in requested_set)
            omitted = ()
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

        if extended and (extension_reason or missing_requested):
            status = ProjectionStatus.UNAVAILABLE
        elif record.envelope.availability is not AvailabilityStatusV1.AVAILABLE:
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

        deliver_sections = not restriction_reason and record.envelope.availability is AvailabilityStatusV1.AVAILABLE
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
            requested_section_ids=requested_sections,
            selected_section_ids=tuple(s.section_id for s in section_selection) if deliver_sections else (),
            omitted_section_ids=tuple(dict.fromkeys((
                *(sid for sid in section_ids if sid not in requested_sections or not deliver_sections),
                *(sid for sid in requested_sections if sid not in section_ids),
            ))) if not redacted else (),
            redacted_section_ids=requested_sections if redacted else (),
        )
        fields = dict(
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
            sections=section_selection if deliver_sections else (),
            result_dependencies=dependency_wire if deliver_sections else None,
            semantic_selection=semantic_wire if deliver_sections else None,
        )
        return fields, record.sensitivity, spec, extended, deliver_sections


_PAGE_METADATA_FIELDS = frozenset({
    "consumer_id", "consumer_version", "projection_ref", "envelope_ref",
    "execution_status", "availability", "completeness_status", "numerical_method",
    "inference_basis", "evaluation_design", "validation_summary", "status", "audit",
    "lineage_refs", "data_snapshot_ref", "data_snapshot_digest", "renderer_key",
})
_BUNDLE_FIELDS = frozenset({"schema_version", "source_ref", "source_digest", "commit_id",
    "result_identity", "section_contract_digest", "section", "facts", "result_dependencies",
    "projection_metadata"})


def parse_result_section_bundle(raw: bytes) -> Mapping[str, object]:
    """Validate reconstructed canonical values, NEVER grant source authority."""
    from workbench.contracts.evidence.result_pages import MAX_BUNDLE_BYTES
    from workbench.evidence.result_dependencies import validate_result_dependency_manifest
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_BUNDLE_BYTES:
            raise ValueError("bundle byte limit")
        value = json.loads(raw)
        if (type(value) is not dict or set(value) != _BUNDLE_FIELDS
                or type(value["schema_version"]) is not int or value["schema_version"] != 1
                or value["section_contract_digest"] != RESULT_SECTIONS_CONTRACT_DIGEST
                or canonical_json_v1(value).encode("utf-8") != raw):
            raise ValueError("bundle schema or canonical bytes differ")
        for key in ("source_ref", "commit_id"):
            _text(value[key], key)
        _digest(value["source_digest"], "source_digest")
        if type(value["result_identity"]) is not dict:
            raise ValueError("result identity must be an object")
        metadata = value["projection_metadata"]
        if type(metadata) is not dict or set(metadata) != _PAGE_METADATA_FIELDS:
            raise ValueError("projection metadata fields differ")
        from workbench.contracts.common.foundation_status import NumericalMethodV1, InferenceBasisV1, EvaluationDesignV1
        from workbench.contracts.evidence.envelope import ValidationSummaryV1
        for key, enum in (("status", ProjectionStatus), ("execution_status", ExecutionStatusV1),
                          ("availability", AvailabilityStatusV1), ("completeness_status", CompletenessStatusV1),
                          ("numerical_method", NumericalMethodV1), ("inference_basis", InferenceBasisV1),
                          ("evaluation_design", EvaluationDesignV1)):
            enum(metadata[key])
        for key in ("consumer_id", "consumer_version", "envelope_ref"):
            _text(metadata[key], key)
        projection_ref = ContractRefV1.from_dict(metadata["projection_ref"])
        ValidationSummaryV1.from_dict(metadata["validation_summary"])
        audit_wire = metadata["audit"]
        audit_fields = set(ProjectionAuditV1.__dataclass_fields__) - {"egress_receipt_id", "egress_receipt_digest"}
        if type(audit_wire) is not dict or set(audit_wire) != audit_fields:
            raise ValueError("audit fields differ")
        audit = ProjectionAuditV1(**{**audit_wire, "policy_ref": ContractRefV1.from_dict(audit_wire["policy_ref"])})
        declared = default_projection_registry().resolve(metadata["consumer_id"])
        if declared is None:
            raise ValueError("bundle consumer is not declared")
        declared = _spec_for_audit_policy(declared, audit.destination, audit.policy_ref)
        if (metadata["consumer_version"] != declared.semantic_version
                or projection_ref != declared.projection_ref
                or metadata["renderer_key"] != declared.renderer_key
                or audit.policy_ref != declared.policy_ref):
            raise ValueError("bundle consumer declaration differs from catalog")
        if (metadata["status"] not in {"available", "degraded"} or metadata["availability"] != "available"
                or audit.destination not in {"local", "remote"} or audit.restriction_reason is not None
                or audit.redacted_fact_ids or audit.redacted_section_ids or audit.raw_rows_rejected
                or set(audit.selected_fact_ids).intersection(audit.omitted_fact_ids)
                or set(audit.selected_section_ids).intersection(audit.omitted_section_ids)):
            raise ValueError("bundle is not a deliverable section selection")
        _string_tuple(metadata["lineage_refs"], "lineage_refs")
        if metadata["renderer_key"] is not None:
            _text(metadata["renderer_key"], "renderer_key")
        if (metadata["data_snapshot_ref"] is None) != (metadata["data_snapshot_digest"] is None):
            raise ValueError("snapshot identity pair missing")
        if metadata["data_snapshot_ref"] is not None:
            _text(metadata["data_snapshot_ref"], "data_snapshot_ref")
            _digest(metadata["data_snapshot_digest"], "data_snapshot_digest")
        if metadata["envelope_ref"] != f"evidence-envelope:{value['source_digest']}":
            raise ValueError("envelope reference differs from source digest")
        if type(value["facts"]) is not list:
            raise ValueError("facts must be a list")
        facts = tuple(NumericFactV1.from_dict(f) for f in value["facts"])
        by_id = {f.fact_id: f for f in facts}
        if len(by_id) != len(facts):
            raise ValueError("duplicate facts")
        manifest_wire = value["result_dependencies"]
        manifest = validate_result_dependency_manifest(manifest_wire,
            project_ref=manifest_wire["project_ref"], run_id=manifest_wire["run_id"])
        for key in ("project_ref", "run_id"):
            if key in value["result_identity"] and value["result_identity"][key] != manifest_wire[key]:
                raise ValueError("bundle identity differs from manifest")
        records = {r["artifact_id"]: r for r in manifest.records}
        section = ResultSectionV1.from_dict(value["section"], facts=by_id, dependency_ids=set(records))
        if set(section.fact_refs) != set(by_id):
            raise ValueError("bundle facts must equal section references")
        if (section.to_dict()["status"] not in {"available", "unavailable", "not_applicable"}
                or audit.selected_section_ids != (section.section_id,)
                or audit.requested_section_ids != (section.section_id,)
                or audit.selected_fact_ids != tuple(by_id) or set(audit.requested_fact_ids) != set(by_id)):
            raise ValueError("selection audit differs from bundle")
        closure = set(section.dependency_refs)
        for fact in facts:
            selector = fact.source_selector
            if selector.artifact_ref not in records or records[selector.artifact_ref]["sha256"] != selector.artifact_digest:
                raise ValueError("fact source differs from seal")
            closure.add(selector.artifact_ref)
        if closure != set(records):
            raise ValueError("bundle manifest must equal selected closure")
        return freeze_json(value)
    except (ValueError, TypeError, KeyError, RecursionError) as exc:
        raise EvidenceProjectionError("RESULT_SECTION_BUNDLE_INVALID", "reconstructed section bundle is invalid") from exc


def _result_section_bundle_bytes(fields):
    """Canonical value serialization shared by page issuance and reassembly.

    Private admission fields are required by the callers; these bytes alone
    never grant authority or permit unbudgeted delivery.
    """
    if len(fields["sections"]) != 1:
        raise EvidenceProjectionError("RESULT_SECTION_BUNDLE_INVALID", "one selected section required")
    metadata = {key: fields[key] for key in _PAGE_METADATA_FIELDS}
    metadata.update(projection_ref=fields["projection_ref"].to_dict(), status=fields["status"].value,
                    audit=fields["audit"].to_dict(), lineage_refs=list(fields["lineage_refs"]))
    bundle = dict(schema_version=1, source_ref=fields["artifact_ref"], source_digest=fields["envelope_digest"],
        commit_id=fields["commit_id"], result_identity=dict(fields["result_identity"]),
        section_contract_digest=RESULT_SECTIONS_CONTRACT_DIGEST, section=fields["sections"][0].to_dict(),
        facts=[f.to_dict() for f in fields["facts"]], result_dependencies=thaw_json(fields["result_dependencies"]),
        projection_metadata=metadata)
    raw = canonical_json_v1(bundle).encode("utf-8")
    parse_result_section_bundle(raw)
    return raw


def _make_local_result_page_api():
    from workbench.contracts.evidence.result_pages import ResultBundlePagerV1, ResultPageError, MAX_PAGE_BYTES
    issued = weakref.WeakKeyDictionary()
    lock = RLock()

    def build(source, consumer_id, section_id):
        registry = default_projection_registry()
        fields, observed, spec, extended, deliver = registry._prepare_selection(source,
            consumer_id=consumer_id, destination="local", requested_fact_ids=(), requested_section_ids=(section_id,))
        if (not extended or not deliver or fields["status"] not in {ProjectionStatus.AVAILABLE, ProjectionStatus.DEGRADED}
                or len(fields["sections"]) != 1
                or fields["sections"][0].to_dict()["status"] not in {"available", "unavailable", "not_applicable"}):
            raise EvidenceProjectionError(fields["audit"].restriction_reason or "RESULT_PAGE_SECTION_UNAVAILABLE",
                                          "selected section cannot be paged")
        rows = _structured_row_count(fields["facts"], fields["sections"], fields["result_dependencies"])
        if rows > spec.max_row_budget:
            raise EvidenceProjectionError("RESULT_PAGE_ROW_BUDGET_EXCEEDED", "full section row charge exceeds policy")
        raw = _result_section_bundle_bytes(fields)
        return raw, observed, spec, rows

    def binding_digest(source, raw, observed, spec):
        return sha256_canonical({"source_id": id(source), "source_binding": source._payload_digest(),
            "bundle": sha256_canonical(json.loads(raw)), "observed_sensitivity": observed.value,
            "policy": spec.to_dict(), "destination": "local"})

    class ServerOwnedLocalResultPageAdmissionV1:
        __slots__ = ("__weakref__",)

        def __init__(self):
            raise TypeError("only the server registry issues page admissions")

        def __setattr__(self, name, value):
            raise TypeError("page admission is immutable")

        def __copy__(self):
            raise TypeError("page admission cannot be copied")

        def __deepcopy__(self, memo):
            raise TypeError("page admission cannot be copied")

        def __reduce__(self):
            raise TypeError("page admission cannot be serialized")

        def page(self, *, offset, max_wire_bytes=None, envelope_reserve_bytes=0):
            if type(self) is not ServerOwnedLocalResultPageAdmissionV1:
                raise EvidenceProjectionError("RESULT_PAGE_AUTHORITY_REQUIRED", "exact page admission required")
            with lock:
                state = issued.get(self)
            if state is None:
                raise EvidenceProjectionError("RESULT_PAGE_AUTHORITY_REQUIRED", "page admission was not issued")
            source, consumer_id, section_id, raw, observed, spec, request, proof, pager = state
            current, current_observed, current_spec, rows = build(source, consumer_id, section_id)
            if (current != raw or current_observed is not observed or current_spec != spec
                    or request.subject_id != id(self) or request.scope_ref != source._scope_ref
                    or request.payload_digest != binding_digest(source, raw, observed, spec)):
                raise EvidenceProjectionError("RESULT_PAGE_BINDING_CHANGED", "page admission binding changed")
            try:
                validate_host_proof(source._authority_handle, request, proof)
            except EvidenceHostAuthorityError as exc:
                raise EvidenceProjectionError(exc.code, str(exc)) from exc
            limit = min(MAX_PAGE_BYTES, spec.max_token_budget * 4)
            if max_wire_bytes is not None:
                if type(max_wire_bytes) is not int or not 0 < max_wire_bytes <= limit:
                    raise EvidenceProjectionError("RESULT_PAGE_BUDGET_EXCEEDED", "page budget is outside declared policy")
                limit = max_wire_bytes
            if type(envelope_reserve_bytes) is not int or not 0 <= envelope_reserve_bytes < limit:
                raise EvidenceProjectionError("RESULT_PAGE_BUDGET_EXCEEDED", "invalid wrapper reserve")
            wire = dict(schema_version=1, authority="server-owned", source="persisted-typed-evidence-page",
                consumer_id=consumer_id, destination="local", artifact_ref=source.artifact_id,
                commit_id=source.commit_id, envelope_digest=source._envelope_digest,
                identity={"project_ref": source._project_ref, "run_id": source._run_id, "scope_ref": source.scope_ref},
                observed_sensitivity=observed.value, policy_ref=spec.policy_ref.to_dict(),
                audit={"row_budget": rows, "token_budget": 0, "envelope_reserve_bytes": envelope_reserve_bytes},
                page={}, wire_digest="0" * 64)
            # Reserve exact wrapper bytes plus the maximum count width; then
            # settle audit/digest on the complete wire, not just base64 bytes.
            overhead = len(canonical_json_v1(wire).encode("utf-8")) - 2 + len(str(spec.max_token_budget))
            try:
                page = pager.page(offset=offset, max_wire_bytes=limit,
                                  envelope_reserve_bytes=envelope_reserve_bytes + overhead)
            except ResultPageError as exc:
                raise EvidenceProjectionError(exc.code, str(exc)) from exc
            wire["page"] = page.to_dict()
            while True:
                wire["wire_digest"] = sha256_canonical({k: v for k, v in wire.items() if k != "wire_digest"})
                size = len(canonical_json_v1(wire).encode("utf-8")) + envelope_reserve_bytes
                tokens = (size + 3) // 4
                if size > limit or tokens > spec.max_token_budget:
                    raise EvidenceProjectionError("RESULT_PAGE_BUDGET_EXCEEDED", "final page wire exceeds policy")
                if tokens == wire["audit"]["token_budget"]:
                    return freeze_json(wire)
                wire["audit"]["token_budget"] = tokens

    def prepare(self, source, *, consumer_id, section_id, destination="local"):
        if destination != "local":
            raise EvidenceProjectionError("RESULT_PAGE_REMOTE_EGRESS_REQUIRED", "remote paging is not admitted")
        if type(self) is not ConsumerProjectionRegistryV1:
            raise EvidenceProjectionError("RESULT_PAGE_AUTHORITY_REQUIRED", "exact registry required")
        consumer_id = _text(consumer_id, "consumer_id")
        declared = default_projection_registry().resolve(consumer_id)
        if declared is None or ConsumerProjectionRegistryV1.resolve(self, consumer_id) != declared:
            raise EvidenceProjectionError("RESULT_PAGE_POLICY_NOT_DECLARED", "page policy must be server declared")
        section_id = _text(section_id, "section_id")
        raw, observed, spec, _rows = build(source, consumer_id, section_id)
        admission = object.__new__(ServerOwnedLocalResultPageAdmissionV1)
        try:
            request = build_authority_request(source._authority_handle, purpose="evidence.consumer.local_result_page",
                scope_ref=source.scope_ref, subject_id=id(admission), payload_digest=binding_digest(source, raw, observed, spec))
            proof = issue_host_proof(source._authority_handle, request)
            validate_host_proof(source._authority_handle, request, proof)
        except EvidenceHostAuthorityError as exc:
            raise EvidenceProjectionError(exc.code, str(exc)) from exc
        pager = ResultBundlePagerV1(raw, binding=dict(source_ref=source.artifact_id,
            source_digest=source._envelope_digest, section_id=section_id, consumer_id=consumer_id, destination="local"))
        with lock:
            issued[admission] = (source, consumer_id, section_id, raw, observed, spec, request, proof, pager)
        return admission

    ConsumerProjectionRegistryV1.prepare_local_result_page_admission = prepare
    return ServerOwnedLocalResultPageAdmissionV1


ServerOwnedLocalResultPageAdmissionV1 = _make_local_result_page_api()
del _make_local_result_page_api


def _make_structured_projection_admission_api():
    """Keep issuance records and host proofs outside caller-reachable values."""
    admissions = weakref.WeakKeyDictionary()
    lock = RLock()

    class ServerOwnedStructuredProjectionAdmissionV1:
        __slots__ = ("__weakref__",)

        def __init__(self):
            raise TypeError("structured projection admission requires the private server issuer")

        def __setattr__(self, _name, _value):
            raise TypeError("structured projection admissions are immutable")

        def __copy__(self):
            raise TypeError("structured projection admissions cannot be copied")

        def __deepcopy__(self, _memo):
            raise TypeError("structured projection admissions cannot be copied")

        def __reduce__(self):
            raise TypeError("structured projection admissions cannot be serialized")

    def build(source, query):
        registry = default_projection_registry()
        if query.get("page_selection") is not None:
            from workbench.contracts.evidence.result_pages import pack_result_page, ResultPageError
            section_id, offset, limit = query["page_selection"]
            fields, observed, spec, extended, deliver = registry._prepare_selection(source,
                consumer_id=query["consumer_id"], destination="remote", requested_fact_ids=(),
                requested_section_ids=(section_id,))
            if (not extended or not deliver
                    or fields["status"] not in {ProjectionStatus.AVAILABLE, ProjectionStatus.DEGRADED}):
                raise EvidenceProjectionError(fields["audit"].restriction_reason or "RESULT_PAGE_SECTION_UNAVAILABLE",
                                              "remote section cannot be admitted")
            rows = _structured_row_count(fields["facts"], fields["sections"], fields["result_dependencies"])
            if rows > spec.max_row_budget:
                raise EvidenceProjectionError("RESULT_PAGE_ROW_BUDGET_EXCEEDED", "whole section exceeds row policy")
            if type(limit) is not int or not 0 < limit <= min(8192, spec.max_token_budget * 4):
                raise EvidenceProjectionError("RESULT_PAGE_BUDGET_EXCEEDED", "remote page limit exceeds policy")
            payload = dict(schema_version=1, delivery_kind="result_section_page", consumer_id=query["consumer_id"],
                destination="remote", artifact_ref=source.artifact_id, commit_id=source.commit_id,
                envelope_digest=source._envelope_digest, read_completeness="PARTIAL", completion_scope="section",
                identity={"project_ref": source._project_ref, "run_id": source._run_id, "scope_ref": source.scope_ref},
                max_wire_bytes=limit, row_budget=rows, page={})
            # Reserve actual UTF-8 payload framing and final receipt wrapper.
            reserve = len(json.dumps(payload, ensure_ascii=False, allow_nan=False,
                                     separators=(",", ":")).encode()) - 2 + 1024
            try:
                payload["page"] = pack_result_page(_result_section_bundle_bytes(fields), binding=dict(
                    source_ref=source.artifact_id, source_digest=source._envelope_digest, section_id=section_id,
                    consumer_id=query["consumer_id"], destination="remote"), offset=offset,
                    max_wire_bytes=limit, envelope_reserve_bytes=reserve).to_dict()
            except ResultPageError as exc:
                raise EvidenceProjectionError(exc.code, str(exc)) from exc
            return freeze_json({"evidence:projection": payload}), observed, sha256_canonical(spec.to_dict())
        projection, observed, spec, extended = ConsumerProjectionRegistryV1._build_projection(registry, source, **query)
        if not extended:
            raise EvidenceProjectionError("structured_admission_extension_required", "a sealed extension is required")
        if projection.status not in {ProjectionStatus.AVAILABLE, ProjectionStatus.DEGRADED}:
            raise EvidenceProjectionError(projection.audit.restriction_reason or "structured_admission_unavailable",
                                          "structured projection cannot be admitted")
        context = freeze_json({"evidence:projection": projection.egress_payload()})
        return context, observed, sha256_canonical(spec.to_dict())

    def proof_digest(source, query, context, observed, spec_digest):
        return sha256_canonical({
            "source_identity": id(source), "source_binding": source._payload_digest(),
            "destination": query["destination"], "consumer_id": query["consumer_id"],
            "policy_digest": spec_digest, "observed_sensitivity": observed.value,
            "canonical_context_digest": sha256_canonical(context),
        })

    def prepare(self, source, *, consumer_id, destination, requested_fact_ids=None,
                requested_section_ids=None, coefficient_selection=None, requested_section_types=None,
                provenance_selection=None, page_selection=None
                ) -> ServerOwnedStructuredProjectionAdmissionV1:
        if type(self) is not ConsumerProjectionRegistryV1:
            raise EvidenceProjectionError("structured_admission_registry_required", "exact central registry required")
        if destination != "remote":
            raise EvidenceProjectionError("structured_admission_remote_destination_required", "no local projection upgrade")
        declared = default_projection_registry().resolve(consumer_id)
        candidate = ConsumerProjectionRegistryV1.resolve(self, consumer_id)
        if declared is None or type(candidate) is not ConsumerProjectionSpecV1 or candidate != declared:
            raise EvidenceProjectionError("structured_admission_policy_not_declared", "caller projection policies cannot issue admission")
        query = {"consumer_id": consumer_id, "destination": destination}
        for key, value in (("requested_fact_ids", requested_fact_ids), ("requested_section_ids", requested_section_ids),
                           ("requested_section_types", requested_section_types)):
            query[key] = None if value is None else _string_tuple(value, key)
        if coefficient_selection is not None:
            if type(coefficient_selection) is not ModelCoefficientSelectionV1:
                raise EvidenceProjectionError("semantic_selector_invalid", "typed coefficient selector required")
            coefficient_selection = type(coefficient_selection)(coefficient_selection.model_id,
                terms=coefficient_selection.terms, roles=coefficient_selection.roles)
        query["coefficient_selection"] = coefficient_selection
        if provenance_selection is not None:
            if type(provenance_selection) is not ModelProvenanceSelectionV1:
                raise EvidenceProjectionError("semantic_selector_invalid", "typed provenance selector required")
            if any(value is not None for value in (coefficient_selection, requested_fact_ids,
                                                   requested_section_ids, requested_section_types)):
                raise EvidenceProjectionError("semantic_selection_mixed", "selectors are mutually exclusive")
            provenance_selection = ModelProvenanceSelectionV1(provenance_selection.model_id,
                terms=provenance_selection.terms, roles=provenance_selection.roles)
        query["provenance_selection"] = provenance_selection
        if page_selection is not None:
            if (type(page_selection) is not tuple or len(page_selection) != 3
                    or any(value is not None for value in (requested_fact_ids, requested_section_ids,
                        coefficient_selection, requested_section_types, provenance_selection))):
                raise EvidenceProjectionError("RESULT_PAGE_SELECTION_INVALID", "page selectors cannot be mixed")
            section_id, offset, limit = page_selection
            _text(section_id, "section_id")
            if type(offset) is not int or offset < 0:
                raise EvidenceProjectionError("RESULT_PAGE_INVALID", "invalid page offset")
            query["page_selection"] = (section_id, offset, limit)
        query = MappingProxyType(query)
        context, observed, spec_digest = build(source, query)
        admission = object.__new__(ServerOwnedStructuredProjectionAdmissionV1)
        try:
            request = build_authority_request(source._authority_handle, purpose="evidence.consumer.structured_projection",
                scope_ref=source._scope_ref, subject_id=id(admission),
                payload_digest=proof_digest(source, query, context, observed, spec_digest))
            proof = issue_host_proof(source._authority_handle, request)
            validate_host_proof(source._authority_handle, request, proof)
        except EvidenceHostAuthorityError as exc:
            raise EvidenceProjectionError(exc.code, str(exc)) from exc
        with lock:
            admissions[admission] = (source, query, context, observed, spec_digest, request, proof)
        return admission

    def validate_server_owned_structured_projection_admission(admission: ServerOwnedStructuredProjectionAdmissionV1
            ) -> tuple[Mapping[str, object], SensitivityClassV1]:
        if type(admission) is not ServerOwnedStructuredProjectionAdmissionV1:
            raise EvidenceProjectionError("structured_admission_authority_required", "exact server-issued admission required")
        with lock:
            state = admissions.get(admission)
        if state is None:
            raise EvidenceProjectionError("structured_admission_authority_required", "admission was not issued by the server")
        source, query, context, observed, spec_digest, request, proof = state
        current, current_observed, current_spec = build(source, query)
        if (current_observed is not observed or current_spec != spec_digest
                or canonical_json_v1(current) != canonical_json_v1(context)
                or request.subject_id != id(admission) or request.scope_ref != source._scope_ref
                or request.payload_digest != proof_digest(source, query, context, observed, spec_digest)):
            raise EvidenceProjectionError("structured_admission_binding_changed", "admission source or payload binding changed")
        try:
            validate_host_proof(source._authority_handle, request, proof)
        except EvidenceHostAuthorityError as exc:
            raise EvidenceProjectionError(exc.code, str(exc)) from exc
        return context, observed

    def prepare_remote_page(self, source, *, consumer_id, section_id, offset, max_wire_bytes=8192):
        return prepare(self, source, consumer_id=consumer_id, destination="remote",
                       page_selection=(section_id, offset, max_wire_bytes))

    def deliver_remote_page(self, admission, *, gateway=None, receipt=None, issuer=None):
        if type(self) is not ConsumerProjectionRegistryV1:
            raise EvidenceProjectionError("RESULT_PAGE_AUTHORITY_REQUIRED", "exact registry required")
        if gateway is None or receipt is None or issuer is None:
            raise EvidenceProjectionError("egress_receipt_required", "remote page requires an exact egress receipt")
        try:
            require_context_egress_receipt(gateway, receipt, issuer=issuer)
            context, observed = validate_server_owned_structured_projection_admission(admission)
            payload = context["evidence:projection"]
            materialized = issuer.materializer_store.resolve(gateway.materialization_result_ref)
            if (payload.get("delivery_kind") != "result_section_page" or gateway.destination != "remote"
                    or gateway.sensitivity is not observed
                    or canonical_json_v1(materialized.materialized_context) != canonical_json_v1(context)
                    or self.resolve(payload["consumer_id"]) != default_projection_registry().resolve(payload["consumer_id"])):
                raise EvidenceProjectionError("RESULT_PAGE_EGRESS_MISMATCH", "receipt does not authorize this exact page")
            result = dict(schema_version=1, destination="remote", read_completeness="PARTIAL",
                payload=thaw_json(payload), egress_receipt_id=receipt.receipt_id,
                egress_receipt_digest=receipt.receipt_digest)
            size = len(json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode())
            if (size > payload["max_wire_bytes"] or (size + 3) // 4 > gateway.token_budget
                    or payload["row_budget"] > gateway.row_budget):
                raise EvidenceProjectionError("RESULT_PAGE_BUDGET_EXCEEDED", "final remote page exceeds policy")
            return result
        except EgressContractError as exc:
            raise EvidenceProjectionError(exc.code, "remote page egress rejected") from exc

    ConsumerProjectionRegistryV1.prepare_structured_projection_admission = prepare
    ConsumerProjectionRegistryV1.prepare_remote_result_page_admission = prepare_remote_page
    ConsumerProjectionRegistryV1.deliver_remote_result_page = deliver_remote_page
    return ServerOwnedStructuredProjectionAdmissionV1, validate_server_owned_structured_projection_admission


(ServerOwnedStructuredProjectionAdmissionV1,
 validate_server_owned_structured_projection_admission) = _make_structured_projection_admission_api()
del _make_structured_projection_admission_api


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
    "ServerOwnedLocalResultPageAdmissionV1",
    "parse_result_section_bundle",
    "ServerOwnedStructuredProjectionAdmissionV1",
    "validate_server_owned_structured_projection_admission",
    "ModelCoefficientSelectionV1",
    "COEFFICIENT_ROLE_PATHS_V1",
    "COEFFICIENT_SELECTION_CONTRACT_DIGEST",
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
