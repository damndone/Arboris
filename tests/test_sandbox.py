"""v1.7 G3 — the sandbox's guarantees must be PROVEN, not assumed.

Each test drives real code through the real sandbox and asserts the boundary
actually holds. A sandbox that is only asserted in a docstring is not a sandbox.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workbench.sandbox import (
    SandboxLimits,
    SandboxTimeoutError,
    SandboxUnavailableError,
    isolation_backend,
    run_python_sandboxed,
)

pytestmark = pytest.mark.skipif(
    isolation_backend() is None,
    reason="no OS sandbox backend on this platform",
)


def _script(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "script.py"
    path.write_text(body, encoding="utf-8")
    return path


def test_sandbox_runs_ordinary_code_and_captures_stdout(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    script = _script(tmp_path, "print('hello from the sandbox')")

    result = run_python_sandboxed(script, writable_dirs=[out])

    assert result.ok, result.stderr
    assert "hello from the sandbox" in result.stdout


def test_sandbox_denies_network_egress(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    script = _script(
        tmp_path,
        "import socket\n"
        "try:\n"
        "    s = socket.create_connection(('1.1.1.1', 80), timeout=3)\n"
        "    print('NETWORK_REACHED')\n"
        "except Exception as exc:\n"
        "    print('NETWORK_BLOCKED')\n",
    )

    result = run_python_sandboxed(script, writable_dirs=[out])

    assert "NETWORK_REACHED" not in result.stdout
    assert "NETWORK_BLOCKED" in result.stdout


def test_sandbox_allows_writes_inside_the_output_dir(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    target = out / "result.txt"
    script = _script(tmp_path, f"open({str(target)!r}, 'w').write('ok')")

    result = run_python_sandboxed(script, writable_dirs=[out])

    assert result.ok, result.stderr
    assert target.read_text() == "ok"


def test_sandbox_denies_writes_outside_the_output_dir(tmp_path: Path) -> None:
    """The source-immutability guarantee: code cannot touch its own input."""
    out = tmp_path / "out"
    out.mkdir()
    source = tmp_path / "source.csv"
    source.write_text("a,b\n1,2\n", encoding="utf-8")
    script = _script(
        tmp_path,
        f"try:\n"
        f"    open({str(source)!r}, 'w').write('CLOBBERED')\n"
        f"    print('WRITE_ALLOWED')\n"
        f"except Exception:\n"
        f"    print('WRITE_BLOCKED')\n",
    )

    result = run_python_sandboxed(script, writable_dirs=[out])

    assert "WRITE_ALLOWED" not in result.stdout
    assert "WRITE_BLOCKED" in result.stdout
    # the source survived byte-for-byte
    assert source.read_text() == "a,b\n1,2\n"


def test_sandbox_kills_runaway_cpu(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    script = _script(tmp_path, "while True:\n    pass\n")

    result = run_python_sandboxed(
        script,
        writable_dirs=[out],
        limits=SandboxLimits(cpu_seconds=1, wall_seconds=20.0),
    )

    # SIGXCPU (or a non-zero exit) — the point is it does not run forever
    assert not result.ok


def test_sandbox_enforces_wall_clock(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    script = _script(tmp_path, "import time\ntime.sleep(30)\n")

    with pytest.raises(SandboxTimeoutError):
        run_python_sandboxed(
            script,
            writable_dirs=[out],
            limits=SandboxLimits(cpu_seconds=30, wall_seconds=2.0),
        )


def test_sandbox_does_not_inherit_host_secrets(tmp_path: Path, monkeypatch) -> None:
    """An LLM key in the parent env must never reach transform code."""
    monkeypatch.setenv("WORKBENCH_LLM_API_KEY", "sk-super-secret")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")
    out = tmp_path / "out"
    out.mkdir()
    script = _script(
        tmp_path,
        "import os\n"
        "print('KEYS', [k for k in os.environ if 'KEY' in k.upper() or 'SECRET' in k.upper()])\n"
        "print('VALUES_LEAKED', 'sk-super-secret' in repr(dict(os.environ)))\n",
    )

    result = run_python_sandboxed(script, writable_dirs=[out])

    assert "KEYS []" in result.stdout
    assert "VALUES_LEAKED False" in result.stdout


def test_refuses_to_run_without_an_isolation_backend(tmp_path: Path, monkeypatch) -> None:
    """Fail closed: no backend → refuse, never fall back to bare exec."""
    import workbench.sandbox as sandbox_module

    monkeypatch.setattr(sandbox_module, "isolation_backend", lambda: None)
    out = tmp_path / "out"
    out.mkdir()
    script = _script(tmp_path, "print('should never run')")

    with pytest.raises(SandboxUnavailableError):
        sandbox_module.run_python_sandboxed(script, writable_dirs=[out])
