"""C2 policy and exact-host admission, without execution capability.

This module intentionally provides only immutable pre-launch contracts.  It
does not import C1, invoke a backend, construct a command, or retain a canary
or capability.  A future, separately reviewed C2 phase may consume these
bindings only after it supplies a real OS adapter and fresh canary protocol.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import PurePosixPath
import re
from typing import Protocol


_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_POLICY_ID = re.compile(r"^[a-z][a-z0-9-]{2,63}$")
_ALLOWED_ROLES = frozenset({"backend", "python", "runner", "runtime", "fixture"})
_FIXED_PYTHON_ARGS = ("-B", "-I", "-S")


class C2PolicyError(RuntimeError):
    """Structured pre-launch C2 policy rejection."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _reject(code: str, detail: str) -> None:
    raise C2PolicyError(code, detail)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_sha256(value: str, label: str, *, code: str) -> None:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        _reject(code, f"{label} must be a lowercase sha256")


def _require_commit(value: str, label: str, *, code: str) -> None:
    if not isinstance(value, str) or not _COMMIT_SHA.fullmatch(value):
        _reject(code, f"{label} must be an exact lowercase Git commit SHA")


@dataclass(frozen=True)
class HostInstanceFingerprintV1:
    """Canonical observed host facts; its digest deliberately excludes clock time."""

    schema_version: str
    os_family: str
    os_build: str
    architecture: str
    backend_name: str
    backend_version: str
    backend_identity_sha256: str
    feature_flags: tuple[str, ...]
    observed_monotonic_ns: int

    def validate(self) -> None:
        if self.schema_version != "1":
            _reject("C2_UNSUPPORTED_HOST", "unsupported host fingerprint schema")
        for label, value in (
            ("os_family", self.os_family),
            ("os_build", self.os_build),
            ("architecture", self.architecture),
            ("backend_name", self.backend_name),
            ("backend_version", self.backend_version),
        ):
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                _reject("C2_UNSUPPORTED_HOST", f"host fingerprint {label} is malformed")
        _require_sha256(self.backend_identity_sha256, "backend identity", code="C2_UNSUPPORTED_HOST")
        if (
            not isinstance(self.feature_flags, tuple)
            or not self.feature_flags
            or tuple(sorted(set(self.feature_flags))) != self.feature_flags
            or any(not isinstance(flag, str) or not flag for flag in self.feature_flags)
        ):
            _reject("C2_UNSUPPORTED_HOST", "host fingerprint features must be a sorted, non-empty tuple")
        if not isinstance(self.observed_monotonic_ns, int) or isinstance(self.observed_monotonic_ns, bool) or self.observed_monotonic_ns < 0:
            _reject("C2_UNSUPPORTED_HOST", "host fingerprint monotonic timestamp is malformed")

    @property
    def digest(self) -> str:
        self.validate()
        return _canonical_digest(
            {
                "schema_version": self.schema_version,
                "os_family": self.os_family,
                "os_build": self.os_build,
                "architecture": self.architecture,
                "backend_name": self.backend_name,
                "backend_version": self.backend_version,
                "backend_identity_sha256": self.backend_identity_sha256,
                "feature_flags": list(self.feature_flags),
            }
        )


class HostProbeV1(Protocol):
    """Injected host-fact probe.  It must not run candidates or use caches."""

    def probe_host(self) -> HostInstanceFingerprintV1: ...


@dataclass(frozen=True)
class SupportedHostC2:
    """One exact acceptable host/backend identity, never a broad platform class."""

    os_family: str
    os_build: str
    architecture: str
    backend_name: str
    backend_version: str
    backend_identity_sha256: str
    required_features: tuple[str, ...]

    def validate(self) -> None:
        for label, value in (
            ("os_family", self.os_family),
            ("os_build", self.os_build),
            ("architecture", self.architecture),
            ("backend_name", self.backend_name),
            ("backend_version", self.backend_version),
        ):
            if not isinstance(value, str) or not value.strip() or "\x00" in value:
                _reject("C2_POLICY_INVALID", f"supported host {label} is malformed")
        _require_sha256(self.backend_identity_sha256, "supported host backend identity", code="C2_POLICY_INVALID")
        if (
            not isinstance(self.required_features, tuple)
            or not self.required_features
            or tuple(sorted(set(self.required_features))) != self.required_features
            or any(not isinstance(flag, str) or not flag for flag in self.required_features)
        ):
            _reject("C2_POLICY_INVALID", "supported host features must be a sorted, non-empty tuple")

    def classify(self, observed: HostInstanceFingerprintV1) -> None:
        observed.validate()
        if (
            observed.os_family != self.os_family
            or observed.os_build != self.os_build
            or observed.architecture != self.architecture
            or observed.backend_name != self.backend_name
            or observed.feature_flags != self.required_features
        ):
            _reject("C2_UNSUPPORTED_HOST", "observed host does not match an exact supported-host record")
        if (
            observed.backend_version != self.backend_version
            or observed.backend_identity_sha256 != self.backend_identity_sha256
        ):
            _reject("C2_TRUST_IDENTITY_MISMATCH", "observed backend version or identity drifted")


