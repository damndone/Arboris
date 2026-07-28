"""Fail-closed verification of generic custom-capability attestations."""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from .canonical import canonical_json_bytes, domain_digest
from .contracts import (
    AttestationEnvelope,
    VerificationContext,
    VerifiedClaims,
    REQUIRED_BINDINGS,
    SCHEMA_VERSION,
    _VERIFIED_CLAIMS_TOKEN,
)


class VerificationCode(str, Enum):
    ATTESTATION_INVALID = "CUSTOM_CAPABILITY_ATTESTATION_INVALID"
    ATTESTATION_KIND_UNSUPPORTED = "CUSTOM_CAPABILITY_ATTESTATION_KIND_UNSUPPORTED"
    AUTHORITY_UNTRUSTED = "CUSTOM_CAPABILITY_AUTHORITY_UNTRUSTED"
    AUTHENTICATION_BACKEND_UNAVAILABLE = "CUSTOM_CAPABILITY_AUTHENTICATION_BACKEND_UNAVAILABLE"
    AUTHENTICATION_SCHEME_UNSUPPORTED = "CUSTOM_CAPABILITY_AUTHENTICATION_SCHEME_UNSUPPORTED"
    AUTHENTICATION_FAILED = "CUSTOM_CAPABILITY_AUTHENTICATION_FAILED"
    ATTESTATION_EXPIRED = "CUSTOM_CAPABILITY_ATTESTATION_EXPIRED"
    ATTESTATION_REVOKED = "CUSTOM_CAPABILITY_ATTESTATION_REVOKED"
    ATTESTATION_STALE = "CUSTOM_CAPABILITY_ATTESTATION_STALE"
    REPLAY_REJECTED = "CUSTOM_CAPABILITY_REPLAY_REJECTED"
    CONTROL_SEQUENCE_MISMATCH = "CUSTOM_CAPABILITY_CONTROL_SEQUENCE_MISMATCH"
    BINDING_MISMATCH = "CUSTOM_CAPABILITY_BINDING_MISMATCH"


class AuthenticationVerifier(Protocol):
    def verify(
        self,
        payload: bytes,
        authentication: str,
        *,
        scheme: str,
        key_id: str,
        authority_id: str,
    ) -> bool:
        """Return whether an authority authentication is valid."""


class AttestationVerificationError(ValueError):
    """Stable, typed failure from the B0 verifier."""

    def __init__(self, code: VerificationCode, message: str) -> None:
        super().__init__(message)
        self.code = code


class Verifier:
    """Verify claims without minting, executing, or persisting anything."""

    def __init__(self, authenticator: AuthenticationVerifier) -> None:
        if authenticator is None or not callable(getattr(authenticator, "verify", None)):
            raise AttestationVerificationError(
                VerificationCode.AUTHENTICATION_BACKEND_UNAVAILABLE,
                "a trusted authentication backend is required",
            )
        self._authenticator = authenticator

    def verify(self, envelope: AttestationEnvelope, context: VerificationContext) -> VerifiedClaims:
        if not isinstance(envelope, AttestationEnvelope):
            raise AttestationVerificationError(
                VerificationCode.ATTESTATION_INVALID,
                "envelope has the wrong type",
            )
        if not isinstance(context, VerificationContext):
            raise AttestationVerificationError(
                VerificationCode.ATTESTATION_INVALID,
                "verification context has the wrong type",
            )
        if envelope.schema_version != SCHEMA_VERSION:
            raise AttestationVerificationError(
                VerificationCode.ATTESTATION_INVALID,
                "unsupported attestation schema",
            )

        snapshot = context.trust_snapshot
        if envelope.authority_id != snapshot.authority_id or envelope.key_id not in snapshot.allowed_key_ids:
            raise AttestationVerificationError(
                VerificationCode.AUTHORITY_UNTRUSTED,
                "authority or key is not in the trust snapshot",
            )
        if envelope.attestation_kind not in snapshot.allowed_kinds:
            raise AttestationVerificationError(
                VerificationCode.ATTESTATION_KIND_UNSUPPORTED,
                "attestation kind is outside authority scope",
            )
        if envelope.auth_scheme not in snapshot.allowed_auth_schemes:
            raise AttestationVerificationError(
                VerificationCode.AUTHENTICATION_SCHEME_UNSUPPORTED,
                "authentication scheme is not allowed",
            )

        try:
            signing_bytes = canonical_json_bytes(envelope.signing_dict())
        except ValueError as error:
            raise AttestationVerificationError(
                VerificationCode.ATTESTATION_INVALID,
                "attestation cannot be canonically encoded",
            ) from error
        try:
            authenticated = self._authenticator.verify(
                signing_bytes,
                envelope.authentication,
                scheme=envelope.auth_scheme,
                key_id=envelope.key_id,
                authority_id=envelope.authority_id,
            )
        except Exception as error:
            raise AttestationVerificationError(
                VerificationCode.AUTHENTICATION_FAILED,
                "authentication backend rejected the envelope",
            ) from error
        if not authenticated:
            raise AttestationVerificationError(
                VerificationCode.AUTHENTICATION_FAILED,
                "authentication backend rejected the envelope",
            )

        now = context.now
        if now < snapshot.valid_from or now >= snapshot.valid_until:
            raise AttestationVerificationError(
                VerificationCode.ATTESTATION_STALE,
                "trust snapshot is not valid at verification time",
            )
        if envelope.issued_at > now or envelope.expires_at <= now:
            raise AttestationVerificationError(
                VerificationCode.ATTESTATION_EXPIRED,
                "attestation is outside its validity interval",
            )
        if envelope.issued_at < snapshot.valid_from or envelope.expires_at > snapshot.valid_until:
            raise AttestationVerificationError(
                VerificationCode.ATTESTATION_STALE,
                "attestation exceeds the trust snapshot interval",
            )
        if envelope.control_sequence < context.minimum_control_sequence:
            raise AttestationVerificationError(
                VerificationCode.CONTROL_SEQUENCE_MISMATCH,
                "attestation control sequence is stale",
            )

        required = REQUIRED_BINDINGS[envelope.attestation_kind]
        if not required <= set(context.expected_bindings):
            raise AttestationVerificationError(
                VerificationCode.BINDING_MISMATCH,
                "verification context omits required generic bindings",
            )
        binding = envelope.claims["binding"]
        if not required <= set(binding):
            raise AttestationVerificationError(
                VerificationCode.BINDING_MISMATCH,
                "attestation is missing required generic bindings",
            )
        for key, expected in context.expected_bindings.items():
            if key not in binding or binding[key] != expected:
                raise AttestationVerificationError(
                    VerificationCode.BINDING_MISMATCH,
                    f"attestation binding mismatch for {key}",
                )

        if envelope.nonce in context.revoked_nonces:
            raise AttestationVerificationError(
                VerificationCode.ATTESTATION_REVOKED,
                "attestation nonce is revoked",
            )
        if envelope.nonce in context.consumed_nonces:
            raise AttestationVerificationError(
                VerificationCode.REPLAY_REJECTED,
                "attestation nonce has already been consumed",
            )

        return VerifiedClaims(
            envelope=envelope,
            signing_digest=domain_digest("workbench-attestation-signing-v1", envelope.signing_dict()),
            _token=_VERIFIED_CLAIMS_TOKEN,
        )


__all__ = [
    "AttestationVerificationError",
    "AuthenticationVerifier",
    "VerificationCode",
    "Verifier",
]
