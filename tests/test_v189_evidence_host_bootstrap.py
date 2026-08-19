from __future__ import annotations

import array
import dataclasses
import multiprocessing
import os
import socket
import tempfile
from unittest.mock import patch

import pytest

from workbench.canonical import canonical_json_v1
from workbench.evidence.authority import HostAuthorityEndpointConfigV1
from workbench.evidence.deployment_authority import (
    EVIDENCE_SUPERVISOR_CONTROL_FD,
    EVIDENCE_SUPERVISOR_PROTOCOL,
    bootstrap_evidence_host_authority,
)
import workbench.evidence.deployment_authority as deployment_module
from workbench.evidence.registry import create_server_evidence_registry

from test_v189_evidence_envelope import _TestAuthorityServer, _host_config


def _host() -> _TestAuthorityServer:
    directory = tempfile.mkdtemp(prefix="wb-evidence-host-")
    return _TestAuthorityServer(path=os.path.join(directory, "a.sock"))


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
    ancillary: list[tuple[int, int, bytes]] = []
    if endpoint_fd is not None:
        fds = array.array("i", [endpoint_fd])
        ancillary.append((socket.SOL_SOCKET, socket.SCM_RIGHTS, fds.tobytes()))
    channel.sendmsg([payload], ancillary)


def _bootstrap_child(control_fd: int | None, result_queue) -> None:
    if control_fd is None:
        try:
            os.close(EVIDENCE_SUPERVISOR_CONTROL_FD)
        except OSError:
            pass
    else:
        os.dup2(control_fd, EVIDENCE_SUPERVISOR_CONTROL_FD)
    try:
        endpoint = bootstrap_evidence_host_authority()
        registry = create_server_evidence_registry(
            scope_ref=endpoint.scope_ref,
            authority_handle=endpoint,
        )
        result_queue.put(("ok", registry.scope_ref))
    except Exception as exc:  # noqa: BLE001 - child reports the boundary result
        result_queue.put(("error", type(exc).__name__, getattr(exc, "code", None), str(exc)))


def _bootstrap_twice_child(control_fd: int, result_queue) -> None:
    os.dup2(control_fd, EVIDENCE_SUPERVISOR_CONTROL_FD)
    try:
        endpoint = bootstrap_evidence_host_authority()
        endpoint.close()
        bootstrap_evidence_host_authority()
    except Exception as exc:  # noqa: BLE001 - child reports the replay boundary
        result_queue.put(("error", type(exc).__name__, getattr(exc, "code", None), str(exc)))


def _bootstrap_properties_child(control_fd: int, result_queue) -> None:
    os.dup2(control_fd, EVIDENCE_SUPERVISOR_CONTROL_FD)
    try:
        endpoint = bootstrap_evidence_host_authority()
        result_queue.put(
            (
                "ok",
                endpoint._channel.get_inheritable(),  # package-boundary probe
                os.get_inheritable(endpoint._channel.fileno()),
            )
        )
        endpoint.close()
    except Exception as exc:  # noqa: BLE001 - child reports the boundary result
        result_queue.put(("error", type(exc).__name__, getattr(exc, "code", None), str(exc)))


def _run_child(
    host: _TestAuthorityServer,
    config: HostAuthorityEndpointConfigV1,
    *,
    include_endpoint: bool = True,
    replace_endpoint: bool = False,
):
    context = multiprocessing.get_context("fork")
    parent_control, child_control = socket.socketpair()
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) if include_endpoint else None
    if endpoint is not None:
        endpoint.connect(host.path)
    result_queue = context.Queue()
    process = context.Process(
        target=_bootstrap_child,
        args=(child_control.fileno(), result_queue),
    )
    process.start()
    child_control.close()
    replacement = None
    if replace_endpoint:
        host.listener.close()
        os.unlink(host.path)
        replacement = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        replacement.bind(host.path)
        replacement.listen(1)
    try:
        _send_control(parent_control, config, endpoint.fileno() if endpoint is not None else None)
        result = result_queue.get(timeout=5)
        process.join(timeout=5)
        return result
    finally:
        parent_control.close()
        if endpoint is not None:
            endpoint.close()
        if replacement is not None:
            replacement.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