@dataclass(frozen=True)
class TrustedPathIdentityV1:
    """A no-follow identity observation supplied by a future trusted parent."""

    role: str
    path: str
    device: int
    inode: int
    content_sha256: str
    owner_uid: int
    mode: int
    ancestor_chain_sha256: str
    ancestor_chain_root_owned: bool
    ancestor_chain_group_or_other_writable: bool
    is_symlink: bool
    is_live_repository: bool

    def validate(self, *, read_root: bool) -> None:
        if self.role not in _ALLOWED_ROLES:
            _reject("C2_POLICY_INVALID", "trusted identity role is not allowlisted")
        if not isinstance(self.path, str) or not self.path.startswith("/") or "\x00" in self.path:
            _reject("C2_POLICY_INVALID", "trusted identity path must be absolute")
        normalized = str(PurePosixPath(self.path))
        if normalized != self.path or self.path == "/":
            _reject("C2_POLICY_INVALID", "trusted identity path is broad or non-canonical")
        if self.path == "/root" or self.path.startswith(("/Users/", "/home/", "/root/")):
            _reject("C2_POLICY_INVALID", "trusted identity path may not be a home path")
        if not isinstance(self.device, int) or self.device < 0 or not isinstance(self.inode, int) or self.inode <= 0:
            _reject("C2_POLICY_INVALID", "trusted identity device or inode is invalid")
        _require_sha256(self.content_sha256, "trusted identity content", code="C2_POLICY_INVALID")
        _require_sha256(self.ancestor_chain_sha256, "trusted identity ancestor chain", code="C2_POLICY_INVALID")
        if self.owner_uid != 0 or not self.ancestor_chain_root_owned:
            _reject("C2_POLICY_INVALID", "C2 trusts only root-owned runtime identities and ancestors")
        if self.mode & 0o022 or self.ancestor_chain_group_or_other_writable:
            _reject("C2_POLICY_INVALID", "trusted identity or ancestor chain is group/other writable")
        if self.is_symlink:
            _reject("C2_POLICY_INVALID", "trusted identity may not be a symlink")
        if read_root and self.is_live_repository:
            _reject("C2_POLICY_INVALID", "C2 read roots may not be live repository checkouts")

    def canonical(self) -> dict[str, object]:
        return {
            "role": self.role,
            "path": self.path,
            "device": self.device,
            "inode": self.inode,
            "content_sha256": self.content_sha256,
            "owner_uid": self.owner_uid,
            "mode": self.mode,
            "ancestor_chain_sha256": self.ancestor_chain_sha256,
            "ancestor_chain_root_owned": self.ancestor_chain_root_owned,
            "ancestor_chain_group_or_other_writable": self.ancestor_chain_group_or_other_writable,
            "is_symlink": self.is_symlink,
            "is_live_repository": self.is_live_repository,
        }


