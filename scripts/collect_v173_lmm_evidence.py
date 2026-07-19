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
import math
import os
import re
import shlex
import statistics
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as element_tree
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path


CONTRACT_LOCK_COMMIT = "0251f0a30d984bdbb2cfab404e6c646deab60cae"
FULL_SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
FIXTURE_ROOT_RELATIVE_PATH = Path("tests/fixtures/models/linear_mixed_effects")
STRICT_RUNNER_RELATIVE_PATH = Path(
    "tests/evaluation/linear_mixed_effects/strict_runner.py"
)
STRICT_SCHEMA_VERSION = "v173_lmm_strict_candidate_evaluation_v3"
WARMUP_FIT_COUNT = 2
COLD_FIT_COUNT = 7
HOT_FIT_COUNT = 7
STRICT_RESULT_NAMES = (
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
FIXTURE_RELATIVE_PATH = FIXTURE_ROOT_RELATIVE_PATH / "known_truth.csv"
STRICT_PAYLOAD_FIELDS = frozenset(
    {
        "schema_version",
        "status",
        "candidate_root",
        "candidate_sha",
        "suite_command",
        "suite_exit_code",
        "suite_status",
        "suite_error",
        "suite_duration_seconds",
        "duration_seconds",
        "results",
        "junit_test_counts",
        "performance",
        "strict_isolation",
        "artifacts",
        "generated_at",
    }
)
PERFORMANCE_FIELDS = frozenset(
    {"status", "environment", "fixture", "warmups", "cold_fits", "hot_fits", "summary"}
)
PERFORMANCE_ENVIRONMENT_FIELDS = frozenset(
    {
        "python_version",
        "statsmodels_version",
        "node_version",
        "os_family",
        "dependency_lock_hash",
    }
)
PERFORMANCE_FIXTURE_FIELDS = frozenset({"path", "sha256", "rows", "subjects"})
PERFORMANCE_FIT_FIELDS = frozenset(
    {"duration_seconds", "artifact_path", "artifact_sha256"}
)
PERFORMANCE_SUMMARY_FIELDS = frozenset(
    {
        "cold_p50_seconds",
        "cold_p95_seconds",
        "hot_p50_seconds",
        "hot_p95_seconds",
        "failure_count",
        "artifact_count",
        "full_forest_refetch",
        "full_forest_refetch_basis",
        "provider_call_observation",
        "provider_call_observation_basis",
    }
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


def _evaluator_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _evidence_artifact_root(output: Path) -> Path:
    return output.parent / f"{output.stem}.artifacts"


def _validate_output_locations(
    *, output: Path, candidate_root: Path, evaluator_root: Path
) -> tuple[Path, Path]:
    """Reject evaluator/candidate-owned destinations before creating any evidence."""

    resolved_output = output.resolve()
    artifact_root = _evidence_artifact_root(resolved_output).resolve()
    forbidden_roots = (
        ("candidate worktree", candidate_root.resolve()),
        ("evaluator worktree", evaluator_root.resolve()),
    )
    for label, forbidden_root in forbidden_roots:
        for path, path_label in (
            (resolved_output, "strict evidence output"),
            (artifact_root, "derived strict artifact root"),
        ):
            if path.is_relative_to(forbidden_root):
                raise EvidenceCollectionError(
                    f"{path_label} must be outside the {label}: {path}"
                )
    return resolved_output, artifact_root


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


def _preflight_evaluator(
    root: Path,
    command_records: list[dict[str, object]],
    *,
    artifact_root: Path | None = None,
) -> dict[str, str]:
    """Require the evaluator itself to stay clean and pinned during evidence work."""

    if not root.is_dir() or not (root / ".git").exists():
        raise EvidenceCollectionError(f"evaluator root is not a Git checkout: {root}")
    commit = _git_output(
        root,
        ["rev-parse", "HEAD"],
        command_records,
        artifact_root=artifact_root,
    )
    status = _git_output(
        root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
        command_records,
        artifact_root=artifact_root,
    )
    if status:
        raise EvidenceCollectionError(
            "evaluator worktree is dirty; strict evidence requires a clean evaluator"
        )
    return {"evaluator_commit": commit}


def _post_execution_evaluator_audit(
    root: Path,
    preflight: dict[str, str],
    command_records: list[dict[str, object]],
    *,
    artifact_root: Path | None = None,
) -> dict[str, str]:
    observed = _preflight_evaluator(
        root,
        command_records,
        artifact_root=artifact_root,
    )
    if observed != preflight:
        raise EvidenceCollectionError("evaluator HEAD changed during strict evaluation")
    return observed


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


def _require_exact_mapping_keys(
    value: object, expected: frozenset[str], name: str
) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or set(value) != expected:
        raise EvidenceCollectionError(f"strict payload {name} has an invalid schema")
    return value


def _require_nonnegative_number(value: object, name: str) -> float:
    if type(value) not in {int, float}:
        raise EvidenceCollectionError(
            f"strict payload {name} must be a finite nonnegative number"
        )
    normalized = float(value)
    if not math.isfinite(normalized) or normalized < 0:
        raise EvidenceCollectionError(
            f"strict payload {name} must be a finite nonnegative number"
        )
    return normalized


def _validate_artifact_descriptor(
    value: object, *, name: str, expected_path: Path
) -> dict[str, str]:
    descriptor = _require_exact_mapping_keys(value, frozenset({"path", "sha256"}), name)
    path_value = descriptor["path"]
    digest = descriptor["sha256"]
    if type(path_value) is not str or Path(path_value).resolve() != expected_path.resolve():
        raise EvidenceCollectionError(f"strict payload artifact {name} has an unexpected path")
    if (
        type(digest) is not str
        or not re.fullmatch(r"[0-9a-f]{64}", digest)
        or not expected_path.is_file()
        or _sha256_file(expected_path) != digest
    ):
        raise EvidenceCollectionError(f"strict payload artifact {name} is incomplete or tampered")
    return {"path": path_value, "sha256": digest}


def _validate_strict_junit(
    junit_path: Path, expected_counts: Mapping[str, object]
) -> None:
    try:
        root = element_tree.parse(junit_path).getroot()
    except element_tree.ParseError as error:
        raise EvidenceCollectionError("strict JUnit artifact is not parseable") from error
    module_to_result = {
        filename.removesuffix(".py"): result_name
        for result_name, filename in STRICT_TEST_FILES.items()
    }
    observed_counts = {name: 0 for name in STRICT_RESULT_NAMES}
    testcases = list(root.iter("testcase"))
    if not testcases:
        raise EvidenceCollectionError("strict JUnit artifact has zero testcases")
    for testcase in testcases:
        classname = testcase.get("classname", "")
        result_name = module_to_result.get(classname.rsplit(".", 1)[-1])
        if result_name is None:
            raise EvidenceCollectionError("strict JUnit includes a non-candidate testcase")
        if testcase.find("skipped") is not None:
            raise EvidenceCollectionError("strict JUnit reports a skipped testcase")
        if testcase.find("failure") is not None or testcase.find("error") is not None:
            raise EvidenceCollectionError("strict JUnit reports a failed testcase")
        observed_counts[result_name] += 1
    if any(count == 0 for count in observed_counts.values()):
        raise EvidenceCollectionError("strict JUnit has zero expected test results")
    if {
        name: expected_counts[name] for name in STRICT_RESULT_NAMES
    } != observed_counts:
        raise EvidenceCollectionError("strict JUnit testcase counts do not match strict payload")


def _load_json_mapping(path: Path, name: str) -> dict[str, object]:
    def reject_non_finite(value: str) -> object:
        raise ValueError(f"non-finite JSON constant: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    try:
        parsed = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=reject_non_finite,
            object_pairs_hook=reject_duplicate_keys,
        )
    except (OSError, ValueError) as error:
        raise EvidenceCollectionError(
            f"strict {name} artifact is not strict JSON"
        ) from error
    if not isinstance(parsed, dict):
        raise EvidenceCollectionError(f"strict {name} artifact must be a JSON object")
    return parsed


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise EvidenceCollectionError("strict performance has no measurements")
    if len(ordered) == 1:
        return ordered[0]
    position = 0.95 * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _require_positive_int(value: object, name: str) -> int:
    if type(value) is not int or value <= 0:
        raise EvidenceCollectionError(f"strict payload {name} must be a positive integer")
    return value


def _validate_performance_fit_series(
    value: object,
    *,
    name: str,
    expected_count: int,
    strict_artifact_dir: Path,
    observed_paths: set[Path],
) -> list[float]:
    if not isinstance(value, list) or len(value) != expected_count:
        raise EvidenceCollectionError(
            f"strict payload performance {name} must contain exactly {expected_count} fits"
        )
    durations: list[float] = []
    for index, fit in enumerate(value):
        fit_wire = _require_exact_mapping_keys(
            fit, PERFORMANCE_FIT_FIELDS, f"performance.{name}[{index}]"
        )
        duration = _require_nonnegative_number(
            fit_wire["duration_seconds"], f"performance.{name}[{index}].duration_seconds"
        )
        artifact_path = fit_wire["artifact_path"]
        artifact_sha256 = fit_wire["artifact_sha256"]
        expected_path = (
            strict_artifact_dir
            / "performance"
            / name
            / str(index)
            / "linear_mixed_effects_contract.json"
        ).resolve()
        if type(artifact_path) is not str or Path(artifact_path).resolve() != expected_path:
            raise EvidenceCollectionError(
                f"strict payload performance {name}[{index}] has an unexpected artifact path"
            )
        if (
            type(artifact_sha256) is not str
            or not re.fullmatch(r"[0-9a-f]{64}", artifact_sha256)
            or not expected_path.is_file()
            or _sha256_file(expected_path) != artifact_sha256
        ):
            raise EvidenceCollectionError(
                f"strict payload performance {name}[{index}] artifact is incomplete or tampered"
            )
        if expected_path in observed_paths:
            raise EvidenceCollectionError("strict performance reuses a per-fit artifact path")
        observed_paths.add(expected_path)
        durations.append(duration)
    return durations


def _validate_performance_payload(
    performance: Mapping[str, object],
    *,
    strict_artifact_dir: Path,
    performance_artifact_path: Path,
    expected_fixture_sha256: str,
) -> dict[str, object]:
    wire = _require_exact_mapping_keys(performance, PERFORMANCE_FIELDS, "performance")
    if wire["status"] != "passed":
        raise EvidenceCollectionError("strict payload performance did not pass")

    environment = _require_exact_mapping_keys(
        wire["environment"], PERFORMANCE_ENVIRONMENT_FIELDS, "performance.environment"
    )
    if any(type(value) is not str or not value for value in environment.values()):
        raise EvidenceCollectionError("strict payload performance environment is incomplete")
    if not re.fullmatch(r"[0-9a-f]{64}", str(environment["dependency_lock_hash"])):
        raise EvidenceCollectionError("strict payload performance dependency lock hash is invalid")

    fixture = _require_exact_mapping_keys(
        wire["fixture"], PERFORMANCE_FIXTURE_FIELDS, "performance.fixture"
    )
    if (
        fixture["path"] != FIXTURE_RELATIVE_PATH.as_posix()
        or fixture["sha256"] != expected_fixture_sha256
    ):
        raise EvidenceCollectionError("strict payload fixture hash does not match the candidate fixture used")
    _require_positive_int(fixture["rows"], "performance.fixture.rows")
    _require_positive_int(fixture["subjects"], "performance.fixture.subjects")

    observed_paths: set[Path] = set()
    _validate_performance_fit_series(
        wire["warmups"],
        name="warmups",
        expected_count=WARMUP_FIT_COUNT,
        strict_artifact_dir=strict_artifact_dir,
        observed_paths=observed_paths,
    )
    cold = _validate_performance_fit_series(
        wire["cold_fits"],
        name="cold",
        expected_count=COLD_FIT_COUNT,
        strict_artifact_dir=strict_artifact_dir,
        observed_paths=observed_paths,
    )
    hot = _validate_performance_fit_series(
        wire["hot_fits"],
        name="hot",
        expected_count=HOT_FIT_COUNT,
        strict_artifact_dir=strict_artifact_dir,
        observed_paths=observed_paths,
    )
    summary = _require_exact_mapping_keys(
        wire["summary"], PERFORMANCE_SUMMARY_FIELDS, "performance.summary"
    )
    expected_summary = {
        "cold_p50_seconds": statistics.median(cold),
        "cold_p95_seconds": _percentile_95(cold),
        "hot_p50_seconds": statistics.median(hot),
        "hot_p95_seconds": _percentile_95(hot),
    }
    for name, expected in expected_summary.items():
        observed = _require_nonnegative_number(summary[name], f"performance.summary.{name}")
        if observed != expected:
            raise EvidenceCollectionError(
                f"strict payload performance summary {name} does not match measured fits"
            )
    if type(summary["failure_count"]) is not int or summary["failure_count"] != 0:
        raise EvidenceCollectionError("strict payload performance summary failure_count is invalid")
    actual_artifact_count = sum(
        1
        for path in performance_artifact_path.parent.rglob("*")
        if path.is_file() and path != performance_artifact_path
    )
    if type(summary["artifact_count"]) is not int or summary["artifact_count"] != actual_artifact_count:
        raise EvidenceCollectionError("strict payload performance summary artifact_count is invalid")
    if summary["full_forest_refetch"] is not False:
        raise EvidenceCollectionError("strict payload performance summary full_forest_refetch is invalid")
    if summary["full_forest_refetch_basis"] != "direct local runner invocation; no graph-store path":
        raise EvidenceCollectionError("strict payload performance summary refetch basis is invalid")
    if summary["provider_call_observation"] != "not_proven":
        raise EvidenceCollectionError("strict payload performance summary provider observation is invalid")
    if (
        summary["provider_call_observation_basis"]
        != "provider-bearing environment was cleared and scoped Python guards "
        "were installed before candidate imports; this is not OS-level egress proof"
    ):
        raise EvidenceCollectionError("strict payload performance summary provider basis is invalid")

    persisted = _load_json_mapping(performance_artifact_path, "performance")
    if persisted != dict(wire):
        raise EvidenceCollectionError(
            "strict performance artifact does not exactly match the strict payload"
        )
    return dict(wire)


def _validate_strict_payload(
    payload: object,
    *,
    root: Path,
    candidate_sha: str,
    evaluator_root: Path,
    strict_artifact_dir: Path,
    expected_fixture_sha256: str | None = None,
) -> dict[str, object]:
    """Reject a claimed strict pass unless every inner fact is self-consistent."""

    wire = _require_exact_mapping_keys(payload, STRICT_PAYLOAD_FIELDS, "root")
    if wire["schema_version"] != STRICT_SCHEMA_VERSION:
        raise EvidenceCollectionError("strict payload schema_version is unsupported")
    if wire["status"] != "passed" or wire["suite_status"] != "passed":
        raise EvidenceCollectionError("strict payload does not report a passed suite")
    if wire["candidate_root"] != str(root.resolve()):
        raise EvidenceCollectionError("strict payload candidate_root does not match candidate")
    if wire["candidate_sha"] != candidate_sha:
        raise EvidenceCollectionError("strict payload candidate_sha does not match candidate")
    if expected_fixture_sha256 is None:
        candidate_fixture = root / FIXTURE_RELATIVE_PATH
        if not candidate_fixture.is_file():
            raise EvidenceCollectionError("candidate is missing canonical fixture used by strict evaluation")
        expected_fixture_sha256 = _sha256_file(candidate_fixture)
    if wire["suite_exit_code"] != 0 or wire["suite_error"] is not None:
        raise EvidenceCollectionError("strict payload reports a non-passing pytest suite")
    _require_nonnegative_number(wire["suite_duration_seconds"], "suite_duration_seconds")
    _require_nonnegative_number(wire["duration_seconds"], "duration_seconds")
    if not isinstance(wire["suite_command"], list) or not all(
        type(item) is str for item in wire["suite_command"]
    ):
        raise EvidenceCollectionError("strict payload suite_command is invalid")
    expected_test_paths = [
        str(
            (evaluator_root / "tests" / "evaluation" / "linear_mixed_effects" / filename).resolve()
        )
        for filename in STRICT_TEST_FILES.values()
    ]
    observed_test_paths = [
        item for item in wire["suite_command"] if item.endswith(".py")
    ]
    if observed_test_paths != expected_test_paths:
        raise EvidenceCollectionError("strict payload suite_command does not select exactly the candidate tests")

    results = _require_exact_mapping_keys(
        wire["results"], frozenset(STRICT_RESULT_NAMES), "results"
    )
    if any(results[name] != "passed" for name in STRICT_RESULT_NAMES):
        raise EvidenceCollectionError("strict payload did not pass every required result")
    junit_counts = _require_exact_mapping_keys(
        wire["junit_test_counts"], frozenset(STRICT_RESULT_NAMES), "junit_test_counts"
    )
    if any(type(junit_counts[name]) is not int or junit_counts[name] <= 0 for name in STRICT_RESULT_NAMES):
        raise EvidenceCollectionError("strict payload has zero expected test results")

    artifacts = _require_exact_mapping_keys(
        wire["artifacts"], frozenset({"stdout", "stderr", "junit", "performance"}), "artifacts"
    )
    _validate_artifact_descriptor(
        artifacts["stdout"], name="stdout", expected_path=strict_artifact_dir / "strict-suite.stdout.txt"
    )
    _validate_artifact_descriptor(
        artifacts["stderr"], name="stderr", expected_path=strict_artifact_dir / "strict-suite.stderr.txt"
    )
    junit_descriptor = _validate_artifact_descriptor(
        artifacts["junit"], name="junit", expected_path=strict_artifact_dir / "strict-suite.junit.xml"
    )
    performance_descriptor = _validate_artifact_descriptor(
        artifacts["performance"], name="performance", expected_path=strict_artifact_dir / "performance" / "performance.json"
    )
    _validate_strict_junit(Path(junit_descriptor["path"]), junit_counts)
    _validate_performance_payload(
        _require_exact_mapping_keys(wire["performance"], PERFORMANCE_FIELDS, "performance"),
        strict_artifact_dir=strict_artifact_dir,
        performance_artifact_path=Path(performance_descriptor["path"]),
        expected_fixture_sha256=expected_fixture_sha256,
    )
    return dict(wire)


def _run_strict_candidate_evaluation(
    *,
    root: Path,
    candidate_sha: str,
    evaluator_root: Path,
    artifact_root: Path,
    command_records: list[dict[str, object]],
    expected_fixture_sha256: str | None = None,
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
            "stdout_sha256": _sha256_bytes(completed.stdout.encode("utf-8")),
            "stderr_sha256": _sha256_bytes(completed.stderr.encode("utf-8")),
            "output_artifact": str(stdout_path),
            "stderr_artifact": str(stderr_path),
        }
    )
    result_path = strict_artifact_dir / "strict-suite.json"
    if not result_path.is_file():
        raise EvidenceCollectionError(
            "strict candidate evaluation did not persist strict-suite.json"
        )
    payload = _load_json_mapping(result_path, "suite result")
    if completed.returncode != 0:
        raise EvidenceCollectionError(
            "strict candidate evaluation failed; see persistent artifacts under "
            f"{strict_artifact_dir}"
        )
    return _validate_strict_payload(
        payload,
        root=root,
        candidate_sha=candidate_sha,
        evaluator_root=evaluator_root,
        strict_artifact_dir=strict_artifact_dir,
        expected_fixture_sha256=expected_fixture_sha256,
    )


def _artifact_manifest(artifact_root: Path) -> list[dict[str, str]]:
    return [
        {"path": str(path), "sha256": _sha256_file(path)}
        for path in sorted(artifact_root.rglob("*"))
        if path.is_file()
    ]


def _inner_pytest_record(strict: Mapping[str, object]) -> dict[str, object]:
    """Copy the inner pytest facts into the outer manifest without inference."""

    artifacts = strict["artifacts"]
    assert isinstance(artifacts, Mapping)
    stdout = artifacts["stdout"]
    stderr = artifacts["stderr"]
    junit = artifacts["junit"]
    assert isinstance(stdout, Mapping)
    assert isinstance(stderr, Mapping)
    assert isinstance(junit, Mapping)
    return {
        "command": strict["suite_command"],
        "exit_code": strict["suite_exit_code"],
        "duration_seconds": strict["suite_duration_seconds"],
        "stdout_sha256": stdout["sha256"],
        "stderr_sha256": stderr["sha256"],
        "junit_sha256": junit["sha256"],
    }


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
    evaluator_root = _evaluator_root()
    output, artifact_root = _validate_output_locations(
        output=output,
        candidate_root=root,
        evaluator_root=evaluator_root,
    )
    if output.exists():
        raise EvidenceCollectionError(f"refusing to overwrite existing evidence artifact: {output}")
    if artifact_root.exists():
        raise EvidenceCollectionError(
            f"refusing to overwrite existing strict evaluation artifacts: {artifact_root}"
    )
    artifact_root.mkdir(parents=True, exist_ok=False)
    evaluator_preflight = _preflight_evaluator(
        evaluator_root,
        command_records,
        artifact_root=artifact_root,
    )
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
        expected_fixture_sha256=str(
            preflight["fixture_hashes"][FIXTURE_RELATIVE_PATH.as_posix()]
        ),
    )
    performance = strict.get("performance")
    if not isinstance(performance, dict) or performance.get("status") != "passed":
        raise EvidenceCollectionError("strict candidate evaluation did not complete performance")
    results = strict.get("results")
    if (
        not isinstance(results, dict)
        or set(results) != set(STRICT_RESULT_NAMES)
        or any(value != "passed" for value in results.values())
    ):
        raise EvidenceCollectionError("strict candidate evaluation did not pass every required suite result")
    _post_execution_audit(
        root,
        candidate,
        preflight,
        command_records,
        artifact_root=artifact_root,
    )
    _post_execution_evaluator_audit(
        evaluator_root,
        evaluator_preflight,
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
        "evaluation_harness_commit": evaluator_preflight["evaluator_commit"],
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
        "inner_pytest": _inner_pytest_record(strict),
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
    candidate_root = args.candidate_worktree.resolve()
    try:
        output, artifact_root = _validate_output_locations(
            output=args.output,
            candidate_root=candidate_root,
            evaluator_root=_evaluator_root(),
        )
    except EvidenceCollectionError as error:
        print(str(error), file=sys.stderr)
        return 1
    try:
        payload = _collect(
            root=candidate_root,
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
