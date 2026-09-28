from __future__ import annotations

import array
import dataclasses
import hashlib
import hmac
import json
import multiprocessing
import os
import socket
import stat
import tempfile
import threading
from itertools import count
from pathlib import Path

import pytest

from workbench.canonical import canonical_json_v1
from workbench.evidence.authority import (
    EvidenceHostAuthorityError,
    HostAuthorityEndpointConfigV1,
    admit_host_authority_endpoint,
)
from workbench.evidence.deployment_authority import (
    EVIDENCE_SUPERVISOR_CONTROL_FD,
    EVIDENCE_SUPERVISOR_PROTOCOL,
    bootstrap_evidence_host_authority,
)
from workbench.evidence.registry import create_server_evidence_registry


class _SupervisorHost:
    """Small test-only host process surrogate speaking the locked RPC protocol."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = str(root / "authority.sock")
        self.listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.listener.bind(self.path)
        self.listener.listen(8)
        endpoint_stat = os.lstat(self.path)
        self.endpoint_device = int(endpoint_stat.st_dev)
        self.endpoint_inode = int(endpoint_stat.st_ino)
        self.secret = bytes.fromhex("22" * 32)
        self.session_ref = f"session:supervisor:{os.getpid()}"
        self._proofs: dict[str, str] = {}
        self._counter = count(1)
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def config(self, *, scope_ref: str, peer_pid: int | None = None) -> HostAuthorityEndpointConfigV1:
        return HostAuthorityEndpointConfigV1(
            endpoint_path=self.path,
            endpoint_device=self.endpoint_device,
            endpoint_inode=self.endpoint_inode,
            peer_uid=os.getuid(),
            peer_pid=os.getpid() if peer_pid is None else peer_pid,
            scope_ref=scope_ref,
            session_ref=self.session_ref,
            shared_secret=self.secret.hex(),
        )

    @staticmethod
    def _read_frame(channel: socket.socket) -> dict[str, object] | None:
        raw = bytearray()
        while True:
            chunk = channel.recv(4096)
            if not chunk:
                return None
            raw.extend(chunk)
            if b"\n" not in chunk:
                continue
            frame, _, _tail = bytes(raw).partition(b"\n")
            value = json.loads(frame.decode("utf-8"))
            if type(value) is not dict:
                raise ValueError("host request is not an object")
            return value

    @staticmethod
    def _send_frame(channel: socket.socket, value: dict[str, object]) -> None:
        channel.sendall(canonical_json_v1(value).encode("utf-8") + b"\n")

    @staticmethod
    def _request_key(request: object) -> str:
        if type(request) is not dict:
            raise ValueError("request is not an object")
        return hashlib.sha256(canonical_json_v1(request).encode("utf-8")).hexdigest()

    def _serve_client(self, channel: socket.socket) -> None:
        try:
            while True:
                message = self._read_frame(channel)
                if message is None:
                    return
                operation = message.get("operation")
                if operation == "session":
                    request = message.get("request")
                    if type(request) is not dict:
                        raise ValueError("session request is invalid")
                    challenge = request.get("challenge")
                    owner_pid = request.get("owner_pid")
                    endpoint = request.get("endpoint")
                    if type(challenge) is not str or type(owner_pid) is not int or type(endpoint) is not dict:
                        raise ValueError("session request is invalid")
                    attestation = hmac.new(
                        self.secret,
                        canonical_json_v1(
                            {
                                "challenge": challenge,
                                "endpoint": endpoint,
                                "owner_pid": owner_pid,
                                "session_ref": self.session_ref,
                            }
                        ).encode("utf-8"),
                        hashlib.sha256,
                    ).hexdigest()
                    response = {
                        "ok": True,
                        "session_ref": self.session_ref,
                        "attestation": attestation,
                    }
                elif operation == "issue":
                    request = message.get("request")
                    key = self._request_key(request)
                    proof = f"supervisor-proof:{next(self._counter)}"
                    self._proofs[key] = proof
                    response = {"ok": True, "proof": proof}
                elif operation == "validate":
                    request = message.get("request")
                    key = self._request_key(request)
                    response = {
                        "ok": True,
                        "accepted": self._proofs.get(key) == message.get("proof"),
                    }
                else:
                    response = {"ok": False}
                self._send_frame(channel, response)
        except (OSError, ValueError, json.JSONDecodeError):
            return
        finally:
            channel.close()

    def _serve(self) -> None:
        try:
            while not self._stop.is_set():
                channel, _address = self.listener.accept()
                threading.Thread(target=self._serve_client, args=(channel,), daemon=True).start()
        except OSError:
            return

    def connect(self) -> socket.socket:
        channel = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        channel.connect(self.path)
        return channel

    def replace_endpoint_path(self) -> socket.socket:
        self.listener.close()
        os.unlink(self.path)
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        replacement.bind(self.path)
        replacement.listen(1)
        return replacement

    def close(self) -> None:
        self._stop.set()
        self.listener.close()
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass


def _send_control(
    channel: socket.socket,
    config: HostAuthorityEndpointConfigV1,
    endpoint_fd: int | None,
) -> None:
    payload = canonical_json_v1(
        {
            "protocol": EVIDENCE_SUPERVISOR_PROTOCOL,
            "config": dataclasses.asdict(config),
        }
    ).encode("utf-8") + b"\n"
    ancillary = []
    if endpoint_fd is not None:
        fds = array.array("i", [endpoint_fd])
        ancillary.append((socket.SOL_SOCKET, socket.SCM_RIGHTS, fds.tobytes()))
    channel.sendmsg([payload], ancillary)


def _child_bootstrap(control_fd: int | None, result_queue) -> None:
    if control_fd is not None:
        os.dup2(control_fd, EVIDENCE_SUPERVISOR_CONTROL_FD)
    else:
        try:
            os.close(EVIDENCE_SUPERVISOR_CONTROL_FD)
        except OSError:
            pass
    try:
        endpoint = bootstrap_evidence_host_authority()
        registry = create_server_evidence_registry(
            scope_ref=endpoint.scope_ref,
            authority_handle=endpoint,
        )
        result_queue.put(("ok", registry.scope_ref))
    except Exception as exc:  # noqa: BLE001 - child reports the typed boundary
        result_queue.put(("error", type(exc).__name__, getattr(exc, "code", None), str(exc)))


def _run_child_with_control(
    host: _SupervisorHost,
    config: HostAuthorityEndpointConfigV1,
    *,
    send_endpoint: bool = True,
    replace_endpoint: bool = False,
):
    context = multiprocessing.get_context("fork")
    parent_control, child_control = socket.socketpair()
    endpoint = host.connect() if send_endpoint else None
    queue = context.Queue()
    process = context.Process(target=_child_bootstrap, args=(child_control.fileno(), queue))
    process.start()
    child_control.close()
    if replace_endpoint:
        replacement = host.replace_endpoint_path()
    else:
        replacement = None
    try:
        _send_control(parent_control, config, endpoint.fileno() if endpoint is not None else None)
        value = queue.get(timeout=5)
        process.join(timeout=5)
        return value
    finally:
        parent_control.close()
        if endpoint is not None:
            endpoint.close()
        if replacement is not None:
            replacement.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


def test_supervisor_host_bootstrap_reaches_public_evidence_registry(tmp_path: Path) -> None:
    root = tmp_path / "host"
    root.mkdir()
    host = _SupervisorHost(root)
    try:
        result = _run_child_with_control(
            host,
            host.config(scope_ref="scope:project:supervisor"),
        )
        assert result == ("ok", "scope:project:supervisor")
    finally:
        host.close()


def test_missing_supervisor_control_fails_closed_before_registry() -> None:
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    process = context.Process(target=_child_bootstrap, args=(None, queue))
    process.start()
    result = queue.get(timeout=5)
    process.join(timeout=5)
    assert result[0] == "error"
    assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"


def test_control_payload_without_endpoint_fd_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "host"
    root.mkdir()
    host = _SupervisorHost(root)
    try:
        result = _run_child_with_control(
            host,
            host.config(scope_ref="scope:project:no-fd"),
            send_endpoint=False,
        )
        assert result[0] == "error"
        assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        host.close()


def test_endpoint_replacement_is_rejected_before_registry(tmp_path: Path) -> None:
    root = tmp_path / "host"
    root.mkdir()
    host = _SupervisorHost(root)
    try:
        result = _run_child_with_control(
            host,
            host.config(scope_ref="scope:project:replaced"),
            replace_endpoint=True,
        )
        assert result[0] == "error"
        assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        host.close()


def test_public_admission_rejects_caller_selected_trust_root(tmp_path: Path) -> None:
    root = tmp_path / "host"
    root.mkdir()
    host = _SupervisorHost(root)
    channel = host.connect()
    try:
        with pytest.raises(EvidenceHostAuthorityError) as exc_info:
            admit_host_authority_endpoint(
                channel,
                deployment_config=host.config(scope_ref="scope:project:caller"),
            )
        assert exc_info.value.code == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        channel.close()
        host.close()


def test_bootstrap_has_no_request_config_or_resolver_argument() -> None:
    assert not bootstrap_evidence_host_authority.__code__.co_argcount