@dataclass(frozen=True)
class TrustedEvaluatorV1:
    """Allowlisted evaluator identity; it is not a lane helper or import target."""

    schema_version: str
    evaluator_tree_sha: str
    evaluator_package_sha256: str
    runner_entrypoint_sha256: str
    fixture_manifest_sha256: str
    interpreter_identity_sha256: str
    runtime_manifest_sha256: str
    integration_sha: str

    def validate(self) -> None:
        if self.schema_version != "1":
            _reject("C2_POLICY_INVALID", "unsupported trusted evaluator schema")
        _require_commit(self.evaluator_tree_sha, "evaluator tree", code="C2_POLICY_INVALID")
        _require_commit(self.integration_sha, "evaluator integration", code="C2_POLICY_INVALID")
        for label, value in (
            ("evaluator package", self.evaluator_package_sha256),
            ("runner entrypoint", self.runner_entrypoint_sha256),
            ("fixture manifest", self.fixture_manifest_sha256),
            ("interpreter identity", self.interpreter_identity_sha256),
            ("runtime manifest", self.runtime_manifest_sha256),
        ):
            _require_sha256(value, label, code="C2_POLICY_INVALID")

    def canonical(self) -> dict[str, str]:
        return {
            "schema_version": self.schema_version,
            "evaluator_tree_sha": self.evaluator_tree_sha,
            "evaluator_package_sha256": self.evaluator_package_sha256,
            "runner_entrypoint_sha256": self.runner_entrypoint_sha256,
            "fixture_manifest_sha256": self.fixture_manifest_sha256,
            "interpreter_identity_sha256": self.interpreter_identity_sha256,
            "runtime_manifest_sha256": self.runtime_manifest_sha256,
            "integration_sha": self.integration_sha,
        }


@dataclass(frozen=True)
class TrustedRuntimeFactsV1:
    """Observed trusted facts for identity revalidation; no commands or paths from callers."""

    backend: TrustedPathIdentityV1
    python_interpreter: TrustedPathIdentityV1
    runner: TrustedPathIdentityV1
    runtime_read_roots: tuple[TrustedPathIdentityV1, ...]
    fixture_read_roots: tuple[TrustedPathIdentityV1, ...]
    trusted_evaluator: TrustedEvaluatorV1


@dataclass(frozen=True)
class HostAdmissionV1:
    """Pre-canary binding carried internally by a future parent lifecycle."""

    policy_digest: str
    template_digest: str
    host_fingerprint_sha256: str
    backend_name: str


