"""Deployment-bound host authority for the Agent Compiler.

The compiler is deliberately not an authority server.  It can only use a
handle admitted from a deployment-owned pathname Unix endpoint (or a
supervisor-passed descriptor) after the endpoint path, inode, OS peer
credentials and host handshake have all been checked.  The configuration is
loaded from a supervisor-owned file; request objects and Python constructors
never supply the trust root.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
import ctypes
import ctypes.util
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import socket
import stat
import struct
import sys
from threading import RLock
import threading
from typing import Any
from weakref import WeakKeyDictionary

from ..canonical import canonical_json_v1


_PROTOCOL_VERSION = "workbench-host-authority.v1"
_CONFIG_SCHEMA_VERSION = "workbench-host-authority-config.v1"
_CONFIG_ENV = "WORKBENCH_AGENT_HOST_AUTHORITY_CONFIG"
_MAX_FRAME_BYTES = 256_000
_MAX_CONFIG_BYTES = 64 * 1024
_SOCKET_TIMEOUT_SECONDS = 2.0
_MACOS_SOL_LOCAL = 0
_MACOS_LOCAL_PEERPID = 0x002


class HostAuthorityChannelError(ValueError):
    """A stable fail-closed error returned by endpoint admission or RPC."""

    def __init__(self, code: str, message: str = "host authority rejected request") -> None:
        self.code = code
        super().__init__(message)


def _reject(message: str, code: str = "FORGED_AUTHORITY") -> HostAuthorityChannelError:
    return HostAuthorityChannelError(code, message)


def _opaque_id(value: object, prefix: str) -> str:
    if (
        type(value) is not str
        or not value.startswith(prefix)
        or len(value) <= len(prefix)
        or any(token in value for token in ("/", "\\", "..", "://"))
    ):
        raise _reject("opaque host authority identity is invalid")
    return value


def _safe_scope(value: object) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.startswith(("project:", "workspace:", "notebook:", "scope:"))
        or any(token in value for token in ("/", "\\", "..", "://"))
        or not value.partition(":")[2]
    ):
        raise _reject("host authority scope is invalid")
    return value


def _safe_ref(value: object, prefix: str) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or not value.startswith(prefix)
        or not value.partition(":")[2]
        or any(token in value for token in ("/", "\\", "..", "://"))
    ):
        raise _reject("host authority reference is invalid")
    return value


def _config_snapshot(config: "HostAuthorityEndpointConfigV1") -> tuple[object, ...]:
    return (
        config.endpoint_path,
        config.endpoint_device,
        config.endpoint_inode,
        config.peer_uid,
        config.peer_pid,
        config.scope_ref,
        config.session_ref,
        config.shared_secret,
        config.purpose_prefix,
    )


@dataclass(frozen=True, slots=True, weakref_slot=True, init=False)
class HostAuthorityEndpointConfigV1:
    """A deployment-owned endpoint identity.

    Direct construction is intentionally unavailable.  The only supported
    source is :func:`load_host_authority_config`, which reads an externally
    configured, non-symlink, non-group/world-writable file.  The object is
    registered by that loader and the admission functions reject equal-looking
    objects created by callers or by ``object.__new__``.
    """

    endpoint_path: str
    endpoint_device: int
    endpoint_inode: int
    peer_uid: int
    peer_pid: int
    scope_ref: str
    session_ref: str
    shared_secret: str
    purpose_prefix: str

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("host endpoint configuration must come from deployment")

    @classmethod
    def _from_deployment_payload(cls, payload: Mapping[str, object]) -> "HostAuthorityEndpointConfigV1":
        expected = {
            "schema_version",
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
        if type(payload) is not dict or set(payload) != expected:
            raise _reject("host endpoint configuration shape is invalid", "HOST_AUTHORITY_REQUIRED")
        if payload["schema_version"] != _CONFIG_SCHEMA_VERSION:
            raise _reject("host endpoint configuration version is invalid", "HOST_AUTHORITY_REQUIRED")
        endpoint_path = payload["endpoint_path"]
        if (
            type(endpoint_path) is not str
            or not endpoint_path.startswith("/")
            or "\x00" in endpoint_path
            or os.path.islink(endpoint_path)
        ):
            raise _reject("host endpoint path is invalid", "HOST_AUTHORITY_REQUIRED")
        for name in ("endpoint_device", "endpoint_inode", "peer_uid", "peer_pid"):
            value = payload[name]
            if type(value) is not int or value < 0:
                raise _reject(f"host endpoint {name} is invalid", "HOST_AUTHORITY_REQUIRED")
        if payload["peer_pid"] == 0:
            raise _reject("host endpoint peer pid is invalid", "HOST_AUTHORITY_REQUIRED")
        scope_ref = _safe_scope(payload["scope_ref"])
        session_ref = _safe_ref(payload["session_ref"], "session:")
        secret = payload["shared_secret"]
        if type(secret) is not str:
            raise _reject("host endpoint handshake secret is invalid", "HOST_AUTHORITY_REQUIRED")
        try:
            secret_bytes = bytes.fromhex(secret)
        except ValueError as exc:
            raise _reject("host endpoint handshake secret is not hex", "HOST_AUTHORITY_REQUIRED") from exc
        if len(secret_bytes) < 32:
            raise _reject("host endpoint handshake secret is too short", "HOST_AUTHORITY_REQUIRED")
        purpose_prefix = payload["purpose_prefix"]
        if type(purpose_prefix) is not str or not purpose_prefix.startswith("agent."):
            raise _reject("host endpoint purpose is invalid", "HOST_AUTHORITY_REQUIRED")
        value = object.__new__(cls)
        for name, item in (
            ("endpoint_path", endpoint_path),
            ("endpoint_device", payload["endpoint_device"]),
            ("endpoint_inode", payload["endpoint_inode"]),
            ("peer_uid", payload["peer_uid"]),
            ("peer_pid", payload["peer_pid"]),
            ("scope_ref", scope_ref),
            ("session_ref", session_ref),
            ("shared_secret", secret),
            ("purpose_prefix", purpose_prefix),
        ):
            object.__setattr__(value, name, item)
        with _CONFIG_ADMISSIONS_LOCK:
            _CONFIG_ADMISSIONS[value] = (value, _config_snapshot(value))
        return value

    @property
    def secret_bytes(self) -> bytes:
        _require_config(self)
        try:
            return bytes.fromhex(self.shared_secret)
        except (AttributeError, TypeError, ValueError) as exc:
            raise _reject("host endpoint handshake secret is invalid") from exc

    def identity_wire(self) -> dict[str, object]:
        _require_config(self)
        return {
            "endpoint_path": self.endpoint_path,
            "endpoint_device": self.endpoint_device,
            "endpoint_inode": self.endpoint_inode,
            "peer_uid": self.peer_uid,
            "peer_pid": self.peer_pid,
            "scope_ref": self.scope_ref,
            "session_ref": self.session_ref,
            "purpose_prefix": self.purpose_prefix,
        }

    def __copy__(self) -> "HostAuthorityEndpointConfigV1":
        raise TypeError("host endpoint configuration cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> "HostAuthorityEndpointConfigV1":
        raise TypeError("host endpoint configuration cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("host endpoint configuration cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("host endpoint configuration cannot be serialized")


_CONFIG_ADMISSIONS: WeakKeyDictionary[HostAuthorityEndpointConfigV1, tuple[object, ...]] = WeakKeyDictionary()
_CONFIG_ADMISSIONS_LOCK = RLock()


def _require_config(config: object) -> HostAuthorityEndpointConfigV1:
    if type(config) is not HostAuthorityEndpointConfigV1:
        raise _reject("deployment-owned host configuration is required", "HOST_AUTHORITY_REQUIRED")
    try:
        with _CONFIG_ADMISSIONS_LOCK:
            record = _CONFIG_ADMISSIONS.get(config)
        if record is None or record[0] is not config or record[1] != _config_snapshot(config):
            raise _reject("host configuration was not loaded from deployment", "HOST_AUTHORITY_REQUIRED")
        return config
    except HostAuthorityChannelError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise _reject("host configuration is malformed", "HOST_AUTHORITY_REQUIRED") from exc


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise _reject("host configuration contains duplicate keys", "HOST_AUTHORITY_REQUIRED")
        result[key] = value
    return result


def _read_deployment_file(path_value: object) -> dict[str, object]:
    if type(path_value) is not str or not path_value.startswith("/") or "\x00" in path_value:
        raise _reject("host configuration path is invalid", "HOST_AUTHORITY_REQUIRED")
    path = Path(path_value)
    try:
        parent_stat = os.lstat(path.parent)
        if (
            stat.S_ISLNK(parent_stat.st_mode)
            or not stat.S_ISDIR(parent_stat.st_mode)
            or parent_stat.st_mode & 0o022
        ):
            raise _reject("host configuration parent is not deployment-owned", "HOST_AUTHORITY_REQUIRED")
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except HostAuthorityChannelError:
        raise
    except OSError as exc:
        raise _reject("host configuration file is unavailable", "HOST_AUTHORITY_REQUIRED") from exc
    try:
        info = os.fstat(fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_mode & 0o022
            or int(info.st_uid) not in {0, os.getuid()}
        ):
            raise _reject("host configuration file is not deployment-owned", "HOST_AUTHORITY_REQUIRED")
        raw = os.read(fd, _MAX_CONFIG_BYTES + 1)
        if len(raw) > _MAX_CONFIG_BYTES:
            raise _reject("host configuration file exceeds its limit", "HOST_AUTHORITY_REQUIRED")
    except HostAuthorityChannelError:
        raise
    except OSError as exc:
        raise _reject("host configuration file could not be read", "HOST_AUTHORITY_REQUIRED") from exc
    finally:
        os.close(fd)
    try:
        payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, HostAuthorityChannelError) as exc:
        raise _reject("host configuration is not valid JSON", "HOST_AUTHORITY_REQUIRED") from exc
    if type(payload) is not dict:
        raise _reject("host configuration must be an object", "HOST_AUTHORITY_REQUIRED")
    return payload


def load_host_authority_config() -> HostAuthorityEndpointConfigV1:
    """Load the deployment-supplied authority identity.

    The path is intentionally not an API argument.  It comes from the host
    process environment established at service startup, and the file itself
    must be stable and non-writable by group/other users.  An absent setting is
    a typed fail-closed condition.
    """

    path = os.environ.get(_CONFIG_ENV)
    if not path:
        raise _reject("no configured host authority endpoint", "HOST_AUTHORITY_REQUIRED")
    return HostAuthorityEndpointConfigV1._from_deployment_payload(_read_deployment_file(path))


def _peer_uid_pid(channel: socket.socket) -> tuple[int, int]:
    try:
        if sys.platform == "darwin":
            libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
            getpeereid = libc.getpeereid
            getpeereid.argtypes = [
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_uint),
                ctypes.POINTER(ctypes.c_uint),
            ]
            getpeereid.restype = ctypes.c_int
            uid = ctypes.c_uint()
            gid = ctypes.c_uint()
            if getpeereid(channel.fileno(), ctypes.byref(uid), ctypes.byref(gid)) != 0:
                raise OSError(ctypes.get_errno(), "getpeereid failed")
            raw_pid = channel.getsockopt(_MACOS_SOL_LOCAL, _MACOS_LOCAL_PEERPID, 4)
            peer_pid = struct.unpack("=i", raw_pid)[0]
            return int(uid.value), int(peer_pid)
        peer_cred = getattr(socket, "SO_PEERCRED", None)
        if peer_cred is not None:
            raw = channel.getsockopt(socket.SOL_SOCKET, peer_cred, struct.calcsize("=3i"))
            peer_pid, peer_uid, _peer_gid = struct.unpack("=3i", raw)
            return int(peer_uid), int(peer_pid)
        local_peer_cred = getattr(socket, "LOCAL_PEERCRED", None)
        if local_peer_cred is not None:
            raw = channel.getsockopt(0, local_peer_cred, 64)
            if len(raw) < 8:
                raise OSError("LOCAL_PEERCRED response is incomplete")
            peer_uid = struct.unpack_from("=I", raw, 4)[0]
            local_peer_pid = getattr(socket, "LOCAL_PEERPID", _MACOS_LOCAL_PEERPID)
            raw_pid = channel.getsockopt(0, local_peer_pid, 4)
            peer_pid = struct.unpack("=i", raw_pid)[0]
            return int(peer_uid), int(peer_pid)
    except (AttributeError, OSError, struct.error, TypeError, ValueError) as exc:
        raise _reject("host endpoint peer credentials are unavailable") from exc
    raise _reject("host endpoint peer credentials are unsupported")


def _endpoint_path(channel: socket.socket) -> str:
    try:
        value = channel.getpeername()
    except OSError as exc:
        raise _reject("host endpoint has no pathname identity") from exc
    if isinstance(value, bytes):
        try:
            value = os.fsdecode(value)
        except (TypeError, UnicodeError) as exc:
            raise _reject("host endpoint pathname is invalid") from exc
    if type(value) is not str or not value.startswith("/") or "\x00" in value:
        raise _reject("anonymous and abstract sockets are not host endpoints")
    return value


def _validate_path_components(path: Path) -> None:
    """Reject a stable-looking endpoint whose parent chain contains a symlink."""

    parts = path.parts
    if not parts or parts[0] != "/":
        raise _reject("host endpoint path must be absolute")
    current = Path(parts[0])
    for part in parts[1:]:
        current /= part
        try:
            info = os.lstat(current)
        except OSError as exc:
            raise _reject("host endpoint path component is unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            raise _reject("host endpoint path component is a symlink")


def _validate_endpoint_identity(channel: socket.socket, config: HostAuthorityEndpointConfigV1) -> None:
    _require_config(config)
    try:
        if type(channel) is not socket.socket:
            raise _reject("host endpoint channel is not a socket")
        if channel.fileno() < 0 or channel.family != socket.AF_UNIX or channel.type & 0xF != socket.SOCK_STREAM:
            raise _reject("host endpoint channel is not a Unix stream")
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise _reject("host endpoint channel is invalid") from exc
    peer_uid, peer_pid = _peer_uid_pid(channel)
    if peer_uid != config.peer_uid or peer_pid != config.peer_pid:
        raise _reject("host endpoint peer identity does not match deployment config")
    if peer_pid == os.getpid():
        raise _reject("host authority must be an external process")
    if _endpoint_path(channel) != config.endpoint_path:
        raise _reject("host endpoint path does not match deployment config")
    endpoint_path = Path(config.endpoint_path)
    _validate_path_components(endpoint_path)
    try:
        parent_stat = os.lstat(endpoint_path.parent)
        endpoint_stat = os.lstat(endpoint_path)
    except OSError as exc:
        raise _reject("configured host endpoint is unavailable") from exc
    if (
        stat.S_ISLNK(parent_stat.st_mode)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or parent_stat.st_mode & 0o022
        or int(parent_stat.st_uid) not in {0, config.peer_uid}
        or stat.S_ISLNK(endpoint_stat.st_mode)
        or not stat.S_ISSOCK(endpoint_stat.st_mode)
        or int(endpoint_stat.st_uid) != config.peer_uid
        or (int(endpoint_stat.st_dev), int(endpoint_stat.st_ino))
        != (config.endpoint_device, config.endpoint_inode)
    ):
        raise _reject("configured host endpoint identity is unstable")


def _read_frame(channel: socket.socket) -> dict[str, object]:
    raw = bytearray()
    while len(raw) <= _MAX_FRAME_BYTES:
        try:
            chunk = channel.recv(4096)
        except (OSError, TimeoutError) as exc:
            raise _reject("host authority response could not be read") from exc
        if not chunk:
            raise _reject("host authority channel closed")
        raw.extend(chunk)
        if b"\n" not in chunk:
            continue
        frame, _separator, _tail = bytes(raw).partition(b"\n")
        if not frame:
            raise _reject("host authority response is empty")
        try:
            value = json.loads(frame.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise _reject("host authority response is invalid JSON") from exc
        if type(value) is not dict:
            raise _reject("host authority response is not an object")
        return value
    raise _reject("host authority response exceeds its frame limit")


def _rpc(channel: socket.socket, operation: str, payload: Mapping[str, object]) -> dict[str, object]:
    try:
        encoded = (
            canonical_json_v1(
                {
                    "schema_version": _PROTOCOL_VERSION,
                    "operation": operation,
                    "payload": dict(payload),
                }
            ).encode("utf-8")
            + b"\n"
        )
    except (RecursionError, TypeError, ValueError, OverflowError) as exc:
        raise _reject("host authority request is not canonical") from exc
    if len(encoded) > _MAX_FRAME_BYTES:
        raise _reject("host authority request exceeds its frame limit")
    try:
        channel.sendall(encoded)
        response = _read_frame(channel)
    except HostAuthorityChannelError:
        raise
    except (AttributeError, OSError, TimeoutError, ValueError) as exc:
        raise _reject("host authority request failed") from exc
    if (
        response.get("schema_version") != _PROTOCOL_VERSION
        or type(response.get("ok")) is not bool
    ):
        raise _reject("host authority response envelope is invalid")
    if not response["ok"]:
        code = response.get("code")
        raise _reject(
            str(response.get("message") or "host authority rejected request"),
            str(code or "FORGED_AUTHORITY"),
        )
    result = response.get("payload")
    if type(result) is not dict:
        raise _reject("host authority response payload is invalid")
    return result


def _handshake(channel: socket.socket, config: HostAuthorityEndpointConfigV1, owner_pid: int) -> str:
    challenge = secrets.token_hex(32)
    identity = config.identity_wire()
    response = _rpc(
        channel,
        "session",
        {
            "endpoint": identity,
            "owner_pid": owner_pid,
            "challenge": challenge,
        },
    )
    session_ref = response.get("session_ref")
    attestation = response.get("attestation")
    if type(session_ref) is not str or session_ref != config.session_ref:
        raise _reject("host did not issue the configured session binding")
    try:
        expected = hmac.new(
            config.secret_bytes,
            canonical_json_v1(
                {
                    "challenge": challenge,
                    "endpoint": identity,
                    "owner_pid": owner_pid,
                    "session_ref": session_ref,
                }
            ).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
    except (HostAuthorityChannelError, TypeError, ValueError, RecursionError) as exc:
        raise _reject("host handshake could not be verified") from exc
    if type(attestation) is not str or not hmac.compare_digest(attestation, expected):
        raise _reject("host endpoint handshake was not attested by deployment")
    return session_ref


class HostAuthorityHandleV1:
    """A non-serializable, process-bound handle to an admitted host endpoint."""

    __slots__ = (
        "_socket",
        "_lock",
        "_channel_id",
        "_closed",
        "_config",
        "_owner_pid",
        "_channel_device",
        "_channel_inode",
        "_session_ref",
        "__weakref__",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("host authority handles are issued by deployment admission")

    @classmethod
    def _from_host_socket(cls, *_args: object, **_kwargs: object) -> "HostAuthorityHandleV1":
        raise TypeError("raw sockets cannot be converted into host authority handles")

    @property
    def channel_id(self) -> str:
        _require_handle(self)
        return self._channel_id

    def _assert_live(self) -> None:
        _require_handle(self)

    def _request(self, operation: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        handle = _require_handle(self)
        if type(operation) is not str or not operation:
            raise _reject("host authority operation is invalid")
        with handle._lock:
            try:
                response = _rpc(handle._socket, operation, payload)
            except HostAuthorityChannelError:
                raise
            except (AttributeError, OSError, TimeoutError, ValueError) as exc:
                raise _reject("host authority request failed") from exc
        _require_handle(handle)
        return response

    def bind_scope(
        self,
        *,
        scope_ref: str,
        principal_ref: str,
        session_ref: str,
        project_ref: str,
    ) -> dict[str, str]:
        return self._request(
            "bind_scope",
            {
                "scope_ref": scope_ref,
                "principal_ref": principal_ref,
                "session_ref": session_ref,
                "project_ref": project_ref,
            },
        )

    def validate_binding(self, binding_id: str) -> dict[str, str]:
        return self._request("validate_binding", {"binding_id": binding_id})

    def issue_discovery_receipt(
        self,
        *,
        binding_id: str,
        query: str,
        manifest_digest: str,
        capability_ids: Iterable[str],
        receipt_digest: str,
    ) -> dict[str, Any]:
        return self._request(
            "issue_discovery_receipt",
            {
                "binding_id": binding_id,
                "query": query,
                "manifest_digest": manifest_digest,
                "capability_ids": list(capability_ids),
                "receipt_digest": receipt_digest,
            },
        )

    def validate_discovery_receipt(self, receipt_id: str) -> dict[str, Any]:
        return self._request("validate_discovery_receipt", {"receipt_id": receipt_id})

    def issue_selection(
        self,
        *,
        receipt_id: str,
        capability_id: str,
        binding_id: str,
        manifest_digest: str,
    ) -> dict[str, Any]:
        return self._request(
            "issue_selection",
            {
                "receipt_id": receipt_id,
                "capability_id": capability_id,
                "binding_id": binding_id,
                "manifest_digest": manifest_digest,
            },
        )

    def validate_selection(self, selection_id: str) -> dict[str, Any]:
        return self._request("validate_selection", {"selection_id": selection_id})

    def close(self) -> None:
        try:
            object.__setattr__(self, "_closed", True)
            self._socket.close()
        except (AttributeError, OSError, TypeError, ValueError):
            object.__setattr__(self, "_closed", True)

    def __copy__(self) -> "HostAuthorityHandleV1":
        raise TypeError("host authority handles cannot be copied")

    def __deepcopy__(self, _memo: dict[int, object]) -> "HostAuthorityHandleV1":
        raise TypeError("host authority handles cannot be copied")

    def __reduce__(self) -> tuple[object, ...]:
        raise TypeError("host authority handles cannot be serialized")

    def __reduce_ex__(self, _protocol: int) -> tuple[object, ...]:
        raise TypeError("host authority handles cannot be serialized")


_HANDLE_ADMISSIONS: WeakKeyDictionary[HostAuthorityHandleV1, tuple[object, ...]] = WeakKeyDictionary()
_HANDLE_ADMISSIONS_LOCK = RLock()


def _require_handle(handle: object) -> HostAuthorityHandleV1:
    if type(handle) is not HostAuthorityHandleV1:
        raise _reject("an admitted host endpoint handle is required")
    try:
        with _HANDLE_ADMISSIONS_LOCK:
            record = _HANDLE_ADMISSIONS.get(handle)
        if record is None or record[0] is not handle:
            raise _reject("host endpoint handle was not admitted by deployment")
        (
            _identity,
            channel,
            config,
            owner_pid,
            channel_device,
            channel_inode,
            session_ref,
            channel_id,
        ) = record
        channel_stat = os.fstat(channel.fileno())
        if (
            handle._socket is not channel
            or handle._config is not config
            or handle._owner_pid != owner_pid
            or handle._channel_device != channel_device
            or handle._channel_inode != channel_inode
            or handle._session_ref != session_ref
            or handle._channel_id != channel_id
            or owner_pid != os.getpid()
            or type(channel) is not socket.socket
            or channel.fileno() < 0
            or (int(channel_stat.st_dev), int(channel_stat.st_ino)) != (channel_device, channel_inode)
            or handle._closed
        ):
            raise _reject("host endpoint handle binding changed")
        _validate_endpoint_identity(channel, config)
        return handle
    except HostAuthorityChannelError:
        raise
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise _reject("host endpoint handle is invalid") from exc


def admit_host_authority_endpoint(
    authority_handle: object,
    *,
    deployment_config: HostAuthorityEndpointConfigV1,
) -> HostAuthorityHandleV1:
    """Admit a connected endpoint using only deployment configuration."""

    config = _require_config(deployment_config)
    if type(authority_handle) is not socket.socket:
        raise _reject("host endpoint admission requires a raw Unix socket")
    try:
        authority_handle.settimeout(_SOCKET_TIMEOUT_SECONDS)
        _validate_endpoint_identity(authority_handle, config)
        owner_pid = os.getpid()
        session_ref = _handshake(authority_handle, config, owner_pid)
        channel_stat = os.fstat(authority_handle.fileno())
        handle = object.__new__(HostAuthorityHandleV1)
        channel_id = "channel:" + secrets.token_hex(16)
        for name, value in (
            ("_socket", authority_handle),
            ("_lock", threading.RLock()),
            ("_channel_id", channel_id),
            ("_closed", False),
            ("_config", config),
            ("_owner_pid", owner_pid),
            ("_channel_device", int(channel_stat.st_dev)),
            ("_channel_inode", int(channel_stat.st_ino)),
            ("_session_ref", session_ref),
        ):
            object.__setattr__(handle, name, value)
        with _HANDLE_ADMISSIONS_LOCK:
            _HANDLE_ADMISSIONS[handle] = (
                handle,
                authority_handle,
                config,
                owner_pid,
                int(channel_stat.st_dev),
                int(channel_stat.st_ino),
                session_ref,
                channel_id,
            )
        _require_handle(handle)
        return handle
    except BaseException:
        try:
            authority_handle.close()
        except (AttributeError, OSError, ValueError):
            pass
        raise


def admit_host_authority_fd(
    fd: object,
    *,
    deployment_config: HostAuthorityEndpointConfigV1,
) -> HostAuthorityHandleV1:
    """Admit a supervisor-passed connected descriptor without trusting its integer."""

    config = _require_config(deployment_config)
    if type(fd) is not int or fd < 0:
        raise _reject("supervisor-passed host endpoint FD is invalid")
    try:
        duplicated_fd = os.dup(fd)
        channel = socket.socket(fileno=duplicated_fd)
    except (OSError, TypeError, ValueError) as exc:
        raise _reject("supervisor-passed host endpoint FD is unavailable") from exc
    try:
        return admit_host_authority_endpoint(channel, deployment_config=config)
    except BaseException:
        channel.close()
        raise


class HostAuthorityServerV1:
    """Removed in-process test server.

    Keeping the symbol makes the C0 import surface explicit, while making its
    constructor unusable prevents a caller from selecting scope, peer or
    handshake material inside the compiler process.  Production wiring owns a
    separate endpoint process and passes an admitted handle.
    """

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("host authority servers are deployment-owned and external")


HostAuthorityEndpointV1 = HostAuthorityHandleV1
HostAuthorityChannelV1 = HostAuthorityHandleV1


__all__ = [
    "HostAuthorityChannelError",
    "HostAuthorityEndpointConfigV1",
    "HostAuthorityEndpointV1",
    "HostAuthorityHandleV1",
    "HostAuthorityChannelV1",
    "HostAuthorityServerV1",
    "admit_host_authority_endpoint",
    "admit_host_authority_fd",
    "load_host_authority_config",
]
