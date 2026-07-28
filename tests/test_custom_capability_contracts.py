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


NOW = datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc)


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
        "authentication": "opaque-authentication",
    }
    value.update(changes)
    return AttestationEnvelope(**value)


def _snapshot() -> AuthorityTrustSnapshot:
    return AuthorityTrustSnapshot(
        snapshot_id="snapshot-a",
        authority_id="authority-a",
        allowed_kinds=frozenset(CLAIM_KINDS),
        allowed_key_ids=frozenset({"key-a"}),
        allowed_auth_schemes=frozenset({"scheme-a"}),
        valid_from=NOW - timedelta(minutes=1),
        valid_until=NOW + timedelta(minutes=10),
    )


def test_envelope_normalizes_aware_times_and_returns_a_copyable_wire_shape() -> None:
    issued_at = NOW.astimezone(timezone(timedelta(hours=-4)))
    envelope = _envelope(issued_at=issued_at, expires_at=issued_at + timedelta(minutes=5))

    assert envelope.issued_at == NOW
    assert envelope.to_dict()["issued_at"] == "2026-07-26T12:00:00.000000Z"
    assert envelope.signing_dict().get("authentication") is None


@pytest.mark.parametrize(
    "changes, message",
    [
        ({"schema_version": "unknown"}, "schema"),
        ({"attestation_kind": "unknown"}, "kind"),
        ({"issued_at": datetime(2026, 7, 26, 12, 0)}, "timezone"),
        ({"expires_at": NOW}, "after"),
        ({"control_sequence": -1}, "non-negative"),
        ({"claims": {"binding": {}, "payload": {}}}, "non-empty"),
    ],
)
def test_envelope_rejects_invalid_contracts(changes, message: str) -> None:
    with pytest.raises(ContractError, match=message):
        _envelope(**changes)


def test_from_dict_rejects_unknown_and_missing_root_fields() -> None:
    value = _envelope().to_dict()
    value["unexpected"] = True
    with pytest.raises(ContractError, match="unknown fields"):
        AttestationEnvelope.from_dict(value)

    round_trip = AttestationEnvelope.from_dict(_envelope().to_dict())
    assert round_trip == _envelope()

    value = _envelope().to_dict()
    del value["authentication"]
    with pytest.raises(ContractError, match="missing fields"):
        AttestationEnvelope.from_dict(value)


def test_claims_are_structurally_bounded_and_deeply_immutable() -> None:
    envelope = _envelope()

    with pytest.raises(TypeError):
        envelope.claims["binding"] = {}  # type: ignore[index]
    with pytest.raises(TypeError):
        envelope.claims["binding"]["attempt_id"] = "changed"  # type: ignore[index]


def test_verification_context_requires_nonempty_expected_bindings() -> None:
    with pytest.raises(ContractError, match="expected_bindings"):
        VerificationContext(trust_snapshot=_snapshot(), expected_bindings={}, now=NOW)
