"""External host authority channel for Evidence Core.

Evidence does not mint a signing key or accept a caller-shaped Python object
as an authority.  A raw socket is only admitted when a trusted deployment
configuration binds its pathname (or pre-admitted descriptor identity), peer
uid/pid, scope and session, and when the endpoint proves possession of the
deployment handshake secret.  The resulting endpoint handle is process- and
owner-bound; public Evidence factories never accept a raw socket.

The host runtime is intentionally outside this package for deployed hosts. A
local macOS backend may instead use the explicit bootstrap-only local handle;
it is still exact-object, process-bound and scope-bound, and it never accepts
an authority-shaped value from an HTTP request or an LLM.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import hashlib
import hmac
import json
import os
import secrets
import socket
import stat
import struct
import sys
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final
from weakref import WeakKeyDictionary

from workbench.canonical import canonical_json_v1


EVIDENCE_HOST_AUTHORITY_REQUIRED: Final[str] = "EVIDENCE_HOST_AUTHORITY_REQUIRED"
EVIDENCE_HOST_AUTHORITY_UNAVAILABLE: Final[str] = "EVIDENCE_HOST_AUTHORITY_UNAVAILABLE"
EVIDENCE_HOST_AUTHORITY_TIMEOUT: Final[str] = "EVIDENCE_HOST_AUTHORITY_TIMEOUT"
_MAX_FRAME_BYTES: Final[int] = 64 * 1024
EVIDENCE_HOST_AUTHORITY_RPC_TIMEOUT_SECONDS: Final[float] = 1.0
_MACOS_SOL_LOCAL: Final[int] = 0
_MACOS_LOCAL_PEERPID: Final[int] = 0x002
_CHANNEL_LOCKS: WeakKeyDictionary[object, threading.RLock] = WeakKeyDictionary()
_CHANNEL_LOCKS_GUARD = threading.Lock()
_ENDPOINT_ADMISSIONS: WeakKeyDictionary[object, tuple[object, ...]] = WeakKeyDictionary()
_ENDPOINT_ADMISSIONS_GUARD = threading.Lock()
_LOCAL_AUTHORITY_ISSUER = object()
_LOCAL_AUTHORITY_ADMISSIONS: dict[int, tuple[object, ...]] = {}
_LOCAL_AUTHORITY_ADMISSIONS_GUARD = threading.Lock()


class EvidenceHostAuthorityError(ValueError):
    """A stable fail-closed error for an absent or invalid host authority."""

    def __init__(self, code: str = EVIDENCE_HOST_AUTHORITY_REQUIRED, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or code)


def _deployment_config_from_supervisor() -> "HostAuthorityEndpointConfigV1":
    """Return deployment-owned authority material, or fail closed.

    The production host adapter must replace this seam with a resolver backed
    by its supervisor/OS boundary.  Evidence intentionally has no default
    environment, module secret, or caller registration API.  Package-local
    tests patch this seam only to model that external boundary; a caller that
    supplies ``deployment_config`` to a public admission function is never
    accepted as the trust root.
    """

    raise EvidenceHostAuthorityError(
        EVIDENCE_HOST_AUTHORITY_REQUIRED,
        "no deployment-owned host authority resolver is configured",
    )


@dataclass(frozen=True, slots=True)
class HostAuthorityEndpointConfigV1:
    """Deployment-owned identity of the host authority endpoint.

    This value is deployment input, not request input.  Production must load
    it from a supervisor-owned configuration channel or pair it with a
    supervisor-admitted descriptor.  Evidence never invents a default path,
    uid, pid, session, or handshake secret.

    ``endpoint_path`` is always required, including when the host supplies a
    pre-admitted FD.  This deliberately excludes anonymous and abstract
    sockets from the trust root.  ``shared_secret`` is deployment material
    used only for the bootstrap
    attestation; it is never generated or persisted by Evidence.
    """

    endpoint_path: str
    endpoint_device: int
    endpoint_inode: int
    peer_uid: int
    peer_pid: int
    scope_ref: str
    session_ref: str
    shared_secret: str
    purpose_prefix: str = "evidence."

    def __post_init__(self) -> None:
        if type(self.endpoint_path) is not str or not self.endpoint_path.startswith("/"):
            raise EvidenceHostAuthorityError(message="authority endpoint path is invalid")
        if "\x00" in self.endpoint_path or os.path.islink(self.endpoint_path):
            raise EvidenceHostAuthorityError(message="authority endpoint path is not stable")
        for name, value in (
            ("endpoint_device", self.endpoint_device),
            ("endpoint_inode", self.endpoint_inode),
            ("peer_uid", self.peer_uid),
            ("peer_pid", self.peer_pid),
        ):
            if type(value) is not int or value < 0:
                raise EvidenceHostAuthorityError(message=f"authority {name} is invalid")
        if self.peer_pid == 0:
            raise EvidenceHostAuthorityError(message="authority peer pid is invalid")
        if type(self.scope_ref) is not str or not self.scope_ref or "/" in self.scope_ref or "\\" in self.scope_ref:
            raise EvidenceHostAuthorityError(message="authority scope is invalid")
        if type(self.session_ref) is not str or not self.session_ref or "/" in self.session_ref:
            raise EvidenceHostAuthorityError(message="authority session is invalid")
        if type(self.shared_secret) is not str:
            raise EvidenceHostAuthorityError(message="authority handshake secret is invalid")
        try:
            secret = bytes.fromhex(self.shared_secret)
        except ValueError as exc:
            raise EvidenceHostAuthorityError(message="authority handshake secret is not hex") from exc
        if len(secret) < 32:
            raise EvidenceHostAuthorityError(message="authority handshake secret is too short")
        if type(self.purpose_prefix) is not str or not self.purpose_prefix.startswith("evidence."):
            raise EvidenceHostAuthorityError(message="authority purpose prefix is invalid")

    @property
    def secret_bytes(self) -> bytes:
        """Return deployment material for the one-time endpoint attestation."""

        return bytes.fromhex(self.shared_secret)

    def identity_wire(self) -> dict[str, object]:
        """Return non-secret identity claims sent to the host endpoint."""

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


_DEPLOYMENT_CONFIG_UNSET = object()


def _admission_config(candidate: object) -> HostAuthorityEndpointConfigV1:
    """Resolve configuration only from the deployment-owned host seam."""

    if candidate is not _DEPLOYMENT_CONFIG_UNSET:
        raise _reject(
            "caller-selected host authority configuration is not a trust root"
        )
    try:
        config = _deployment_config_from_supervisor()
    except EvidenceHostAuthorityError:
        raise
    except BaseException as exc:
        raise _reject("deployment host authority resolver failed closed") from exc
    if type(config) is not HostAuthorityEndpointConfigV1:
        raise _reject("deployment host authority resolver returned invalid input")
    return _copy_endpoint_config(config)


class HostAuthorityEndpointV1:
    """An admitted, owner-bound host endpoint capability.

    The constructor is intentionally unusable.  Instances are created only
    by :func:`admit_host_authority_endpoint` after OS identity and handshake
    checks.  A registry of the exact admitted object identity prevents
    ``object.__new__`` field copies from becoming capabilities; the owner PID
    check prevents fork reuse.
    """

    __slots__ = (
        "_channel",
        "_config",
        "_owner_pid",
        "_channel_device",
        "_channel_inode",
        "_session_ref",
        "__weakref__",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("host endpoints must come from server endpoint admission")

    @property
    def scope_ref(self) -> str:
        _require_endpoint(self)
        return self._config.scope_ref

    @property
    def session_ref(self) -> str:
        _require_endpoint(self)
        return self._session_ref

    def close(self) -> None:
        """Close the admitted channel; subsequent use fails closed."""

        _require_endpoint(self)
        self._channel.close()

    def __reduce__(self):
        raise TypeError("host endpoint handles are deployment-bound capabilities")

    def __copy__(self):
        raise TypeError("host endpoint handles are deployment-bound capabilities")

    def __deepcopy__(self, _memo: object):
        raise TypeError("host endpoint handles are deployment-bound capabilities")


class LocalHostAuthorityHandleV1:
    """Backend-owned authority for the explicitly supported local host.

    The constructor and bootstrap issuer are intentionally blocked. The local
    bootstrap service loads the key from its admission-gated project store and
    creates one exact handle. Public evidence code can only use the live object
    registered in ``_LOCAL_AUTHORITY_ADMISSIONS``; copying visible fields does
    not create a capability.
    """

    __slots__ = (
        "_authority_id",
        "_scope_ref",
        "_session_ref",
        "_owner_pid",
        "_secret",
        "_secret_digest",
        "_issuer",
        "_closed",
        "__weakref__",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("local authority handles must come from local host bootstrap")

    @classmethod
    def _from_bootstrap(
        cls,
        *,
        authority_id: str,
        scope_ref: str,
        session_ref: str,
        secret: bytes,
    ) -> "LocalHostAuthorityHandleV1":
        if (
            _LOCAL_AUTHORITY_ISSUER is None
            or type(authority_id) is not str
            or not authority_id
            or type(scope_ref) is not str
            or not scope_ref
            or type(session_ref) is not str
            or not session_ref
            or type(secret) is not bytes
            or len(secret) < 32
        ):
            raise _reject("local authority bootstrap material is invalid")
        handle = object.__new__(cls)
        object.__setattr__(handle, "_authority_id", authority_id)
        object.__setattr__(handle, "_scope_ref", scope_ref)
        object.__setattr__(handle, "_session_ref", session_ref)
        object.__setattr__(handle, "_owner_pid", os.getpid())
        object.__setattr__(handle, "_secret", bytes(secret))
        object.__setattr__(handle, "_secret_digest", hashlib.sha256(secret).hexdigest())
        object.__setattr__(handle, "_issuer", _LOCAL_AUTHORITY_ISSUER)
        object.__setattr__(handle, "_closed", False)
        with _LOCAL_AUTHORITY_ADMISSIONS_GUARD:
            _LOCAL_AUTHORITY_ADMISSIONS[id(handle)] = (
                handle,
                authority_id,
                scope_ref,
                session_ref,
                os.getpid(),
                hashlib.sha256(secret).hexdigest(),
                _LOCAL_AUTHORITY_ISSUER,
            )
        _require_local(handle)
        return handle

    @property
    def authority_id(self) -> str:
        _require_local(self)
        return self._authority_id

    @property
    def scope_ref(self) -> str:
        _require_local(self)
        return self._scope_ref

    @property
    def session_ref(self) -> str:
        _require_local(self)
        return self._session_ref

    def close(self) -> None:
        _require_local(self)
        with _LOCAL_AUTHORITY_ADMISSIONS_GUARD:
            _LOCAL_AUTHORITY_ADMISSIONS.pop(id(self), None)
        object.__setattr__(self, "_closed", True)

    def __reduce__(self):
        raise TypeError("local authority handles are backend-bound capabilities")

    def __copy__(self):
        raise TypeError("local authority handles cannot be copied")

    def __deepcopy__(self, _memo: object):
        raise TypeError("local authority handles cannot be copied")


@dataclass(frozen=True, slots=True)
class EvidenceAuthorityRequestV1:
    """The exact binding a host channel must authorize."""

    purpose: str
    scope_ref: str
    owner_pid: int
    session_ref: str
    root_fd: int | None
    root_device: int | None
    root_inode: int | None
    subject_id: int
    payload_digest: str

    def __post_init__(self) -> None:
        if type(self.purpose) is not str or not self.purpose or "/" in self.purpose:
            raise EvidenceHostAuthorityError(message="authority purpose is invalid")
        if type(self.scope_ref) is not str or not self.scope_ref:
            raise EvidenceHostAuthorityError(message="authority scope is invalid")
        if type(self.owner_pid) is not int or self.owner_pid <= 0:
            raise EvidenceHostAuthorityError(message="authority owner is invalid")
        if type(self.session_ref) is not str or not self.session_ref:
            raise EvidenceHostAuthorityError(message="authority session is invalid")
        if type(self.subject_id) is not int or self.subject_id <= 0:
            raise EvidenceHostAuthorityError(message="authority subject is invalid")
        if type(self.payload_digest) is not str or not self.payload_digest:
            raise EvidenceHostAuthorityError(message="authority payload binding is invalid")
        roots = (self.root_fd, self.root_device, self.root_inode)
        if any(value is not None for value in roots) and not all(value is not None for value in roots):
            raise EvidenceHostAuthorityError(message="authority root binding is incomplete")
        if any(type(value) is not int or value < 0 for value in roots if value is not None):
            raise EvidenceHostAuthorityError(message="authority root binding is invalid")

    def to_wire(self) -> dict[str, object]:
        return {
            "purpose": self.purpose,
            "scope_ref": self.scope_ref,
            "owner_pid": self.owner_pid,
            "session_ref": self.session_ref,
            "root_fd": self.root_fd,
            "root_device": self.root_device,
            "root_inode": self.root_inode,
            "subject_id": self.subject_id,
            "payload_digest": self.payload_digest,
        }


HostAuthorityChannelV1 = HostAuthorityEndpointV1
HostAuthorityHandleV1 = HostAuthorityEndpointV1


def _reject(
    message: str,
    *,
    code: str = EVIDENCE_HOST_AUTHORITY_REQUIRED,
) -> EvidenceHostAuthorityError:
    return EvidenceHostAuthorityError(code=code, message=message)


def _require_local(handle: object) -> LocalHostAuthorityHandleV1:
    if type(handle) is not LocalHostAuthorityHandleV1:
        raise _reject("Evidence requires a server-owned local authority handle")
    try:
        with _LOCAL_AUTHORITY_ADMISSIONS_GUARD:
            record = _LOCAL_AUTHORITY_ADMISSIONS.get(id(handle))
        if (
            record is None
            or record[0] is not handle
            or handle._issuer is not _LOCAL_AUTHORITY_ISSUER
            or handle._closed is not False
            or handle._owner_pid != os.getpid()
            or record[1] != handle._authority_id
            or record[2] != handle._scope_ref
            or record[3] != handle._session_ref
            or record[4] != handle._owner_pid
            or record[5] != handle._secret_digest
            or hashlib.sha256(handle._secret).hexdigest() != handle._secret_digest
            or record[6] is not _LOCAL_AUTHORITY_ISSUER
        ):
            raise _reject("the local authority handle binding changed")
        return handle
    except EvidenceHostAuthorityError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise _reject("the local authority handle is invalid") from exc


def _is_local_handle(handle: object) -> bool:
    return type(handle) is LocalHostAuthorityHandleV1


def _local_request_wire(
    handle: LocalHostAuthorityHandleV1,
    request: EvidenceAuthorityRequestV1,
) -> bytes:
    _require_local(handle)
    if type(request) is not EvidenceAuthorityRequestV1:
        raise _reject("the local authority request is malformed")
    if (
        request.owner_pid != os.getpid()
        or request.scope_ref != handle._scope_ref
        or request.session_ref != handle._session_ref
        or not request.purpose.startswith("evidence.")
    ):
        raise _reject("the local authority request is not backend-bound")
    if request.root_fd is not None:
        root_device, root_inode = _root_identity(request.root_fd)
        if (root_device, root_inode) != (request.root_device, request.root_inode):
            raise _reject("the local authority root identity changed")
    return canonical_json_v1(
        {
            "authority_id": handle._authority_id,
            "request": request.to_wire(),
        }
    ).encode("utf-8")


def _copy_endpoint_config(config: HostAuthorityEndpointConfigV1) -> HostAuthorityEndpointConfigV1:
    return HostAuthorityEndpointConfigV1(
        endpoint_path=config.endpoint_path,
        endpoint_device=config.endpoint_device,
        endpoint_inode=config.endpoint_inode,
        peer_uid=config.peer_uid,
        peer_pid=config.peer_pid,
        scope_ref=config.scope_ref,
        session_ref=config.session_ref,
        shared_secret=config.shared_secret,
        purpose_prefix=config.purpose_prefix,
    )


def _raw_channel(handle: object) -> socket.socket:
    if type(handle) is not socket.socket:
        raise _reject("the authority admission handle must be a raw Unix socket")
    try:
        fileno = handle.fileno()
        family = handle.family
        socket_type = handle.type & 0xF
    except (AttributeError, OSError) as exc:
        raise _reject("the authority admission handle is unavailable") from exc
    if fileno < 0 or family != socket.AF_UNIX or socket_type != socket.SOCK_STREAM:
        raise _reject("the authority admission handle is not a Unix stream socket")
    return handle


def _set_channel_non_inheritable(channel: socket.socket) -> None:
    try:
        channel.set_inheritable(False)
        if channel.get_inheritable():
            raise OSError("authority channel remained inheritable")
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise _reject("the authority channel could not be made non-inheritable") from exc


def _peer_uid_pid(channel: socket.socket) -> tuple[int, int]:
    try:
        if sys.platform == "darwin":
            libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.dylib", use_errno=True)
            getpeereid = libc.getpeereid
            getpeereid.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
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
        raise _reject("the host endpoint peer credentials are unavailable") from exc
    raise _reject("the host endpoint peer credentials are unsupported")


def _endpoint_path(channel: socket.socket) -> str:
    try:
        peer_name = channel.getpeername()
    except OSError as exc:
        raise _reject("the host endpoint has no peer identity") from exc
    if isinstance(peer_name, bytes):
        try:
            peer_name = os.fsdecode(peer_name)
        except (TypeError, UnicodeError) as exc:
            raise _reject("the host endpoint path is invalid") from exc
    if type(peer_name) is not str or not peer_name.startswith("/") or "\x00" in peer_name:
        raise _reject("anonymous and abstract Unix sockets are not host endpoints")
    return peer_name


def _validate_endpoint_identity(channel: socket.socket, config: HostAuthorityEndpointConfigV1) -> None:
    peer_uid, peer_pid = _peer_uid_pid(channel)
    if peer_uid != config.peer_uid or peer_pid != config.peer_pid:
        raise _reject("the host endpoint peer identity does not match deployment config")
    peer_path = _endpoint_path(channel)
    if peer_path != config.endpoint_path:
        raise _reject("the host endpoint path does not match deployment config")
    parent_path = os.path.dirname(config.endpoint_path)
    try:
        parent_stat = os.lstat(parent_path)
    except OSError as exc:
        raise _reject("the host endpoint parent is unavailable") from exc
    if (
        stat.S_ISLNK(parent_stat.st_mode)
        or not stat.S_ISDIR(parent_stat.st_mode)
        or int(parent_stat.st_uid) not in {0, config.peer_uid}
        or (parent_stat.st_mode & 0o022)
    ):
        raise _reject("the host endpoint parent is not deployment-owned")
    try:
        endpoint_stat = os.lstat(config.endpoint_path)
    except OSError as exc:
        raise _reject("the configured host endpoint is unavailable") from exc
    if (
        stat.S_ISLNK(endpoint_stat.st_mode)
        or not stat.S_ISSOCK(endpoint_stat.st_mode)
        or int(endpoint_stat.st_uid) != config.peer_uid
    ):
        raise _reject("the configured host endpoint is not a stable Unix socket")
    endpoint_device = int(endpoint_stat.st_dev)
    endpoint_inode = int(endpoint_stat.st_ino)
    if (endpoint_device, endpoint_inode) != (config.endpoint_device, config.endpoint_inode):
        raise _reject("the host endpoint inode identity does not match deployment config")


def _channel_lock(handle: object) -> threading.RLock:
    with _CHANNEL_LOCKS_GUARD:
        lock = _CHANNEL_LOCKS.get(handle)
        if lock is None:
            lock = threading.RLock()
            _CHANNEL_LOCKS[handle] = lock
        return lock


def _read_frame(channel: socket.socket) -> dict[str, object]:
    raw = bytearray()
    while len(raw) <= _MAX_FRAME_BYTES:
        try:
            chunk = channel.recv(4096)
        except socket.timeout as exc:
            raise _reject(
                "the host authority response timed out",
                code=EVIDENCE_HOST_AUTHORITY_TIMEOUT,
            ) from exc
        except OSError as exc:
            raise EvidenceHostAuthorityError(
                EVIDENCE_HOST_AUTHORITY_UNAVAILABLE,
                "the host authority response could not be read",
            ) from exc
        if not chunk:
            raise _reject(
                "the host authority channel closed",
                code=EVIDENCE_HOST_AUTHORITY_UNAVAILABLE,
            )
        raw.extend(chunk)
        if b"\n" in chunk:
            frame, _, tail = bytes(raw).partition(b"\n")
            if tail:
                raise _reject("the host authority response contains extra frames")
            if not frame:
                raise _reject("the host authority response is empty")
            try:
                value = json.loads(frame.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
                raise _reject("the host authority response is invalid JSON") from exc
            if type(value) is not dict:
                raise _reject("the host authority response is not an object")
            return value
    raise _reject("the host authority response exceeds the frame limit")


def _rpc_socket(channel: socket.socket, message: Mapping[str, object]) -> dict[str, object]:
    try:
        raw = canonical_json_v1(dict(message)).encode("utf-8") + b"\n"
    except (TypeError, ValueError, OverflowError, RecursionError) as exc:
        raise _reject("the host authority request is not canonical") from exc
    if len(raw) > _MAX_FRAME_BYTES:
        raise _reject("the host authority request exceeds the frame limit")
    with _channel_lock(channel):
        try:
            previous_timeout = channel.gettimeout()
            channel.settimeout(EVIDENCE_HOST_AUTHORITY_RPC_TIMEOUT_SECONDS)
        except (AttributeError, OSError, ValueError) as exc:
            raise EvidenceHostAuthorityError(
                EVIDENCE_HOST_AUTHORITY_UNAVAILABLE,
                "the host authority channel could not be configured",
            ) from exc
        try:
            channel.sendall(raw)
            return _read_frame(channel)
        except socket.timeout as exc:
            raise EvidenceHostAuthorityError(
                EVIDENCE_HOST_AUTHORITY_TIMEOUT,
                "the host authority request timed out",
            ) from exc
        except EvidenceHostAuthorityError:
            raise
        except OSError as exc:
            raise EvidenceHostAuthorityError(
                EVIDENCE_HOST_AUTHORITY_UNAVAILABLE,
                "the host authority request could not be sent",
            ) from exc
        finally:
            try:
                channel.settimeout(previous_timeout)
            except (OSError, ValueError):
                pass


def _handshake(channel: socket.socket, config: HostAuthorityEndpointConfigV1, owner_pid: int) -> str:
    challenge = secrets.token_hex(32)
    identity = config.identity_wire()
    response = _rpc_socket(
        channel,
        {
            "operation": "session",
            "request": {
                "endpoint": identity,
                "owner_pid": owner_pid,
                "challenge": challenge,
            },
        },
    )
    session_ref = response.get("session_ref")
    attestation = response.get("attestation")
    if response.get("ok") is not True or type(session_ref) is not str or session_ref != config.session_ref:
        raise _reject("the host did not issue the configured session binding")
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
    if type(attestation) is not str or not hmac.compare_digest(attestation, expected):
        raise _reject("the host endpoint handshake was not attested by deployment")
    return session_ref


def _admit_host_authority_endpoint_with_config(
    authority_handle: object,
    *,
    deployment_config: HostAuthorityEndpointConfigV1,
) -> HostAuthorityEndpointV1:
    """Internal admission after the host resolver supplied its snapshot."""

    if type(deployment_config) is not HostAuthorityEndpointConfigV1:
        raise _reject("deployment host authority resolver returned invalid input")
    channel = _raw_channel(authority_handle)
    _set_channel_non_inheritable(channel)
    _validate_endpoint_identity(channel, deployment_config)
    owner_pid = os.getpid()
    try:
        session_ref = _handshake(channel, deployment_config, owner_pid)
        config_snapshot = _copy_endpoint_config(deployment_config)
        endpoint = object.__new__(HostAuthorityEndpointV1)
        channel_stat = os.fstat(channel.fileno())
        object.__setattr__(endpoint, "_channel", channel)
        object.__setattr__(endpoint, "_config", config_snapshot)
        object.__setattr__(endpoint, "_owner_pid", owner_pid)
        object.__setattr__(endpoint, "_channel_device", int(channel_stat.st_dev))
        object.__setattr__(endpoint, "_channel_inode", int(channel_stat.st_ino))
        object.__setattr__(endpoint, "_session_ref", session_ref)
        with _ENDPOINT_ADMISSIONS_GUARD:
            _ENDPOINT_ADMISSIONS[endpoint] = (
                endpoint,
                channel,
                config_snapshot,
                owner_pid,
                int(channel_stat.st_dev),
                int(channel_stat.st_ino),
                session_ref,
                canonical_json_v1(config_snapshot.identity_wire()),
                hashlib.sha256(config_snapshot.shared_secret.encode("ascii")).hexdigest(),
            )
        _require_endpoint(endpoint)
        return endpoint
    except EvidenceHostAuthorityError:
        raise
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise _reject("the host endpoint admission failed closed") from exc


def admit_host_authority_endpoint(
    authority_handle: object,
    *,
    deployment_config: object = _DEPLOYMENT_CONFIG_UNSET,
) -> HostAuthorityEndpointV1:
    """Admit a raw channel using only deployment-resolved identity.

    ``deployment_config`` is retained as a compatibility-shaped keyword only
    so old callers receive a stable typed rejection.  Public callers may not
    provide trust-root fields; the supervisor resolver is the sole accepted
    source.
    """

    config = _admission_config(deployment_config)
    return _admit_host_authority_endpoint_with_config(
        authority_handle,
        deployment_config=config,
    )


def admit_host_authority_fd(
    fd: object,
    *,
    deployment_config: object = _DEPLOYMENT_CONFIG_UNSET,
) -> HostAuthorityEndpointV1:
    """Admit a supervisor-passed FD using host-resolved identity."""

    config = _admission_config(deployment_config)
    if type(fd) is not int or fd < 0:
        raise _reject("the pre-admitted host endpoint FD is invalid")
    duplicated_fd = -1
    channel: socket.socket | None = None
    try:
        duplicated_fd = os.dup(fd)
        os.set_inheritable(duplicated_fd, False)
        channel = socket.socket(fileno=duplicated_fd)
        duplicated_fd = -1
    except (OSError, TypeError, ValueError) as exc:
        if channel is not None:
            channel.close()
        elif duplicated_fd >= 0:
            try:
                os.close(duplicated_fd)
            except OSError:
                pass
        raise _reject("the pre-admitted host endpoint FD is unavailable") from exc
    try:
        assert channel is not None
        return _admit_host_authority_endpoint_with_config(channel, deployment_config=config)
    except BaseException:
        if channel is not None:
            channel.close()
        raise


def _require_endpoint(handle: object) -> object:
    if _is_local_handle(handle):
        return _require_local(handle)
    if type(handle) is not HostAuthorityEndpointV1:
        raise _reject("Evidence requires an admitted host endpoint handle")
    try:
        with _ENDPOINT_ADMISSIONS_GUARD:
            record = _ENDPOINT_ADMISSIONS.get(handle)
        if record is None or record[0] is not handle:
            raise _reject("the host endpoint handle was not admitted by the server boundary")
        (
            channel,
            config,
            owner_pid,
            channel_device,
            channel_inode,
            session_ref,
            config_wire,
            secret_digest,
        ) = record[1:]
        if (
            handle._channel is not channel
            or handle._config != config
            or handle._owner_pid != owner_pid
            or handle._channel_device != channel_device
            or handle._channel_inode != channel_inode
            or handle._session_ref != session_ref
            or canonical_json_v1(handle._config.identity_wire()) != config_wire
            or hashlib.sha256(handle._config.shared_secret.encode("ascii")).hexdigest() != secret_digest
        ):
            raise _reject("the host endpoint handle binding changed")
        if owner_pid != os.getpid():
            raise _reject("the host endpoint handle belongs to another process")
        if type(channel) is not socket.socket or channel.fileno() < 0:
            raise _reject("the host endpoint channel is closed")
        _validate_endpoint_identity(channel, config)
        return handle
    except EvidenceHostAuthorityError:
        raise
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        raise _reject("the host endpoint handle is invalid") from exc


def _endpoint_channel(handle: object) -> tuple[HostAuthorityEndpointV1, socket.socket]:
    endpoint = _require_endpoint(handle)
    return endpoint, endpoint._channel


def build_authority_request(
    handle: object,
    *,
    purpose: str,
    scope_ref: str,
    subject_id: int,
    payload_digest: str,
    root_fd: int | None = None,
) -> EvidenceAuthorityRequestV1:
    """Build a request from live process, endpoint and descriptor identity."""

    if _is_local_handle(handle):
        local = _require_local(handle)
        if scope_ref != local._scope_ref:
            raise _reject("local authority scope is not backend-bound")
        if type(purpose) is not str or not purpose.startswith("evidence."):
            raise _reject("local authority purpose is not allowed")
        root_device, root_inode = _root_identity(root_fd)
        try:
            return EvidenceAuthorityRequestV1(
                purpose=purpose,
                scope_ref=scope_ref,
                owner_pid=os.getpid(),
                session_ref=local._session_ref,
                root_fd=root_fd,
                root_device=root_device,
                root_inode=root_inode,
                subject_id=subject_id,
                payload_digest=payload_digest,
            )
        except EvidenceHostAuthorityError:
            raise
        except (AttributeError, TypeError, ValueError) as exc:
            raise _reject("the local authority request is malformed") from exc
    endpoint = _require_endpoint(handle)
    if scope_ref != endpoint._config.scope_ref:
        raise _reject("authority scope is not bound to the configured endpoint")
    if type(purpose) is not str or not purpose.startswith(endpoint._config.purpose_prefix):
        raise _reject("authority purpose is not allowed by the configured endpoint")
    root_device, root_inode = _root_identity(root_fd)
    try:
        return EvidenceAuthorityRequestV1(
            purpose=purpose,
            scope_ref=scope_ref,
            owner_pid=os.getpid(),
            session_ref=endpoint._session_ref,
            root_fd=root_fd,
            root_device=root_device,
            root_inode=root_inode,
            subject_id=subject_id,
            payload_digest=payload_digest,
        )
    except EvidenceHostAuthorityError:
        raise
    except (AttributeError, TypeError, ValueError) as exc:
        raise _reject("the host authority request is malformed") from exc


def issue_host_proof(handle: object, request: EvidenceAuthorityRequestV1) -> str:
    """Ask the external host to issue an opaque proof."""

    if _is_local_handle(handle):
        local = _require_local(handle)
        wire = _local_request_wire(local, request)
        digest = hmac.new(local._secret, wire, hashlib.sha256).hexdigest()
        return f"local.v1:{local._authority_id}:{digest}"

    endpoint, channel = _endpoint_channel(handle)
    if type(request) is not EvidenceAuthorityRequestV1:
        raise _reject("the host authority request is malformed")
    try:
        request_scope = request.scope_ref
        request_session = request.session_ref
        request_wire = request.to_wire()
    except (AttributeError, TypeError, ValueError) as exc:
        raise _reject("the host authority request is malformed") from exc
    if request_scope != endpoint._config.scope_ref or request_session != endpoint._session_ref:
        raise _reject("the host authority request is not endpoint-bound")
    response = _rpc_socket(channel, {"operation": "issue", "request": request_wire})
    proof = response.get("proof")
    if response.get("ok") is not True or type(proof) is not str or not proof:
        raise _reject("the host refused the authority request")
    return proof


def validate_host_proof(
    handle: object,
    request: EvidenceAuthorityRequestV1,
    proof: object,
) -> None:
    """Fail closed unless the configured host validates the exact request."""

    if _is_local_handle(handle):
        local = _require_local(handle)
        wire = _local_request_wire(local, request)
        if type(proof) is not str or not proof.startswith(
            f"local.v1:{local._authority_id}:"
        ):
            raise _reject("the local authority proof is invalid")
        supplied = proof.rsplit(":", 1)[-1]
        expected = hmac.new(local._secret, wire, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(supplied, expected):
            raise _reject("the local authority rejected the exact request")
        return

    endpoint, channel = _endpoint_channel(handle)
    if type(request) is not EvidenceAuthorityRequestV1:
        raise _reject("the host authority request is malformed")
    try:
        request_owner = request.owner_pid
        request_scope = request.scope_ref
        request_session = request.session_ref
        request_root_fd = request.root_fd
        request_root_device = request.root_device
        request_root_inode = request.root_inode
        request_wire = request.to_wire()
    except (AttributeError, TypeError, ValueError) as exc:
        raise _reject("the host authority request is malformed") from exc
    if (
        request_owner != os.getpid()
        or request_scope != endpoint._config.scope_ref
        or request_session != endpoint._session_ref
        or type(proof) is not str
        or not proof
    ):
        raise _reject("the authority owner, endpoint or proof changed")
    if request_root_fd is not None:
        root_device, root_inode = _root_identity(request_root_fd)
        if (root_device, root_inode) != (request_root_device, request_root_inode):
            raise _reject("the authority root identity changed")
    response = _rpc_socket(
        channel,
        {
            "operation": "validate",
            "request": request_wire,
            "proof": proof,
        },
    )
    if response.get("ok") is not True or response.get("accepted") is not True:
        raise _reject("the host rejected the authority proof")


def _root_identity(root_fd: int | None) -> tuple[int | None, int | None]:
    if root_fd is None:
        return None, None
    if type(root_fd) is not int or root_fd < 0:
        raise _reject("the authority root descriptor is invalid")
    try:
        result = os.fstat(root_fd)
    except OSError as exc:
        raise _reject("the authority root descriptor is unavailable") from exc
    if not stat.S_ISDIR(result.st_mode):
        raise _reject("the authority root descriptor is not a directory")
    return int(result.st_dev), int(result.st_ino)


__all__ = [
    "EVIDENCE_HOST_AUTHORITY_REQUIRED",
    "EVIDENCE_HOST_AUTHORITY_UNAVAILABLE",
    "EVIDENCE_HOST_AUTHORITY_TIMEOUT",
    "EVIDENCE_HOST_AUTHORITY_RPC_TIMEOUT_SECONDS",
    "EvidenceAuthorityRequestV1",
    "EvidenceHostAuthorityError",
    "HostAuthorityEndpointConfigV1",
    "HostAuthorityEndpointV1",
    "LocalHostAuthorityHandleV1",
    "HostAuthorityChannelV1",
    "HostAuthorityHandleV1",
    "admit_host_authority_endpoint",
    "admit_host_authority_fd",
    "build_authority_request",
    "issue_host_proof",
    "validate_host_proof",
]
