"""Trusted-fixture C2 canary protocol with parent-owned audit facts only.

The protocol accepts a typed adapter supplied by tests or a future reviewed
backend layer.  This module does not start a process and has no candidate,
executor, or token surface.  A positive result is solely a canary receipt;
it is never evaluation evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
from typing import Protocol
import uuid

from .frozen_containment_adapters import BubblewrapPlanV1, RoleBindingsV1, SeatbeltPlanV1, render_bubblewrap_plan, render_seatbelt_plan
from .frozen_containment_c2 import C2PolicyError, HostAdmissionV1, HostProbeV1, RuntimePolicyC2


CANARY_ASSERTIONS_V1 = (
    "frozen_read_works",
    "frozen_write_denied",
    "external_sentinel_denied",
    "network_denied",
    "ignored_helper_unimportable",
    "sole_output_writable",
    "fixed_python_bootstrap",
)
_MAX_FRAME_BYTES = 64 * 1024
_MAX_STREAM_BYTES = 1024 * 1024
_SHA256 = frozenset("0123456789abcdef")


@dataclass(frozen=True)
class CanaryFixtureV1:
    fixture_id: str
    fixture_sha256: str

    def validate(self) -> None:
        if self.fixture_id != "c2-trusted-canary-v1":
            raise ValueError("untrusted canary fixture identifier")
        if not _is_sha256(self.fixture_sha256):
            raise ValueError("trusted canary fixture digest is malformed")


@dataclass(frozen=True)
class CanaryAdapterResultV1:
    exit_code: int
    timed_out: bool
    frame: bytes
    stdout: bytes
    stderr: bytes


@dataclass(frozen=True)
class CanaryObservationV1:
    schema_version: str
    assertions: tuple[tuple[str, bool], ...]


@dataclass(frozen=True)
class CanaryAuditReceiptV1:
    schema_version: str
    audit_record_sha256: str
    policy_digest: str
    template_digest: str
    host_fingerprint_sha256: str
    assertion_digest: str


@dataclass(frozen=True)
class CanaryOutcomeV1:
    passed: bool
    code: str
    audit_receipt: CanaryAuditReceiptV1 | None
    reason: str
    evaluation_evidence: None = None


class CanaryAdapterV1(Protocol):
    """A future reviewed adapter's trusted-fixture operation, not an executor API."""

    def run_trusted_fixture(self, plan: SeatbeltPlanV1 | BubblewrapPlanV1, fixture: CanaryFixtureV1) -> CanaryAdapterResultV1: ...


class CanaryAuditStore:
    """Descriptor-anchored no-replace audit writer for bounded canary facts."""

    def __init__(self, root: Path):
        self._root = root

    def publish_success(self, record: dict[str, object]) -> CanaryAuditReceiptV1:
        content = _canonical_bytes(record)
        if len(content) > 16 * 1024:
            raise OSError("canary audit record exceeds bounded size")
        digest = hashlib.sha256(content).hexdigest()
        self._write_no_replace(f"canary-{digest}.json", content)
        return CanaryAuditReceiptV1(
            schema_version="1",
            audit_record_sha256=digest,
            policy_digest=str(record["policy_digest"]),
            template_digest=str(record["template_digest"]),
            host_fingerprint_sha256=str(record["host_fingerprint_sha256"]),
            assertion_digest=str(record["assertion_digest"]),
        )

    def record_rejection(self, *, code: str, reason: str) -> None:
        bounded_reason = " ".join(reason.split())[:256]
        record = {"schema_version": "1", "kind": "canary_rejection", "code": code, "reason": bounded_reason}
        content = _canonical_bytes(record)
        self._write_no_replace(f"reject-{hashlib.sha256(content).hexdigest()}-{uuid.uuid4().hex}.json", content)

    def _write_no_replace(self, name: str, content: bytes) -> None:
        self._root.mkdir(parents=True, exist_ok=True)
        root_fd = _open_audit_root(self._root)
        temporary = f".{name}.{uuid.uuid4().hex}.tmp"
        fd = -1
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=root_fd)
            _write_all(fd, content)
            os.fsync(fd)
            os.close(fd)
            fd = -1
            os.link(temporary, name, src_dir_fd=root_fd, dst_dir_fd=root_fd, follow_symlinks=False)
            os.unlink(temporary, dir_fd=root_fd)
            os.fsync(root_fd)
            reread = _read_no_follow(root_fd, name)
            if reread != content:
                raise OSError("canary audit reread did not match written content")
        finally:
            if fd >= 0:
                os.close(fd)
            try:
                os.unlink(temporary, dir_fd=root_fd)
            except FileNotFoundError:
                pass
            os.close(root_fd)


