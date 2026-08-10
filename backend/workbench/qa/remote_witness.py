"""Fail-closed client for an independent remote browser-witness verifier.

The remote service is intentionally outside Workbench's process.  It receives
the exact detached-signature payload produced by :mod:`workbench.qa.witness`
and verifies the provider's WebAuthn/browser witness policy.  This adapter does
not mint attestations, retry requests, or turn a provider failure into a local
acceptance.

Configure it with:

``WORKBENCH_WITNESS_PROVIDER_URL``
    HTTPS endpoint accepting the verification request.
``WORKBENCH_WITNESS_PROVIDER_ID``
    Stable provider identifier echoed by the response.
``WORKBENCH_WITNESS_PROVIDER_TOKEN``
    Optional bearer token; never included in manifests or diagnostics.
``WORKBENCH_WITNESS_PROVIDER_TIMEOUT_SECONDS``
    Optional timeout from 0.1 through 30 seconds (default 8 seconds).

Load through the existing explicit seam with
``workbench.qa.remote_witness:from_environment``.  Missing configuration
remains unavailable and therefore keeps completion ``NOT VERIFIED``.
"""

from __future__ import annotations

import base64
import json
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from workbench.qa.witness import WITNESS_PROTOCOL, WitnessUnavailable


_MAX_RESPONSE_BYTES = 64 * 1024
_DEFAULT_TIMEOUT_SECONDS = 8.0
_MIN_TIMEOUT_SECONDS = 0.1
_MAX_TIMEOUT_SECONDS = 30.0
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
_RESPONSE_FIELDS = {
    "protocol",
    "provider_id",
    "key_id",
    "verified",
    "human_identity_verified",
}


Transport = Callable[[Request, float], tuple[int, bytes]]


class _NoRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, *args: object, **kwargs: object):
        raise WitnessUnavailable("remote witness provider redirect is forbidden")


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
        raise WitnessUnavailable(f"remote witness {label} is invalid")
    return value


