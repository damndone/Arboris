"""Deterministic package-local evidence admission registry."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from threading import RLock

from workbench.canonical import sha256_canonical

from .authority import (
    EVIDENCE_HOST_AUTHORITY_REQUIRED,
    EvidenceHostAuthorityError,
    build_authority_request,
    issue_host_proof,
    validate_host_proof,
)
from .contracts import (
    ArtifactAdmissionV1,
    artifact_content_hash,
    EvidenceCoreContractError,
    EvidenceBindingV1,
    EvidenceEnvelopeFacadeV1,
    _opaque_ref,
)


class EvidenceRegistryError(ValueError):
    """A closed-world registry failure with a stable reason code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _registry_error(code: str, message: str) -> EvidenceRegistryError:
    return EvidenceRegistryError(code, message)


def _canonical_content(value: object) -> tuple[EvidenceEnvelopeFacadeV1, bytes]:
    try:
        if type(value) is bytes:
            envelope = EvidenceEnvelopeFacadeV1.from_bytes(value)
        elif type(value) is dict:
            envelope = EvidenceEnvelopeFacadeV1.from_dict(value)
        elif type(value) is EvidenceEnvelopeFacadeV1:
            envelope = EvidenceEnvelopeFacadeV1.from_bytes(value.canonical_bytes())
        else:
            raise _registry_error(
                "EVIDENCE_CONTENT_INVALID",
                "artifact content must be a strict envelope dict, facade, or canonical bytes",
            )
    except EvidenceRegistryError:
        raise
    except EvidenceCoreContractError as exc:
        raise _registry_error("EVIDENCE_CORRUPT", str(exc)) from exc
    raw = envelope.canonical_bytes()
    return envelope, raw


class _EvidenceRegistryReceiptV1:
    """Opaque host proof bound to one registry-owned admission."""

    __slots__ = ("_registry", "_record", "_artifact_id", "_request", "_proof")

    def __init__(
        self,
        registry: "EvidenceRegistryV1",
        record: ArtifactAdmissionV1,
        request: object,
        proof: object,
    ) -> None:
        self._registry = registry
        self._record = record
        self._artifact_id = record.artifact_id
        self._request = request
        self._proof = proof

    def __reduce__(self):
        raise TypeError("registry receipts are host-bound capabilities")

    def __copy__(self):
        raise TypeError("registry receipts are host-bound capabilities")

    def __deepcopy__(self, memo):
        raise TypeError("registry receipts are host-bound capabilities")