def run_trusted_canary(
    *,
    policy: RuntimePolicyC2,
    admission: HostAdmissionV1,
    host_probe: HostProbeV1,
    bindings: RoleBindingsV1,
    adapter: CanaryAdapterV1,
    fixture: CanaryFixtureV1,
    audit_store: CanaryAuditStore,
) -> CanaryOutcomeV1:
    """Validate one trusted fixture through a fake/reviewed adapter result.

    No positive path creates an execution permission or reusable handle.
    """

    try:
        fixture.validate()
        fresh_admission = policy.reprobe_before_launch(host_probe, admission)
        plan = _render_plan(policy, fresh_admission, bindings)
    except C2PolicyError as error:
        _best_effort_rejection(audit_store, error.code, error.detail)
        return CanaryOutcomeV1(False, error.code, None, error.detail)
    except (TypeError, ValueError) as error:
        _best_effort_rejection(audit_store, "C2_CANARY_FAILED", "canary preflight rejected")
        return CanaryOutcomeV1(False, "C2_CANARY_FAILED", "canary preflight rejected")

    try:
        result = adapter.run_trusted_fixture(plan, fixture)
        observation = _validate_adapter_result(result)
        record = _success_record(policy, fresh_admission, plan, fixture, result, observation)
        receipt = audit_store.publish_success(record)
    except Exception:
        _best_effort_rejection(audit_store, "C2_CANARY_FAILED", "trusted canary assertion or audit rejected")
        return CanaryOutcomeV1(False, "C2_CANARY_FAILED", None, "trusted canary assertion or audit rejected")
    return CanaryOutcomeV1(True, "C2_CANARY_PASSED", receipt, "all required trusted-fixture assertions passed")


def _render_plan(policy: RuntimePolicyC2, admission: HostAdmissionV1, bindings: RoleBindingsV1) -> SeatbeltPlanV1 | BubblewrapPlanV1:
    if admission.backend_name == "seatbelt":
        return render_seatbelt_plan(policy, admission, bindings)
    if admission.backend_name == "bubblewrap":
        return render_bubblewrap_plan(policy, admission, bindings)
    raise C2PolicyError("C2_UNSUPPORTED_HOST", "no reviewed renderer exists for the admitted backend")


def _validate_adapter_result(result: object) -> CanaryObservationV1:
    if not isinstance(result, CanaryAdapterResultV1):
        raise ValueError("adapter returned malformed result")
    if result.timed_out or result.exit_code != 0:
        raise ValueError("trusted fixture did not complete successfully")
    if not all(isinstance(stream, bytes) and len(stream) <= _MAX_STREAM_BYTES for stream in (result.stdout, result.stderr)):
        raise ValueError("trusted fixture stream overflow")
    observation = _parse_exact_frame(result.frame)
    assertions = dict(observation.assertions)
    if set(assertions) != set(CANARY_ASSERTIONS_V1) or not all(value is True for value in assertions.values()):
        raise ValueError("required canary assertions did not all pass")
    return observation


def _parse_exact_frame(frame: object) -> CanaryObservationV1:
    if not isinstance(frame, bytes) or len(frame) < 4:
        raise ValueError("canary frame is missing")
    declared = struct.unpack(">I", frame[:4])[0]
    if declared > _MAX_FRAME_BYTES or len(frame) != 4 + declared:
        raise ValueError("canary frame length is invalid")
    try:
        payload = json.loads(frame[4:].decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("canary frame is malformed") from error
    if not isinstance(payload, dict) or set(payload) != {"schema_version", "assertions"} or payload["schema_version"] != "1":
        raise ValueError("canary frame schema is invalid")
    assertions = payload["assertions"]
    if not isinstance(assertions, dict) or set(assertions) != set(CANARY_ASSERTIONS_V1):
        raise ValueError("canary assertion set is invalid")
    if any(type(value) is not bool for value in assertions.values()):
        raise ValueError("canary assertions must be booleans")
    return CanaryObservationV1("1", tuple((name, assertions[name]) for name in CANARY_ASSERTIONS_V1))


def _success_record(
    policy: RuntimePolicyC2,
    admission: HostAdmissionV1,
    plan: SeatbeltPlanV1 | BubblewrapPlanV1,
    fixture: CanaryFixtureV1,
    result: CanaryAdapterResultV1,
    observation: CanaryObservationV1,
) -> dict[str, object]:
    assertion_digest = _canonical_digest({name: value for name, value in observation.assertions})
    return {
        "schema_version": "1",
        "kind": "trusted_fixture_canary",
        "policy_digest": policy.policy_digest,
        "template_digest": plan.template_digest,
        "host_fingerprint_sha256": admission.host_fingerprint_sha256,
        "fixture_id": fixture.fixture_id,
        "fixture_sha256": fixture.fixture_sha256,
        "assertion_digest": assertion_digest,
        "stdout_sha256": hashlib.sha256(result.stdout).hexdigest(),
        "stderr_sha256": hashlib.sha256(result.stderr).hexdigest(),
    }


def _best_effort_rejection(audit_store: CanaryAuditStore, code: str, reason: str) -> None:
    try:
        audit_store.record_rejection(code=code, reason=reason)
    except Exception:
        pass


def _canonical_digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _is_sha256(value: str) -> bool:
    return isinstance(value, str) and len(value) == 64 and set(value) <= _SHA256


def _open_audit_root(root: Path) -> int:
    info = os.lstat(root)
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise OSError("audit root is not a safe directory")
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)


def _read_no_follow(directory_fd: int, name: str) -> bytes:
    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory_fd)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise OSError("audit record is not regular")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(fd, 64 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
    finally:
        os.close(fd)


def _write_all(fd: int, content: bytes) -> None:
    offset = 0
    while offset < len(content):
        written = os.write(fd, content[offset:])
        if written <= 0:
            raise OSError("could not write complete audit record")
        offset += written


__all__ = [
    "CANARY_ASSERTIONS_V1",
    "CanaryAdapterResultV1",
    "CanaryAuditReceiptV1",
    "CanaryAuditStore",
    "CanaryFixtureV1",
    "CanaryObservationV1",
    "CanaryOutcomeV1",
    "run_trusted_canary",
]
