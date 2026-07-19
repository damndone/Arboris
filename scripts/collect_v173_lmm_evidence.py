#!/usr/bin/env python3
"""Collect non-secret, repeatable LMM performance evidence for one candidate.

This script deliberately evaluates only the checked-out, supplied candidate.
It never creates a worktree, reads another Lane's uncommitted files, calls a
provider, or overwrites an existing evidence artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import importlib
import json
import os
import platform
import shlex
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any


CONTRACT_LOCK_COMMIT = "0251f0a30d984bdbb2cfab404e6c646deab60cae"
PROTECTED_PATHS = (
    "backend/workbench/agent/orchestrator.py",
    "backend/workbench/agent/operations.py",
    "backend/workbench/analysis_loop/contracts.py",
    "backend/workbench/analysis_loop/storage.py",
    "backend/workbench/engine/pack.py",
    "backend/workbench/engine/registry.py",
    "backend/workbench/engine/capabilities.py",
    "backend/workbench/graph_store.py",
    "frontend/src/workbench/AgentSurfaceContext.tsx",
    "scripts/gate.sh",
    "tests/test_honest_did_adversarial.py",
    "tests/test_honest_did_sd_adversarial.py",
)
FIXTURE_RELATIVE_PATH = Path("tests/fixtures/models/linear_mixed_effects/known_truth.csv")
RUNNER_MODULE = "workbench.engine.packs.linear_mixed_effects.runner"


class EvidenceCollectionError(RuntimeError):
    """Raised for an unacceptably supplied candidate or a failed local fit."""


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _command_text(command: list[str]) -> str:
    return shlex.join(command)


def _run_git(
    root: Path,
    arguments: list[str],
    command_records: list[dict[str, object]],
    *,
    require_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(root), *arguments]
    started = time.perf_counter()
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    duration = time.perf_counter() - started
    output = completed.stdout + completed.stderr
    command_records.append(
        {
            "command": _command_text(command),
            "exit_code": completed.returncode,
            "duration_seconds": duration,
            "output_sha256": _sha256_bytes(output.encode("utf-8")),
        }
    )
    if require_success and completed.returncode != 0:
        raise EvidenceCollectionError(
            f"Git preflight failed: {_command_text(command)} (exit {completed.returncode})"
        )
    return completed


def _git_output(
    root: Path, arguments: list[str], command_records: list[dict[str, object]]
) -> str:
    return _run_git(root, arguments, command_records).stdout.strip()


def _resolve_candidate(
    root: Path, candidate: str, command_records: list[dict[str, object]]
) -> str:
    if not root.is_dir():
        raise EvidenceCollectionError(f"candidate worktree does not exist: {root}")
    if not (root / ".git").exists():
        raise EvidenceCollectionError(f"candidate worktree is not a Git checkout: {root}")

    resolved = _git_output(root, ["rev-parse", "--verify", f"{candidate}^{{commit}}"], command_records)
    head = _git_output(root, ["rev-parse", "HEAD"], command_records)
    if resolved != head:
        raise EvidenceCollectionError(
            "candidate SHA must be exactly the clean candidate worktree HEAD; "
            f"requested {resolved}, found {head}"
        )

    status = _git_output(
        root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        command_records,
    )
    if status:
        raise EvidenceCollectionError(
            "candidate worktree is dirty; independent evaluation refuses uncommitted input"
        )

    ancestor = _run_git(
        root,
        ["merge-base", "--is-ancestor", CONTRACT_LOCK_COMMIT, resolved],
        command_records,
        require_success=False,
    )
    if ancestor.returncode != 0:
        raise EvidenceCollectionError(
            f"candidate {resolved} does not descend from contract lock {CONTRACT_LOCK_COMMIT}"
        )

    protected = _git_output(
        root,
        ["diff", "--name-only", f"{CONTRACT_LOCK_COMMIT}..{resolved}", "--", *PROTECTED_PATHS],
        command_records,
    )
    if protected:
        raise EvidenceCollectionError(
            "candidate changes protected paths: " + ", ".join(protected.splitlines())
        )
    return resolved


@contextmanager
def _block_network() -> Iterator[None]:
    """Make an accidental provider/network call a deterministic local failure."""

    original_connect = socket.socket.connect
    original_create_connection = socket.create_connection

    def blocked(*_args: object, **_kwargs: object) -> object:
        raise EvidenceCollectionError(
            "network access is forbidden during independent local evidence collection"
        )

    socket.socket.connect = blocked  # type: ignore[assignment]
    socket.create_connection = blocked  # type: ignore[assignment]
    try:
        yield
    finally:
        socket.socket.connect = original_connect  # type: ignore[assignment]
        socket.create_connection = original_create_connection  # type: ignore[assignment]


def _fixture_shape(path: Path) -> tuple[int, int]:
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return len(rows), len({row["participant_id"] for row in rows})


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise EvidenceCollectionError("cannot calculate a percentile with no measurements")
    if len(ordered) == 1:
        return ordered[0]
    position = 0.95 * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _load_fit(root: Path) -> tuple[Callable[..., object], str]:
    candidate_backend = str(root / "backend")
    if candidate_backend not in sys.path:
        sys.path.insert(0, candidate_backend)
    try:
        module = importlib.import_module(RUNNER_MODULE)
    except ModuleNotFoundError as error:
        missing = error.name or RUNNER_MODULE
        raise EvidenceCollectionError(
            f"supplied candidate does not provide required module: {missing}"
        ) from error
    try:
        fit = getattr(module, "fit_linear_mixed_effects")
    except AttributeError as error:
        raise EvidenceCollectionError(
            "supplied candidate runner has no fit_linear_mixed_effects helper"
        ) from error
    if not callable(fit):
        raise EvidenceCollectionError("fit_linear_mixed_effects is not callable")
    return fit, candidate_backend


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
        raise EvidenceCollectionError("runner must return exactly (result, fitted)")
    result, fitted = outcome
    if not isinstance(result, Mapping):
        raise EvidenceCollectionError("runner result must be a mapping")
    if result.get("model_type") != "linear_mixed_effects":
        raise EvidenceCollectionError("runner result does not identify linear_mixed_effects")
    if getattr(fitted, "converged", None) is not True:
        raise EvidenceCollectionError("measured LMM fit did not converge")

    artifact = run_root / "linear_mixed_effects_contract.json"
    if not artifact.is_file():
        raise EvidenceCollectionError("runner did not write linear_mixed_effects_contract.json")
    return {
        "duration_seconds": duration,
        "artifact_path": str(artifact),
        "artifact_sha256": _sha256_file(artifact),
    }


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    if path.exists():
        raise EvidenceCollectionError(f"refusing to overwrite existing evidence artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    os.replace(temporary, path)


def _collect(
    *, root: Path, candidate: str, output: Path, command_records: list[dict[str, object]]
) -> dict[str, object]:
    candidate_commit = _resolve_candidate(root, candidate, command_records)
    fixture = root / FIXTURE_RELATIVE_PATH
    if not fixture.is_file():
        raise EvidenceCollectionError(f"candidate is missing canonical fixture: {fixture}")
    rows, subjects = _fixture_shape(fixture)
    fit, _candidate_backend = _load_fit(root)

    try:
        import statsmodels
    except ModuleNotFoundError as error:
        raise EvidenceCollectionError("existing local statsmodels dependency is unavailable") from error

    with tempfile.TemporaryDirectory(prefix="v173-lmm-evidence-") as temporary_dir:
        working_root = Path(temporary_dir)
        with _block_network():
            warmups = [
                _fit_once(fit, fixture, working_root / "warmups" / str(index))
                for index in range(2)
            ]
            cold = [
                _fit_once(fit, fixture, working_root / "cold" / str(index))
                for index in range(7)
            ]
            hot_root = working_root / "hot"
            hot = [_fit_once(fit, fixture, hot_root) for _ in range(7)]
        artifact_count = sum(1 for path in working_root.rglob("*") if path.is_file())

    collector_root = Path(__file__).resolve().parents[1]
    collector_commit = _git_output(
        collector_root, ["rev-parse", "HEAD"], command_records
    )
    cold_durations = [float(item["duration_seconds"]) for item in cold]
    hot_durations = [float(item["duration_seconds"]) for item in hot]
    return {
        "schema_version": "v173_lmm_performance_evidence_v1",
        "status": "passed",
        "evaluated_commit": candidate_commit,
        "contract_lock_commit": CONTRACT_LOCK_COMMIT,
        "evaluation_harness_commit": collector_commit,
        "environment": {
            "python_version": sys.version.split()[0],
            "statsmodels_version": statsmodels.__version__,
            "os_family": platform.system(),
        },
        "fixture": {
            "path": str(FIXTURE_RELATIVE_PATH),
            "sha256": _sha256_file(fixture),
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
            "real_provider_calls_basis": "socket connections were blocked during every fit",
        },
        "commands": command_records,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        required=True,
        help="exact candidate commit SHA to evaluate (must equal candidate worktree HEAD)",
    )
    parser.add_argument(
        "--candidate-worktree",
        type=Path,
        default=Path.cwd(),
        help="clean checked-out candidate worktree; defaults to the current directory",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="new JSON evidence path; an existing artifact is never overwritten",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command_records: list[dict[str, object]] = []
    started = time.perf_counter()
    try:
        payload = _collect(
            root=args.candidate_worktree.resolve(),
            candidate=args.candidate,
            output=args.output,
            command_records=command_records,
        )
        payload["collector_duration_seconds"] = time.perf_counter() - started
        _write_json(args.output, payload)
    except EvidenceCollectionError as error:
        failure = {
            "schema_version": "v173_lmm_performance_evidence_v1",
            "status": "failed",
            "error": str(error),
            "contract_lock_commit": CONTRACT_LOCK_COMMIT,
            "collector_duration_seconds": time.perf_counter() - started,
            "commands": command_records,
        }
        try:
            _write_json(args.output, failure)
        except EvidenceCollectionError:
            pass
        print(str(error), file=sys.stderr)
        return 1

    print(json.dumps({"status": "passed", "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
