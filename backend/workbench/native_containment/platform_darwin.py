"""Darwin Seatbelt canary adapter with typed fail-closed results."""

from __future__ import annotations

import hashlib
import math
import os
import platform
import resource
import signal
import tempfile
import subprocess
from pathlib import Path
from typing import Callable, Mapping

from .host import CanaryAssertion, CanaryResult, HostIdentity
from .policy import ContainmentPolicy


class DarwinCanaryHarness:
    CANARY_CASES = (
        "host_read_denied",
        "directory_enumeration_denied",
        "network_denied",
        "write_escape_denied",
        "descriptor_inheritance_denied",
        "process_tree_cleanup",
        "output_root_only_writable",
    )

    _CANARY_SCRIPT = r"""
import os
import socket
import subprocess
import sys
import time

case = sys.argv[1]
output_root = sys.argv[2]

def denied(action):
    try:
        action()
    except (OSError, PermissionError):
        return True
    return False

if case == "host_read_denied":
    ok = denied(lambda: open("/etc/hosts", "rb").read(1))
elif case == "directory_enumeration_denied":
    ok = denied(lambda: os.listdir("/"))
elif case == "network_denied":
    def connect():
        with socket.create_connection(("198.51.100.1", 9), timeout=0.25):
            pass
    ok = denied(connect)
elif case == "write_escape_denied":
    outside = os.path.join(os.path.dirname(output_root), "escape-marker")
    ok = denied(lambda: open(outside, "wb").write(b"escape"))
elif case == "descriptor_inheritance_denied":
    inherited = []
    for fd in range(3, 64):
        try:
            os.fstat(fd)
        except OSError:
            continue
        inherited.append(fd)
    ok = not inherited
elif case == "process_tree_cleanup":
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    time.sleep(60)
    ok = False
elif case == "output_root_only_writable":
    target = os.path.join(output_root, "canary-output")
    with open(target, "wb") as handle:
        handle.write(b"ok")
    ok = open(target, "rb").read() == b"ok"
else:
    ok = False

raise SystemExit(0 if ok else 1)
"""

    def __init__(
        self,
        *,
        python_executable: str,
        backend_executable: str,
        canary_probe: Callable[[ContainmentPolicy], Mapping[str, bool]] | None = None,
        host_supported: Callable[[], bool] | None = None,
        backend_available: Callable[[], bool] | None = None,
    ) -> None:
        self.python_executable = python_executable
        self.backend_executable = backend_executable
        self.canary_probe = canary_probe
        self.host_supported = host_supported or (lambda: platform.system() == "Darwin")
        self.backend_available = backend_available or (lambda: Path(self.backend_executable).is_file())
        self._probe_reason: str | None = None

    def discover_identity(self) -> HostIdentity:
        path = Path(self.backend_executable)
        if not path.is_absolute() or not path.is_file():
            raise OSError("Darwin containment backend is unavailable")
        return HostIdentity(
            os_name=platform.system(),
            kernel_release=platform.release(),
            architecture=platform.machine(),
            backend_executable=str(path),
            backend_version="unknown",
            backend_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
        )

    def run(self, policy: ContainmentPolicy) -> CanaryResult:
        if not isinstance(policy, ContainmentPolicy):
            raise TypeError("policy must be a ContainmentPolicy")
        if not self.host_supported():
            return CanaryResult.unsupported("NATIVE_CONTAINMENT_HOST_UNSUPPORTED")
        if not self.backend_available():
            return CanaryResult.unsupported("NATIVE_CONTAINMENT_BACKEND_UNAVAILABLE")
        if not Path(self.python_executable).is_file():
            return CanaryResult.unsupported("NATIVE_CONTAINMENT_INTERPRETER_UNAVAILABLE")
        try:
            self._probe_reason = None
            results = self.canary_probe(policy) if self.canary_probe is not None else self._default_probe(policy)
        except (OSError, subprocess.SubprocessError):
            return CanaryResult.unsupported("NATIVE_CONTAINMENT_CANARY_FAILED")
        assertions = tuple(
            CanaryAssertion(case_id=case, passed=bool(results.get(case, False)), reason="canary assertion")
            for case in self.CANARY_CASES
        )
        if all(item.passed for item in assertions):
            return CanaryResult("supported", "NATIVE_CONTAINMENT_CANARY_PASSED", assertions)
        return CanaryResult(
            "unsupported",
            self._probe_reason or "NATIVE_CONTAINMENT_CANARY_FAILED",
            assertions,
        )

    def _default_probe(self, policy: ContainmentPolicy) -> Mapping[str, bool]:
        if not self.backend_executable.startswith("/"):
            return {}
        with tempfile.TemporaryDirectory(prefix="workbench-native-canary-") as root_name:
            root = Path(root_name)
            output_root = root / "output"
            output_root.mkdir()
            profile = self._seatbelt_profile(output_root)
            results: dict[str, bool] = {}
            for case in self.CANARY_CASES:
                results[case] = self._run_case(policy, case, profile, output_root)
            return results

    def _seatbelt_profile(self, output_root: Path) -> str:
        """Build the fixed deny-by-default profile used only by trusted canaries."""

        output = output_root.resolve()
        python_parent = Path(self.python_executable).resolve().parent
        return "\n".join(
            (
                "(version 1)",
                "(deny default)",
                "(deny network*)",
                "(allow process-exec)",
                "(allow process-fork)",
                "(allow signal (target self))",
                "(allow sysctl-read)",
                '(allow file-read* (subpath "/usr"))',
                '(allow file-read* (subpath "/System"))',
                '(allow file-read* (subpath "/Library"))',
                f'(allow file-read* (subpath "{python_parent}"))',
                f'(allow file-read* (subpath "{output}"))',
                f'(allow file-write* (subpath "{output}"))',
                '(allow file-write-data (literal "/dev/null"))',
            )
        )

    def _environment(self, policy: ContainmentPolicy) -> dict[str, str]:
        environment = dict(policy.environment_allowlist)
        for name in (
            "OMP_NUM_THREADS",
            "OPENBLAS_NUM_THREADS",
            "MKL_NUM_THREADS",
            "VECLIB_MAXIMUM_THREADS",
        ):
            environment.setdefault(name, "1")
        return environment

    def _preexec(self, policy: ContainmentPolicy):
        budget = policy.budget

        def apply_limits() -> None:  # pragma: no cover - runs in the child process
            os.setsid()
            resource.setrlimit(
                resource.RLIMIT_CPU,
                (max(1, math.ceil(budget.cpu_millis / 1000)), max(1, math.ceil(budget.cpu_millis / 1000))),
            )
            resource.setrlimit(
                resource.RLIMIT_FSIZE,
                (max(budget.stdout_bytes, budget.stderr_bytes), max(budget.stdout_bytes, budget.stderr_bytes)),
            )
            try:
                resource.setrlimit(resource.RLIMIT_AS, (budget.memory_bytes, budget.memory_bytes))
            except (ValueError, OSError):
                self._probe_reason = "NATIVE_CONTAINMENT_RESOURCE_LIMIT_UNAVAILABLE"

        return apply_limits

    @staticmethod
    def _classify_probe_failure(diagnostic: str, returncode: int) -> str | None:
        if "sandbox_apply" in diagnostic:
            return "NATIVE_CONTAINMENT_SANDBOX_APPLY_FAILED"
        if returncode in {134, -signal.SIGABRT}:
            return "NATIVE_CONTAINMENT_SANDBOX_PROFILE_ABORTED"
        return None

    def _run_case(self, policy: ContainmentPolicy, case: str, profile: str, output_root: Path) -> bool:
        if case not in self.CANARY_CASES:
            return False
        timeout = max(0.1, min(policy.budget.wall_millis / 1000, 30.0))
        stdout_path = output_root / f"{case}.stdout"
        stderr_path = output_root / f"{case}.stderr"
        argv = [
            self.backend_executable,
            "-p",
            profile,
            self.python_executable,
            "-I",
            "-c",
            self._CANARY_SCRIPT,
            case,
            str(output_root),
        ]
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env=self._environment(policy),
                cwd=str(output_root),
                preexec_fn=self._preexec(policy),
                close_fds=True,
            )
            try:
                process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._kill_process_group(process)
                process.wait()
                return case == "process_tree_cleanup"
            finally:
                self._kill_process_group(process)
        if stdout_path.stat().st_size > policy.budget.stdout_bytes:
            return False
        if stderr_path.stat().st_size > policy.budget.stderr_bytes:
            return False
        diagnostic = stderr_path.read_bytes()[:4096].decode("utf-8", errors="replace").lower()
        failure_reason = self._classify_probe_failure(diagnostic, process.returncode)
        if failure_reason is not None:
            self._probe_reason = failure_reason
        return process.returncode == 0

    @staticmethod
    def _kill_process_group(process: subprocess.Popen) -> None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except PermissionError:
            process.kill()


__all__ = ["DarwinCanaryHarness"]
