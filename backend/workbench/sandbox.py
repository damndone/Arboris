"""OS-level sandbox for running untrusted transform code (v1.7 G3).

This is the piece that gates `code.execute`. It is deliberately narrow and
fail-closed, and its guarantees are stated honestly:

WHAT IT ENFORCES
  * no network egress (the sandbox profile denies all sockets);
  * no filesystem writes outside the operation's own output directory;
  * bounded CPU seconds, address space, output file size and wall clock;
  * a scrubbed environment — provider API keys and other host secrets are
    never inherited by the child.

WHAT IT DOES NOT CLAIM
  * it is not a defence against a determined attacker with a kernel exploit;
  * reads of the local filesystem are permitted (the code needs the Python
    stdlib and site-packages, and the data is the user's own, on their own
    machine). The threat model is an LLM- or user-authored transform that
    misbehaves — deleting the source, hanging, or phoning home — not a
    hostile adversary who already has code execution on the box.

If no OS isolation backend is available we REFUSE to run rather than degrade
to in-process `exec`, because a Python-level guard is not a sandbox and
pretending otherwise would be the actual security failure.
"""

from __future__ import annotations

import os
import platform
import resource
import signal
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CPU_SECONDS = 10
DEFAULT_MEMORY_BYTES = 1_024 * 1_024 * 1_024  # 1 GiB
DEFAULT_WALL_SECONDS = 30.0
DEFAULT_OUTPUT_BYTES = 64 * 1_024 * 1_024  # 64 MiB


class SandboxUnavailableError(RuntimeError):
    """No OS isolation backend — execution must not proceed."""


class SandboxTimeoutError(RuntimeError):
    """The sandboxed process exceeded its wall-clock budget."""


@dataclass(frozen=True)
class SandboxLimits:
    cpu_seconds: int = DEFAULT_CPU_SECONDS
    memory_bytes: int = DEFAULT_MEMORY_BYTES
    wall_seconds: float = DEFAULT_WALL_SECONDS
    output_bytes: int = DEFAULT_OUTPUT_BYTES


@dataclass(frozen=True)
class SandboxResult:
    returncode: int
    stdout: str
    stderr: str
    duration_s: float

    @property
    def ok(self) -> bool:
        return self.returncode == 0


def isolation_backend() -> str | None:
    """Name the available OS isolation backend, or None if there is none."""

    if platform.system() == "Darwin" and shutil.which("sandbox-exec"):
        return "seatbelt"
    if shutil.which("bwrap"):
        return "bubblewrap"
    return None


def _seatbelt_profile(writable: list[Path]) -> str:
    """Allow-by-default, then deny the two things that matter: network + writes.

    Reads stay allowed (stdlib/site-packages/input). Writes are re-allowed only
    under the operation's own output directory and the private temp dir.
    """

    lines = [
        "(version 1)",
        "(allow default)",
        "(deny network*)",
        "(deny file-write*)",
    ]
    for path in writable:
        lines.append(f'(allow file-write* (subpath "{path.resolve()}"))')
    # /dev/null is needed by common libraries; it is a write to a sink, not the FS.
    lines.append('(allow file-write-data (literal "/dev/null"))')
    return "\n".join(lines)


def _scrubbed_env(home: Path) -> dict[str, str]:
    """A minimal environment. Host secrets (API keys) are never inherited."""

    return {
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        "TMPDIR": str(home),
        "PYTHONDONTWRITEBYTECODE": "1",
        # keep matplotlib headless and off the user's config dir
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": str(home),
        "LC_ALL": "en_US.UTF-8",
        "LANG": "en_US.UTF-8",
    }


def _apply_rlimits(limits: SandboxLimits):
    def _preexec() -> None:  # pragma: no cover - runs in the child process
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.output_bytes, limits.output_bytes))
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        except (ValueError, OSError):
            # Some platforms refuse RLIMIT_AS for the interpreter itself; CPU and
            # file-size limits still bound the damage.
            pass
        os.setsid()

    return _preexec


def _read_capped_output(path: Path, limit: int) -> str:
    """Read at most ``limit`` bytes from one child output stream."""

    with path.open("rb") as handle:
        raw = handle.read(limit)
    return raw.decode("utf-8", errors="replace")


def _kill_process_group(process: subprocess.Popen) -> None:
    """Stop the sandbox process and descendants created by the transform."""

    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except PermissionError:
        process.kill()


def run_python_sandboxed(
    script_path: Path,
    *,
    writable_dirs: list[Path],
    limits: SandboxLimits | None = None,
) -> SandboxResult:
    """Run one Python script under OS isolation. Refuses without a backend."""

    effective = limits or SandboxLimits()
    backend = isolation_backend()
    if backend is None:
        raise SandboxUnavailableError(
            "No OS sandbox backend is available (need macOS sandbox-exec or "
            "Linux bwrap). Refusing to execute untrusted code unsandboxed."
        )

    with tempfile.TemporaryDirectory(prefix="wb-sandbox-home-") as home_name:
        home = Path(home_name)
        writable = [*[Path(p) for p in writable_dirs], home]

        if backend == "seatbelt":
            profile = _seatbelt_profile(writable)
            argv = [
                "sandbox-exec",
                "-p",
                profile,
                sys.executable,
                "-I",
                str(script_path),
            ]
        else:  # bubblewrap
            argv = ["bwrap", "--unshare-net", "--ro-bind", "/", "/", "--dev", "/dev"]
            for path in writable:
                argv += ["--bind", str(path.resolve()), str(path.resolve())]
            argv += ["--proc", "/proc", sys.executable, "-I", str(script_path)]

        stdout_path = home / "stdout.bin"
        stderr_path = home / "stderr.bin"
        started = time.monotonic()
        timed_out = False
        with stdout_path.open("wb") as stdout_file, stderr_path.open("wb") as stderr_file:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=stdout_file,
                stderr=stderr_file,
                env=_scrubbed_env(home),
                cwd=str(home),
                preexec_fn=_apply_rlimits(effective),
                close_fds=True,
            )
            try:
                returncode = process.wait(timeout=effective.wall_seconds)
            except subprocess.TimeoutExpired as exc:
                timed_out = True
                _kill_process_group(process)
                process.wait()
                raise SandboxTimeoutError(
                    f"sandboxed code exceeded {effective.wall_seconds}s wall clock"
                ) from exc
            finally:
                if not timed_out:
                    # A transform can spawn a descendant and exit immediately;
                    # clean up the process group even when the leader finished.
                    _kill_process_group(process)
        duration = time.monotonic() - started
        stdout = _read_capped_output(stdout_path, effective.output_bytes)
        stderr = _read_capped_output(stderr_path, effective.output_bytes)

    return SandboxResult(
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
        duration_s=duration,
    )


__all__ = [
    "SandboxLimits",
    "SandboxResult",
    "SandboxTimeoutError",
    "SandboxUnavailableError",
    "isolation_backend",
    "run_python_sandboxed",
]
