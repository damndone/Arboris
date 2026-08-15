"""Immutable persistence bindings for version-pinned evidence envelopes."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from workbench.canonical import sha256_canonical
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.common.envelope import ContractError, require_exact_keys
from workbench.contracts.common.foundation_status import TransactionStatusV1
from workbench.contracts.evidence.envelope import NotApplicableV1


EVIDENCE_IDEMPOTENCY_CONFLICT = "EVIDENCE_IDEMPOTENCY_CONFLICT"
EVIDENCE_IDEMPOTENCY_KEY_MISMATCH = "EVIDENCE_IDEMPOTENCY_KEY_MISMATCH"

_ERROR_MESSAGES = {
    EVIDENCE_IDEMPOTENCY_CONFLICT: "idempotency key is already bound to a different request",
    EVIDENCE_IDEMPOTENCY_KEY_MISMATCH: "retry idempotency key does not match the binding",
}
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class EvidencePersistenceContractError(ValueError):
    """A retry-resolution failure with a stable public code."""

    def __init__(self, code: str) -> None:
        if code not in _ERROR_MESSAGES:
            raise ValueError("unknown evidence persistence error code")
        self.code = code
        super().__init__(f"{code}: {_ERROR_MESSAGES[code]}")


def _text(value: object, name: str) -> str:
    if type(value) is not str or not value or value != value.strip():
        raise ContractError(f"{name} must be an exact non-empty string")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ContractError(f"{name} must be a lowercase SHA-256 digest")
    return value


def _string_tuple(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ContractError(f"{name} must be an array")
    return tuple(_text(item, f"{name}[]") for item in value)


def _wire_dict(
    value: object,
    required: set[str],
    name: str,
) -> dict[str, object]:
    if type(value) is not dict:
        raise ContractError(f"{name} must be a built-in dict")
    require_exact_keys(value, required, name)
    return value


def _wire_mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict:
        raise ContractError(f"{name} must be a built-in dict")
    return value


def _supersedes(value: object) -> str | NotApplicableV1:
    if type(value) is str:
        return _text(value, "supersedes_ref")
    if not isinstance(value, Mapping):
        raise ContractError("supersedes_ref must be a string or NotApplicableV1")
    return NotApplicableV1.from_dict(value)


def _serialize_supersedes(value: str | NotApplicableV1) -> object:
    return value if type(value) is str else value.to_dict()


@dataclass(frozen=True)
class EvidenceCommitRequestV1:
    artifact_admission_ref: str
    projector_ref: ContractRefV1
    envelope_digest: str
    idempotency_key: str
    supersedes_ref: str | NotApplicableV1
    invalidation_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.artifact_admission_ref, "artifact_admission_ref")
        if type(self.projector_ref) is not ContractRefV1:
            raise ContractError("projector_ref must be ContractRefV1")
        _digest(self.envelope_digest, "envelope_digest")
        _text(self.idempotency_key, "idempotency_key")
        if type(self.supersedes_ref) is str:
            _text(self.supersedes_ref, "supersedes_ref")
        elif type(self.supersedes_ref) is not NotApplicableV1:
            raise ContractError("supersedes_ref must be a string or NotApplicableV1")
        object.__setattr__(
            self,
            "invalidation_refs",
            _string_tuple(self.invalidation_refs, "invalidation_refs"),
        )

    @property
    def request_digest(self) -> str:
        return sha256_canonical(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_admission_ref": self.artifact_admission_ref,
            "projector_ref": self.projector_ref.to_dict(),
            "envelope_digest": self.envelope_digest,
            "idempotency_key": self.idempotency_key,
            "supersedes_ref": _serialize_supersedes(self.supersedes_ref),
            "invalidation_refs": list(self.invalidation_refs),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "EvidenceCommitRequestV1":
        value = _wire_dict(
            value,
            {
                "artifact_admission_ref",
                "projector_ref",
                "envelope_digest",
                "idempotency_key",
                "supersedes_ref",
                "invalidation_refs",
            },
            "evidence_commit_request",
        )
        return cls(
            artifact_admission_ref=value["artifact_admission_ref"],  # type: ignore[arg-type]
            projector_ref=ContractRefV1.from_dict(
                _wire_mapping(value["projector_ref"], "projector_ref")
            ),
            envelope_digest=value["envelope_digest"],  # type: ignore[arg-type]
            idempotency_key=value["idempotency_key"],  # type: ignore[arg-type]
            supersedes_ref=_supersedes(value["supersedes_ref"]),
            invalidation_refs=_string_tuple(
                value["invalidation_refs"], "invalidation_refs"
            ),
        )


@dataclass(frozen=True)
class FailureReceiptV1:
    code: str
    message: str
    retryable: bool
    evidence_refs: tuple[str, ...]

    def __post_init__(self) -> None:
        _text(self.code, "code")
        _text(self.message, "message")
        if type(self.retryable) is not bool:
            raise ContractError("retryable must be a boolean")
        object.__setattr__(
            self,
            "evidence_refs",
            _string_tuple(self.evidence_refs, "evidence_refs"),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "evidence_refs": list(self.evidence_refs),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "FailureReceiptV1":
        value = _wire_dict(
            value,
            {"code", "message", "retryable", "evidence_refs"},
            "failure_receipt",
        )
        return cls(
            code=value["code"],  # type: ignore[arg-type]
            message=value["message"],  # type: ignore[arg-type]
            retryable=value["retryable"],  # type: ignore[arg-type]
            evidence_refs=_string_tuple(value["evidence_refs"], "evidence_refs"),
        )


@dataclass(frozen=True)
class EvidenceCommitBindingV1:
    commit_id: str
    request_digest: str
    artifact_admission_ref: str
    projector_ref: ContractRefV1
    envelope_digest: str
    idempotency_key: str
    transaction_status: TransactionStatusV1
    supersedes_ref: str | NotApplicableV1
    invalidation_refs: tuple[str, ...]
    failure_receipt: FailureReceiptV1 | NotApplicableV1

    def __post_init__(self) -> None:
        _text(self.commit_id, "commit_id")
        _digest(self.request_digest, "request_digest")
        request = EvidenceCommitRequestV1(
            artifact_admission_ref=self.artifact_admission_ref,
            projector_ref=self.projector_ref,
            envelope_digest=self.envelope_digest,
            idempotency_key=self.idempotency_key,
            supersedes_ref=self.supersedes_ref,
            invalidation_refs=self.invalidation_refs,
        )
        object.__setattr__(self, "invalidation_refs", request.invalidation_refs)
        if self.request_digest != request.request_digest:
            raise ContractError("request_digest does not match request-bound fields")
        if type(self.transaction_status) is not TransactionStatusV1:
            raise ContractError("transaction_status must be TransactionStatusV1")
        if self.transaction_status is TransactionStatusV1.FAILED:
            if type(self.failure_receipt) is not FailureReceiptV1:
                raise ContractError("failed binding requires FailureReceiptV1")
        elif type(self.failure_receipt) is not NotApplicableV1:
            raise ContractError(
                "committed and invalidated bindings require NotApplicableV1 failure_receipt"
            )
        if (
            self.transaction_status is TransactionStatusV1.INVALIDATED
            and not self.invalidation_refs
        ):
            raise ContractError("invalidated binding requires invalidation_refs")

    def to_dict(self) -> dict[str, object]:
        return {
            "commit_id": self.commit_id,
            "request_digest": self.request_digest,
            "artifact_admission_ref": self.artifact_admission_ref,
            "projector_ref": self.projector_ref.to_dict(),
            "envelope_digest": self.envelope_digest,
            "idempotency_key": self.idempotency_key,
            "transaction_status": self.transaction_status.value,
            "supersedes_ref": _serialize_supersedes(self.supersedes_ref),
            "invalidation_refs": list(self.invalidation_refs),
            "failure_receipt": self.failure_receipt.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "EvidenceCommitBindingV1":
        value = _wire_dict(
            value,
            {
                "commit_id",
                "request_digest",
                "artifact_admission_ref",
                "projector_ref",
                "envelope_digest",
                "idempotency_key",
                "transaction_status",
                "supersedes_ref",
                "invalidation_refs",
                "failure_receipt",
            },
            "evidence_commit_binding",
        )
        try:
            status = TransactionStatusV1(value["transaction_status"])
        except (TypeError, ValueError) as exc:
            raise ContractError("transaction_status is invalid") from exc
        raw_failure = _wire_mapping(value["failure_receipt"], "failure_receipt")
        failure_receipt: FailureReceiptV1 | NotApplicableV1
        if raw_failure.get("status") == "not_applicable":
            failure_receipt = NotApplicableV1.from_dict(raw_failure)
        else:
            failure_receipt = FailureReceiptV1.from_dict(raw_failure)
        return cls(
            commit_id=value["commit_id"],  # type: ignore[arg-type]
            request_digest=value["request_digest"],  # type: ignore[arg-type]
            artifact_admission_ref=value["artifact_admission_ref"],  # type: ignore[arg-type]
            projector_ref=ContractRefV1.from_dict(
                _wire_mapping(value["projector_ref"], "projector_ref")
            ),
            envelope_digest=value["envelope_digest"],  # type: ignore[arg-type]
            idempotency_key=value["idempotency_key"],  # type: ignore[arg-type]
            transaction_status=status,
            supersedes_ref=_supersedes(value["supersedes_ref"]),
            invalidation_refs=_string_tuple(
                value["invalidation_refs"], "invalidation_refs"
            ),
            failure_receipt=failure_receipt,
        )


def resolve_idempotent_retry(
    existing_binding: EvidenceCommitBindingV1,
    request: EvidenceCommitRequestV1,
) -> EvidenceCommitBindingV1:
    """Return an existing immutable binding only for the exact same request."""

    if type(existing_binding) is not EvidenceCommitBindingV1:
        raise ContractError("existing_binding must be EvidenceCommitBindingV1")
    if type(request) is not EvidenceCommitRequestV1:
        raise ContractError("request must be EvidenceCommitRequestV1")
    if request.idempotency_key != existing_binding.idempotency_key:
        raise EvidencePersistenceContractError(EVIDENCE_IDEMPOTENCY_KEY_MISMATCH)
    if request.request_digest != existing_binding.request_digest:
        raise EvidencePersistenceContractError(EVIDENCE_IDEMPOTENCY_CONFLICT)
    return existing_binding


class EvidencePersistencePortV1(Protocol):
    def commit(self, request: EvidenceCommitRequestV1) -> EvidenceCommitBindingV1: ...

    def load(self, commit_id: str) -> EvidenceCommitBindingV1 | None: ...


__all__ = [
    "EVIDENCE_IDEMPOTENCY_CONFLICT",
    "EVIDENCE_IDEMPOTENCY_KEY_MISMATCH",
    "EvidenceCommitBindingV1",
    "EvidenceCommitRequestV1",
    "EvidencePersistenceContractError",
    "EvidencePersistencePortV1",
    "FailureReceiptV1",
    "resolve_idempotent_retry",
]