def _run_fragmented_child(
    host: _TestAuthorityServer,
    config: HostAuthorityEndpointConfigV1,
    *,
    tail: bytes = b"",
):
    context = multiprocessing.get_context("fork")
    parent_control, child_control = socket.socketpair()
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.connect(host.path)
    result_queue = context.Queue()
    process = context.Process(
        target=_bootstrap_properties_child,
        args=(child_control.fileno(), result_queue),
    )
    process.start()
    child_control.close()
    payload = canonical_json_v1(
        {"protocol": EVIDENCE_SUPERVISOR_PROTOCOL, "config": dataclasses.asdict(config)}
    ).encode("utf-8") + b"\n" + tail
    split_at = max(1, len(payload) // 2)
    try:
        parent_control.sendmsg(
            [payload[:split_at]],
            [
                (
                    socket.SOL_SOCKET,
                    socket.SCM_RIGHTS,
                    array.array("i", [endpoint.fileno()]).tobytes(),
                )
            ],
        )
        parent_control.sendall(payload[split_at:])
        result = result_queue.get(timeout=5)
        process.join(timeout=5)
        return result
    finally:
        parent_control.close()
        endpoint.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


class _FakeControlChannel:
    family = socket.AF_UNIX
    type = socket.SOCK_STREAM

    def __init__(self, *, result=None, error: BaseException | None = None, restore_error: bool = False):
        self.result = result
        self.error = error
        self.restore_error = restore_error
        self.timeout_values: list[object] = []
        self.inheritable_values: list[bool] = []
        self.closed = False

    def gettimeout(self):
        return None

    def settimeout(self, value):
        self.timeout_values.append(value)
        if self.restore_error and value is None and len(self.timeout_values) > 1:
            raise OSError("timeout restore failed")

    def set_inheritable(self, value: bool) -> None:
        self.inheritable_values.append(value)

    def recvmsg(self, *_args):
        if self.error is not None:
            raise self.error
        return self.result

    def close(self) -> None:
        self.closed = True


def _patch_fake_control(monkeypatch, fake: _FakeControlChannel, *, duplicated_fd: int = 601):
    closed: list[int] = []
    monkeypatch.setattr(deployment_module.os, "dup", lambda _fd: duplicated_fd)
    monkeypatch.setattr(deployment_module.os, "close", lambda fd: closed.append(fd))
    monkeypatch.setattr(
        deployment_module.socket,
        "socket",
        lambda *, fileno: fake,
    )
    monkeypatch.setattr(
        deployment_module,
        "_peer_uid_pid",
        lambda _channel: (os.getuid(), os.getppid()),
    )
    return closed


def test_control_duplicate_is_closed_when_socket_wrapping_fails(monkeypatch) -> None:
    closed: list[int] = []
    monkeypatch.setattr(deployment_module.os, "dup", lambda _fd: 601)
    monkeypatch.setattr(deployment_module.os, "close", lambda fd: closed.append(fd))

    def fail_socket(*, fileno):
        raise OSError(f"cannot wrap {fileno}")

    monkeypatch.setattr(deployment_module.socket, "socket", fail_socket)
    with pytest.raises(Exception):
        deployment_module._control_socket()
    assert 601 in closed


def test_control_duplicate_is_closed_when_fixed_fd_close_fails(monkeypatch) -> None:
    closed: list[int] = []

    def close_fd(fd: int) -> None:
        closed.append(fd)
        if fd == EVIDENCE_SUPERVISOR_CONTROL_FD:
            raise OSError("fixed descriptor close failed")

    monkeypatch.setattr(deployment_module.os, "dup", lambda _fd: 602)
    monkeypatch.setattr(deployment_module.os, "close", close_fd)
    with pytest.raises(Exception):
        deployment_module._control_socket()
    assert 602 in closed


def test_unsupported_ancillary_after_or_before_rights_closes_all_received_fds(monkeypatch) -> None:
    rights_fd = 777
    fake = _FakeControlChannel(
        result=(
            b"not-json\n",
            [
                (socket.SOL_SOCKET, 999, b"unsupported"),
                (socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [rights_fd]).tobytes()),
            ],
            0,
            None,
        )
    )
    closed = _patch_fake_control(monkeypatch, fake)
    with pytest.raises(Exception):
        deployment_module._control_socket()
    assert rights_fd in closed


def test_timeout_restore_failure_still_closes_received_rights(monkeypatch) -> None:
    rights_fd = 778
    fake = _FakeControlChannel(
        result=(
            b"not-json\n",
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, array.array("i", [rights_fd]).tobytes())],
            0,
            None,
        ),
        restore_error=True,
    )
    closed = _patch_fake_control(monkeypatch, fake)
    with pytest.raises(Exception):
        deployment_module._control_socket()
    assert rights_fd in closed


def test_control_channel_is_explicitly_non_inheritable_before_parse(monkeypatch) -> None:
    fake = _FakeControlChannel(result=(b"not-json\n", [], 0, None))
    _patch_fake_control(monkeypatch, fake)
    with pytest.raises(Exception):
        deployment_module._control_socket()
    assert fake.inheritable_values == [False]


@pytest.mark.parametrize(
    ("transport_error", "expected_code"),
    (
        (socket.timeout("timed out"), "EVIDENCE_HOST_AUTHORITY_TIMEOUT"),
        (OSError("transport closed"), "EVIDENCE_HOST_AUTHORITY_UNAVAILABLE"),
    ),
)
def test_control_transport_errors_use_typed_evidence_codes(
    monkeypatch,
    transport_error: BaseException,
    expected_code: str,
) -> None:
    fake = _FakeControlChannel(error=transport_error)
    _patch_fake_control(monkeypatch, fake)
    with pytest.raises(Exception) as exc_info:
        deployment_module._control_socket()
    assert getattr(exc_info.value, "code", None) == expected_code


def test_supervisor_control_bootstraps_public_evidence_registry() -> None:
    host = _host()
    try:
        result = _run_child(
            host,
            _host_config(host, scope_ref="scope:project:supervisor"),
        )
        assert result == ("ok", "scope:project:supervisor")
    finally:
        host.close()