@dataclass(frozen=True)
class RuntimePolicyC2:
    """Integration-owned immutable C2 configuration with no execution surface."""

    schema_version: str
    policy_id: str
    integration_sha: str
    supported_hosts: tuple[SupportedHostC2, ...]
    backend: TrustedPathIdentityV1
    python_interpreter: TrustedPathIdentityV1
    runner: TrustedPathIdentityV1
    runtime_read_roots: tuple[TrustedPathIdentityV1, ...]
    fixture_read_roots: tuple[TrustedPathIdentityV1, ...]
    trusted_evaluator: TrustedEvaluatorV1
    max_cpu_seconds: int
    max_memory_bytes: int
    max_file_bytes: int
    max_open_files: int
    max_processes: int
    max_wall_clock_ms: int
    caller_command: tuple[str, ...] | None = None
    caller_environment: dict[str, str] | None = None

    @property
    def fixed_python_args(self) -> tuple[str, str, str]:
        return _FIXED_PYTHON_ARGS

    def validate(self) -> RuntimePolicyC2:
        if self.schema_version != "1" or not _POLICY_ID.fullmatch(self.policy_id):
            _reject("C2_POLICY_INVALID", "C2 policy schema or identifier is invalid")
        _require_commit(self.integration_sha, "integration", code="C2_POLICY_INVALID")
        if self.caller_command is not None or self.caller_environment is not None:
            _reject("C2_POLICY_INVALID", "C2 policy rejects caller-supplied command or environment")
        if not self.supported_hosts or len(set(self.supported_hosts)) != len(self.supported_hosts):
            _reject("C2_POLICY_INVALID", "C2 policy requires distinct exact supported-host records")
        for host in self.supported_hosts:
            host.validate()
        self.backend.validate(read_root=False)
        self.python_interpreter.validate(read_root=False)
        self.runner.validate(read_root=False)
        if self.backend.role != "backend" or self.python_interpreter.role != "python" or self.runner.role != "runner":
            _reject("C2_POLICY_INVALID", "fixed backend, Python, and runner roles are required")
        if any(host.backend_identity_sha256 != self.backend.content_sha256 for host in self.supported_hosts):
            _reject("C2_POLICY_INVALID", "supported host backend identity must bind the fixed backend")
        self._validate_roots(self.runtime_read_roots, "runtime")
        self._validate_roots(self.fixture_read_roots, "fixture")
        all_roots = (*self.runtime_read_roots, *self.fixture_read_roots)
        for index, root in enumerate(all_roots):
            for other in all_roots[index + 1 :]:
                if _nested_or_equal(root.path, other.path):
                    _reject("C2_POLICY_INVALID", "runtime and fixture roots may not overlap or nest")
        self.trusted_evaluator.validate()
        if self.trusted_evaluator.integration_sha != self.integration_sha:
            _reject("C2_POLICY_INVALID", "trusted evaluator must bind the exact assembled Integration SHA")
        if self.trusted_evaluator.interpreter_identity_sha256 != self.python_interpreter.content_sha256:
            _reject("C2_POLICY_INVALID", "trusted evaluator interpreter identity does not bind fixed Python")
        if self.trusted_evaluator.runner_entrypoint_sha256 != self.runner.content_sha256:
            _reject("C2_POLICY_INVALID", "trusted evaluator runner digest does not bind fixed runner")
        if self.trusted_evaluator.runtime_manifest_sha256 != _root_manifest_digest(self.runtime_read_roots):
            _reject("C2_POLICY_INVALID", "trusted evaluator runtime digest does not bind fixed runtime roots")
        if self.trusted_evaluator.fixture_manifest_sha256 != _root_manifest_digest(self.fixture_read_roots):
            _reject("C2_POLICY_INVALID", "trusted evaluator fixture manifest does not bind fixed fixture roots")
        for label, value in (
            ("max_cpu_seconds", self.max_cpu_seconds),
            ("max_memory_bytes", self.max_memory_bytes),
            ("max_file_bytes", self.max_file_bytes),
            ("max_open_files", self.max_open_files),
            ("max_processes", self.max_processes),
            ("max_wall_clock_ms", self.max_wall_clock_ms),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                _reject("C2_POLICY_INVALID", f"{label} must be a positive fixed limit")
        return self

    def _validate_roots(self, roots: tuple[TrustedPathIdentityV1, ...], label: str) -> None:
        if not roots or len(set(roots)) != len(roots):
            _reject("C2_POLICY_INVALID", f"C2 policy requires distinct {label} roots")
        expected_role = "runtime" if label == "runtime" else "fixture"
        for root in roots:
            root.validate(read_root=True)
            if root.role != expected_role:
                _reject("C2_POLICY_INVALID", f"{label} root carries an incorrect role")

    @property
    def policy_digest(self) -> str:
        self.validate()
        return _canonical_digest(self._canonical(include_limits=True))

    @property
    def template_digest(self) -> str:
        self.validate()
        return _canonical_digest(
            {
                "policy_digest": self.policy_digest,
                "backend": self.backend.canonical(),
                "python": self.python_interpreter.canonical(),
                "runner": self.runner.canonical(),
                "fixed_python_args": list(self.fixed_python_args),
                "roles": ["candidate_snapshot", "evaluator_snapshot", "runtime_root", "fixture_root", "child_write_root", "parent_audit_root"],
            }
        )

    def _canonical(self, *, include_limits: bool) -> dict[str, object]:
        value: dict[str, object] = {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "integration_sha": self.integration_sha,
            "supported_hosts": [
                {
                    "os_family": host.os_family,
                    "os_build": host.os_build,
                    "architecture": host.architecture,
                    "backend_name": host.backend_name,
                    "backend_version": host.backend_version,
                    "backend_identity_sha256": host.backend_identity_sha256,
                    "required_features": list(host.required_features),
                }
                for host in self.supported_hosts
            ],
            "backend": self.backend.canonical(),
            "python": self.python_interpreter.canonical(),
            "runner": self.runner.canonical(),
            "runtime_read_roots": [root.canonical() for root in self.runtime_read_roots],
            "fixture_read_roots": [root.canonical() for root in self.fixture_read_roots],
            "trusted_evaluator": self.trusted_evaluator.canonical(),
            "fixed_python_args": list(self.fixed_python_args),
        }
        if include_limits:
            value["limits"] = {
                "max_cpu_seconds": self.max_cpu_seconds,
                "max_memory_bytes": self.max_memory_bytes,
                "max_file_bytes": self.max_file_bytes,
                "max_open_files": self.max_open_files,
                "max_processes": self.max_processes,
                "max_wall_clock_ms": self.max_wall_clock_ms,
            }
        return value

    def admit_host(self, probe: HostProbeV1) -> HostAdmissionV1:
        self.validate()
        observed = _probe_host(probe)
        matches = [
            host
            for host in self.supported_hosts
            if (
                host.os_family == observed.os_family
                and host.os_build == observed.os_build
                and host.architecture == observed.architecture
                and host.backend_name == observed.backend_name
            )
        ]
        if not matches:
            _reject("C2_UNSUPPORTED_HOST", "no exact supported-host record")
        if len(matches) != 1:
            _reject("C2_POLICY_INVALID", "supported-host records are ambiguous")
        matches[0].classify(observed)
        return HostAdmissionV1(
            policy_digest=self.policy_digest,
            template_digest=self.template_digest,
            host_fingerprint_sha256=observed.digest,
            backend_name=observed.backend_name,
        )

    def revalidate_trust(self, observed: TrustedRuntimeFactsV1) -> None:
        self.validate()
        if not isinstance(observed, TrustedRuntimeFactsV1):
            _reject("C2_TRUST_IDENTITY_MISMATCH", "trusted runtime facts are malformed")
        try:
            self._validate_observed(observed)
        except C2PolicyError as error:
            if error.code == "C2_POLICY_INVALID":
                _reject("C2_TRUST_IDENTITY_MISMATCH", "trusted runtime identity became invalid")
            raise
        if observed != TrustedRuntimeFactsV1(
            backend=self.backend,
            python_interpreter=self.python_interpreter,
            runner=self.runner,
            runtime_read_roots=self.runtime_read_roots,
            fixture_read_roots=self.fixture_read_roots,
            trusted_evaluator=self.trusted_evaluator,
        ):
            _reject("C2_TRUST_IDENTITY_MISMATCH", "trusted runtime identity drifted")

    def _validate_observed(self, observed: TrustedRuntimeFactsV1) -> None:
        observed.backend.validate(read_root=False)
        observed.python_interpreter.validate(read_root=False)
        observed.runner.validate(read_root=False)
        self._validate_roots(observed.runtime_read_roots, "runtime")
        self._validate_roots(observed.fixture_read_roots, "fixture")
        observed.trusted_evaluator.validate()

    def reprobe_before_launch(self, probe: HostProbeV1, admission: HostAdmissionV1) -> HostAdmissionV1:
        self.validate()
        if not isinstance(admission, HostAdmissionV1) or (
            admission.policy_digest != self.policy_digest or admission.template_digest != self.template_digest
        ):
            _reject("C2_TRUST_IDENTITY_MISMATCH", "host admission is not bound to this policy and template")
        fresh = self.admit_host(probe)
        if fresh.host_fingerprint_sha256 != admission.host_fingerprint_sha256:
            _reject("C2_TRUST_IDENTITY_MISMATCH", "host fingerprint drifted after admission")
        return fresh


def _probe_host(probe: HostProbeV1) -> HostInstanceFingerprintV1:
    if not hasattr(probe, "probe_host"):
        _reject("C2_UNSUPPORTED_HOST", "host probe does not implement HostProbeV1")
    try:
        observed = probe.probe_host()
    except Exception as error:
        raise C2PolicyError("C2_UNSUPPORTED_HOST", "host probe failed") from error
    if not isinstance(observed, HostInstanceFingerprintV1):
        _reject("C2_UNSUPPORTED_HOST", "host probe returned malformed facts")
    observed.validate()
    return observed


def _nested_or_equal(left: str, right: str) -> bool:
    left_parts = PurePosixPath(left).parts
    right_parts = PurePosixPath(right).parts
    return left_parts[: len(right_parts)] == right_parts or right_parts[: len(left_parts)] == left_parts


def _root_manifest_digest(roots: tuple[TrustedPathIdentityV1, ...]) -> str:
    if len(roots) == 1:
        return roots[0].content_sha256
    return _canonical_digest([root.canonical() for root in roots])


__all__ = [
    "C2PolicyError",
    "HostAdmissionV1",
    "HostInstanceFingerprintV1",
    "HostProbeV1",
    "RuntimePolicyC2",
    "SupportedHostC2",
    "TrustedEvaluatorV1",
    "TrustedPathIdentityV1",
    "TrustedRuntimeFactsV1",
]
