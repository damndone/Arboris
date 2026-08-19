"""Supervisor-only bootstrap for the Evidence host authority channel.

The Evidence package intentionally has no public resolver or configuration
setter.  A deployment supervisor reserves one inherited Unix control FD,
sends one canonical descriptor plus one client FD with ``SCM_RIGHTS``, and
the Workbench process verifies that the control peer is its real parent before
the existing endpoint admission code is allowed to run.

This module is a transport/bootstrap seam, not an authority server.  It does
not mint secrets, choose a scope, or decide whether an Evidence request is
allowed.  Those facts arrive from the supervisor and are bound to the OS peer
and the already-locked Evidence handshake.
"""

from __future__ import annotations

import array
import json
import os
import socket
from typing import Final

from .authority import (
    EVIDENCE_HOST_AUTHORITY_REQUIRED,
    EVIDENCE_HOST_AUTHORITY_TIMEOUT,
    EVIDENCE_HOST_AUTHORITY_UNAVAILABLE,
    EvidenceHostAuthorityError,
    HostAuthorityEndpointConfigV1,
    HostAuthorityEndpointV1,
    _admit_host_authority_endpoint_with_config,
    _peer_uid_pid,
)


# This descriptor is reserved by the Workbench deployment contract.  A high
# fixed number avoids colliding with Python runtime pipes and standard streams
# while remaining independent of a request/environment-selected FD.
EVIDENCE_SUPERVISOR_CONTROL_FD: Final[int] = 197
EVIDENCE_SUPERVISOR_PROTOCOL: Final[str] = "workbench-evidence-supervisor/v1"
_MAX_CONTROL_FRAME_BYTES: Final[int] = 64 * 1024
_CONTROL_TIMEOUT_SECONDS: Final[float] = 1.0
_CONTROL_READ_BYTES: Final[int] = 4 * 1024
_CONTROL_FD_LIMIT: Final[int] = 4
_CONFIG_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "endpoint_path",
        "endpoint_device",
        "endpoint_inode",
        "peer_uid",
        "peer_pid",
        "scope_ref",
        "session_ref",
        "shared_secret",
        "purpose_prefix",
    }
)


def _reject(message: str, *, code: str = EVIDENCE_HOST_AUTHORITY_REQUIRED) -> EvidenceHostAuthorityError:
    return EvidenceHostAuthorityError(code=code, message=message)


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise _reject("supervisor control payload contains duplicate keys")
        value[key] = item
    return value


def _close_received_fds(endpoint_fds: list[int]) -> None:
    for endpoint_fd in endpoint_fds:
        try:
            os.close(endpoint_fd)
        except OSError:
            pass


def _set_non_inheritable(value: object) -> None:
    """Make a descriptor/socket non-inheritable before authority use."""

    try:
        setter = getattr(value, "set_inheritable", None)
        if callable(setter):
            setter(False)
            return
        fd = value if type(value) is int else value.fileno()  # type: ignore[union-attr]
        os.set_inheritable(fd, False)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise _reject("supervisor authority descriptor could not be made non-inheritable") from exc


