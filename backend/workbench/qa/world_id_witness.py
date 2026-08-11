"""Fail-closed World ID proof verifier for human-backed browser witnesses.

The witness envelope keeps the existing detached-attestation shape.  For this
provider, its ``signature`` field contains an exact IDKit result encoded as
``world-id-json-base64:<base64>``.  The result is forwarded byte-for-byte to
World's official verification endpoint; Workbench never creates or rewrites a
proof.

The IDKit action is derived from the exact detached witness payload.  A
successful result must therefore bind every observation field to the proof,
use the production environment, identify a proof-of-human credential, and
report completed user presence.  Staging/simulator results remain unavailable
rather than being promoted to a human-identity claim.

Configuration:

``WORKBENCH_WORLD_ID_RP_ID``
    World ID relying-party ID (required; normally ``rp_...``).
``WORKBENCH_WORLD_ID_VERIFY_URL``
    Optional official endpoint override for controlled testing.  It must still
    be the HTTPS ``developer.world.org/api/v4/verify/<rp_id>`` endpoint.
``WORKBENCH_WORLD_ID_ACTION_PREFIX``
    Optional action prefix; defaults to ``workbench-confirm-v1-``.
``WORKBENCH_WORLD_ID_TIMEOUT_SECONDS``
    Optional bounded timeout from 0.1 through 30 seconds (default 8 seconds).

The RP signing key and IDKit UI belong to the external World ID client flow;
they are never read or exposed by this verifier.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from workbench.qa.witness import WitnessUnavailable


_DEFAULT_ACTION_PREFIX = "workbench-confirm-v1-"
_DEFAULT_TIMEOUT_SECONDS = 8.0
_MIN_TIMEOUT_SECONDS = 0.1
_MAX_TIMEOUT_SECONDS = 30.0
_MAX_RESPONSE_BYTES = 64 * 1024
_MAX_IDKIT_BYTES = 256 * 1024
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_PREFIX = "world-id-json-base64:"
_OFFICIAL_HOST = "developer.world.org"
_PROVIDER_PROTOCOL_VERSION = "4.0"


Transport = Callable[[Request, float], tuple[int, bytes]]


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object):
        raise WitnessUnavailable("World ID verification redirect is forbidden")


_NO_REDIRECT_OPENER = build_opener(_NoRedirectHandler())


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON field: {key}")
        result[key] = value
    return result


def _required_id(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or _SAFE_ID.fullmatch(value) is None:
        raise WitnessUnavailable(f"World ID {label} is invalid")
    return value


def _timeout(value: object) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as error:
        raise WitnessUnavailable("World ID timeout is invalid") from error
    if not _MIN_TIMEOUT_SECONDS <= timeout <= _MAX_TIMEOUT_SECONDS:
        raise WitnessUnavailable("World ID timeout is outside the allowed range")
    return timeout


def _endpoint(value: object, rp_id: str) -> str:
    endpoint = value
    if endpoint is None:
        endpoint = f"https://{_OFFICIAL_HOST}/api/v4/verify/{rp_id}"
    if not isinstance(endpoint, str) or not endpoint:
        raise WitnessUnavailable("World ID verification URL is not configured")
    parsed = urlsplit(endpoint)
    if parsed.scheme.casefold() != "https":
        raise WitnessUnavailable("World ID verification URL must use HTTPS")
    if (
        parsed.hostname != _OFFICIAL_HOST
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise WitnessUnavailable(
            "World ID verification URL must be the official developer endpoint"
        )
    expected_path = f"/api/v4/verify/{rp_id}"
    if parsed.path != expected_path:
        raise WitnessUnavailable("World ID verification URL has the wrong RP path")
    return endpoint


def _default_transport(request: Request, timeout: float) -> tuple[int, bytes]:
    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:
            return int(response.status), response.read(_MAX_RESPONSE_BYTES + 1)
    except WitnessUnavailable:
        raise
    except HTTPError as error:
        return int(error.code), error.read(_MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, URLError) as error:
        raise WitnessUnavailable("World ID verification request failed") from error


def _json_object(raw: bytes, label: str) -> Mapping[str, Any]:
    if not isinstance(raw, bytes) or len(raw) > _MAX_IDKIT_BYTES:
        raise WitnessUnavailable(f"World ID {label} is too large")
    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (UnicodeDecodeError, ValueError) as error:
        raise WitnessUnavailable(f"World ID {label} is not valid JSON") from error
    if not isinstance(value, Mapping):
        raise WitnessUnavailable(f"World ID {label} must be a JSON object")
    return value


def _challenge_digest(payload: bytes) -> str:
    body = _json_object(payload, "witness payload")
    value = body.get("challenge_digest")
    if not isinstance(value, str) or _SHA256.fullmatch(value.casefold()) is None:
        raise WitnessUnavailable("World ID witness payload has no valid challenge digest")
    return value.casefold()


def _idkit_result(signature: str) -> tuple[bytes, Mapping[str, Any]]:
    if not isinstance(signature, str) or not signature.startswith(_SIGNATURE_PREFIX):
        raise WitnessUnavailable(
            "World ID witness signature must contain an encoded IDKit result"
        )
    encoded = signature[len(_SIGNATURE_PREFIX) :]
    if not encoded:
        raise WitnessUnavailable("World ID IDKit result is empty")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise WitnessUnavailable("World ID IDKit result encoding is invalid") from error
    return raw, _json_object(raw, "IDKit result")


def _payload_digest(payload: bytes) -> str:
    _challenge_digest(payload)
    return hashlib.sha256(payload).hexdigest()


def _expected_action(prefix: str, payload_digest: str) -> str:
    action = f"{prefix}{payload_digest}"
    if not _SAFE_ID.fullmatch(action):
        raise WitnessUnavailable("World ID action prefix produces an invalid action")
    return action


def _validate_idkit_request(
    result: Mapping[str, Any], *, expected_action: str
) -> None:
    if result.get("protocol_version") != _PROVIDER_PROTOCOL_VERSION:
        raise WitnessUnavailable("World ID proof must use protocol version 4.0")
    if result.get("action") != expected_action:
        raise WitnessUnavailable(
            "World ID proof action is not bound to the exact witness payload"
        )
    if result.get("environment") != "production":
        raise WitnessUnavailable("World ID staging proof is not human identity evidence")
    if result.get("user_presence_completed") is not True:
        raise WitnessUnavailable("World ID user presence was not completed")
    responses = result.get("responses")
    if not isinstance(responses, list) or not responses:
        raise WitnessUnavailable("World ID proof has no response")
    if not any(
        isinstance(response, Mapping)
        and response.get("identifier") == "proof_of_human"
        for response in responses
    ):
        raise WitnessUnavailable("World ID proof has no proof_of_human response")


def _validate_verification_response(
    response: Mapping[str, Any], *, expected_action: str
) -> bool:
    if type(response.get("success")) is not bool:
        raise WitnessUnavailable("World ID verification response is invalid")
    action = response.get("action")
    if not isinstance(action, str):
        raise WitnessUnavailable("World ID verification response is invalid")
    if action != expected_action:
        raise WitnessUnavailable("World ID verification action drifted")
    environment = response.get("environment")
    if environment is not None and environment != "production":
        raise WitnessUnavailable("World ID verification environment is not production")
    results = response.get("results")
    if not isinstance(results, list) or not results:
        raise WitnessUnavailable("World ID verification response has no results")
    valid_results = [
        result
        for result in results
        if isinstance(result, Mapping)
        and result.get("identifier") == "proof_of_human"
        and type(result.get("success")) is bool
    ]
    if not valid_results:
        raise WitnessUnavailable("World ID verification response has no proof_of_human result")
    if response.get("success") is False:
        return False
    if not any(result.get("success") is True for result in valid_results):
        return False
    nullifier = response.get("nullifier")
    if not isinstance(nullifier, str) or not nullifier:
        raise WitnessUnavailable("World ID verification response has no nullifier")
    return True


@dataclass
class WorldIdWitnessVerifier:
    """Verify one exact-payload-bound IDKit proof through World Portal."""

    rp_id: str
    endpoint_url: str | None = None
    action_prefix: str = _DEFAULT_ACTION_PREFIX
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    transport: Transport = _default_transport
    _human_identity_verified: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.rp_id = _required_id(self.rp_id, "RP ID")
        if not self.rp_id.startswith("rp_"):
            raise WitnessUnavailable("World ID RP ID must start with rp_")
        self.endpoint_url = _endpoint(self.endpoint_url, self.rp_id)
        if not isinstance(self.action_prefix, str) or not self.action_prefix:
            raise WitnessUnavailable("World ID action prefix is invalid")
        self.timeout_seconds = _timeout(self.timeout_seconds)
        if not callable(self.transport):
            raise WitnessUnavailable("World ID transport is not callable")

    @property
    def key_id(self) -> str:
        return f"world-id:{self.rp_id}"

    @property
    def human_identity_verified(self) -> bool:
        return self._human_identity_verified

    def verify(self, *, key_id: str, payload: bytes, signature: str) -> bool:
        self._human_identity_verified = False
        if key_id != self.key_id:
            raise WitnessUnavailable("World ID witness key ID drifted")
        if not isinstance(payload, bytes):
            raise WitnessUnavailable("World ID witness payload must be bytes")
        payload_digest = _payload_digest(payload)
        expected_action = _expected_action(self.action_prefix, payload_digest)
        raw_result, result = _idkit_result(signature)
        _validate_idkit_request(result, expected_action=expected_action)
        request = Request(
            self.endpoint_url,
            data=raw_result,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "workbench-world-id-witness/1",
            },
            method="POST",
        )
        try:
            status, body = self.transport(request, self.timeout_seconds)
        except WitnessUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 - provider failures fail closed.
            raise WitnessUnavailable("World ID verification request failed") from error
        if type(status) is not int or status != 200:
            raise WitnessUnavailable(f"World ID verification returned HTTP {status}")
        if not isinstance(body, bytes) or len(body) > _MAX_RESPONSE_BYTES:
            raise WitnessUnavailable("World ID verification response is too large")
        response = _json_object(body, "verification response")
        verified = _validate_verification_response(
            response,
            expected_action=expected_action,
        )
        self._human_identity_verified = verified
        return verified


def from_environment() -> WorldIdWitnessVerifier:
    """Build the provider from explicit local configuration."""

    rp_id = os.environ.get("WORKBENCH_WORLD_ID_RP_ID")
    if rp_id is None:
        raise WitnessUnavailable("World ID RP ID is not configured")
    timeout = os.environ.get(
        "WORKBENCH_WORLD_ID_TIMEOUT_SECONDS",
        str(_DEFAULT_TIMEOUT_SECONDS),
    )
    return WorldIdWitnessVerifier(
        rp_id=rp_id,
        endpoint_url=os.environ.get("WORKBENCH_WORLD_ID_VERIFY_URL"),
        action_prefix=os.environ.get(
            "WORKBENCH_WORLD_ID_ACTION_PREFIX",
            _DEFAULT_ACTION_PREFIX,
        ),
        timeout_seconds=_timeout(timeout),
    )


__all__ = ["WorldIdWitnessVerifier", "from_environment"]
