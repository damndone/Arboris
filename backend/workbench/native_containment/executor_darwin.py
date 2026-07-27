"""Explicitly experimental Darwin executor for local Capability Factory work.

The executor is intentionally not a generic subprocess helper.  A trusted
resolver must bind a request's content references to a prepared, read-only
input root, a fresh output root, and an absolute executable.  The request
itself never carries a host path, command, source, or user payload.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
import signal
import subprocess
from threading import RLock
import time
from typing import Any, Callable

from .contracts import ContainmentReport, ContainmentRequest
from .host import CanaryResult
from .platform_darwin import DarwinCanaryHarness
from .policy import ContainmentPolicy


class DarwinExecutionError(ValueError):
    """Raised when a trusted execution specification is unsafe or incomplete."""


@dataclass(frozen=True, slots=True)
class DarwinExecutionSpec:
    """Trusted server-side binding for one content-addressed execution."""

    input_bundle_ref: str
    output_namespace_ref: str
    executable: Path
    executable_digest: str
    arguments: tuple[str, ...]
    input_root: Path
    output_root: Path

    def __post_init__(self) -> None:
        if not isinstance(self.input_bundle_ref, str) or len(self.input_bundle_ref) != 64:
            raise DarwinExecutionError("input_bundle_ref is invalid")
        if not isinstance(self.output_namespace_ref, str) or len(self.output_namespace_ref) != 64:
            raise DarwinExecutionError("output_namespace_ref is invalid")
        for digest, field in (
            (self.input_bundle_ref, "input_bundle_ref"),
            (self.output_namespace_ref, "output_namespace_ref"),
        ):
            if any(char not in "0123456789abcdef" for char in digest):
                raise DarwinExecutionError(f"{field} is invalid")
        if not isinstance(self.executable, Path) or not self.executable.is_absolute():
            raise DarwinExecutionError("executable must be absolute")
        executable = self.executable.resolve()
        if not executable.is_absolute() or not executable.is_file():
            raise DarwinExecutionError("executable must be a regular file")
        object.__setattr__(self, "executable", executable)
        if (
            not isinstance(self.executable_digest, str)
            or len(self.executable_digest) != 64
            or any(char not in "0123456789abcdef" for char in self.executable_digest)
        ):
            raise DarwinExecutionError("executable_digest is invalid")
        arguments = tuple(self.arguments)
        if len(arguments) > 64:
            raise DarwinExecutionError("arguments exceed the bounded limit")
        if any(
            not isinstance(argument, str)
            or not argument
            or len(argument) > 4096
            or any(ord(char) < 0x20 for char in argument)
            for argument in arguments
        ):
            raise DarwinExecutionError("arguments contain unsafe values")
        object.__setattr__(self, "arguments", arguments)
        for path, field in ((self.input_root, "input_root"), (self.output_root, "output_root")):
            if not isinstance(path, Path) or not path.is_absolute():
                raise DarwinExecutionError(f"{field} must be absolute")
            if path.is_symlink() or not path.is_dir():
                raise DarwinExecutionError(f"{field} must be a regular directory")
            current = path
            while True:
                if current.is_symlink():
                    raise DarwinExecutionError(f"{field} contains a symlink ancestor")
                if current.parent == current:
                    break
                current = current.parent
        if self.input_root == self.output_root:
            raise DarwinExecutionError("input and output roots must be distinct")

    @property
    def content_digest(self) -> str:
        payload = "\x00".join(
            (
                self.input_bundle_ref,
                self.output_namespace_ref,
                str(self.executable),
                self.executable_digest,
                *self.arguments,
                str(self.input_root),
                str(self.output_root),
            )
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True, slots=True)
class DarwinSpawnedProcess:
    """One idempotently spawned process awaiting trusted supervisor collection."""

    handle_ref: str
    request: ContainmentRequest
    policy: ContainmentPolicy
    spec: DarwinExecutionSpec
    process: Any
    stdout_path: Path
    stderr_path: Path
    stdout_file: Any
    stderr_file: Any


Resolver = Callable[[ContainmentRequest], DarwinExecutionSpec | None]
ProcessFactory = Callable[..., subprocess.Popen]
ProcessSnapshot = Callable[[int], tuple[int, int] | None]


class DarwinExperimentalExecutor:
    """Run one explicitly selected local experimental attempt under Seatbelt."""

    PROFILE_ID = "darwin-seatbelt-experimental-v1"

    def __init__(
        self,
        *,
        resolver: Resolver,
        assessment_ref: str | None = None,
        backend_executable: str = "/usr/bin/sandbox-exec",
        process_factory: ProcessFactory | None = None,
        process_snapshot: ProcessSnapshot | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not callable(resolver):
            raise DarwinExecutionError("resolver must be callable")
        self.resolver = resolver
        if assessment_ref is not None and (
            not isinstance(assessment_ref, str)
            or len(assessment_ref) != 64
            or any(char not in "0123456789abcdef" for char in assessment_ref)
        ):
            raise DarwinExecutionError("assessment_ref is invalid")
        self.assessment_ref = assessment_ref
        self.backend_executable = backend_executable
        self.process_factory = process_factory or subprocess.Popen
        self.process_snapshot = process_snapshot or self._default_process_snapshot
        self.sleeper = sleeper
        self.clock = clock
        self._lock = RLock()
        self._active: dict[str, DarwinSpawnedProcess] = {}
        self._completed: dict[str, ContainmentReport] = {}
        self._request_handles: dict[str, tuple[str, str]] = {}
        self._spawning: set[str] = set()
        self._collecting: set[str] = set()

    def __call__(
        self,
        request: ContainmentRequest,
        policy: ContainmentPolicy,
        canary: CanaryResult,
    ) -> ContainmentReport:
        if not isinstance(request, ContainmentRequest):
            raise DarwinExecutionError("request must be a ContainmentRequest")
        if not isinstance(policy, ContainmentPolicy):
            raise DarwinExecutionError("policy must be a ContainmentPolicy")
        if not isinstance(canary, CanaryResult):
            raise DarwinExecutionError("canary must be a CanaryResult")
        if canary.status != "supported":
            return self._report(request, "unsupported", canary.reason_code)
        if policy.profile_id != self.PROFILE_ID or policy.resource_enforcement != "observed_memory":
            return self._report(request, "unsupported", "NATIVE_CONTAINMENT_EXPERIMENTAL_PROFILE_REQUIRED")
        if not Path(self.backend_executable).is_file() or not Path(self.backend_executable).is_absolute():
            return self._report(request, "unsupported", "NATIVE_CONTAINMENT_BACKEND_UNAVAILABLE")
        try:
            cached = self._completed_for_request(request)
            if cached is not None:
                return cached
            spawned = self.spawn(request, policy, canary)
            return self.collect(spawned)
        except DarwinExecutionError:
            return self._report(request, "failed", "NATIVE_CONTAINMENT_EXECUTION_SPEC_INVALID")
        except (OSError, subprocess.SubprocessError):
            return self._report(request, "failed", "NATIVE_CONTAINMENT_EXECUTOR_FAILED")

    def spawn(
        self,
        request: ContainmentRequest,
        policy: ContainmentPolicy,
        canary: CanaryResult,
    ) -> DarwinSpawnedProcess:
        if not isinstance(request, ContainmentRequest):
            raise DarwinExecutionError("request must be a ContainmentRequest")
        if not isinstance(policy, ContainmentPolicy):
            raise DarwinExecutionError("policy must be a ContainmentPolicy")
        if not isinstance(canary, CanaryResult) or canary.status != "supported":
            raise DarwinExecutionError("spawn requires a supported canary")
        if policy.profile_id != self.PROFILE_ID or policy.resource_enforcement != "observed_memory":
            raise DarwinExecutionError("experimental profile is required")
        if self.assessment_ref is None:
            raise DarwinExecutionError("host assessment is unbound")
        spec = self.resolver(request)
        if spec is None:
            raise DarwinExecutionError("execution spec is unavailable")
        self._validate_binding(request, spec)
        if hashlib.sha256(spec.executable.read_bytes()).hexdigest() != spec.executable_digest:
            raise DarwinExecutionError("executable changed")
        request_ref = request.content_digest
        spec_ref = spec.content_digest
        with self._lock:
            if request_ref in self._spawning:
                raise DarwinExecutionError("execution spawn is already in progress")
            prior = self._request_handles.get(request_ref)
            if prior is not None:
                if prior[1] != spec_ref:
                    raise DarwinExecutionError("execution replay uses a different spec")
                active = self._active.get(prior[0])
                if active is not None:
                    return active
                if prior[0] in self._completed:
                    raise DarwinExecutionError("execution attempt has already completed")
            handle_ref = self._handle_ref(request, policy, spec)
            self._request_handles[request_ref] = (handle_ref, spec_ref)
            self._spawning.add(request_ref)
        harness = DarwinCanaryHarness(
            python_executable=str(spec.executable),
            backend_executable=self.backend_executable,
        )
        profile = harness._seatbelt_profile(
            spec.output_root,
            input_root=spec.input_root,
            executable_parent=spec.executable.parent,
        )
        stdout_path = spec.output_root / ".workbench-stdout"
        stderr_path = spec.output_root / ".workbench-stderr"
        argv = [self.backend_executable, "-p", profile, str(spec.executable), *spec.arguments]
        stdout_file = stdout_path.open("wb")
        stderr_file = stderr_path.open("wb")
        try:
            process = self.process_factory(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env=harness._environment(policy),
                cwd=str(spec.output_root),
                preexec_fn=harness._preexec(policy),
                close_fds=True,
            )
        except BaseException:
            stdout_file.close()
            stderr_file.close()
            with self._lock:
                self._spawning.discard(request_ref)
            raise
        spawned = DarwinSpawnedProcess(
            handle_ref=handle_ref,
            request=request,
            policy=policy,
            spec=spec,
            process=process,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
        )
        with self._lock:
            self._spawning.discard(request_ref)
            self._active[handle_ref] = spawned
        return spawned

    def collect(self, spawned: DarwinSpawnedProcess) -> ContainmentReport:
        if not isinstance(spawned, DarwinSpawnedProcess):
            raise DarwinExecutionError("spawned process is invalid")
        with self._lock:
            cached = self._completed.get(spawned.handle_ref)
            if cached is not None:
                return cached
            if spawned.handle_ref in self._collecting:
                raise DarwinExecutionError("execution collection is already in progress")
            self._collecting.add(spawned.handle_ref)
        try:
            try:
                outcome = self._wait_for_process(spawned.process, spawned.policy)
                if outcome is not None:
                    report = self._report(spawned.request, "failed", outcome)
                elif (
                    spawned.stdout_path.stat().st_size > spawned.policy.budget.stdout_bytes
                    or spawned.stderr_path.stat().st_size > spawned.policy.budget.stderr_bytes
                ):
                    report = self._report(spawned.request, "failed", "NATIVE_CONTAINMENT_OUTPUT_LIMIT_EXCEEDED")
                elif spawned.process.returncode != 0:
                    report = self._report(spawned.request, "failed", "NATIVE_CONTAINMENT_CHILD_FAILED")
                else:
                    output_ref = self._output_bundle_digest(
                        spawned.spec.output_root,
                        spawned.policy.budget.stdout_bytes + spawned.policy.budget.stderr_bytes,
                    )
                    report = ContainmentReport(
                        attempt_id=spawned.request.attempt_id,
                        request_digest=spawned.request.content_digest,
                        status="completed",
                        reason_code="NATIVE_CONTAINMENT_COMPLETED",
                        assessment_ref=self.assessment_ref,
                        output_bundle_ref=output_ref,
                    )
            except (OSError, subprocess.SubprocessError):
                report = self._report(spawned.request, "failed", "NATIVE_CONTAINMENT_EXECUTOR_FAILED")
        except DarwinExecutionError:
            report = self._report(spawned.request, "failed", "NATIVE_CONTAINMENT_OUTPUT_INVALID")
        finally:
            spawned.stdout_file.close()
            spawned.stderr_file.close()
            with self._lock:
                self._active.pop(spawned.handle_ref, None)
                self._completed[spawned.handle_ref] = report
                self._collecting.discard(spawned.handle_ref)
        return report

    def _completed_for_request(self, request: ContainmentRequest) -> ContainmentReport | None:
        with self._lock:
            prior = self._request_handles.get(request.content_digest)
            if prior is None:
                return None
            return self._completed.get(prior[0])

    @staticmethod
    def _handle_ref(request: ContainmentRequest, policy: ContainmentPolicy, spec: DarwinExecutionSpec) -> str:
        value = hashlib.sha256(
            f"{request.content_digest}\x00{policy.content_digest}\x00{spec.content_digest}".encode("utf-8")
        ).hexdigest()
        return f"handle-{value}"

    def _wait_for_process(self, process: subprocess.Popen, policy: ContainmentPolicy) -> str | None:
        deadline = self.clock() + max(0.1, min(policy.budget.wall_millis / 1000, 86_400.0))
        while True:
            returncode = process.poll()
            if returncode is not None:
                return None
            snapshot = self.process_snapshot(process.pid)
            if snapshot is None:
                self._kill_process(process)
                return "NATIVE_CONTAINMENT_RESOURCE_MONITOR_UNAVAILABLE"
            pid_count, memory_bytes = snapshot
            if pid_count > policy.budget.pid_count:
                self._kill_process(process)
                return "NATIVE_CONTAINMENT_PID_LIMIT_EXCEEDED"
            if memory_bytes > policy.budget.memory_bytes:
                self._kill_process(process)
                return "NATIVE_CONTAINMENT_MEMORY_LIMIT_OBSERVED"
            if self.clock() >= deadline:
                self._kill_process(process)
                return "NATIVE_CONTAINMENT_WALL_LIMIT_EXCEEDED"
            self.sleeper(0.02)

    @staticmethod
    def _validate_binding(request: ContainmentRequest, spec: DarwinExecutionSpec) -> None:
        if spec.input_bundle_ref != request.input_bundle_ref:
            raise DarwinExecutionError("execution input is not bound to the request")
        if spec.output_namespace_ref != request.output_namespace_ref:
            raise DarwinExecutionError("execution output is not bound to the request")

    @staticmethod
    def _report(request: ContainmentRequest, status: str, reason_code: str) -> ContainmentReport:
        return ContainmentReport(
            attempt_id=request.attempt_id,
            request_digest=request.content_digest,
            status=status,
            reason_code=reason_code,
        )

    @staticmethod
    def _kill_process(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def _default_process_snapshot(root_pid: int) -> tuple[int, int] | None:
        try:
            completed = subprocess.run(
                ["/bin/ps", "-axo", "pid=,ppid=,rss="],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=1,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if completed.returncode != 0:
            return None
        records: dict[int, tuple[int, int]] = {}
        try:
            for line in completed.stdout.splitlines():
                values = line.split()
                if len(values) != 3:
                    continue
                pid, parent, rss = (int(item) for item in values)
                records[pid] = (parent, rss * 1024)
        except (TypeError, ValueError):
            return None
        if root_pid not in records:
            return None
        descendants = {root_pid}
        changed = True
        while changed:
            changed = False
            for pid, (parent, _rss) in records.items():
                if parent in descendants and pid not in descendants:
                    descendants.add(pid)
                    changed = True
        return len(descendants), sum(records[pid][1] for pid in descendants)

    @staticmethod
    def _output_bundle_digest(root: Path, maximum_bytes: int) -> str:
        if root.is_symlink() or not root.is_dir():
            raise DarwinExecutionError("output root is not a regular directory")
        digest = hashlib.sha256()
        total = 0
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise DarwinExecutionError("output contains a symlink")
            if not path.is_file():
                continue
            size = path.stat().st_size
            total += size
            if total > maximum_bytes:
                raise DarwinExecutionError("output exceeds the bounded bundle size")
            relative = path.relative_to(root).as_posix().encode("utf-8")
            digest.update(len(relative).to_bytes(4, "big"))
            digest.update(relative)
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    digest.update(chunk)
        return digest.hexdigest()


__all__ = [
    "DarwinExecutionError",
    "DarwinExecutionSpec",
    "DarwinExperimentalExecutor",
    "DarwinSpawnedProcess",
]