def _https_endpoint(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise WitnessUnavailable("remote witness provider URL is not configured")
    parsed = urlsplit(value)
    if parsed.scheme.casefold() != "https":
        raise WitnessUnavailable("remote witness provider URL must use HTTPS")
    if not parsed.netloc or parsed.username or parsed.password:
        raise WitnessUnavailable("remote witness provider URL is invalid")
    if parsed.query or parsed.fragment:
        raise WitnessUnavailable(
            "remote witness provider URL cannot contain query or fragment data"
        )
    if parsed.hostname is None:
        raise WitnessUnavailable("remote witness provider URL has no host")
    return value


def _timeout(value: object) -> float:
    try:
        timeout = float(value)
    except (TypeError, ValueError) as error:
        raise WitnessUnavailable("remote witness timeout is invalid") from error
    if not _MIN_TIMEOUT_SECONDS <= timeout <= _MAX_TIMEOUT_SECONDS:
        raise WitnessUnavailable("remote witness timeout is outside the allowed range")
    return timeout


def _default_transport(request: Request, timeout: float) -> tuple[int, bytes]:
    """Make one bounded request; urllib's retry behavior is deliberately absent."""

    try:
        with _NO_REDIRECT_OPENER.open(request, timeout=timeout) as response:
            return int(response.status), response.read(_MAX_RESPONSE_BYTES + 1)
    except WitnessUnavailable:
        raise
    except HTTPError as error:
        return int(error.code), error.read(_MAX_RESPONSE_BYTES + 1)
    except (OSError, TimeoutError, URLError) as error:
        raise WitnessUnavailable("remote witness provider request failed") from error


@dataclass
class RemoteWitnessVerifier:
    """Call one explicitly configured remote provider for signature verification."""

    endpoint_url: str
    provider_id: str
    bearer_token: str | None = None
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    transport: Transport = _default_transport
    _human_identity_verified: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        self.endpoint_url = _https_endpoint(self.endpoint_url)
        self.provider_id = _required_id(self.provider_id, "provider ID")
        if self.bearer_token is not None and not isinstance(self.bearer_token, str):
            raise WitnessUnavailable("remote witness bearer token is invalid")
        self.timeout_seconds = _timeout(self.timeout_seconds)
        if not callable(self.transport):
            raise WitnessUnavailable("remote witness transport is not callable")

    @property
    def human_identity_verified(self) -> bool:
        """Return only the identity assurance from the last provider response."""

        return self._human_identity_verified

    def verify(self, *, key_id: str, payload: bytes, signature: str) -> bool:
        """Return the remote provider's exact verification decision once."""

        key_id = _required_id(key_id, "key ID")
        if not isinstance(payload, bytes):
            raise WitnessUnavailable("remote witness payload must be bytes")
        if not isinstance(signature, str) or not signature:
            raise WitnessUnavailable("remote witness signature is invalid")
        request_payload = {
            "key_id": key_id,
            "payload_base64": base64.b64encode(payload).decode("ascii"),
            "provider_id": self.provider_id,
            "protocol": WITNESS_PROTOCOL,
            "signature": signature,
        }
        request = Request(
            self.endpoint_url,
            data=json.dumps(
                request_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "workbench-remote-witness/1",
                **(
                    {"Authorization": f"Bearer {self.bearer_token}"}
                    if self.bearer_token
                    else {}
                ),
            },
            method="POST",
        )
        try:
            status, body = self.transport(request, self.timeout_seconds)
        except WitnessUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 - provider failures fail closed.
            raise WitnessUnavailable("remote witness provider request failed") from error
        if type(status) is not int or status != 200:
            raise WitnessUnavailable(
                f"remote witness provider returned HTTP {status}"
            )
        if not isinstance(body, bytes) or len(body) > _MAX_RESPONSE_BYTES:
            raise WitnessUnavailable("remote witness provider response is too large")
        try:
            response: Any = json.loads(
                body.decode("utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            )
        except (UnicodeDecodeError, ValueError) as error:
            raise WitnessUnavailable("remote witness provider response is not JSON") from error
        if not isinstance(response, Mapping) or set(response) != _RESPONSE_FIELDS:
            raise WitnessUnavailable("remote witness provider response fields are invalid")
        if response["protocol"] != WITNESS_PROTOCOL:
            raise WitnessUnavailable("remote witness provider protocol drifted")
        if response["provider_id"] != self.provider_id:
            raise WitnessUnavailable("remote witness provider ID drifted")
        if response["key_id"] != key_id:
            raise WitnessUnavailable("remote witness provider key ID drifted")
        if type(response["verified"]) is not bool:
            raise WitnessUnavailable("remote witness provider decision is invalid")
        if type(response["human_identity_verified"]) is not bool:
            raise WitnessUnavailable(
                "remote witness provider identity decision is invalid"
            )
        self._human_identity_verified = response["human_identity_verified"]
        return response["verified"]


def from_environment() -> RemoteWitnessVerifier:
    """Build the remote adapter from explicit operator configuration."""

    endpoint_url = os.environ.get("WORKBENCH_WITNESS_PROVIDER_URL")
    provider_id = os.environ.get("WORKBENCH_WITNESS_PROVIDER_ID")
    if endpoint_url is None or provider_id is None:
        raise WitnessUnavailable(
            "remote witness provider URL and provider ID are not configured"
        )
    timeout = os.environ.get(
        "WORKBENCH_WITNESS_PROVIDER_TIMEOUT_SECONDS",
        str(_DEFAULT_TIMEOUT_SECONDS),
    )
    return RemoteWitnessVerifier(
        endpoint_url=endpoint_url,
        provider_id=provider_id,
        bearer_token=os.environ.get("WORKBENCH_WITNESS_PROVIDER_TOKEN"),
        timeout_seconds=_timeout(timeout),
    )


__all__ = ["RemoteWitnessVerifier", "from_environment"]
