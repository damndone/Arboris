from datetime import datetime, timedelta, timezone

import pytest

from workbench.custom_capability.contracts import (
    AttestationEnvelope,
    AuthorityTrustSnapshot,
    CLAIM_KINDS,
    ContractError,
    REQUIRED_BINDINGS,
    SCHEMA_VERSION,
    VerificationContext,
)
from workbench.custom_capability.verifier import (
    AttestationVerificationError,
    VerificationCode,
    Verifier,
)


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


class FakeAuthenticator:
    def __init__(self, accepted: bool = True) -> None:
        self.accepted = accepted
        self.calls: list[tuple[bytes, str, str, str, str]] = []

    def verify(self, payload: bytes, authentication: str, *, scheme: str, key_id: str, authority_id: str) -> bool:
        self.calls.append((payload, authentication, scheme, key_id, authority_id))
        return self.accepted and authentication == "accepted"


def _bindings(kind: str) -> dict[str, str]:
    return {
        name: ("a" * 64 if name.endswith("_digest") else f"{name}-value")
        for name in REQUIRED_BINDINGS[kind]
    }


def _envelope(kind: str = "execution_result", **changes) -> AttestationEnvelope:
    value = {
        "schema_version": SCHEMA_VERSION,
        "attestation_kind": kind,
        "authority_id": "authority-a",
        "key_id": "key-a",
        "auth_scheme": "scheme-a",
        "issued_at": NOW,
        "expires_at": NOW + timedelta(minutes=5),
        "nonce": "nonce-a",
        "control_sequence": 10,
        "claims": {"binding": _bindings(kind), "payload": {"opaque": "value"}},
        "authentication": "accepted",
    }
    value.update(changes)
    return AttestationEnvelope(**value)


def _context(envelope: AttestationEnvelope, **changes) -> VerificationContext:
    expected = dict(envelope.claims["binding"])
    value = {
        "trust_snapshot": AuthorityTrustSnapshot(
            snapshot_id="snapshot-a",
            authority_id="authority-a",
            allowed_kinds=frozenset(CLAIM_KINDS),
            allowed_key_ids=frozenset({"key-a"}),
            allowed_auth_schemes=frozenset({"scheme-a"}),
            valid_from=NOW - timedelta(minutes=1),
            valid_until=NOW + timedelta(minutes=10),
        ),
        "expected_bindings": expected,
        "now": NOW,
        "minimum_control_sequence": 10,
        "consumed_nonces": frozenset(),
        "revoked_nonces": frozenset(),
    }
    value.update(changes)
    return VerificationContext(**value)


def test_verifier_accepts_authenticated_and_fully_bound_claims() -> None:
    authenticator = FakeAuthenticator()
    envelope = _envelope()

    verified = Verifier(authenticator).verify(envelope, _context(envelope))

    assert verified.envelope == envelope
    assert len(verified.signing_digest) == 64
    assert authenticator.calls[0][1:] == ("accepted", "scheme-a", "key-a", "authority-a")


def test_verifier_requires_an_authentication_backend() -> None:
    with pytest.raises(AttestationVerificationError) as error:
        Verifier(None)  # type: ignore[arg-type]

    assert error.value.code == VerificationCode.AUTHENTICATION_BACKEND_UNAVAILABLE


def test_verified_claims_cannot_be_constructed_by_a_caller() -> None:
    envelope = _envelope()

    with pytest.raises(ContractError, match="only be created by the verifier"):
        from workbench.custom_capability.contracts import VerifiedClaims

        VerifiedClaims(envelope, "a" * 64)


@pytest.mark.parametrize(
    "envelope_changes, context_changes, code",
    [
        ({"authority_id": "other"}, {}, VerificationCode.AUTHORITY_UNTRUSTED),
        ({"key_id": "other"}, {}, VerificationCode.AUTHORITY_UNTRUSTED),
        ({"auth_scheme": "other"}, {}, VerificationCode.AUTHENTICATION_SCHEME_UNSUPPORTED),
        (
            {"issued_at": NOW - timedelta(minutes=10), "expires_at": NOW - timedelta(minutes=1)},
            {},
            VerificationCode.ATTESTATION_EXPIRED,
        ),
        ({"control_sequence": 9}, {}, VerificationCode.CONTROL_SEQUENCE_MISMATCH),
        ({}, {"consumed_nonces": frozenset({"nonce-a"})}, VerificationCode.REPLAY_REJECTED),
        ({}, {"revoked_nonces": frozenset({"nonce-a"})}, VerificationCode.ATTESTATION_REVOKED),
    ],
)
def test_verifier_rejects_untrusted_or_stale_claims(envelope_changes, context_changes, code) -> None:
    envelope = _envelope(**envelope_changes)
    with pytest.raises(AttestationVerificationError) as error:
        Verifier(FakeAuthenticator()).verify(envelope, _context(envelope, **context_changes))

    assert error.value.code == code


def test_verifier_rejects_authentication_failure() -> None:
    envelope = _envelope()
    with pytest.raises(AttestationVerificationError) as error:
        Verifier(FakeAuthenticator(accepted=False)).verify(envelope, _context(envelope))

    assert error.value.code == VerificationCode.AUTHENTICATION_FAILED


def test_verifier_rejects_binding_mismatch_before_returning_claims() -> None:
    envelope = _envelope()
    context = _context(envelope, expected_bindings={**envelope.claims["binding"], "attempt_id": "different"})

    with pytest.raises(AttestationVerificationError) as error:
        Verifier(FakeAuthenticator()).verify(envelope, context)

    assert error.value.code == VerificationCode.BINDING_MISMATCH


def test_verifier_rejects_an_incomplete_expected_binding_context() -> None:
    envelope = _envelope()
    incomplete = {"attempt_id": envelope.claims["binding"]["attempt_id"]}

    with pytest.raises(AttestationVerificationError) as error:
        Verifier(FakeAuthenticator()).verify(envelope, _context(envelope, expected_bindings=incomplete))

    assert error.value.code == VerificationCode.BINDING_MISMATCH


@pytest.mark.parametrize("kind", sorted(CLAIM_KINDS))
def test_each_claim_kind_requires_its_generic_binding_set(kind: str) -> None:
    envelope = _envelope(kind)
    binding = dict(envelope.claims["binding"])
    binding.pop(next(iter(REQUIRED_BINDINGS[kind])))
    malformed = _envelope(kind, claims={"binding": binding, "payload": {}})

    with pytest.raises(AttestationVerificationError) as error:
        Verifier(FakeAuthenticator()).verify(malformed, _context(envelope))

    assert error.value.code == VerificationCode.BINDING_MISMATCH


def test_verifier_does_not_accept_a_different_output_or_attempt_identity() -> None:
    original = _envelope()
    changed = dict(original.claims["binding"])
    changed["output_bundle_digest"] = "b" * 64
    changed["attempt_id"] = "changed-attempt"
    changed_envelope = _envelope(claims={"binding": changed, "payload": {"opaque": "value"}})

    with pytest.raises(AttestationVerificationError) as error:
        Verifier(FakeAuthenticator()).verify(changed_envelope, _context(original))

    assert error.value.code == VerificationCode.BINDING_MISMATCH
