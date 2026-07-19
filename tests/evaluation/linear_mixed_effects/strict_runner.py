#!/usr/bin/env python3
"""Run one complete LMM evaluation in a candidate-only subprocess.

The evidence collector launches this program instead of importing a candidate.
It clears provider-bearing environment state and installs the network guard
before pytest can collect a candidate-facing module.  It also owns local
performance measurement so no candidate code ever runs in the collector.
"""

from __future__ import annotations

import argparse
import contextlib
import csv
import hashlib
import importlib
import json
import os
import platform
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as element_tree
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any


STRICT_ENV = "WORKBENCH_EVALUATION_REQUIRE_CANDIDATE"
CANDIDATE_ROOT_ENV = "WORKBENCH_EVALUATION_CANDIDATE_ROOT"
EVALUATOR_ROOT_ENV = "WORKBENCH_EVALUATION_EVALUATOR_ROOT"
BLOCKED_ENV_NAMES = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GOOGLE_API_KEY",
    "AZURE_OPENAI_API_KEY",
)
FIXTURE_RELATIVE_PATH = Path("tests/fixtures/models/linear_mixed_effects/known_truth.csv")
RUNNER_MODULE = "workbench.engine.packs.linear_mixed_effects.runner"
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
RESULT_NAMES = (
    "contract_validation",
    "known_truth",
    "fault_injection",
    "agent_boundaries",
    "compare_restrictions",
    "deterministic_overclaim_checks",
)
STRICT_TEST_FILES = {
    "contract_validation": "test_contract_compatibility.py",
    "known_truth": "test_known_truth.py",
    "fault_injection": "test_fault_injection.py",
    "agent_boundaries": "test_agent_boundaries.py",
    "compare_restrictions": "test_compare_restrictions.py",
    "deterministic_overclaim_checks": "test_report_claims.py",
}
LMM_RESULT_CONTRACT = "linear_mixed_effects.result"
LMM_RESULT_CONTRACT_VERSION = "1.0"
LMM_RESULT_PRODUCER_VERSION = "linear_mixed_effects@1.0"
STRICT_OUTPUT_METADATA_SCHEMA_VERSION = "v173_lmm_strict_output_metadata_v1"
STRICT_JUNIT_SUMMARY_SCHEMA_VERSION = "v173_lmm_strict_junit_summary_v1"
MAX_REPORTED_STREAM_BYTES = 65536
RAW_STREAM_CAPTURE_POLICY = (
    "raw pytest stdout and stderr are discarded; hashes cover complete streams"
)


