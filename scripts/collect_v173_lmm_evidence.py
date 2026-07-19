#!/usr/bin/env python3
"""Collect strict, non-secret LMM evidence for one supplied candidate commit.

This parent process never imports candidate code.  It verifies a clean,
full-SHA candidate before launching the unique strict evaluation subprocess,
then repeats the same Git and fixture audits afterwards.  A passed manifest
therefore means the full strict suite and persistent local performance run
completed against that exact unchanged candidate; it is not browser acceptance.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path


CONTRACT_LOCK_COMMIT = "0251f0a30d984bdbb2cfab404e6c646deab60cae"
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
FIXTURE_ROOT_RELATIVE_PATH = Path("tests/fixtures/models/linear_mixed_effects")
STRICT_RUNNER_RELATIVE_PATH = Path(
    "tests/evaluation/linear_mixed_effects/strict_runner.py"
)

# These are immutable C1 contracts or central paths whose change would make an
# independent feature-candidate result meaningless.  The strict feature
# allowlist below additionally rejects every unlisted change.
PROTECTED_PATHS = (
    "backend/workbench/agent/orchestrator.py",
    "backend/workbench/agent/operations.py",
    "backend/workbench/analysis_loop/contracts.py",
    "backend/workbench/analysis_loop/storage.py",
    "backend/workbench/analysis_loop/adapters.py",
    "backend/workbench/analysis_loop/compare.py",
    "backend/workbench/analysis_loop/validation.py",
    "backend/workbench/contracts",
    "backend/workbench/diagnostic_preview/contract_validation.py",
    "backend/workbench/engine/capabilities.py",
    "backend/workbench/engine/pack.py",
    "backend/workbench/engine/registry.py",
    "backend/workbench/engine/stages/validation.py",
    "backend/workbench/graph_store.py",
    "backend/workbench/lineage/manual_patch_validation.py",
    "backend/workbench/lineage/node_write_validation.py",
    "backend/workbench/narrative",
    "backend/workbench/validation.py",
    "frontend/src/workbench/AgentSurfaceContext.tsx",
    "scripts/gate.sh",
    "tests/contracts/test_lmm_canonical_packets.py",
    "tests/contracts/test_lmm_contracts.py",
    "tests/contracts/test_lmm_error_contract.py",
    "tests/fixtures/models/linear_mixed_effects",
    "tests/test_honest_did_adversarial.py",
    "tests/test_honest_did_sd_adversarial.py",
)

# The evaluator accepts only standalone Feature Lane changes.  Integration
# changes to central adapters need their own approved candidate/evidence run,
# rather than silently broadening this evaluation boundary.
ALLOWED_CANDIDATE_PREFIXES = (
    "backend/workbench/agent/recipes/lmm_explanation.py",
    "backend/workbench/agent/recipes/repeated_measures.py",
    "backend/workbench/engine/packs/linear_mixed_effects/",
    "frontend/src/runForm/RepeatedMeasuresControls.test.tsx",
    "frontend/src/runForm/RepeatedMeasuresControls.tsx",
    "frontend/src/workbench/repeatedMeasures/",
    "tests/agent/test_repeated_measures_recovery.py",
    "tests/agent/test_repeated_measures_recipe.py",
    "tests/models/linear_mixed_effects/",
)


class EvidenceCollectionError(RuntimeError):
    """Raised for rejected input or a non-passing strict candidate evaluation."""


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


def _validate_full_sha(candidate: str) -> None:
    if not FULL_SHA_PATTERN.fullmatch(candidate):
        raise EvidenceCollectionError(
            "candidate SHA must be a 40-character full SHA in lowercase hexadecimal"
        )


def _command_output_path(artifact_root: Path | None, ordinal: int) -> Path | None:
    if artifact_root is None:
        return None
    return artifact_root / "commands" / f"{ordinal:03d}.txt"


def _run_git(
    root: Path,
    arguments: list[str],
    command_records: list[dict[str, object]],
    *,
    artifact_root: Path | None = None,
    require_success: bool = True,
) -> subprocess.CompletedProcess[str]:
    command = ["git", "-C", str(root), *arguments]
    started = time.perf_counter()
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    duration = time.perf_counter() - started
    output = completed.stdout + completed.stderr
    output_path = _command_output_path(artifact_root, len(command_records) + 1)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    record: dict[str, object] = {
        "command": _command_text(command),
        "exit_code": completed.returncode,
        "duration_seconds": duration,
        "output_sha256": _sha256_bytes(output.encode("utf-8")),
    }
    if output_path is not None:
        record["output_artifact"] = str(output_path)
    command_records.append(record)
    if require_success and completed.returncode != 0:
        raise EvidenceCollectionError(
            f"Git audit failed: {_command_text(command)} (exit {completed.returncode})"
        )
    return completed


def _git_output(
    root: Path,
    arguments: list[str],
    command_records: list[dict[str, object]],
    *,
    artifact_root: Path | None = None,
) -> str:
    return _run_git(
        root,
        arguments,
        command_records,
        artifact_root=artifact_root,
    ).stdout.strip()


def _changed_paths(
    root: Path,
    candidate: str,
    command_records: list[dict[str, object]],
    *,
    artifact_root: Path | None = None,
) -> list[str]:
    output = _git_output(
        root,
        ["diff", "--name-only", f"{CONTRACT_LOCK_COMMIT}..{candidate}"],
        command_records,
        artifact_root=artifact_root,
    )
    return [path for path in output.splitlines() if path]


def _is_allowed_candidate_path(path: str) -> bool:
    return any(
        path == allowed or path.startswith(allowed)
        for allowed in ALLOWED_CANDIDATE_PREFIXES
    )


def _assert_candidate_diff_is_allowed(changed_paths: list[str]) -> None:
    disallowed = [path for path in changed_paths if not _is_allowed_candidate_path(path)]
    if disallowed:
        raise EvidenceCollectionError(
            "candidate changes outside the strict Feature path allowlist: "
            + ", ".join(disallowed)
        )


def _resolve_candidate(
    root: Path,
    candidate: str,
    command_records: list[dict[str, object]],
    *,
    artifact_root: Path | None = None,
) -> str:
    """Verify that ``candidate`` is exactly the clean, allowed checkout HEAD."""

    _validate_full_sha(candidate)
    if not root.is_dir():
        raise EvidenceCollectionError(f"candidate worktree does not exist: {root}")
    if not (root / ".git").exists():
        raise EvidenceCollectionError(f"candidate worktree is not a Git checkout: {root}")

    resolved_command = _run_git(
        root,
        ["rev-parse", "--verify", f"{candidate}^{{commit}}"],
        command_records,
        artifact_root=artifact_root,
        require_success=False,
    )
    if resolved_command.returncode != 0:
        raise EvidenceCollectionError(
            f"candidate SHA does not resolve to a commit in supplied worktree: {candidate}"
        )
    resolved = resolved_command.stdout.strip()
    if resolved != candidate:
        raise EvidenceCollectionError(
            "candidate SHA did not resolve exactly to the supplied full SHA: "
            f"supplied {candidate}, resolved {resolved}"
        )
    head = _git_output(
        root,
        ["rev-parse", "HEAD"],
        command_records,
        artifact_root=artifact_root,
    )
    if resolved != head:
        raise EvidenceCollectionError(
            "candidate SHA must be exactly the clean candidate worktree HEAD; "
            f"requested {resolved}, found {head}"
        )
    if resolved == CONTRACT_LOCK_COMMIT:
        raise EvidenceCollectionError(
            "candidate must be after contract lock; evaluating C1 itself is forbidden"
        )

    status = _git_output(
        root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        command_records,
        artifact_root=artifact_root,
    )
    if status:
        raise EvidenceCollectionError(
            "candidate worktree is dirty; independent evaluation refuses uncommitted input"
        )

    ancestor = _run_git(
        root,
        ["merge-base", "--is-ancestor", CONTRACT_LOCK_COMMIT, resolved],
        command_records,
        artifact_root=artifact_root,
        require_success=False,
    )
    if ancestor.returncode != 0:
        raise EvidenceCollectionError(
            f"candidate {resolved} does not descend from contract lock {CONTRACT_LOCK_COMMIT}"
        )

    protected = _git_output(
        root,
        [
            "diff",
            "--name-only",
            f"{CONTRACT_LOCK_COMMIT}..{resolved}",
            "--",
            *PROTECTED_PATHS,
        ],
        command_records,
        artifact_root=artifact_root,
    )
    if protected:
        raise EvidenceCollectionError(
            "candidate changes protected paths: " + ", ".join(protected.splitlines())
        )
    _assert_candidate_diff_is_allowed(
        _changed_paths(
            root,
            resolved,
            command_records,
            artifact_root=artifact_root,
        )
    )
    return resolved


def _snapshot_fixtures(root: Path) -> dict[str, str]:
    fixture_root = root / FIXTURE_ROOT_RELATIVE_PATH
    if not fixture_root.is_dir():
        raise EvidenceCollectionError(f"candidate is missing canonical fixture root: {fixture_root}")
    snapshot = {
        path.relative_to(root).as_posix(): _sha256_file(path)
        for path in sorted(fixture_root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }
    if not snapshot:
        raise EvidenceCollectionError(f"candidate fixture root is empty: {fixture_root}")
    known_truth = (FIXTURE_ROOT_RELATIVE_PATH / "known_truth.csv").as_posix()
    if known_truth not in snapshot:
        raise EvidenceCollectionError("candidate is missing canonical fixture: " + known_truth)
    return snapshot


def _preflight_candidate(
    root: Path,
    candidate: str,
    command_records: list[dict[str, object]],
    *,
    artifact_root: Path | None = None,
) -> dict[str, object]:
    resolved = _resolve_candidate(
        root,
        candidate,
        command_records,
        artifact_root=artifact_root,
    )
    return {
        "candidate_commit": resolved,
        "fixture_hashes": _snapshot_fixtures(root),
    }


def _post_execution_audit(
    root: Path,
    candidate: str,
    preflight: dict[str, object],
    command_records: list[dict[str, object]],
    *,
    artifact_root: Path | None = None,
) -> dict[str, object]:
    """Repeat the preflight after candidate code has run in a child process."""

    fixture_hashes = _snapshot_fixtures(root)
    candidate_error: EvidenceCollectionError | None = None
    try:
        resolved = _resolve_candidate(
            root,
            candidate,
            command_records,
            artifact_root=artifact_root,
        )
    except EvidenceCollectionError as error:
        candidate_error = error
        resolved = ""
    if fixture_hashes != preflight["fixture_hashes"]:
        raise EvidenceCollectionError("fixture content changed during strict evaluation")
    if candidate_error is not None:
        raise candidate_error
    if resolved != preflight["candidate_commit"]:
        raise EvidenceCollectionError("candidate HEAD changed during strict evaluation")
    return {"candidate_commit": resolved, "fixture_hashes": fixture_hashes}


def _strict_child_environment() -> dict[str, str]:
    """Do not even inherit provider configuration into the strict subprocess."""

    return {"PYTHONUNBUFFERED": "1"}


def _run_strict_candidate_evaluation(
    *,
    root: Path,
    candidate_sha: str,
    evaluator_root: Path,
    artifact_root: Path,
    command_records: list[dict[str, object]],
) -> dict[str, object]:
    strict_runner = evaluator_root / STRICT_RUNNER_RELATIVE_PATH
    if not strict_runner.is_file():
        raise EvidenceCollectionError(f"strict evaluation entrypoint is missing: {strict_runner}")
    strict_artifact_dir = artifact_root / "strict-suite"
    command = [
        sys.executable,
        str(strict_runner),
        "--candidate-root",
        str(root),
        "--candidate-sha",
        candidate_sha,
        "--evaluator-root",
        str(evaluator_root),
        "--artifact-dir",
        str(strict_artifact_dir),
    ]
    started = time.perf_counter()
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=artifact_root,
        env=_strict_child_environment(),
    )
    duration = time.perf_counter() - started
    stdout_path = artifact_root / "strict-runner.stdout.txt"
    stderr_path = artifact_root / "strict-runner.stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    combined_output = completed.stdout + completed.stderr
    command_records.append(
        {
            "command": _command_text(command),
            "exit_code": completed.returncode,
            "duration_seconds": duration,
            "output_sha256": _sha256_bytes(combined_output.encode("utf-8")),
            "output_artifact": str(stdout_path),
            "stderr_artifact": str(stderr_path),
        }
    )
    result_path = strict_artifact_dir / "strict-suite.json"
    if not result_path.is_file():
        raise EvidenceCollectionError(
            "strict candidate evaluation did not persist strict-suite.json"
        )
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise EvidenceCollectionError("strict-suite.json is not valid JSON") from error
    if completed.returncode != 0 or payload.get("status") != "passed":
        raise EvidenceCollectionError(
            "strict candidate evaluation failed; see persistent artifacts under "
            f"{strict_artifact_dir}"
        )
    if payload.get("suite_exit_code") != 0:
        raise EvidenceCollectionError("strict candidate evaluation reported a nonzero pytest exit")
    return payload


def _artifact_manifest(artifact_root: Path) -> list[dict[str, str]]:
    return [
        {"path": str(path), "sha256": _sha256_file(path)}
        for path in sorted(artifact_root.rglob("*"))
        if path.is_file()
    ]


def _write_json(path: Path, value: dict[str, object]) -> None:
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


def _evaluation_id(candidate_sha: str) -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"eval-v173-lmm-{candidate_sha[:12]}-{timestamp}"


def _collect(
    *,
    root: Path,
    candidate: str,
    output: Path,
    command_records: list[dict[str, object]],
) -> dict[str, object]:
    if output.exists():
        raise EvidenceCollectionError(f"refusing to overwrite existing evidence artifact: {output}")
    artifact_root = output.parent / f"{output.stem}.artifacts"
    if artifact_root.exists():
        raise EvidenceCollectionError(
            f"refusing to overwrite existing strict evaluation artifacts: {artifact_root}"
        )
    artifact_root.mkdir(parents=True, exist_ok=False)
    evaluator_root = Path(__file__).resolve().parents[1]
    preflight = _preflight_candidate(
        root,
        candidate,
        command_records,
        artifact_root=artifact_root,
    )
    strict = _run_strict_candidate_evaluation(
        root=root,
        candidate_sha=str(preflight["candidate_commit"]),
        evaluator_root=evaluator_root,
        artifact_root=artifact_root,
        command_records=command_records,
    )
    performance = strict.get("performance")
    if not isinstance(performance, dict) or performance.get("status") != "passed":
        raise EvidenceCollectionError("strict candidate evaluation did not complete performance")
    results = strict.get("results")
    if not isinstance(results, dict) or any(value != "passed" for value in results.values()):
        raise EvidenceCollectionError("strict candidate evaluation did not pass every required suite result")
    _post_execution_audit(
        root,
        candidate,
        preflight,
        command_records,
        artifact_root=artifact_root,
    )
    collector_commit = _git_output(
        evaluator_root,
        ["rev-parse", "HEAD"],
        command_records,
        artifact_root=artifact_root,
    )
    environment = performance.get("environment")
    if not isinstance(environment, dict):
        raise EvidenceCollectionError("strict performance evidence is missing environment metadata")
    fixture_hashes = preflight["fixture_hashes"]
    if not isinstance(fixture_hashes, dict):
        raise EvidenceCollectionError("internal preflight fixture snapshot is invalid")
    final_results = {str(name): str(value) for name, value in results.items()}
    final_results["performance_collection"] = "passed"
    final_results["browser_acceptance"] = "not_run"
    return {
        "schema_version": "v173_lmm_performance_evidence_v2",
        "status": "passed",
        "evaluation_id": _evaluation_id(str(preflight["candidate_commit"])),
        "evaluated_commit": preflight["candidate_commit"],
        "candidate_worktree": str(root),
        "contract_lock_commit": CONTRACT_LOCK_COMMIT,
        "evaluation_harness_commit": collector_commit,
        "supersedes": [],
        "environment": environment,
        "fixtures": [
            {"path": path, "sha256": digest}
            for path, digest in sorted(fixture_hashes.items())
        ],
        "results": final_results,
        "strict_isolation": strict.get("strict_isolation"),
        "acceptance": {
            "accepted": False,
            "reason": "browser acceptance has not been supplied; strict evidence alone cannot accept a candidate",
        },
        "performance": performance,
        "commands": command_records,
        "artifacts": _artifact_manifest(artifact_root),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--candidate",
        required=True,
        help="exact 40-character lowercase candidate commit SHA (must equal clean HEAD)",
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
        help="new JSON evidence path; existing evidence and artifact directories are never overwritten",
    )
    return parser


def build_failure_payload(
    *,
    requested_candidate: str,
    error: str,
    duration_seconds: float,
    command_records: list[dict[str, object]],
) -> dict[str, object]:
    """Keep a rejected candidate attributable without ever accepting it."""

    return {
        "schema_version": "v173_lmm_performance_evidence_v2",
        "status": "failed",
        "requested_candidate": requested_candidate,
        "error": error,
        "contract_lock_commit": CONTRACT_LOCK_COMMIT,
        "collector_duration_seconds": duration_seconds,
        "acceptance": {"accepted": False},
        "commands": command_records,
        "generated_at": datetime.now(UTC).isoformat(),
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    command_records: list[dict[str, object]] = []
    started = time.perf_counter()
    output = args.output.resolve()
    artifact_root = output.parent / f"{output.stem}.artifacts"
    try:
        payload = _collect(
            root=args.candidate_worktree.resolve(),
            candidate=args.candidate,
            output=output,
            command_records=command_records,
        )
        payload["collector_duration_seconds"] = time.perf_counter() - started
        _write_json(output, payload)
    except EvidenceCollectionError as error:
        failure = build_failure_payload(
            requested_candidate=args.candidate,
            error=str(error),
            duration_seconds=time.perf_counter() - started,
            command_records=command_records,
        )
        if artifact_root.is_dir():
            failure["artifact_root"] = str(artifact_root)
            failure["artifacts"] = _artifact_manifest(artifact_root)
        try:
            _write_json(output, failure)
        except EvidenceCollectionError:
            pass
        print(str(error), file=sys.stderr)
        return 1

    print(json.dumps({"status": "passed", "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