def test_fragmented_control_frame_is_accepted_and_endpoint_fd_is_non_inheritable() -> None:
    host = _host()
    try:
        result = _run_fragmented_child(
            host,
            _host_config(host, scope_ref="scope:project:fragmented"),
        )
        assert result == ("ok", False, False)
    finally:
        host.close()


def test_fragmented_control_frame_with_extra_bytes_fails_closed() -> None:
    host = _host()
    try:
        result = _run_fragmented_child(
            host,
            _host_config(host, scope_ref="scope:project:extra-frame"),
            tail=b"extra\n",
        )
        assert result[0] == "error"
        assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        host.close()


def test_missing_supervisor_control_fails_closed_before_registry() -> None:
    context = multiprocessing.get_context("fork")
    result_queue = context.Queue()
    process = context.Process(target=_bootstrap_child, args=(None, result_queue))
    process.start()
    result = result_queue.get(timeout=5)
    process.join(timeout=5)
    assert result[0] == "error"
    assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"


def test_control_payload_without_passed_endpoint_fails_closed() -> None:
    host = _host()
    try:
        result = _run_child(
            host,
            _host_config(host, scope_ref="scope:project:no-endpoint"),
            include_endpoint=False,
        )
        assert result[0] == "error"
        assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        host.close()


def test_endpoint_replacement_fails_before_registry() -> None:
    host = _host()
    try:
        result = _run_child(
            host,
            _host_config(host, scope_ref="scope:project:replaced"),
            replace_endpoint=True,
        )
        assert result[0] == "error"
        assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        host.close()


def test_bootstrap_is_not_a_request_config_or_resolver_surface() -> None:
    assert bootstrap_evidence_host_authority.__code__.co_argcount == 0
    assert EVIDENCE_SUPERVISOR_CONTROL_FD > 2


def test_control_configuration_must_match_the_parent_peer() -> None:
    host = _host()
    try:
        result = _run_child(
            host,
            _host_config(
                host,
                scope_ref="scope:project:wrong-peer",
                peer_pid=os.getpid() + 1,
            ),
        )
        assert result[0] == "error"
        assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        host.close()


def test_malformed_control_frame_fails_closed() -> None:
    context = multiprocessing.get_context("fork")
    parent_control, child_control = socket.socketpair()
    result_queue = context.Queue()
    process = context.Process(target=_bootstrap_child, args=(child_control.fileno(), result_queue))
    process.start()
    child_control.close()
    try:
        parent_control.sendall(b"not-json\n")
        result = result_queue.get(timeout=5)
        process.join(timeout=5)
        assert result[0] == "error"
        assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        parent_control.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


def test_multiple_passed_endpoint_fds_fail_closed() -> None:
    host = _host()
    context = multiprocessing.get_context("fork")
    parent_control, child_control = socket.socketpair()
    first = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    second = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    first.connect(host.path)
    second.connect(host.path)
    result_queue = context.Queue()
    process = context.Process(target=_bootstrap_child, args=(child_control.fileno(), result_queue))
    process.start()
    child_control.close()
    try:
        config = _host_config(host, scope_ref="scope:project:multiple-fds")
        payload = canonical_json_v1(
            {"protocol": EVIDENCE_SUPERVISOR_PROTOCOL, "config": dataclasses.asdict(config)}
        ).encode("utf-8") + b"\n"
        fds = array.array("i", [first.fileno(), second.fileno()])
        parent_control.sendmsg(
            [payload],
            [(socket.SOL_SOCKET, socket.SCM_RIGHTS, fds.tobytes())],
        )
        result = result_queue.get(timeout=5)
        process.join(timeout=5)
        assert result[0] == "error"
        assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        parent_control.close()
        first.close()
        second.close()
        host.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)


def test_bootstrap_control_is_one_shot_and_replay_fails_closed() -> None:
    host = _host()
    context = multiprocessing.get_context("fork")
    parent_control, child_control = socket.socketpair()
    endpoint = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    endpoint.connect(host.path)
    result_queue = context.Queue()
    process = context.Process(target=_bootstrap_twice_child, args=(child_control.fileno(), result_queue))
    process.start()
    child_control.close()
    try:
        config = _host_config(host, scope_ref="scope:project:replay")
        # sendmsg is required because the endpoint is a deployment-owned FD,
        # not a path or a request field.
        parent_control.sendmsg(
            [
                canonical_json_v1(
                    {"protocol": EVIDENCE_SUPERVISOR_PROTOCOL, "config": dataclasses.asdict(config)}
                ).encode("utf-8")
                + b"\n"
            ],
            [
                (
                    socket.SOL_SOCKET,
                    socket.SCM_RIGHTS,
                    array.array("i", [endpoint.fileno()]).tobytes(),
                )
            ],
        )
        result = result_queue.get(timeout=5)
        process.join(timeout=5)
        assert result[0] == "error"
        assert result[2] == "EVIDENCE_HOST_AUTHORITY_REQUIRED"
    finally:
        parent_control.close()
        endpoint.close()
        host.close()
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