def _control_socket() -> HostAuthorityEndpointV1:
    if os.name != "posix" or not hasattr(socket, "SCM_RIGHTS"):
        raise _reject("supervisor evidence control transport is unavailable")
    duplicated_fd = -1
    channel: socket.socket | None = None
    endpoint_fds: list[int] = []
    try:
        duplicated_fd = os.dup(EVIDENCE_SUPERVISOR_CONTROL_FD)
        # The fixed descriptor is one-shot.  Closing it prevents a later
        # request or a second bootstrap call from replaying the same control
        # channel after the supervisor has delivered its authority material.
        try:
            os.close(EVIDENCE_SUPERVISOR_CONTROL_FD)
        except BaseException:
            _close_received_fds([duplicated_fd])
            duplicated_fd = -1
            raise
        try:
            channel = socket.socket(fileno=duplicated_fd)
        except BaseException:
            _close_received_fds([duplicated_fd])
            duplicated_fd = -1
            raise
        duplicated_fd = -1
        _set_non_inheritable(channel)
    except (OSError, TypeError, ValueError) as exc:
        raise _reject("supervisor evidence control descriptor is unavailable") from exc
    try:
        assert channel is not None
        if channel.family != socket.AF_UNIX or (channel.type & 0xF) != socket.SOCK_STREAM:
            raise _reject("supervisor evidence control descriptor is not a Unix stream")
        peer_uid, peer_pid = _peer_uid_pid(channel)
        parent_pid = os.getppid()
        current_uid = os.getuid()
        if parent_pid <= 1 or peer_pid != parent_pid or peer_uid != current_uid:
            raise _reject("supervisor control peer is not the Workbench parent")
        previous_timeout = channel.gettimeout()
        channel.settimeout(_CONTROL_TIMEOUT_SECONDS)
        try:
            data = bytearray()
            ancillary_error: str | None = None
            while True:
                try:
                    chunk, ancillary, message_flags, _address = channel.recvmsg(
                        min(_CONTROL_READ_BYTES, _MAX_CONTROL_FRAME_BYTES + 1 - len(data)),
                        socket.CMSG_SPACE(array.array("i", [0]).itemsize * _CONTROL_FD_LIMIT),
                    )
                except socket.timeout as exc:
                    raise _reject(
                        "supervisor control transport timed out",
                        code=EVIDENCE_HOST_AUTHORITY_TIMEOUT,
                    ) from exc
                except OSError as exc:
                    raise _reject(
                        "supervisor control transport is unavailable",
                        code=EVIDENCE_HOST_AUTHORITY_UNAVAILABLE,
                    ) from exc
                for level, kind, payload in ancillary:
                    if level != socket.SOL_SOCKET or kind != socket.SCM_RIGHTS:
                        ancillary_error = "supervisor control carried unsupported ancillary data"
                        continue
                    if len(payload) % array.array("i").itemsize:
                        ancillary_error = "supervisor control FD payload is malformed"
                        continue
                    values = array.array("i")
                    values.frombytes(payload)
                    endpoint_fds.extend(int(value) for value in values)
                if message_flags & getattr(socket, "MSG_CTRUNC", 0):
                    raise _reject("supervisor control ancillary data was truncated")
                if ancillary_error is not None:
                    raise _reject(ancillary_error)
                if len(data) + len(chunk) > _MAX_CONTROL_FRAME_BYTES:
                    raise _reject("supervisor control frame exceeds the limit")
                if not chunk:
                    raise _reject(
                        "supervisor control transport closed",
                        code=EVIDENCE_HOST_AUTHORITY_UNAVAILABLE,
                    )
                data.extend(chunk)
                if b"\n" in chunk:
                    break
        finally:
            channel.settimeout(previous_timeout)
        frame, separator, tail = data.partition(b"\n")
        if not separator or tail:
            raise _reject("supervisor control frame must contain exactly one line")
        try:
            payload = json.loads(
                frame.decode("utf-8"),
                object_pairs_hook=_unique_pairs,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, EvidenceHostAuthorityError) as exc:
            raise _reject("supervisor control frame is not valid JSON") from exc
        if type(payload) is not dict or set(payload) != {"protocol", "config"}:
            raise _reject("supervisor control frame shape is invalid")
        if payload.get("protocol") != EVIDENCE_SUPERVISOR_PROTOCOL:
            raise _reject("supervisor control protocol version is invalid")
        config_payload = payload.get("config")
        if type(config_payload) is not dict or set(config_payload) != _CONFIG_FIELDS:
            raise _reject("supervisor evidence configuration shape is invalid")
        try:
            config = HostAuthorityEndpointConfigV1(**config_payload)
        except (TypeError, ValueError) as exc:
            raise _reject("supervisor evidence configuration is invalid") from exc
        if config.peer_uid != peer_uid or config.peer_pid != peer_pid:
            raise _reject("supervisor evidence configuration is not bound to the control peer")
        if len(endpoint_fds) != 1:
            raise _reject("supervisor control must pass exactly one endpoint FD")
        endpoint_fd = endpoint_fds.pop()
        endpoint_channel: socket.socket | None = None
        try:
            _set_non_inheritable(endpoint_fd)
            endpoint_channel = socket.socket(fileno=endpoint_fd)
            _set_non_inheritable(endpoint_channel)
        except (OSError, TypeError, ValueError) as exc:
            if endpoint_channel is not None:
                endpoint_channel.close()
            else:
                try:
                    os.close(endpoint_fd)
                except OSError:
                    pass
            raise _reject("supervisor endpoint FD is unavailable") from exc
        try:
            assert endpoint_channel is not None
            return _admit_host_authority_endpoint_with_config(
                endpoint_channel,
                deployment_config=config,
            )
        except BaseException:
            endpoint_channel.close()
            raise
    except EvidenceHostAuthorityError:
        raise
    except socket.timeout as exc:
        raise _reject(
            "supervisor evidence bootstrap timed out",
            code=EVIDENCE_HOST_AUTHORITY_TIMEOUT,
        ) from exc
    except OSError as exc:
        raise _reject(
            "supervisor evidence bootstrap transport is unavailable",
            code=EVIDENCE_HOST_AUTHORITY_UNAVAILABLE,
        ) from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise _reject("supervisor evidence bootstrap failed closed") from exc
    finally:
        if channel is not None:
            channel.close()
        if duplicated_fd >= 0:
            _close_received_fds([duplicated_fd])
        _close_received_fds(endpoint_fds)


def bootstrap_evidence_host_authority() -> HostAuthorityEndpointV1:
    """Consume the one-time supervisor handoff and admit its host endpoint.

    The function intentionally accepts no arguments.  It can only use the
    deployment-reserved inherited control descriptor, so request code cannot
    select the endpoint, scope, session, peer or secret.
    """

    return _control_socket()


__all__ = [
    "EVIDENCE_SUPERVISOR_CONTROL_FD",
    "EVIDENCE_SUPERVISOR_PROTOCOL",
    "bootstrap_evidence_host_authority",
]
