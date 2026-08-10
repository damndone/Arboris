from __future__ import annotations

from dataclasses import replace
import hashlib

import pytest


def _sign(secret: str, *, key_id: str, payload: bytes) -> str:
    return hashlib.sha256(
        secret.encode("utf-8") + b":" + key_id.encode("utf-8") + b":" + payload
    ).hexdigest()


class _TestWitnessVerifier:
    def __init__(self, secret: str = "test-only-secret") -> None:
        self.secret = secret

    def verify(self, *, key_id: str, payload: bytes, signature: str) -> bool:
        return signature == _sign(self.secret, key_id=key_id, payload=payload)


def _challenge():
    from workbench.qa.witness import WitnessChallenge

    return WitnessChallenge.create(
        manifest_digest="a" * 64,
        submission_id="submission:acceptance",
        attempt_no=1,
        operation_ids_digest="b" * 64,
        notebook_id="nb_acceptance",
        option_id="opt_acceptance",
        option_revision=1,
        attempt_started_at=100.0,
        issued_at=100.0,
        expires_at=200.0,
    )


def _signed_attestation(challenge, *, durable_chain_sha256: str):
    from workbench.qa.witness import BrowserWitnessAttestation

    unsigned = BrowserWitnessAttestation.create(
        challenge=challenge,
        browser_session_id="browser_session_acceptance",
        confirmation_recorded_at="1970-01-01T00:01:40.200000+00:00",
        observed_url="http://127.0.0.1:5189/notebook?project_root=%2Ftmp%2Fproject",
        confirmation_control_name="Confirm workflow",
        dom_snapshot_sha256="c" * 64,
        durable_chain_sha256=durable_chain_sha256,
        key_id="qa-witness-test-key",
        signature="placeholder",
    )
    return BrowserWitnessAttestation.create(
        challenge=challenge,
        browser_session_id=unsigned.browser_session_id,
        confirmation_recorded_at=unsigned.confirmation_recorded_at,
        observed_url=unsigned.observed_url,
        confirmation_control_name=unsigned.confirmation_control_name,
        dom_snapshot_sha256=unsigned.dom_snapshot_sha256,
        durable_chain_sha256=unsigned.durable_chain_sha256,
        key_id=unsigned.key_id,
        signature=_sign(
            "test-only-secret",
            key_id=unsigned.key_id,
            payload=unsigned.signing_payload(),
        ),
    )


def _attestation(challenge):
    return _signed_attestation(challenge, durable_chain_sha256="d" * 64)


def _invalid_signature(value):
    from workbench.qa.witness import BrowserWitnessAttestation

    return BrowserWitnessAttestation.create(
        challenge=_challenge(),
        browser_session_id=value.browser_session_id,
        confirmation_recorded_at=value.confirmation_recorded_at,
        observed_url=value.observed_url,
        confirmation_control_name=value.confirmation_control_name,
        dom_snapshot_sha256=value.dom_snapshot_sha256,
        durable_chain_sha256=value.durable_chain_sha256,
        key_id=value.key_id,
        signature="0" * 64,
    )


def test_witness_attestation_binds_the_frozen_submission_and_result_chain() -> None:
    from workbench.qa.witness import verify_witness_attestation

    challenge = _challenge()
    attestation = _attestation(challenge)

    result = verify_witness_attestation(
        challenge,
        attestation,
        verifier=_TestWitnessVerifier(),
        now=150.0,
        expected_durable_chain_sha256="d" * 64,
    )

    assert result.trust_level == "witness_attested"
    assert result.attestation_digest == attestation.attestation_digest
    assert result.human_identity_verified is False


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: replace(value, observed_url="http://evil.invalid"),
        lambda value: replace(value, durable_chain_sha256="e" * 64),
        _invalid_signature,
    ],
)
def test_witness_attestation_rejects_behaviorally_changed_payloads(mutation) -> None:
    from workbench.qa.witness import WitnessVerificationError, verify_witness_attestation

    challenge = _challenge()
    mutated = mutation(_attestation(challenge))

    with pytest.raises(WitnessVerificationError):
        verify_witness_attestation(
            challenge,
            mutated,
            verifier=_TestWitnessVerifier(),
            now=150.0,
            expected_durable_chain_sha256="d" * 64,
        )


def test_witness_attestation_rejects_a_validly_signed_wrong_result_chain() -> None:
    """The durable-chain binding rejects a provider-signed result from another run."""

    from workbench.qa.witness import WitnessVerificationError, verify_witness_attestation

    challenge = _challenge()
    wrong_chain = _signed_attestation(challenge, durable_chain_sha256="e" * 64)

    with pytest.raises(WitnessVerificationError, match="durable result chain"):
        verify_witness_attestation(
            challenge,
            wrong_chain,
            verifier=_TestWitnessVerifier(),
            now=150.0,
            expected_durable_chain_sha256="d" * 64,
        )