class StrictEvaluationError(RuntimeError):
    """Raised when strict isolation or local candidate evaluation fails."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    _write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _write_text(path: Path, value: str) -> None:
    """Atomically finalize runner-owned evidence artifacts."""

    if path.exists():
        raise StrictEvaluationError(f"refusing to overwrite strict evidence artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        handle.write(value)
    os.replace(temporary, path)


class _DigestingTextCapture:
    """Stream candidate-facing text into a digest without retaining its content."""

    encoding = "utf-8"

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._reported_bytes = 0
        self._truncated = False

    def write(self, value: str) -> int:
        encoded = value.encode("utf-8", errors="backslashreplace")
        self._digest.update(encoded)
        remaining = MAX_REPORTED_STREAM_BYTES - self._reported_bytes
        if len(encoded) > remaining:
            self._truncated = True
        self._reported_bytes += min(len(encoded), max(remaining, 0))
        return len(value)

    def flush(self) -> None:
        return None

    def isatty(self) -> bool:
        return False

    def metadata(self) -> tuple[str, int, bool]:
        return self._digest.hexdigest(), self._reported_bytes, self._truncated


def _stream_output_metadata(
    stdout: _DigestingTextCapture,
    stderr: _DigestingTextCapture,
) -> dict[str, object]:
    stdout_sha256, stdout_bytes, stdout_truncated = stdout.metadata()
    stderr_sha256, stderr_bytes, stderr_truncated = stderr.metadata()
    return {
        "schema_version": STRICT_OUTPUT_METADATA_SCHEMA_VERSION,
        "capture_policy": RAW_STREAM_CAPTURE_POLICY,
        "max_reported_bytes": MAX_REPORTED_STREAM_BYTES,
        "stdout_sha256": stdout_sha256,
        "stderr_sha256": stderr_sha256,
        "stdout_bytes_observed": stdout_bytes,
        "stderr_bytes_observed": stderr_bytes,
        "stdout_truncated": stdout_truncated,
        "stderr_truncated": stderr_truncated,
    }


def _safe_error_code(error: BaseException) -> str:
    """Do not persist candidate-controlled exception text in strict evidence."""

    if isinstance(error, StrictEvaluationError) and str(error).startswith("candidate SHA"):
        return "INVALID_CANDIDATE_SHA"
    if isinstance(error, StrictEvaluationError):
        return "STRICT_EVALUATION_ERROR"
    return "UNEXPECTED_STRICT_ERROR"


def _artifact_descriptor(path: Path) -> dict[str, str | None]:
    return {"path": str(path), "sha256": _sha256(path)}


def _validate_full_sha(candidate_sha: str) -> None:
    if not FULL_SHA_PATTERN.fullmatch(candidate_sha):
        raise StrictEvaluationError("candidate SHA must be a 40-character full lowercase SHA")


def _clean_environment(artifact_dir: Path, candidate_root: Path, evaluator_root: Path) -> None:
    """Remove provider/key configuration before any candidate import happens."""

    isolated_home = artifact_dir / "isolated-home"
    isolated_home.mkdir(parents=True, exist_ok=True)
    os.environ.clear()
    os.environ.update(
        {
            "HOME": str(isolated_home),
            "XDG_CACHE_HOME": str(isolated_home / "cache"),
            "XDG_CONFIG_HOME": str(isolated_home / "config"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONNOUSERSITE": "1",
            "PYTHONHASHSEED": "0",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "LANG": "C",
            STRICT_ENV: "1",
            CANDIDATE_ROOT_ENV: str(candidate_root),
            EVALUATOR_ROOT_ENV: str(evaluator_root),
        }
    )
    os.chdir(isolated_home)


def _install_in_process_guards() -> None:
    """Block common Python egress and process-spawn paths before candidate imports.

    This is deliberately a scoped in-process guard, not an operating-system
    sandbox or proof that every possible egress route is unavailable.
    """

    def blocked(*_args: object, **_kwargs: object) -> object:
        raise StrictEvaluationError(
            "network access is forbidden before and during strict candidate evaluation"
        )

    socket.socket.connect = blocked  # type: ignore[assignment]
    socket.socket.connect_ex = blocked  # type: ignore[assignment]
    socket.create_connection = blocked  # type: ignore[assignment]

    def blocked_process(*_args: object, **_kwargs: object) -> object:
        raise StrictEvaluationError(
            "process spawning is forbidden before and during strict candidate evaluation"
        )

    subprocess.Popen = blocked_process  # type: ignore[assignment]
    subprocess.run = blocked_process  # type: ignore[assignment]
    subprocess.call = blocked_process  # type: ignore[assignment]
    subprocess.check_call = blocked_process  # type: ignore[assignment]
    subprocess.check_output = blocked_process  # type: ignore[assignment]
    os.system = blocked_process  # type: ignore[assignment]
    os.popen = blocked_process  # type: ignore[assignment]
    for name in (
        "posix_spawn",
        "posix_spawnp",
        "spawnl",
        "spawnle",
        "spawnlp",
        "spawnlpe",
        "spawnv",
        "spawnve",
        "spawnvp",
        "spawnvpe",
    ):
        if hasattr(os, name):
            setattr(os, name, blocked_process)


def _prepare_import_path(candidate_root: Path, evaluator_root: Path) -> None:
    candidate_backend = (candidate_root / "backend").resolve()
    if not candidate_backend.is_dir():
        raise StrictEvaluationError(f"candidate backend does not exist: {candidate_backend}")

    evaluator_backend = (evaluator_root / "backend").resolve()
    evaluator_root = evaluator_root.resolve()
    retained: list[str] = []
    for entry in sys.path:
        if not entry:
            continue
        try:
            resolved = Path(entry).resolve()
        except OSError:
            retained.append(entry)
            continue
        if resolved in {candidate_root, candidate_backend, evaluator_root, evaluator_backend}:
            continue
        retained.append(entry)
    sys.path[:] = [str(candidate_backend), str(evaluator_root), *retained]
    for name in tuple(sys.modules):
        if name == "workbench" or name.startswith("workbench."):
            del sys.modules[name]


def _assert_candidate_provenance(module_name: str, module: ModuleType, candidate_root: Path) -> None:
    module_file = getattr(module, "__file__", None)
    if not module_file:
        raise StrictEvaluationError(f"candidate module has no __file__: {module_name}")
    resolved_file = Path(module_file).resolve()
    if not resolved_file.is_relative_to(candidate_root.resolve()):
        raise StrictEvaluationError(
            "candidate module loaded outside supplied candidate root: "
            f"{module_name} -> {resolved_file}"
        )


def _fixture_shape(path: Path) -> tuple[int, int]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return len(rows), len({row["participant_id"] for row in rows})


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise StrictEvaluationError("cannot calculate a percentile with no measurements")
    if len(ordered) == 1:
        return ordered[0]
    position = 0.95 * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _load_fit(candidate_root: Path) -> Callable[..., object]:
    try:
        module = importlib.import_module(RUNNER_MODULE)
    except ModuleNotFoundError as error:
        missing = error.name or RUNNER_MODULE
        raise StrictEvaluationError(
            f"supplied candidate does not provide required module: {missing}"
        ) from error
    _assert_candidate_provenance(RUNNER_MODULE, module, candidate_root)
    try:
        fit = getattr(module, "fit_linear_mixed_effects")
    except AttributeError as error:
        raise StrictEvaluationError(
            "supplied candidate runner has no fit_linear_mixed_effects helper"
        ) from error
    if not callable(fit):
        raise StrictEvaluationError("fit_linear_mixed_effects is not callable")
    return fit


def _fit_once(
    fit: Callable[..., object],
    fixture: Path,
    run_root: Path,
) -> dict[str, object]:
    run_root.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    outcome = fit(
        csv_path=fixture,
        outcome="score",
        controls=["baseline_score"],
        options={
            "subject_id": "participant_id",
            "time": "week",
            "group": "arm",
            "fit_method": "reml",
            "random_slope": True,
        },
        run_root=run_root,
    )
    duration = time.perf_counter() - started
    if not isinstance(outcome, tuple) or len(outcome) != 2:
        raise StrictEvaluationError("runner must return exactly (result, fitted)")
    result, fitted = outcome
    if not isinstance(result, Mapping):
        raise StrictEvaluationError("runner result must be a C1 PacketEnvelope mapping")
    try:
        from workbench.contracts.common.envelope import ContractError, PacketEnvelope

        envelope = PacketEnvelope.from_dict(result)
    except (ContractError, TypeError, ValueError) as error:
        raise StrictEvaluationError("runner result must be a valid C1 PacketEnvelope") from error
    if (
        envelope.contract != LMM_RESULT_CONTRACT
        or envelope.contract_version != LMM_RESULT_CONTRACT_VERSION
        or envelope.producer_version != LMM_RESULT_PRODUCER_VERSION
    ):
        raise StrictEvaluationError("runner result has an unexpected C1 packet identity")
    payload = envelope.to_dict()["payload"]
    if not isinstance(payload, Mapping):
        raise StrictEvaluationError("runner C1 packet payload must be an object")
    if payload.get("model_type") != "linear_mixed_effects":
        raise StrictEvaluationError("runner C1 packet payload does not identify linear_mixed_effects")
    if getattr(fitted, "converged", None) is not True:
        raise StrictEvaluationError("measured LMM fit did not converge")

    artifact = run_root / "linear_mixed_effects_contract.json"
    if not artifact.is_file():
        raise StrictEvaluationError("runner did not write linear_mixed_effects_contract.json")
    try:
        stored = json.loads(artifact.read_text(encoding="utf-8"))
        stored_envelope = PacketEnvelope.from_dict(stored)
    except (ContractError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise StrictEvaluationError(
            "runner artifact must contain the exact C1 packet returned by the runner"
        ) from error
    if stored_envelope.to_dict() != envelope.to_dict():
        raise StrictEvaluationError(
            "runner artifact must contain the exact C1 packet returned by the runner"
        )
    return {
        "duration_seconds": duration,
        "artifact_path": str(artifact),
        "artifact_sha256": _sha256(artifact),
    }


def _dependency_lock_hash(candidate_root: Path) -> str:
    paths = (candidate_root / "pyproject.toml", candidate_root / "frontend" / "package-lock.json")
    digest = hashlib.sha256()
    for path in paths:
        if not path.is_file():
            raise StrictEvaluationError(f"candidate dependency lock input is missing: {path}")
        digest.update(path.relative_to(candidate_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _collect_performance(candidate_root: Path, artifact_dir: Path) -> dict[str, object]:
    """Measure only after the full strict suite has passed, retaining all outputs."""

    fixture = candidate_root / FIXTURE_RELATIVE_PATH
    if not fixture.is_file():
        raise StrictEvaluationError(f"candidate is missing canonical fixture: {fixture}")
    try:
        import statsmodels
    except ModuleNotFoundError as error:
        raise StrictEvaluationError("existing local statsmodels dependency is unavailable") from error

    fit = _load_fit(candidate_root)
    rows, subjects = _fixture_shape(fixture)
    performance_dir = artifact_dir / "performance"
    performance_dir.mkdir(parents=True, exist_ok=False)
    warmups = [
        _fit_once(fit, fixture, performance_dir / "warmups" / str(index))
        for index in range(2)
    ]
    cold = [
        _fit_once(fit, fixture, performance_dir / "cold" / str(index))
        for index in range(7)
    ]
    hot = [
        _fit_once(fit, fixture, performance_dir / "hot" / str(index))
        for index in range(7)
    ]
    cold_durations = [float(item["duration_seconds"]) for item in cold]
    hot_durations = [float(item["duration_seconds"]) for item in hot]
    artifact_count = sum(1 for path in performance_dir.rglob("*") if path.is_file())
    payload: dict[str, object] = {
        "status": "passed",
        "environment": {
            "python_version": sys.version.split()[0],
            "statsmodels_version": statsmodels.__version__,
            "node_version": "not_run",
            "os_family": platform.system(),
            "dependency_lock_hash": _dependency_lock_hash(candidate_root),
        },
        "fixture": {
            "path": str(FIXTURE_RELATIVE_PATH),
            "sha256": _sha256(fixture),
            "rows": rows,
            "subjects": subjects,
        },
        "warmups": warmups,
        "cold_fits": cold,
        "hot_fits": hot,
        "summary": {
            "cold_p50_seconds": statistics.median(cold_durations),
            "cold_p95_seconds": _percentile_95(cold_durations),
            "hot_p50_seconds": statistics.median(hot_durations),
            "hot_p95_seconds": _percentile_95(hot_durations),
            "failure_count": 0,
            "artifact_count": artifact_count,
            "full_forest_refetch": False,
            "full_forest_refetch_basis": "direct local runner invocation; no graph-store path",
            "provider_call_observation": "not_proven",
            "provider_call_observation_basis": (
                "provider-bearing environment was cleared and scoped Python guards "
                "were installed before candidate imports; this is not OS-level egress proof"
            ),
        },
    }
    _write_json(performance_dir / "performance.json", payload)
    return payload


def _failed_result_states() -> dict[str, str]:
    return {name: "failed" for name in RESULT_NAMES}


def _summarize_strict_junit(junit_path: Path) -> tuple[dict[str, str], dict[str, int]]:
    """Derive each required result from durable, complete JUnit evidence."""

    if not junit_path.is_file():
        raise StrictEvaluationError("strict suite JUnit artifact is missing")
    try:
        root = element_tree.parse(junit_path).getroot()
    except element_tree.ParseError as error:
        raise StrictEvaluationError("strict suite JUnit artifact is not parseable") from error

    module_to_result = {
        filename.removesuffix(".py"): result_name
        for result_name, filename in STRICT_TEST_FILES.items()
    }
    states = {name: "passed" for name in RESULT_NAMES}
    counts = {name: 0 for name in RESULT_NAMES}
    testcases = list(root.iter("testcase"))
    if not testcases:
        raise StrictEvaluationError("strict suite JUnit artifact has zero testcases")
    for testcase in testcases:
        classname = testcase.get("classname", "")
        module_name = classname.rsplit(".", 1)[-1]
        result_name = module_to_result.get(module_name)
        identifier = f"{classname}::{testcase.get('name', '')}"
        if result_name is None:
            raise StrictEvaluationError(
                "strict suite JUnit includes a non-candidate test: " + identifier
            )
        counts[result_name] += 1
        if testcase.find("skipped") is not None:
            raise StrictEvaluationError(
                "strict suite JUnit reports a skip: " + identifier
            )
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            states[result_name] = "failed"
    missing = [name for name, count in counts.items() if count == 0]
    if missing:
        raise StrictEvaluationError(
            "strict suite JUnit has zero test results for: " + ", ".join(missing)
        )
    return states, counts


def _junit_summary_payload(
    results: Mapping[str, str], counts: Mapping[str, int]
) -> dict[str, object]:
    """Persist structural JUnit facts without retaining raw candidate-facing XML."""

    return {
        "schema_version": STRICT_JUNIT_SUMMARY_SCHEMA_VERSION,
        "results": {name: results[name] for name in RESULT_NAMES},
        "test_counts": {name: counts[name] for name in RESULT_NAMES},
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--evaluator-root", type=Path, required=True)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    candidate_root = args.candidate_root.resolve()
    evaluator_root = args.evaluator_root.resolve()
    artifact_dir = args.artifact_dir.resolve()
    suite_root = evaluator_root / "tests" / "evaluation" / "linear_mixed_effects"
    started = time.perf_counter()
    artifact_dir.mkdir(parents=True, exist_ok=False)
    raw_junit_descriptor, raw_junit_name = tempfile.mkstemp(
        prefix="v173-lmm-strict-", suffix=".junit.xml"
    )
    os.close(raw_junit_descriptor)
    raw_junit_path = Path(raw_junit_name)
    raw_junit_path.unlink()
    junit_summary_path = artifact_dir / "strict-suite.junit.summary.json"
    output_metadata_path = artifact_dir / "strict-suite.output.json"
    suite_command = [
        sys.executable,
        "-m",
        "pytest",
        *[str(suite_root / filename) for filename in STRICT_TEST_FILES.values()],
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "pythonpath=",
        "--junitxml",
        str(raw_junit_path),
    ]
    captured_stdout = _DigestingTextCapture()
    captured_stderr = _DigestingTextCapture()
    suite_exit_code = 1
    suite_duration_seconds = 0.0
    suite_error: str | None = None
    results = _failed_result_states()
    junit_test_counts = {name: 0 for name in RESULT_NAMES}
    performance: dict[str, object] = {"status": "not_run"}
    try:
        _validate_full_sha(args.candidate_sha)
        _clean_environment(artifact_dir, candidate_root, evaluator_root)
        _install_in_process_guards()
        _prepare_import_path(candidate_root, evaluator_root)
        import pytest

        suite_started = time.perf_counter()
        with (
            contextlib.redirect_stdout(captured_stdout),
            contextlib.redirect_stderr(captured_stderr),
        ):
            suite_exit_code = pytest.main(suite_command[3:])
        suite_duration_seconds = time.perf_counter() - suite_started
        results, junit_test_counts = _summarize_strict_junit(raw_junit_path)
        _write_json(
            junit_summary_path,
            _junit_summary_payload(results, junit_test_counts),
        )
        if (
            suite_exit_code == 0
            and suite_error is None
            and all(state == "passed" for state in results.values())
        ):
            try:
                performance = _collect_performance(candidate_root, artifact_dir)
            except Exception as error:
                performance = {
                    "status": "failed",
                    "error_code": _safe_error_code(error),
                }
    except Exception as error:  # strict failures must become a durable artifact
        suite_error = _safe_error_code(error)
    finally:
        raw_junit_path.unlink(missing_ok=True)

    if not junit_summary_path.exists():
        _write_json(
            junit_summary_path,
            _junit_summary_payload(results, junit_test_counts),
        )
    _write_json(
        output_metadata_path,
        _stream_output_metadata(captured_stdout, captured_stderr),
    )
    suite_status = (
        "passed"
        if (
            suite_exit_code == 0
            and suite_error is None
            and all(state == "passed" for state in results.values())
        )
        else "failed"
    )
    status = "passed" if suite_status == "passed" and performance["status"] == "passed" else "failed"
    payload: dict[str, object] = {
        "schema_version": "v173_lmm_strict_candidate_evaluation_v4",
        "status": status,
        "candidate_root": str(candidate_root),
        "candidate_sha": args.candidate_sha,
        "suite_command": suite_command,
        "suite_exit_code": suite_exit_code,
        "suite_status": suite_status,
        "suite_error": suite_error,
        "suite_duration_seconds": suite_duration_seconds,
        "duration_seconds": time.perf_counter() - started,
        "results": results,
        "junit_test_counts": junit_test_counts,
        "performance": performance,
        "strict_isolation": {
            "network_guard": (
                "Python-level socket connect/connect_ex/create_connection guard "
                "installed before pytest collection"
            ),
            "process_spawn_guard": (
                "Python-level subprocess and common os process-spawn guards "
                "installed before pytest collection"
            ),
            "provider_environment": "cleared before candidate imports",
            "blocked_environment_names": list(BLOCKED_ENV_NAMES),
            "candidate_module_provenance": "required candidate modules assert __file__ under candidate root",
            "limitations": (
                "scoped process-level Python guards with cleared environment; no "
                "OS-level sandbox or proof of all-network or no-provider behavior"
            ),
        },
        "artifacts": {
            "output_metadata": _artifact_descriptor(output_metadata_path),
            "junit_summary": _artifact_descriptor(junit_summary_path),
            "performance": _artifact_descriptor(
                artifact_dir / "performance" / "performance.json"
            ),
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    _write_json(artifact_dir / "strict-suite.json", payload)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
