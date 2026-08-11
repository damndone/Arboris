from __future__ import annotations

import base64
import json

import pytest

from workbench.qa.witness import WitnessUnavailable


def _world_module():
    try:
        from workbench.qa.world_id_witness import (
            WorldIdWitnessVerifier,
            from_environment,
        )
    except ModuleNotFoundError as error:
        pytest.fail(f"World ID witness provider module is missing: {error}")
    return WorldIdWitnessVerifier, from_environment


class _Transport:
    def __init__(self, *, status: int = 200, body: dict[str, object] | bytes):
        self.status = status
        self.body = body
        self.calls: list[tuple[object, float]] = []

    def __call__(self, request, timeout: float):
        self.calls.append((request, timeout))
        body = self.body
        if isinstance(body, dict):
            body = json.dumps(body, sort_keys=True).encode("utf-8")
        return self.status, body


def _idkit_result(*, action: str, environment: str = "production") -> dict[str, object]:
    return {
        "protocol_version": "4.0",
        "nonce": "nonce-1",
        "action": action,
        "environment": environment,
        "responses": [
            {
                "identifier": "proof_of_human",
                "signal_hash": "0x0",
                "proof": ["0x1", "0x2", "0x3", "0x4", "0x5"],
                "nullifier": "0xabc",
                "issuer_schema_id": 1,
                "expires_at_min": 4_000_000_000,
            }
        ],
        "user_presence_completed": True,
    }


def _payload(challenge_digest: str = "a" * 64) -> bytes:
    return json.dumps(
        {
            "challenge_digest": challenge_digest,
            "protocol": "workbench.qa.browser-witness/v1",
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _encoded_result(result: dict[str, object]) -> str:
    raw = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "world-id-json-base64:" + base64.b64encode(raw).decode("ascii")


def _verify_response(*, action: str, environment: str = "production") -> dict[str, object]:
    return {
        "success": True,
        "results": [
            {
                "identifier": "proof_of_human",
                "success": True,
                "nullifier": "0xabc",
                "code": "verified",
                "detail": "ok",
            }
        ],
        "action": action,
        "nullifier": "0xabc",
        "created_at": "2026-08-11T00:00:00Z",
        "environment": environment,
    }


def test_world_id_provider_requires_an_rp_id(monkeypatch) -> None:
    _, from_environment = _world_module()
    monkeypatch.delenv("WORKBENCH_WORLD_ID_RP_ID", raising=False)

    with pytest.raises(WitnessUnavailable, match="RP ID"):
        from_environment()


def test_world_id_provider_forwards_the_raw_idkit_result_and_binds_action() -> None:
    WorldIdWitnessVerifier, _ = _world_module()
    challenge_digest = "a" * 64
    action = f"workbench-confirm-v1-{challenge_digest}"
    result = _idkit_result(action=action)
    raw_result = json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )
    transport = _Transport(body=_verify_response(action=action))
    verifier = WorldIdWitnessVerifier(
        rp_id="rp_workbench",
        transport=transport,
    )

    assert (
        verifier.verify(
            key_id="world-id:rp_workbench",
            payload=_payload(challenge_digest),
            signature=_encoded_result(result),
        )
        is True
    )
    assert verifier.human_identity_verified is True
    request, timeout = transport.calls[0]
    assert timeout == verifier.timeout_seconds
    assert request.full_url == "https://developer.world.org/api/v4/verify/rp_workbench"
    assert request.method == "POST"
    assert request.data == raw_result


def test_world_id_provider_rejects_an_action_not_bound_to_the_challenge() -> None:
    WorldIdWitnessVerifier, _ = _world_module()
    transport = _Transport(body=_verify_response(action="other-action"))
    verifier = WorldIdWitnessVerifier(rp_id="rp_workbench", transport=transport)

    with pytest.raises(WitnessUnavailable, match="action"):
        verifier.verify(
            key_id="world-id:rp_workbench",
            payload=_payload("a" * 64),
            signature=_encoded_result(_idkit_result(action="other-action")),
        )
    assert transport.calls == []


@pytest.mark.parametrize(
    "environment,user_presence",
    [("staging", True), ("production", False)],
)
def test_world_id_provider_never_escalates_nonproduction_or_missing_presence(
    environment: str, user_presence: bool
) -> None:
    WorldIdWitnessVerifier, _ = _world_module()
    action = f"workbench-confirm-v1-{'a' * 64}"
    result = _idkit_result(action=action, environment=environment)
    result["user_presence_completed"] = user_presence
    transport = _Transport(
        body=_verify_response(action=action, environment=environment)
    )
    verifier = WorldIdWitnessVerifier(rp_id="rp_workbench", transport=transport)

    with pytest.raises(WitnessUnavailable, match="human|presence|staging"):
        verifier.verify(
            key_id="world-id:rp_workbench",
            payload=_payload(),
            signature=_encoded_result(result),
        )
    assert verifier.human_identity_verified is False


def test_world_id_provider_rejects_invalid_remote_response() -> None:
    WorldIdWitnessVerifier, _ = _world_module()
    action = f"workbench-confirm-v1-{'a' * 64}"
    verifier = WorldIdWitnessVerifier(
        rp_id="rp_workbench",
        transport=_Transport(body={"success": True}),
    )

    with pytest.raises(WitnessUnavailable, match="response"):
        verifier.verify(
            key_id="world-id:rp_workbench",
            payload=_payload(),
            signature=_encoded_result(_idkit_result(action=action)),
        )


def test_world_id_provider_accepts_verification_response_without_optional_environment() -> None:
    WorldIdWitnessVerifier, _ = _world_module()
    action = f"workbench-confirm-v1-{'a' * 64}"
    response = _verify_response(action=action)
    response.pop("environment")
    verifier = WorldIdWitnessVerifier(
        rp_id="rp_workbench",
        transport=_Transport(body=response),
    )

    assert verifier.verify(
        key_id="world-id:rp_workbench",
        payload=_payload(),
        signature=_encoded_result(_idkit_result(action=action)),
    ) is True
