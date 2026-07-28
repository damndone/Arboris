"""Generic, immutable contracts for the custom-capability trust core.

This module deliberately contains no execution, filesystem, network, or
domain-specific analysis semantics.  Authentication is supplied by a trusted
deployment boundary and is verified by :mod:`verifier`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Mapping


SCHEMA_VERSION = "workbench_attestation_v1"
CLAIM_KINDS = frozenset(
    {
        "invocation_intent",
        "execution_result",
        "containment",
        "evidence",
    }
)

_ROOT_FIELDS = frozenset(
    {
        "schema_version",
        "attestation_kind",
        "authority_id",
        "key_id",
        "auth_scheme",
        "issued_at",
        "expires_at",
        "nonce",
        "control_sequence",
        "claims",
        "authentication",
    }
)
_CLAIMS_FIELDS = frozenset({"binding", "payload"})
_MAX_IDENTIFIER = 256
_MAX_NONCE = 512
_MAX_CLAIM_DEPTH = 16
_MAX_CLAIM_KEYS = 256
_MAX_CLAIM_LIST = 1024
_MAX_CLAIM_STRING = 4096
_VERIFIED_CLAIMS_TOKEN = object()


class ContractError(ValueError):
    """Raised when an attestation contract is malformed."""


def _require_text(value: Any, field: str, *, maximum: int = _MAX_IDENTIFIER) -> str:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise ContractError(f"{field} must be a non-empty bounded string")
    if any(ord(char) < 0x20 for char in value):
        raise ContractError(f"{field} contains a control character")
    return value


def _require_digest(value: Any, field: str) -> str:
    text = _require_text(value, field, maximum=64)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        raise ContractError(f"{field} must be a lowercase SHA-256 digest")
    return text


def _normalize_time(value: Any, field: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ContractError(f"{field} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _validate_claim_value(value: Any, *, depth: int = 0) -> Any:
    if depth > _MAX_CLAIM_DEPTH:
        raise ContractError("claims exceed maximum nesting depth")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > _MAX_CLAIM_STRING:
            raise ContractError("claim string exceeds maximum length")
        return value
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            raise ContractError("claims cannot contain non-finite numbers")
        return value
    if isinstance(value, Mapping):
        if len(value) > _MAX_CLAIM_KEYS:
            raise ContractError("claims exceed maximum object keys")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ContractError("claim object keys must be strings")
            normalized[key] = _validate_claim_value(item, depth=depth + 1)
        return MappingProxyType(normalized)
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_CLAIM_LIST:
            raise ContractError("claims exceed maximum list length")
        return tuple(_validate_claim_value(item, depth=depth + 1) for item in value)
    raise ContractError(f"unsupported claim value type: {type(value).__name__}")


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_plain(item) for item in value]
    return value


def _validate_claims(value: Any) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractError("claims must be an object")
    unknown = set(value) - _CLAIMS_FIELDS
    missing = _CLAIMS_FIELDS - set(value)
    if unknown:
        raise ContractError(f"claims contain unknown fields: {sorted(unknown)}")
    if missing:
        raise ContractError(f"claims are missing fields: {sorted(missing)}")
    binding = value["binding"]
    if not isinstance(binding, Mapping) or not binding:
        raise ContractError("claims.binding must be a non-empty object")
    for key in binding:
        _require_text(key, "binding key")
        item = binding[key]
        if not isinstance(item, (str, bool, int)) or isinstance(item, bool) and key.endswith("_digest"):
            raise ContractError("binding values must be scalar identity values")
        if key.endswith("_digest"):
            _require_digest(item, key)
    payload = value["payload"]
    if not isinstance(payload, Mapping):
        raise ContractError("claims.payload must be an object")
    return _validate_claim_value(value)


@dataclass(frozen=True, slots=True)
class AttestationEnvelope:
    """Authenticated, immutable envelope shared by all B0 claim kinds."""

    schema_version: str
    attestation_kind: str
    authority_id: str
    key_id: str
    auth_scheme: str
    issued_at: datetime
    expires_at: datetime
    nonce: str
    control_sequence: int
    claims: Mapping[str, Any]
    authentication: str

    def __post_init__(self) -> None:
        if self.schema_version != SCHEMA_VERSION:
            raise ContractError("unsupported attestation schema version")
        if self.attestation_kind not in CLAIM_KINDS:
            raise ContractError("unsupported attestation kind")
        _require_text(self.authority_id, "authority_id")
        _require_text(self.key_id, "key_id")
        _require_text(self.auth_scheme, "auth_scheme")
        issued_at = _normalize_time(self.issued_at, "issued_at")
        expires_at = _normalize_time(self.expires_at, "expires_at")
        if expires_at <= issued_at:
            raise ContractError("expires_at must be after issued_at")
        _require_text(self.nonce, "nonce", maximum=_MAX_NONCE)
        if not isinstance(self.control_sequence, int) or isinstance(self.control_sequence, bool) or self.control_sequence < 0:
            raise ContractError("control_sequence must be a non-negative integer")
        _validate_claims(self.claims)
        _require_text(self.authentication, "authentication", maximum=8192)
        object.__setattr__(self, "issued_at", issued_at)
        object.__setattr__(self, "expires_at", expires_at)
        object.__setattr__(self, "claims", _validate_claims(self.claims))

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "AttestationEnvelope":
        if not isinstance(value, Mapping):
            raise ContractError("attestation envelope must be an object")
        unknown = set(value) - _ROOT_FIELDS
        missing = _ROOT_FIELDS - set(value)
        if unknown:
            raise ContractError(f"envelope contains unknown fields: {sorted(unknown)}")
        if missing:
            raise ContractError(f"envelope is missing fields: {sorted(missing)}")
        payload = dict(value)
        for field in ("issued_at", "expires_at"):
            raw_time = payload[field]
            if isinstance(raw_time, str):
                try:
                    payload[field] = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
                except ValueError as error:
                    raise ContractError(f"{field} must be an ISO timestamp") from error
        return cls(**payload)

    def to_dict(self, *, include_authentication: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": self.schema_version,
            "attestation_kind": self.attestation_kind,
            "authority_id": self.authority_id,
            "key_id": self.key_id,
            "auth_scheme": self.auth_scheme,
            "issued_at": self.issued_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "expires_at": self.expires_at.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "nonce": self.nonce,
            "control_sequence": self.control_sequence,
            "claims": _plain(self.claims),
        }
        if include_authentication:
            value["authentication"] = self.authentication
        return value

    def signing_dict(self) -> dict[str, Any]:
        return self.to_dict(include_authentication=False)


@dataclass(frozen=True, slots=True)
class AuthorityTrustSnapshot:
    """Immutable trust roots supplied by a trusted server bootstrap."""

    snapshot_id: str
    authority_id: str
    allowed_kinds: frozenset[str]
    allowed_key_ids: frozenset[str]
    allowed_auth_schemes: frozenset[str]
    valid_from: datetime
    valid_until: datetime

    def __post_init__(self) -> None:
        _require_text(self.snapshot_id, "snapshot_id")
        _require_text(self.authority_id, "authority_id")
        if not self.allowed_kinds or not set(self.allowed_kinds) <= CLAIM_KINDS:
            raise ContractError("allowed_kinds must contain supported claim kinds")
        if not self.allowed_key_ids or any(not isinstance(item, str) or not item for item in self.allowed_key_ids):
            raise ContractError("allowed_key_ids must be non-empty strings")
        if not self.allowed_auth_schemes or any(not isinstance(item, str) or not item for item in self.allowed_auth_schemes):
            raise ContractError("allowed_auth_schemes must be non-empty strings")
        start = _normalize_time(self.valid_from, "valid_from")
        end = _normalize_time(self.valid_until, "valid_until")
        if end <= start:
            raise ContractError("valid_until must be after valid_from")
        object.__setattr__(self, "valid_from", start)
        object.__setattr__(self, "valid_until", end)
        object.__setattr__(self, "allowed_kinds", frozenset(self.allowed_kinds))
        object.__setattr__(self, "allowed_key_ids", frozenset(self.allowed_key_ids))
        object.__setattr__(self, "allowed_auth_schemes", frozenset(self.allowed_auth_schemes))


@dataclass(frozen=True, slots=True)
class VerificationContext:
    """Trusted expected bindings and current mutable validity cursors."""

    trust_snapshot: AuthorityTrustSnapshot
    expected_bindings: Mapping[str, Any]
    now: datetime
    minimum_control_sequence: int = 0
    consumed_nonces: frozenset[str] = frozenset()
    revoked_nonces: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.expected_bindings, Mapping) or not self.expected_bindings:
            raise ContractError("expected_bindings must be a non-empty object")
        normalized = _validate_claim_value(self.expected_bindings)
        for key, item in normalized.items():
            if not isinstance(item, (str, bool, int)) or isinstance(item, bool) and key.endswith("_digest"):
                raise ContractError("expected binding values must be scalar identity values")
            if key.endswith("_digest"):
                _require_digest(item, key)
        object.__setattr__(self, "expected_bindings", normalized)
        object.__setattr__(self, "now", _normalize_time(self.now, "now"))
        if not isinstance(self.minimum_control_sequence, int) or self.minimum_control_sequence < 0:
            raise ContractError("minimum_control_sequence must be non-negative")
        object.__setattr__(self, "consumed_nonces", frozenset(self.consumed_nonces))
        object.__setattr__(self, "revoked_nonces", frozenset(self.revoked_nonces))


@dataclass(frozen=True, slots=True, init=False)
class VerifiedClaims:
    """Claims that passed structural, authenticity, binding, and freshness checks."""

    envelope: AttestationEnvelope
    signing_digest: str

    def __init__(self, envelope: AttestationEnvelope, signing_digest: str, *, _token: object = None) -> None:
        if _token is not _VERIFIED_CLAIMS_TOKEN:
            raise ContractError("verified claims can only be created by the verifier")
        if not isinstance(envelope, AttestationEnvelope):
            raise ContractError("verified claims have invalid fields")
        _require_digest(signing_digest, "signing_digest")
        object.__setattr__(self, "envelope", envelope)
        object.__setattr__(self, "signing_digest", signing_digest)


REQUIRED_BINDINGS: Mapping[str, frozenset[str]] = MappingProxyType(
    {
        "invocation_intent": frozenset(
            {
                "capability_revision",
                "operation_id",
                "input_bundle_digest",
                "policy_digest",
                "backend_subject_id",
                "protocol_digest",
            }
        ),
        "execution_result": frozenset(
            {
                "intent_digest",
                "attempt_id",
                "input_bundle_digest",
                "operation_id",
                "output_bundle_digest",
                "policy_digest",
                "backend_subject_id",
                "protocol_digest",
            }
        ),
        "containment": frozenset(
            {
                "assessment_id",
                "assessment_digest",
                "backend_subject_id",
                "profile_digest",
                "policy_digest",
                "harness_digest",
            }
        ),
        "evidence": frozenset(
            {
                "implementation_revision",
                "validation_protocol_digest",
                "fixture_provenance_digest",
                "assessment_digest",
            }
        ),
    }
)


__all__ = [
    "AttestationEnvelope",
    "AuthorityTrustSnapshot",
    "CLAIM_KINDS",
    "ContractError",
    "REQUIRED_BINDINGS",
    "SCHEMA_VERSION",
    "VerificationContext",
    "VerifiedClaims",
]