class EvidenceRegistryV1:
    """An in-memory, scope-pinned registry of immutable admitted envelopes.

    The registry stores canonical bytes as the authority.  Caller-owned input
    mappings are parsed and copied at admission; later mutation of those
    mappings cannot mutate a record or make a different record share its
    identity.
    """

    __slots__ = (
        "_scope_ref",
        "_records",
        "_raw",
        "_receipts",
        "_lock",
        "_authority_handle",
        "_authority_request",
        "_authority_proof",
    )

    def __init__(self, *, scope_ref: str, authority_handle: object | None = None) -> None:
        if authority_handle is None:
            raise _registry_error(
                EVIDENCE_HOST_AUTHORITY_REQUIRED,
                "evidence registries require a host-issued authority handle",
            )
        try:
            self._scope_ref = _opaque_ref(scope_ref, "scope_ref")
        except EvidenceCoreContractError as exc:
            raise _registry_error("EVIDENCE_REGISTRY_AUTHORITY_REQUIRED", str(exc)) from exc
        self._records: dict[str, ArtifactAdmissionV1] = {}
        self._raw: dict[str, bytes] = {}
        self._receipts: dict[str, _EvidenceRegistryReceiptV1] = {}
        self._lock = RLock()
        self._authority_handle = authority_handle
        try:
            self._authority_request = build_authority_request(
                authority_handle,
                purpose="evidence.registry",
                scope_ref=self._scope_ref,
                subject_id=id(self),
                payload_digest=self._authority_payload_digest(),
            )
            self._authority_proof = issue_host_proof(authority_handle, self._authority_request)
            self._require_authority()
        except EvidenceHostAuthorityError as exc:
            raise _registry_error(exc.code, str(exc)) from exc

    def _authority_payload_digest(self) -> str:
        return sha256_canonical({"scope_ref": self._scope_ref})

    def _require_authority(self) -> None:
        try:
            scope_ref = self._scope_ref
            request = self._authority_request
            proof = self._authority_proof
            handle = self._authority_handle
            if request.subject_id != id(self) or request.scope_ref != scope_ref:
                raise EvidenceHostAuthorityError(message="registry subject binding is invalid")
            if request.payload_digest != self._authority_payload_digest():
                raise EvidenceHostAuthorityError(message="registry payload binding is invalid")
            validate_host_proof(handle, request, proof)
        except EvidenceHostAuthorityError as exc:
            raise _registry_error(
                EVIDENCE_HOST_AUTHORITY_REQUIRED,
                str(exc),
            ) from exc
        except (AttributeError, TypeError, ValueError) as exc:
            raise _registry_error(EVIDENCE_HOST_AUTHORITY_REQUIRED, "registry authority is malformed") from exc

    def __reduce__(self):
        raise TypeError("evidence registries are host-bound capabilities")

    def __copy__(self):
        raise TypeError("evidence registries are host-bound capabilities")

    def __deepcopy__(self, memo):
        raise TypeError("evidence registries are host-bound capabilities")

    @property
    def scope_ref(self) -> str:
        self._require_authority()
        return self._scope_ref

    def _host_authority_handle(self) -> object:
        self._require_authority()
        return self._authority_handle

    @staticmethod
    def _record_content_hash(record: ArtifactAdmissionV1) -> str:
        return artifact_content_hash(
            artifact_id=record.artifact_id,
            artifact_type=record.artifact_type,
            scope_ref=record.scope_ref,
            source_ref=record.source_ref,
            validator_ref=record.validator_ref,
            execution_ref=record.execution_ref,
            contract_digest=record.contract_digest,
            envelope=record.envelope,
        )

    def _mint_receipt(self, record: ArtifactAdmissionV1) -> _EvidenceRegistryReceiptV1:
        request = build_authority_request(
            self._authority_handle,
            purpose="evidence.registry.receipt",
            scope_ref=self._scope_ref,
            subject_id=id(record),
            payload_digest=record.content_hash,
        )
        proof = issue_host_proof(self._authority_handle, request)
        return _EvidenceRegistryReceiptV1(
            self,
            record,
            request,
            proof,
        )

    def persistence_receipt(
        self,
        record_or_artifact_id: ArtifactAdmissionV1 | str,
    ) -> object:
        """Return the process-local persistence capability for an admitted record."""

        self._require_authority()
        with self._lock:
            if type(record_or_artifact_id) is str:
                try:
                    artifact_id = _opaque_ref(record_or_artifact_id, "artifact_id")
                except EvidenceCoreContractError as exc:
                    raise _registry_error("EVIDENCE_ARTIFACT_UNKNOWN", str(exc)) from exc
                record = self._records.get(artifact_id)
            elif type(record_or_artifact_id) is ArtifactAdmissionV1:
                record = record_or_artifact_id
                admitted = self._records.get(record.artifact_id)
                if admitted is not record:
                    raise _registry_error(
                        "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
                        "persistence receipt requires the exact registry-owned admission",
                    )
            else:
                raise _registry_error(
                    "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
                    "persistence receipt requires a registry-owned admission",
                )
            if record is None:
                raise _registry_error("EVIDENCE_ARTIFACT_UNKNOWN", "artifact identity is not admitted")
            receipt = self._receipts.get(record.artifact_id)
            if receipt is None:
                receipt = self._mint_receipt(record)
                self._receipts[record.artifact_id] = receipt
            return receipt

    def _validate_persistence_receipt(
        self,
        record: object,
        receipt: object,
    ) -> None:
        self._require_authority()
        try:
            if type(record) is not ArtifactAdmissionV1 or type(receipt) is not _EvidenceRegistryReceiptV1:
                raise _registry_error(
                    "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
                    "persistence requires a registry-issued receipt for an admitted record",
                )
            artifact_id = receipt._artifact_id
            receipt_registry = receipt._registry
            receipt_record = receipt._record
            request = receipt._request
            proof = receipt._proof
            if (
                type(artifact_id) is not str
                or type(receipt_registry) is not EvidenceRegistryV1
                or type(receipt_record) is not ArtifactAdmissionV1
            ):
                raise ValueError("registry receipt fields are malformed")
            admitted = self._records.get(record.artifact_id)
            current = self._receipts.get(record.artifact_id)
            if (
                admitted is not record
                or current is not receipt
                or receipt_registry is not self
                or receipt_record is not record
                or artifact_id != record.artifact_id
            ):
                raise _registry_error(
                    "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
                    "persistence receipt is not issued by the owning registry",
                )
            if self._record_content_hash(record) != record.content_hash:
                raise _registry_error(
                    "EVIDENCE_TAMPERED",
                    "registry-owned admission no longer matches its complete content hash",
                )
            if (
                request.subject_id != id(record)
                or request.scope_ref != self._scope_ref
                or request.payload_digest != record.content_hash
            ):
                raise _registry_error(
                    "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
                    "persistence receipt binding is invalid",
                )
            try:
                validate_host_proof(self._authority_handle, request, proof)
            except EvidenceHostAuthorityError as exc:
                raise _registry_error(EVIDENCE_HOST_AUTHORITY_REQUIRED, str(exc)) from exc
        except EvidenceRegistryError:
            raise
        except (AttributeError, TypeError, ValueError, KeyError) as exc:
            raise _registry_error(
                "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
                "registry receipt is malformed or not server-issued",
            ) from exc

    def validate_persistence_receipt(self, record: object, receipt: object) -> None:
        with self._lock:
            self._validate_persistence_receipt(record, receipt)

    def validate_persistence_capability(self, receipt: object) -> None:
        """Validate a receipt before a persistence consumer reads durable data."""

        self._require_authority()
        if type(receipt) is not _EvidenceRegistryReceiptV1:
            raise _registry_error(
                "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
                "persistence receipt is not server-issued",
            )
        try:
            record = receipt._record
        except (AttributeError, TypeError) as exc:
            raise _registry_error(
                "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
                "persistence receipt is malformed",
            ) from exc
        with self._lock:
            self._validate_persistence_receipt(record, receipt)

    @property
    def artifact_ids(self) -> tuple[str, ...]:
        self._require_authority()
        with self._lock:
            return tuple(sorted(self._records))

    @property
    def records(self) -> tuple[ArtifactAdmissionV1, ...]:
        self._require_authority()
        with self._lock:
            return tuple(self._records[key] for key in sorted(self._records))

    def admit_artifact(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        scope_ref: str,
        content: object,
        source_ref: str,
        validator_ref: object,
        execution_ref: str,
        contract_digest: str,
        content_hash: str | None = None,
        artifact_digest: str | None = None,
    ) -> ArtifactAdmissionV1:
        self._require_authority()
        if scope_ref != self._scope_ref:
            raise _registry_error(
                "EVIDENCE_CROSS_SCOPE",
                "artifact admission scope does not match the registry scope",
            )
        if content_hash is not None and artifact_digest is not None and content_hash != artifact_digest:
            raise _registry_error("EVIDENCE_ARTIFACT_HASH_MISMATCH", "content_hash and artifact_digest disagree")
        expected_hash = content_hash if content_hash is not None else artifact_digest
        envelope, raw = _canonical_content(content)
        try:
            binding = EvidenceBindingV1(
                source_ref=source_ref,
                validator_ref=validator_ref,  # type: ignore[arg-type]
                execution_ref=execution_ref,
                contract_digest=contract_digest,
            )
            actual_hash = artifact_content_hash(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                scope_ref=scope_ref,
                source_ref=binding.source_ref,
                validator_ref=binding.validator_ref,
                execution_ref=binding.execution_ref,
                contract_digest=binding.contract_digest,
                envelope=envelope,
            )
            if expected_hash is not None and expected_hash != actual_hash:
                raise _registry_error(
                    "EVIDENCE_ARTIFACT_HASH_MISMATCH",
                    "admission supplied a content hash that does not match complete artifact metadata",
                )
            record = ArtifactAdmissionV1(
                artifact_id=artifact_id,
                artifact_type=artifact_type,
                scope_ref=scope_ref,
                content_hash=actual_hash,
                source_ref=source_ref,
                validator_ref=binding.validator_ref,
                execution_ref=execution_ref,
                contract_digest=contract_digest,
                envelope=envelope,
            )
        except EvidenceCoreContractError as exc:
            raise _registry_error("EVIDENCE_ADMISSION_INVALID", str(exc)) from exc

        with self._lock:
            existing = self._records.get(record.artifact_id)
            if existing is not None:
                if existing.to_dict() != record.to_dict() or self._raw[record.artifact_id] != raw:
                    raise _registry_error(
                        "EVIDENCE_ARTIFACT_MUTATED",
                        "an immutable artifact identity was presented with different content or bindings",
                    )
                if record.artifact_id not in self._receipts:
                    self._receipts[record.artifact_id] = self._mint_receipt(existing)
                return existing
            self._records[record.artifact_id] = record
            self._raw[record.artifact_id] = raw
            self._receipts[record.artifact_id] = self._mint_receipt(record)
            return record

    def admit_bytes(self, **kwargs: object) -> ArtifactAdmissionV1:
        return self.admit_artifact(**kwargs)  # type: ignore[arg-type]

    def admit_file(
        self,
        *,
        artifact_id: str,
        artifact_type: str,
        scope_ref: str,
        path: Path | str,
        source_ref: str,
        validator_ref: object,
        execution_ref: str,
        contract_digest: str,
        content_hash: str | None = None,
    ) -> ArtifactAdmissionV1:
        """Read one regular file through a no-follow descriptor, then admit it.

        The path is an input capability only.  It is never placed in the
        admission record, packet, index, or projection.
        """

        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
        if os.name != "posix" or not getattr(os, "O_NOFOLLOW", 0):
            raise _registry_error("EVIDENCE_ADMISSION_UNSUPPORTED", "safe artifact admission requires POSIX O_NOFOLLOW")
        fd: int | None = None
        try:
            fd = os.open(os.fspath(path), flags)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                raise OSError("artifact is not a regular file")
            with os.fdopen(fd, "rb", closefd=True) as handle:
                fd = None
                raw = handle.read()
        except (OSError, ValueError) as exc:
            raise _registry_error("EVIDENCE_ARTIFACT_UNAVAILABLE", "artifact file could not be admitted") from exc
        finally:
            if fd is not None:
                os.close(fd)
        return self.admit_artifact(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            scope_ref=scope_ref,
            content=raw,
            source_ref=source_ref,
            validator_ref=validator_ref,
            execution_ref=execution_ref,
            contract_digest=contract_digest,
            content_hash=content_hash,
        )

    def resolve(self, artifact_id: str, *, scope_ref: str | None = None) -> ArtifactAdmissionV1:
        self._require_authority()
        try:
            artifact_id = _opaque_ref(artifact_id, "artifact_id")
        except EvidenceCoreContractError as exc:
            raise _registry_error("EVIDENCE_ARTIFACT_UNKNOWN", str(exc)) from exc
        requested_scope = self._scope_ref if scope_ref is None else scope_ref
        if requested_scope != self._scope_ref:
            raise _registry_error("EVIDENCE_CROSS_SCOPE", "requested scope is outside this registry")
        with self._lock:
            record = self._records.get(artifact_id)
            if record is None:
                raise _registry_error("EVIDENCE_ARTIFACT_UNKNOWN", "artifact identity is not admitted")
            if record.scope_ref != requested_scope:
                raise _registry_error("EVIDENCE_CROSS_SCOPE", "artifact is outside the requested scope")
            if self._record_content_hash(record) != record.content_hash:
                raise _registry_error("EVIDENCE_TAMPERED", "admitted artifact no longer matches its content hash")
            return record

    def get(self, artifact_id: str, *, scope_ref: str | None = None) -> ArtifactAdmissionV1:
        return self.resolve(artifact_id, scope_ref=scope_ref)

    def canonical_bytes(self, artifact_id: str) -> bytes:
        self._require_authority()
        self.resolve(artifact_id)
        with self._lock:
            return bytes(self._raw[artifact_id])

    def snapshot(self) -> tuple[dict[str, object], ...]:
        self._require_authority()
        with self._lock:
            return tuple(self._records[key].to_dict() for key in sorted(self._records))