def test_witness_attestation_rejects_wrong_challenge_and_expiry() -> None:
    from workbench.qa.witness import WitnessVerificationError, verify_witness_attestation

    challenge = _challenge()
    attestation = _attestation(challenge)
    from workbench.qa.witness import WitnessChallenge

    wrong_challenge = WitnessChallenge.create(
        manifest_digest=challenge.manifest_digest,
        submission_id="submission:other",
        attempt_no=challenge.attempt_no,
        operation_ids_digest=challenge.operation_ids_digest,
        notebook_id=challenge.notebook_id,
        option_id=challenge.option_id,
        option_revision=challenge.option_revision,
        attempt_started_at=challenge.attempt_started_at,
        issued_at=challenge.issued_at,
        expires_at=challenge.expires_at,
    )

    with pytest.raises(WitnessVerificationError, match="challenge"):
        verify_witness_attestation(
            wrong_challenge,
            attestation,
            verifier=_TestWitnessVerifier(),
            now=150.0,
            expected_durable_chain_sha256="d" * 64,
        )
    with pytest.raises(WitnessVerificationError, match="expired"):
        verify_witness_attestation(
            challenge,
            attestation,
            verifier=_TestWitnessVerifier(),
            now=201.0,
            expected_durable_chain_sha256="d" * 64,
        )
    with pytest.raises(WitnessVerificationError, match="expired"):
        verify_witness_attestation(
            challenge,
            attestation,
            verifier=_TestWitnessVerifier(),
            now=200.0,
            expected_durable_chain_sha256="d" * 64,
        )


def test_missing_witness_verifier_fails_closed() -> None:
    from workbench.qa.witness import WitnessUnavailable, verify_witness_attestation

    challenge = _challenge()
    attestation = _attestation(challenge)

    with pytest.raises(WitnessUnavailable, match="not configured"):
        verify_witness_attestation(
            challenge,
            attestation,
            verifier=None,
            now=150.0,
            expected_durable_chain_sha256="d" * 64,
        )


def test_local_witness_protocol_never_escalates_to_human_identity_proof() -> None:
    from workbench.qa.witness import verify_witness_attestation

    challenge = _challenge()
    result = verify_witness_attestation(
        challenge,
        _attestation(challenge),
        verifier=_TestWitnessVerifier(),
        now=150.0,
        expected_durable_chain_sha256="d" * 64,
    )

    assert result.trust_level == "witness_attested"
    assert result.human_identity_verified is False


class _IdentityAssuringWitnessVerifier(_TestWitnessVerifier):
    human_identity_verified = True


def test_explicit_provider_identity_assurance_is_propagated() -> None:
    from workbench.qa.witness import verify_witness_attestation

    challenge = _challenge()
    result = verify_witness_attestation(
        challenge,
        _attestation(challenge),
        verifier=_IdentityAssuringWitnessVerifier(),
        now=150.0,
        expected_durable_chain_sha256="d" * 64,
    )

    assert result.trust_level == "human_identity_verified"
    assert result.human_identity_verified is True


def test_witness_verifier_provider_is_optional_but_invalid_specs_fail_closed() -> None:
    from workbench.qa.witness import WitnessUnavailable, load_witness_verifier

    assert load_witness_verifier(None) is None
    with pytest.raises(WitnessUnavailable, match="provider"):
        load_witness_verifier("not-a-provider-spec")


def test_configured_remote_provider_is_selected_without_a_cli_spec(monkeypatch) -> None:
    from workbench.qa.remote_witness import RemoteWitnessVerifier
    from workbench.qa.witness import load_witness_verifier

    monkeypatch.setenv("WORKBENCH_WITNESS_PROVIDER_URL", "https://witness.example/v1/verify")
    monkeypatch.setenv("WORKBENCH_WITNESS_PROVIDER_ID", "witness.example")

    verifier = load_witness_verifier(None)

    assert isinstance(verifier, RemoteWitnessVerifier)


def test_partial_remote_provider_configuration_fails_closed(monkeypatch) -> None:
    from workbench.qa.witness import WitnessUnavailable, load_witness_verifier

    monkeypatch.setenv("WORKBENCH_WITNESS_PROVIDER_URL", "https://witness.example/v1/verify")
    monkeypatch.delenv("WORKBENCH_WITNESS_PROVIDER_ID", raising=False)

    with pytest.raises(WitnessUnavailable, match="URL and provider ID"):
        load_witness_verifier(None)
