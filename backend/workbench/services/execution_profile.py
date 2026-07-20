"""Explicit, process-local admission for locally contained development.

This module deliberately does not participate in C2 candidate evaluation.
It merely makes a locally launched Workbench choose between its existing
fail-closed default and a native-OS-sandbox-verified local development profile.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

from ..sandbox import SandboxTimeoutError, SandboxUnavailableError, run_python_sandboxed


_PROFILE_ENV = "WORKBENCH_EXECUTION_PROFILE"
_DEFAULT_PROFILE = "default"
_LOCAL_CONTAINED_PROFILE = "local_contained"
_DENIED_ERRNOS = {1, 13}


class ExecutionProfileError(RuntimeError):
    """A bounded execution-profile rejection suitable for an API boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ExecutionProfile:
    """The immutable process-local result of explicit startup selection."""

    profile: str
    lmm_admitted: bool
    high_risk_code_admitted: bool
    canary_status: str

    def require_lmm_admission(self) -> None:
        if not self.lmm_admitted:
            raise ExecutionProfileError("LMM_FROZEN_CONTAINMENT_REQUIRED")

    def public_status(self) -> dict[str, object]:
        return {
            "profile": self.profile,
            "lmm_admitted": self.lmm_admitted,
            "high_risk_code_admitted": self.high_risk_code_admitted,
            "canary_status": self.canary_status,
        }


_profile_lock = threading.Lock()
_profile: ExecutionProfile | None = None


def current_execution_profile() -> ExecutionProfile:
    """Return one cached process-local profile, creating it exactly once."""

    global _profile
    with _profile_lock:
        if _profile is None:
            _profile = _create_execution_profile()
        return _profile


def _create_execution_profile() -> ExecutionProfile:
    raw = os.getenv(_PROFILE_ENV, _DEFAULT_PROFILE).strip()
    if raw == "":
        raw = _DEFAULT_PROFILE
    if raw == _DEFAULT_PROFILE:
        return ExecutionProfile(
            profile=_DEFAULT_PROFILE,
            lmm_admitted=False,
            high_risk_code_admitted=False,
            canary_status="not_requested",
        )
    if raw != _LOCAL_CONTAINED_PROFILE:
        raise ExecutionProfileError("LOCAL_CONTAINMENT_PROFILE_INVALID")
    _run_local_containment_canary()
    return ExecutionProfile(
        profile=_LOCAL_CONTAINED_PROFILE,
        lmm_admitted=True,
        high_risk_code_admitted=True,
        canary_status="passed",
    )


def _run_local_containment_canary() -> None:
    """Prove the production sandbox can execute a narrow local canary.

    The child must write only to its declared output directory and receive
    genuine OS denials for an external write and a network connection.  The
    parent trusts neither a child return code nor a human-readable error alone:
    it accepts only the exact compact assertion object below.
    """

    with tempfile.TemporaryDirectory(prefix="wb-local-canary-") as temporary:
        root = Path(temporary)
        output = root / "output"
        output.mkdir()
        script = root / "canary.py"
        script.write_text(
            _canary_script(output=output, outside=root / "outside.txt"),
            encoding="utf-8",
        )
        try:
            result = run_python_sandboxed(script, writable_dirs=[output])
        except (SandboxUnavailableError, SandboxTimeoutError, OSError):
            raise ExecutionProfileError("LOCAL_CONTAINMENT_CANARY_FAILED") from None
    if result.returncode != 0:
        raise ExecutionProfileError("LOCAL_CONTAINMENT_CANARY_FAILED")
    try:
        facts = json.loads(result.stdout)
    except (TypeError, ValueError, json.JSONDecodeError):
        raise ExecutionProfileError("LOCAL_CONTAINMENT_CANARY_FAILED") from None
    if facts != {
        "declared_output_writable": True,
        "external_write_denied": True,
        "network_denied": True,
    }:
        raise ExecutionProfileError("LOCAL_CONTAINMENT_CANARY_FAILED")


def _canary_script(*, output: Path, outside: Path) -> str:
    """Return a fixed child program; all paths are JSON string literals."""

    output_literal = json.dumps(str(output))
    outside_literal = json.dumps(str(outside))
    denied_errnos = json.dumps(sorted(_DENIED_ERRNOS))
    return f'''\
import errno
import json
import socket
from pathlib import Path

output = Path({output_literal})
outside = Path({outside_literal})
denied_errnos = set({denied_errnos})

output.joinpath("canary.txt").write_text("ok", encoding="utf-8")
declared_output_writable = output.joinpath("canary.txt").read_text(encoding="utf-8") == "ok"

try:
    outside.write_text("forbidden", encoding="utf-8")
except OSError as error:
    external_write_denied = error.errno in denied_errnos
else:
    external_write_denied = False

try:
    socket.create_connection(("127.0.0.1", 9), timeout=0.2)
except OSError as error:
    network_denied = error.errno in denied_errnos
else:
    network_denied = False

facts = {{
    "declared_output_writable": declared_output_writable,
    "external_write_denied": external_write_denied,
    "network_denied": network_denied,
}}
print(json.dumps(facts, sort_keys=True))
raise SystemExit(0 if all(facts.values()) else 1)
'''


def _reset_execution_profile_for_test() -> None:
    """Test-only reset; production never changes a selected profile in-process."""

    global _profile
    with _profile_lock:
        _profile = None


__all__ = [
    "ExecutionProfile",
    "ExecutionProfileError",
    "current_execution_profile",
]
