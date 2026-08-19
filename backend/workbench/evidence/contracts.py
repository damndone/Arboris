"""Package-local strict evidence contracts.

The versioned public envelope lives in ``workbench.contracts.evidence``.  This
module is deliberately a small facade around that locked contract plus the
identity/binding records needed by the local evidence kernel.  It does not
define a second envelope grammar and it never turns absent fields into facts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from workbench.canonical import CanonicalJSONError, canonical_json_v1, sha256_canonical
from workbench.contracts.common.envelope import ContractError
from workbench.contracts.common.contract_ref import ContractRefV1
from workbench.contracts.evidence.envelope import (
    EvidenceEnvelopeV1 as LockedEvidenceEnvelopeV1,
    NotApplicableV1,
)


EVIDENCE_CORE_CONTRACT = "evidence-core"
EVIDENCE_CORE_VERSION = "1.0"
EVIDENCE_ENVELOPE_CONTRACT_DIGEST = (
    "a3aa7ac15779077042ef3f0e15ada0df6e1aefc555723c1617f5876d98a22835"
)
EVIDENCE_PERSISTENCE_CONTRACT_DIGEST = (
    "44105bfc2fdada97a92c136bf29e4e2762e4098bbc5207fa47eb27509d0023f2"
)

_SHA256 = re.compile(r"[0-9a-f]{64}")
_FORBIDDEN_REF_PARTS = frozenset({".", ".."})
_OPAQUE_REF = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9:_-]*[A-Za-z0-9])?")
_PROVENANCE_PATH_KEYS = frozenset(
    {"path", "original_path", "source_path", "file", "filename", "uri", "url", "location"}
)


class EvidenceCoreContractError(ContractError):
    """A package-local evidence contract failure with a stable code."""

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _error(code: str, message: str) -> EvidenceCoreContractError:
    return EvidenceCoreContractError(code, message)


def _text(value: object, name: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or "\x00" in value
        or any(ord(char) < 0x20 for char in value)
    ):
        raise _error("EVIDENCE_TEXT_INVALID", f"{name} must be a non-empty text identity")
    return value


def _opaque_ref(value: object, name: str) -> str:
    value = _text(value, name)
    if _OPAQUE_REF.fullmatch(value) is None:
        raise _error("EVIDENCE_REFERENCE_INVALID", f"{name} must be an opaque reference")
    return value


def _digest(value: object, name: str) -> str:
    if type(value) is not str or _SHA256.fullmatch(value) is None:
        raise _error("EVIDENCE_DIGEST_INVALID", f"{name} must be a lowercase SHA-256 digest")
    return value


def _strict_mapping(value: object, name: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise _error("EVIDENCE_WIRE_INVALID", f"{name} must be a built-in JSON object")
    return value


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _error("EVIDENCE_JSON_DUPLICATE_KEY", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_canonical_json(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes:
        raise _error("EVIDENCE_BYTES_INVALID", "evidence bytes must be bytes")
    try:
        parsed = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except EvidenceCoreContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise _error("EVIDENCE_JSON_INVALID", "evidence bytes are not valid JSON") from exc
    if type(parsed) is not dict:
        raise _error("EVIDENCE_WIRE_INVALID", "evidence root must be a JSON object")
    try:
        expected = canonical_json_v1(parsed).encode("utf-8")
    except (CanonicalJSONError, ValueError, OverflowError, RecursionError) as exc:
        raise _error("EVIDENCE_CANONICAL_INVALID", "evidence JSON is not canonical") from exc
    if raw != expected:
        raise _error("EVIDENCE_CANONICAL_INVALID", "evidence bytes are not canonical JSON v1")
    return parsed


def _restore_locked_float_fields(value: dict[str, object]) -> dict[str, object]:
    """Restore C0's typed-float slots after canonical JSON numeric folding.

    Canonical JSON v1 intentionally renders ``98.0`` as ``98``.  The locked
    decoder nevertheless distinguishes float-only fields from integer-capable
    fields, so decoding canonical bytes needs this schema-local re-typing step
    before delegating to C0.  It changes no wire bytes or numeric value.
    """

    facts = value.get("numeric_facts")
    if type(facts) is not list:
        return value
    for fact in facts:
        if type(fact) is not dict:
            continue
        for field in ("standard_error", "confidence_level"):
            if type(fact.get(field)) is int:
                fact[field] = float(fact[field])
        interval = fact.get("confidence_interval")
        if type(interval) is dict:
            for field in ("lower", "upper"):
                if type(interval.get(field)) is int:
                    interval[field] = float(interval[field])
        distribution = fact.get("reference_distribution")
        if type(distribution) is dict and type(distribution.get("degrees_of_freedom")) is int:
            distribution["degrees_of_freedom"] = float(distribution["degrees_of_freedom"])
        checks = fact.get("oracle_checks")
        if type(checks) is list:
            for check in checks:
                if type(check) is dict and type(check.get("observed_difference")) is int:
                    check["observed_difference"] = float(check["observed_difference"])
    return value


def _provenance_error(name: str, message: str) -> EvidenceCoreContractError:
    return _error("EVIDENCE_PROVENANCE_INVALID", f"{name}: {message}")


def _reject_path_like_text(value: object, name: str) -> str:
    if type(value) is not str:
        raise _provenance_error(name, "provenance value must be text")
    try:
        value = _text(value, name)
    except EvidenceCoreContractError as exc:
        raise _provenance_error(name, "provenance value is invalid") from exc
    if (
        "/" in value
        or "\\" in value
        or "://" in value
        or value.startswith(("/", "~"))
        or any(part in _FORBIDDEN_REF_PARTS for part in value.split("/"))
    ):
        raise _provenance_error(name, "raw path-like provenance is not allowed")
    return value


def _validate_contract_ref(value: object, name: str) -> ContractRefV1:
    if type(value) is not ContractRefV1:
        raise _provenance_error(name, "structured reference must be ContractRefV1")
    try:
        _opaque_ref(value.kind, f"{name}.kind")
        _opaque_ref(value.logical_id, f"{name}.logical_id")
    except EvidenceCoreContractError as exc:
        raise _provenance_error(name, "structured reference is not closed and opaque") from exc
    return value


def _validate_provenance_reference(value: object, name: str) -> None:
    if type(value) is str:
        try:
            _opaque_ref(value, name)
        except EvidenceCoreContractError as exc:
            raise _provenance_error(name, "reference is not closed and opaque") from exc
        return
    if type(value) is dict:
        if set(value) == {"status", "reason"}:
            try:
                NotApplicableV1.from_dict(value)
            except (ContractError, TypeError, ValueError) as exc:
                raise _provenance_error(name, "not-applicable reference is invalid") from exc
            return
        try:
            contract_ref = ContractRefV1.from_dict(value)
        except (TypeError, ValueError) as exc:
            raise _provenance_error(name, "structured reference fields are not exact") from exc
        _validate_contract_ref(contract_ref, name)
        return
    raise _provenance_error(name, "reference must be opaque text or a closed structured reference")


def _validate_provenance_tree(value: object, name: str, *, strict_strings: bool = False) -> None:
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise _provenance_error(name, "provenance keys must be text")
            lowered = key.lower()
            child_name = f"{name}.{key}"
            if lowered in _PROVENANCE_PATH_KEYS or lowered.endswith("_path"):
                raise _provenance_error(child_name, "raw path-like provenance is not allowed")
            if lowered == "selector":
                _reject_path_like_text(item, child_name)
            elif (
                lowered.endswith("_ref")
                or lowered in {"ref", "artifact_ref", "reference"}
                or lowered.endswith("_reference")
            ):
                _validate_provenance_reference(item, child_name)
            elif lowered.endswith("_refs") or lowered in {"refs", "references"}:
                if type(item) is not list:
                    raise _provenance_error(child_name, "references must be an array")
                for index, ref in enumerate(item):
                    try:
                        _opaque_ref(ref, f"{child_name}[{index}]")
                    except EvidenceCoreContractError as exc:
                        raise _provenance_error(child_name, "reference is not closed and opaque") from exc
            elif lowered in {"artifact_digest", "content_hash", "envelope_digest"}:
                try:
                    _digest(item, child_name)
                except EvidenceCoreContractError as exc:
                    raise _provenance_error(child_name, "digest is invalid") from exc
            elif strict_strings and type(item) is str:
                _reject_path_like_text(item, child_name)
            _validate_provenance_tree(item, child_name, strict_strings=strict_strings or lowered in {
                "input_provenance",
                "dependencies",
                "source_selector",
            })
        return
    if type(value) is list:
        for index, item in enumerate(value):
            _validate_provenance_tree(item, f"{name}[{index}]", strict_strings=strict_strings)
        return
    if strict_strings and type(value) is str:
        _reject_path_like_text(value, name)


def _validate_envelope_provenance(envelope: "EvidenceEnvelopeFacadeV1") -> None:
    payload = envelope.to_dict()
    input_provenance = payload.get("input_provenance")
    if type(input_provenance) is not dict or set(input_provenance) != {"artifact_ref", "artifact_digest"}:
        raise _provenance_error("input_provenance", "fields are not the closed persistence schema")
    try:
        _opaque_ref(input_provenance["artifact_ref"], "input_provenance.artifact_ref")
        _digest(input_provenance["artifact_digest"], "input_provenance.artifact_digest")
    except EvidenceCoreContractError as exc:
        raise _provenance_error("input_provenance", "artifact reference or digest is invalid") from exc
    _validate_provenance_tree(payload, "envelope")


@dataclass(frozen=True)
class EvidenceEnvelopeFacadeV1:
    """Strict, immutable facade over the C0 ``EvidenceEnvelopeV1``."""

    envelope: LockedEvidenceEnvelopeV1

    def __post_init__(self) -> None:
        if type(self.envelope) is not LockedEvidenceEnvelopeV1:
            raise _error("EVIDENCE_ENVELOPE_TYPE_INVALID", "envelope must be the locked EvidenceEnvelopeV1")

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "EvidenceEnvelopeFacadeV1":
        if type(value) is not dict:
            raise _error("EVIDENCE_WIRE_INVALID", "evidence envelope must be a built-in dict")
        try:
            envelope = LockedEvidenceEnvelopeV1.from_dict(value)
        except (ContractError, TypeError, KeyError, ValueError) as exc:
            if isinstance(exc, EvidenceCoreContractError):
                raise
            raise _error("EVIDENCE_ENVELOPE_INVALID", str(exc)) from exc
        return cls(envelope)

    @classmethod
    def from_bytes(cls, raw: bytes) -> "EvidenceEnvelopeFacadeV1":
        return cls.from_dict(_restore_locked_float_fields(_parse_canonical_json(raw)))

    @classmethod
    def from_json_bytes(cls, raw: bytes) -> "EvidenceEnvelopeFacadeV1":
        return cls.from_bytes(raw)

    def to_dict(self) -> dict[str, object]:
        return self.envelope.to_dict()

    def canonical_bytes(self) -> bytes:
        return canonical_json_v1(self.to_dict()).encode("utf-8")

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.canonical_bytes()).hexdigest()

    @property
    def result_identity(self) -> Mapping[str, Any]:
        return self.envelope.result_identity

    @property
    def family_evidence(self) -> Mapping[str, Any]:
        return self.envelope.family_evidence

    @property
    def execution_status(self) -> str:
        return self.envelope.execution_status.value

    @property
    def availability(self) -> str:
        return self.envelope.availability.value

    @property
    def completeness_status(self) -> str:
        return self.envelope.completeness_status.value

    @property
    def numeric_facts(self) -> tuple[Any, ...]:
        return self.envelope.numeric_facts

    @property
    def validation_summary(self) -> Any:
        return self.envelope.validation_summary


@dataclass(frozen=True)
class EvidenceBindingV1:
    """Provenance required before an envelope can enter the local registry."""

    source_ref: str
    validator_ref: str | ContractRefV1
    execution_ref: str
    contract_digest: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_ref", _opaque_ref(self.source_ref, "source_ref"))
        if type(self.validator_ref) is str:
            object.__setattr__(self, "validator_ref", _opaque_ref(self.validator_ref, "validator_ref"))
        elif type(self.validator_ref) is ContractRefV1:
            try:
                _validate_contract_ref(self.validator_ref, "validator_ref")
            except EvidenceCoreContractError as exc:
                raise _error("EVIDENCE_VALIDATOR_INVALID", "validator_ref contains path-like provenance") from exc
        else:
            raise _error("EVIDENCE_VALIDATOR_INVALID", "validator_ref must be an opaque ref or ContractRefV1")
        object.__setattr__(self, "execution_ref", _opaque_ref(self.execution_ref, "execution_ref"))
        object.__setattr__(self, "contract_digest", _digest(self.contract_digest, "contract_digest"))

    @property
    def validator_identity(self) -> str:
        if type(self.validator_ref) is ContractRefV1:
            return f"{self.validator_ref.kind}:{self.validator_ref.logical_id}:{self.validator_ref.semantic_version}"
        return self.validator_ref

    def to_dict(self) -> dict[str, object]:
        return {
            "source_ref": self.source_ref,
            "validator_ref": self.validator_ref.to_dict()
            if type(self.validator_ref) is ContractRefV1
            else self.validator_ref,
            "execution_ref": self.execution_ref,
            "contract_digest": self.contract_digest,
        }


def _artifact_hash_payload(
    *,
    artifact_id: str,
    artifact_type: str,
    scope_ref: str,
    source_ref: str,
    validator_ref: str | ContractRefV1,
    execution_ref: str,
    contract_digest: str,
    envelope: EvidenceEnvelopeFacadeV1,
) -> dict[str, object]:
    return {
        "artifact_id": artifact_id,
        "artifact_type": artifact_type,
        "scope_ref": scope_ref,
        "source_ref": source_ref,
        "validator_ref": validator_ref.to_dict()
        if type(validator_ref) is ContractRefV1
        else validator_ref,
        "execution_ref": execution_ref,
        "contract_digest": contract_digest,
        "envelope": envelope.to_dict(),
    }


def artifact_content_hash(
    *,
    artifact_id: str,
    artifact_type: str,
    scope_ref: str,
    source_ref: str,
    validator_ref: str | ContractRefV1,
    execution_ref: str,
    contract_digest: str,
    envelope: EvidenceEnvelopeFacadeV1,
) -> str:
    """Hash the complete artifact identity, bindings, and canonical envelope."""

    return sha256_canonical(
        _artifact_hash_payload(
            artifact_id=artifact_id,
            artifact_type=artifact_type,
            scope_ref=scope_ref,
            source_ref=source_ref,
            validator_ref=validator_ref,
            execution_ref=execution_ref,
            contract_digest=contract_digest,
            envelope=envelope,
        )
    )


@dataclass(frozen=True)
class ArtifactAdmissionV1:
    """An immutable, already-validated evidence artifact admission."""

    artifact_id: str
    artifact_type: str
    scope_ref: str
    content_hash: str
    source_ref: str
    validator_ref: str | ContractRefV1
    execution_ref: str
    contract_digest: str
    envelope: EvidenceEnvelopeFacadeV1

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_id", _opaque_ref(self.artifact_id, "artifact_id"))
        object.__setattr__(self, "artifact_type", _text(self.artifact_type, "artifact_type"))
        object.__setattr__(self, "scope_ref", _opaque_ref(self.scope_ref, "scope_ref"))
        object.__setattr__(self, "content_hash", _digest(self.content_hash, "content_hash"))
        binding = EvidenceBindingV1(
            source_ref=self.source_ref,
            validator_ref=self.validator_ref,
            execution_ref=self.execution_ref,
            contract_digest=self.contract_digest,
        )
        object.__setattr__(self, "source_ref", binding.source_ref)
        object.__setattr__(self, "validator_ref", binding.validator_ref)
        object.__setattr__(self, "execution_ref", binding.execution_ref)
        object.__setattr__(self, "contract_digest", binding.contract_digest)
        if type(self.envelope) is not EvidenceEnvelopeFacadeV1:
            raise _error("EVIDENCE_ENVELOPE_TYPE_INVALID", "admission envelope must use the strict facade")
        _validate_envelope_provenance(self.envelope)
        expected_hash = artifact_content_hash(
            artifact_id=self.artifact_id,
            artifact_type=self.artifact_type,
            scope_ref=self.scope_ref,
            source_ref=self.source_ref,
            validator_ref=self.validator_ref,
            execution_ref=self.execution_ref,
            contract_digest=self.contract_digest,
            envelope=self.envelope,
        )
        if self.content_hash != expected_hash:
            raise _error("EVIDENCE_ARTIFACT_HASH_MISMATCH", "artifact content hash does not match complete artifact metadata")
        object.__setattr__(self, "envelope", EvidenceEnvelopeFacadeV1.from_bytes(self.envelope.canonical_bytes()))

    @property
    def family_evidence(self) -> Mapping[str, Any]:
        return self.envelope.family_evidence

    @property
    def binding(self) -> EvidenceBindingV1:
        return EvidenceBindingV1(
            source_ref=self.source_ref,
            validator_ref=self.validator_ref,
            execution_ref=self.execution_ref,
            contract_digest=self.contract_digest,
        )

    @property
    def envelope_digest(self) -> str:
        return self.envelope.content_hash

    def to_dict(self) -> dict[str, object]:
        return {
            "artifact_id": self.artifact_id,
            "artifact_type": self.artifact_type,
            "scope_ref": self.scope_ref,
            "content_hash": self.content_hash,
            "source_ref": self.source_ref,
            "validator_ref": self.validator_ref.to_dict()
            if type(self.validator_ref) is ContractRefV1
            else self.validator_ref,
            "execution_ref": self.execution_ref,
            "contract_digest": self.contract_digest,
            "envelope": self.envelope.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: dict[str, object]) -> "ArtifactAdmissionV1":
        required = {
            "artifact_id",
            "artifact_type",
            "scope_ref",
            "content_hash",
            "source_ref",
            "validator_ref",
            "execution_ref",
            "contract_digest",
            "envelope",
        }
        if type(value) is not dict or set(value) != required:
            raise _error("EVIDENCE_ADMISSION_WIRE_INVALID", "artifact admission fields are not exact")
        validator: str | ContractRefV1
        if type(value["validator_ref"]) is str:
            validator = value["validator_ref"]
        elif type(value["validator_ref"]) is dict:
            try:
                validator = ContractRefV1.from_dict(value["validator_ref"])
            except (TypeError, ValueError) as exc:
                raise _error("EVIDENCE_VALIDATOR_INVALID", "validator_ref is invalid") from exc
        else:
            raise _error("EVIDENCE_VALIDATOR_INVALID", "validator_ref is invalid")
        try:
            envelope = EvidenceEnvelopeFacadeV1.from_bytes(
                canonical_json_v1(value["envelope"]).encode("utf-8")  # type: ignore[arg-type]
            )
        except (EvidenceCoreContractError, TypeError, ValueError) as exc:
            raise _error("EVIDENCE_ENVELOPE_INVALID", "artifact admission envelope is invalid") from exc
        return cls(
            artifact_id=value["artifact_id"],  # type: ignore[arg-type]
            artifact_type=value["artifact_type"],  # type: ignore[arg-type]
            scope_ref=value["scope_ref"],  # type: ignore[arg-type]
            content_hash=value["content_hash"],  # type: ignore[arg-type]
            source_ref=value["source_ref"],  # type: ignore[arg-type]
            validator_ref=validator,
            execution_ref=value["execution_ref"],  # type: ignore[arg-type]
            contract_digest=value["contract_digest"],  # type: ignore[arg-type]
            envelope=envelope,
        )


@dataclass(frozen=True)
class EvidenceFailureReceiptV1:
    """A non-success result that never contains guessed evidence."""

    code: str
    message: str
    artifact_id: str | None = None
    scope_ref: str | None = None
    retryable: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "code", _text(self.code, "code"))
        object.__setattr__(self, "message", _text(self.message, "message"))
        if self.artifact_id is not None:
            object.__setattr__(self, "artifact_id", _opaque_ref(self.artifact_id, "artifact_id"))
        if self.scope_ref is not None:
            object.__setattr__(self, "scope_ref", _opaque_ref(self.scope_ref, "scope_ref"))
        if type(self.retryable) is not bool:
            raise _error("EVIDENCE_FAILURE_RECEIPT_INVALID", "retryable must be a boolean")

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": self.message,
            "artifact_id": self.artifact_id,
            "scope_ref": self.scope_ref,
            "retryable": self.retryable,
        }


def canonical_envelope_bytes(value: EvidenceEnvelopeFacadeV1 | LockedEvidenceEnvelopeV1) -> bytes:
    """Return canonical bytes without permitting a consumer-side re-encoding."""

    if type(value) is EvidenceEnvelopeFacadeV1:
        return value.canonical_bytes()
    if type(value) is LockedEvidenceEnvelopeV1:
        return canonical_json_v1(value.to_dict()).encode("utf-8")
    raise _error("EVIDENCE_ENVELOPE_TYPE_INVALID", "value is not a locked evidence envelope")


def envelope_content_hash(value: EvidenceEnvelopeFacadeV1 | LockedEvidenceEnvelopeV1) -> str:
    return hashlib.sha256(canonical_envelope_bytes(value)).hexdigest()


# Public compatibility names intentionally point at the one locked grammar.
EvidenceEnvelopeV1 = LockedEvidenceEnvelopeV1
StrictEvidenceEnvelopeV1 = EvidenceEnvelopeFacadeV1
ArtifactRecordV1 = ArtifactAdmissionV1


__all__ = [
    "ArtifactAdmissionV1",
    "ArtifactRecordV1",
    "EVIDENCE_CORE_CONTRACT",
    "EVIDENCE_CORE_VERSION",
    "EVIDENCE_ENVELOPE_CONTRACT_DIGEST",
    "EVIDENCE_PERSISTENCE_CONTRACT_DIGEST",
    "EvidenceBindingV1",
    "EvidenceCoreContractError",
    "EvidenceEnvelopeFacadeV1",
    "EvidenceEnvelopeV1",
    "EvidenceFailureReceiptV1",
    "StrictEvidenceEnvelopeV1",
    "artifact_content_hash",
    "canonical_envelope_bytes",
    "envelope_content_hash",
]
