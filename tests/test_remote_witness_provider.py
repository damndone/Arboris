from __future__ import annotations

import base64
import json

import pytest

from workbench.qa.witness import WitnessUnavailable


def _remote_module():
    try:
        from workbench.qa.remote_witness import (
            RemoteWitnessVerifier,
            from_environment,
        )
    except ModuleNotFoundError as error:
        pytest.fail(f"remote witness provider module is missing: {error}")
    return RemoteWitnessVerifier, from_environment


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


def _provider_response(*, provider_id: str = "witness.example", key_id: str = "key-1"):
    return {
        "protocol": "workbench.qa.browser-witness/v1",
        "provider_id": provider_id,
        "key_id": key_id,
        "verified": True,
        "human_identity_verified": False,
    }


def test_remote_provider_loads_from_explicit_environment(monkeypatch) -> None:
    _, from_environment = _remote_module()
    monkeypatch.setenv("WORKBENCH_WITNESS_PROVIDER_URL", "https://witness.example/v1/verify")
    monkeypatch.setenv("WORKBENCH_WITNESS_PROVIDER_ID", "witness.example")

    verifier = from_environment()

    assert verifier.provider_id == "witness.example"
    assert verifier.endpoint_url == "https://witness.example/v1/verify"


def test_remote_provider_requires_https_and_rejects_missing_configuration() -> None:
    RemoteWitnessVerifier, from_environment = _remote_module()

    with pytest.raises(WitnessUnavailable, match="configured|HTTPS"):
        from_environment()
    with pytest.raises(WitnessUnavailable, match="HTTPS"):
        RemoteWitnessVerifier(
            endpoint_url="http://witness.example/v1/verify",
            provider_id="witness.example",
        )


def test_remote_provider_forwards_exact_signed_payload_without_retry() -> None:
    RemoteWitnessVerifier, _ = _remote_module()
    transport = _Transport(body=_provider_response())
    verifier = RemoteWitnessVerifier(
        endpoint_url="https://witness.example/v1/verify",
        provider_id="witness.example",
        transport=transport,
    )

    assert verifier.verify(key_id="key-1", payload=b"challenge-payload", signature="sig") is True

    assert len(transport.calls) == 1
    request, timeout = transport.calls[0]
    assert timeout == verifier.timeout_seconds
    assert request.full_url == "https://witness.example/v1/verify"
    assert request.method == "POST"
    assert request.headers["Content-type"] == "application/json"
    sent = json.loads(request.data)
    assert sent == {
        "key_id": "key-1",
        "payload_base64": base64.b64encode(b"challenge-payload").decode("ascii"),
        "provider_id": "witness.example",
        "protocol": "workbench.qa.browser-witness/v1",
        "signature": "sig",
    }


def test_remote_provider_exposes_only_the_identity_assurance_it_received() -> None:
    RemoteWitnessVerifier, _ = _remote_module()
    response = _provider_response()
    response["human_identity_verified"] = True
    verifier = RemoteWitnessVerifier(
        endpoint_url="https://witness.example/v1/verify",
        provider_id="witness.example",
        transport=_Transport(body=response),
    )

    assert verifier.verify(key_id="key-1", payload=b"payload", signature="sig") is True
    try:
        identity_verified = verifier.human_identity_verified
    except AttributeError as error:
        pytest.fail(f"remote provider identity assurance is not exposed: {error}")
    assert identity_verified is True


def test_remote_provider_rejects_provider_or_key_drift() -> None:
    RemoteWitnessVerifier, _ = _remote_module()

    for response in (
        _provider_response(provider_id="other.example"),
        _provider_response(key_id="other-key"),
    ):
        verifier = RemoteWitnessVerifier(
            endpoint_url="https://witness.example/v1/verify",
            provider_id="witness.example",
            transport=_Transport(body=response),
        )
        with pytest.raises(WitnessUnavailable, match="provider|key"):
            verifier.verify(key_id="key-1", payload=b"payload", signature="sig")


def test_remote_provider_rejects_malformed_or_oversized_responses() -> None:
    RemoteWitnessVerifier, _ = _remote_module()

    malformed = RemoteWitnessVerifier(
        endpoint_url="https://witness.example/v1/verify",
        provider_id="witness.example",
        transport=_Transport(body=b"not-json"),
    )
    with pytest.raises(WitnessUnavailable, match="response|JSON"):
        malformed.verify(key_id="key-1", payload=b"payload", signature="sig")

    oversized = RemoteWitnessVerifier(
        endpoint_url="https://witness.example/v1/verify",
        provider_id="witness.example",
        transport=_Transport(body=b"x" * (64 * 1024 + 1)),
    )
    with pytest.raises(WitnessUnavailable, match="large|size"):
        oversized.verify(key_id="key-1", payload=b"payload", signature="sig")


def test_remote_provider_rejects_duplicate_response_fields() -> None:
    RemoteWitnessVerifier, _ = _remote_module()
    duplicate = json.dumps(_provider_response()).replace(
        '"verified": true', '"verified": true, "verified": false'
    )
    verifier = RemoteWitnessVerifier(
        endpoint_url="https://witness.example/v1/verify",
        provider_id="witness.example",
        transport=_Transport(body=duplicate.encode("utf-8")),
    )

    with pytest.raises(WitnessUnavailable, match="JSON|duplicate"):
        verifier.verify(key_id="key-1", payload=b"payload", signature="sig")


def test_remote_provider_does_not_convert_http_failure_to_verified() -> None:
    RemoteWitnessVerifier, _ = _remote_module()
    transport = _Transport(status=503, body=b"upstream unavailable")
    verifier = RemoteWitnessVerifier(
        endpoint_url="https://witness.example/v1/verify",
        provider_id="witness.example",
        transport=transport,
    )

    with pytest.raises(WitnessUnavailable, match="HTTP"):
        verifier.verify(key_id="key-1", payload=b"payload", signature="sig")
    assert len(transport.calls) == 1


def test_default_transport_uses_a_no_redirect_opener(monkeypatch) -> None:
    try:
        import workbench.qa.remote_witness as remote_witness
    except ModuleNotFoundError as error:
        pytest.fail(f"remote witness provider module is missing: {error}")

    class _RedirectRejectingOpener:
        def open(self, request, *, timeout: float):
            raise WitnessUnavailable("remote witness provider redirect is forbidden")

    if not hasattr(remote_witness, "_NO_REDIRECT_OPENER"):
        pytest.fail("remote witness transport has no redirect policy")
    monkeypatch.setattr(
        remote_witness,
        "_NO_REDIRECT_OPENER",
        _RedirectRejectingOpener(),
    )

    request = remote_witness.Request("https://witness.example/v1/verify")
    with pytest.raises(WitnessUnavailable, match="redirect"):
        remote_witness._default_transport(request, 1.0)