ArtifactRegistryV1 = EvidenceRegistryV1
EvidenceRegistryReceiptV1 = _EvidenceRegistryReceiptV1


def create_server_evidence_registry(
    *,
    scope_ref: str,
    authority_handle: object | None = None,
) -> EvidenceRegistryV1:
    """Create a registry only with a host-issued authority channel."""

    return EvidenceRegistryV1(
        scope_ref=scope_ref,
        authority_handle=authority_handle,
    )


def validate_registry_persistence_receipt(
    record: object,
    receipt: object,
    *,
    registry: EvidenceRegistryV1 | None = None,
) -> None:
    """Validate a registry capability without granting authority to record type alone."""

    if registry is not None:
        if type(registry) is not EvidenceRegistryV1:
            raise _registry_error(
                "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
                "persistence receipt issuer is invalid",
            )
        try:
            registry._require_authority()
        except EvidenceRegistryError:
            raise
    if type(receipt) is not _EvidenceRegistryReceiptV1:
        raise _registry_error(
            "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
            "persistence requires a registry-issued receipt",
        )
    try:
        issuer = receipt._registry
    except (AttributeError, TypeError) as exc:
        raise _registry_error(
            "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
            "persistence receipt is malformed",
        ) from exc
    if type(issuer) is not EvidenceRegistryV1:
        raise _registry_error(
            "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
            "persistence receipt issuer is invalid",
        )
    if registry is not None and registry is not issuer:
        raise _registry_error(
            "EVIDENCE_PERSISTENCE_ADMISSION_REQUIRED",
            "persistence receipt issuer does not match the supplied registry",
        )
    issuer.validate_persistence_receipt(record, receipt)


__all__ = [
    "ArtifactRegistryV1",
    "EvidenceRegistryError",
    "EvidenceRegistryReceiptV1",
    "EvidenceRegistryV1",
    "create_server_evidence_registry",
    "validate_registry_persistence_receipt",
]
