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
import io
import json
import os
import platform
import re
import socket
import statistics
import sys
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
_ALLOWED_META_SKIPS = (
    "test_candidate_import_boundary",
    "test_collector_guardrails",
    "test_strict_candidate_entrypoint",
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
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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


def _install_network_guard() -> None:
    """Block socket connections before pytest imports a candidate module."""

    def blocked(*_args: object, **_kwargs: object) -> object:
        raise StrictEvaluationError(
            "network access is forbidden before and during strict candidate evaluation"
        )

    socket.socket.connect = blocked  # type: ignore[assignment]
    socket.socket.connect_ex = blocked  # type: ignore[assignment]
    socket.create_connection = blocked  # type: ignore[assignment]


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
        raise StrictEvaluationError("runner result must be a mapping")
    if result.get("model_type") != "linear_mixed_effects":
        raise StrictEvaluationError("runner result does not identify linear_mixed_effects")
    if getattr(fitted, "converged", None) is not True:
        raise StrictEvaluationError("measured LMM fit did not converge")

    artifact = run_root / "linear_mixed_effects_contract.json"
    if not artifact.is_file():
        raise StrictEvaluationError("runner did not write linear_mixed_effects_contract.json")
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
            "real_provider_calls": False,
            "real_provider_calls_basis": "socket connections were blocked before every candidate import",
        },
    }
    _write_json(performance_dir / "performance.json", payload)
    return payload


def _unexpected_skips(junit_path: Path) -> list[str]:
    if not junit_path.is_file():
        return []
    root = element_tree.parse(junit_path).getroot()
    unexpected: list[str] = []
    for testcase in root.iter("testcase"):
        if testcase.find("skipped") is None:
            continue
        identifier = f"{testcase.get('classname', '')}::{testcase.get('name', '')}"
        if not any(allowed in identifier for allowed in _ALLOWED_META_SKIPS):
            unexpected.append(identifier)
    return unexpected


def _result_states(status: str) -> dict[str, str]:
    state = "passed" if status == "passed" else "failed"
    return {name: state for name in RESULT_NAMES}


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
    suite_command = [
        sys.executable,
        "-m",
        "pytest",
        str(suite_root),
        "-q",
        "-p",
        "no:cacheprovider",
        "-o",
        "pythonpath=",
        "--junitxml",
        str(artifact_dir / "strict-suite.junit.xml"),
    ]
    started = time.perf_counter()
    artifact_dir.mkdir(parents=True, exist_ok=False)
    stdout_path = artifact_dir / "strict-suite.stdout.txt"
    stderr_path = artifact_dir / "strict-suite.stderr.txt"
    suite_exit_code = 1
    suite_error: str | None = None
    unexpected_skips: list[str] = []
    performance: dict[str, object] = {"status": "not_run"}
    try:
        _validate_full_sha(args.candidate_sha)
        _clean_environment(artifact_dir, candidate_root, evaluator_root)
        _install_network_guard()
        _prepare_import_path(candidate_root, evaluator_root)
        import pytest

        captured_stdout = io.StringIO()
        captured_stderr = io.StringIO()
        with (
            contextlib.redirect_stdout(captured_stdout),
            contextlib.redirect_stderr(captured_stderr),
        ):
            suite_exit_code = pytest.main(suite_command[3:])
        stdout_path.write_text(captured_stdout.getvalue(), encoding="utf-8")
        stderr_path.write_text(captured_stderr.getvalue(), encoding="utf-8")
        unexpected_skips = _unexpected_skips(artifact_dir / "strict-suite.junit.xml")
        if unexpected_skips:
            suite_error = "strict suite reported unexpected skips: " + ", ".join(unexpected_skips)
        if suite_exit_code == 0 and suite_error is None:
            try:
                performance = _collect_performance(candidate_root, artifact_dir)
            except Exception as error:  # preserve a precise failure artifact
                performance = {
                    "status": "failed",
                    "error": f"{type(error).__name__}: {error}",
                }
    except Exception as error:  # strict failures must become a durable artifact
        suite_error = f"{type(error).__name__}: {error}"
        if not stdout_path.exists():
            stdout_path.write_text("", encoding="utf-8")
        if not stderr_path.exists():
            stderr_path.write_text(suite_error + "\n", encoding="utf-8")

    suite_status = "passed" if suite_exit_code == 0 and suite_error is None else "failed"
    status = "passed" if suite_status == "passed" and performance["status"] == "passed" else "failed"
    junit_path = artifact_dir / "strict-suite.junit.xml"
    payload: dict[str, object] = {
        "schema_version": "v173_lmm_strict_candidate_evaluation_v2",
        "status": status,
        "candidate_root": str(candidate_root),
        "candidate_sha": args.candidate_sha,
        "suite_command": suite_command,
        "suite_exit_code": suite_exit_code,
        "suite_status": suite_status,
        "suite_error": suite_error,
        "unexpected_skips": unexpected_skips,
        "duration_seconds": time.perf_counter() - started,
        "results": _result_states(suite_status),
        "performance": performance,
        "strict_isolation": {
            "network_guard": "socket connect/connect_ex/create_connection blocked before pytest collection",
            "provider_environment": "cleared before candidate imports",
            "blocked_environment_names": list(BLOCKED_ENV_NAMES),
            "candidate_module_provenance": "required candidate modules assert __file__ under candidate root",
        },
        "artifacts": {
            "stdout": {"path": str(stdout_path), "sha256": _sha256(stdout_path)},
            "stderr": {"path": str(stderr_path), "sha256": _sha256(stderr_path)},
            "junit": {"path": str(junit_path), "sha256": _sha256(junit_path)},
            "performance": {
                "path": str(artifact_dir / "performance" / "performance.json"),
                "sha256": _sha256(artifact_dir / "performance" / "performance.json"),
            },
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }
    _write_json(artifact_dir / "strict-suite.json", payload)
    return 0 if status == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
