from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from types import ModuleType

import pytest


if os.environ.get("WORKBENCH_EVALUATION_REQUIRE_CANDIDATE") == "1":
    pytest.skip(
        "strict entrypoint meta-tests run outside the candidate evaluation suite",
        allow_module_level=True,
    )


REPO_ROOT = Path(__file__).parents[3]
COLLECTOR_PATH = REPO_ROOT / "scripts" / "collect_v173_lmm_evidence.py"
STRICT_RESULTS = (
    "contract_validation",
    "known_truth",
    "fault_injection",
    "agent_boundaries",
    "compare_restrictions",
    "deterministic_overclaim_checks",
)


def _load_collector() -> ModuleType:
    spec = importlib.util.spec_from_file_location("v173_lmm_collector_guardrails", COLLECTOR_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _git(root: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _commit(root: Path, message: str) -> str:
    _git(root, "add", ".")
    _git(root, "commit", "-m", message)
    return _git(root, "rev-parse", "HEAD")


def _candidate_repo(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "candidate"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "evaluation@example.test")
    _git(root, "config", "user.name", "Evaluation Test")
    fixture = root / "tests" / "fixtures" / "models" / "linear_mixed_effects" / "known_truth.csv"
    fixture.parent.mkdir(parents=True)
    fixture.write_text("participant_id,score\nP1,1\n", encoding="utf-8")
    (root / "README.md").write_text("candidate\n", encoding="utf-8")
    return root, _commit(root, "C1 lock")


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    position = 0.95 * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def _write_candidate_fixture(root: Path) -> str:
    fixture = (
        root
        / "tests"
        / "fixtures"
        / "models"
        / "linear_mixed_effects"
        / "known_truth.csv"
    )
    fixture.parent.mkdir(parents=True, exist_ok=True)
    fixture.write_text("participant_id,score\nP1,1\n", encoding="utf-8")
    return hashlib.sha256(fixture.read_bytes()).hexdigest()


def _write_passing_strict_payload(
    artifact_dir: Path,
    *,
    candidate_root: Path,
    candidate_sha: str,
    fixture_sha256: str,
    junit_contents: str | None = None,
) -> None:
    artifact_dir.mkdir(parents=True)
    output_metadata = artifact_dir / "strict-suite.output.json"
    junit = artifact_dir / "strict-suite.junit.summary.json"
    performance = artifact_dir / "performance" / "performance.json"
    performance.parent.mkdir(parents=True)
    output_metadata_payload = {
        "schema_version": "v173_lmm_strict_output_metadata_v1",
        "capture_policy": "raw pytest stdout and stderr are discarded; hashes cover complete streams",
        "max_reported_bytes": 65536,
        "stdout_sha256": _sha256_text("pytest output\n"),
        "stderr_sha256": _sha256_text(""),
        "stdout_bytes_observed": len("pytest output\n".encode("utf-8")),
        "stderr_bytes_observed": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
    }
    output_metadata.write_text(json.dumps(output_metadata_payload), encoding="utf-8")
    junit_payload = {
        "schema_version": "v173_lmm_strict_junit_summary_v1",
        "results": {name: "passed" for name in STRICT_RESULTS},
        "test_counts": {name: 1 for name in STRICT_RESULTS},
    }
    junit.write_text(
        junit_contents
        if junit_contents is not None
        else json.dumps(junit_payload),
        encoding="utf-8",
    )

    def write_fit(group: str, index: int, duration: float) -> dict[str, object]:
        artifact = (
            performance.parent
            / group
            / str(index)
            / "linear_mixed_effects_contract.json"
        )
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}\n", encoding="utf-8")
        return {
            "duration_seconds": duration,
            "artifact_path": str(artifact),
            "artifact_sha256": hashlib.sha256(artifact.read_bytes()).hexdigest(),
        }

    warmups = [write_fit("warmups", index, 0.01 + index / 100) for index in range(2)]
    cold_fits = [write_fit("cold", index, 1.0 + index) for index in range(7)]
    hot_fits = [write_fit("hot", index, 0.1 + index / 10) for index in range(7)]
    cold_durations = [float(item["duration_seconds"]) for item in cold_fits]
    hot_durations = [float(item["duration_seconds"]) for item in hot_fits]
    performance_payload = {
        "status": "passed",
        "environment": {
            "python_version": "3.test",
            "statsmodels_version": "test",
            "node_version": "not_run",
            "os_family": "TestOS",
            "dependency_lock_hash": "d" * 64,
        },
        "fixture": {
            "path": "tests/fixtures/models/linear_mixed_effects/known_truth.csv",
            "sha256": fixture_sha256,
            "rows": 1,
            "subjects": 1,
        },
        "warmups": warmups,
        "cold_fits": cold_fits,
        "hot_fits": hot_fits,
        "summary": {
            "cold_p50_seconds": statistics.median(cold_durations),
            "cold_p95_seconds": _percentile_95(cold_durations),
            "hot_p50_seconds": statistics.median(hot_durations),
            "hot_p95_seconds": _percentile_95(hot_durations),
            "failure_count": 0,
            "artifact_count": len(warmups) + len(cold_fits) + len(hot_fits),
            "full_forest_refetch": False,
            "full_forest_refetch_basis": "direct local runner invocation; no graph-store path",
            "provider_call_observation": "not_proven",
            "provider_call_observation_basis": (
                "provider-bearing environment was cleared and scoped Python guards "
                "were installed before candidate imports; this is not OS-level egress proof"
            ),
        },
    }
    performance.write_text(json.dumps(performance_payload), encoding="utf-8")
    artifacts = {
        "output_metadata": {
            "path": str(output_metadata),
            "sha256": hashlib.sha256(output_metadata.read_bytes()).hexdigest(),
        },
        "junit_summary": {
            "path": str(junit),
            "sha256": hashlib.sha256(junit.read_bytes()).hexdigest(),
        },
        "performance": {
            "path": str(performance),
            "sha256": hashlib.sha256(performance.read_bytes()).hexdigest(),
        },
    }
    payload = {
        "schema_version": "v173_lmm_strict_candidate_evaluation_v4",
        "status": "passed",
        "candidate_root": str(candidate_root.resolve()),
        "candidate_sha": candidate_sha,
        "suite_command": [
            sys.executable,
            "-m",
            "pytest",
            *[
                str(
                    REPO_ROOT
                    / "tests"
                    / "evaluation"
                    / "linear_mixed_effects"
                    / filename
                )
                for filename in (
                    "test_contract_compatibility.py",
                    "test_known_truth.py",
                    "test_fault_injection.py",
                    "test_agent_boundaries.py",
                    "test_compare_restrictions.py",
                    "test_report_claims.py",
                )
            ],
            "-q",
        ],
        "suite_exit_code": 0,
        "suite_status": "passed",
        "suite_error": None,
        "suite_duration_seconds": 0.25,
        "duration_seconds": 0.5,
        "results": {name: "passed" for name in STRICT_RESULTS},
        "junit_test_counts": {name: 1 for name in STRICT_RESULTS},
        "performance": performance_payload,
        "strict_isolation": {"limitations": "scoped guard"},
        "artifacts": artifacts,
        "generated_at": "2026-07-19T00:00:00+00:00",
    }
    (artifact_dir / "strict-suite.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def _rewrite_performance_evidence(
    artifact_dir: Path,
    mutate: object,
) -> None:
    payload_path = artifact_dir / "strict-suite.json"
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    performance = payload["performance"]
    assert isinstance(performance, dict)
    assert callable(mutate)
    mutate(performance)
    performance_path = artifact_dir / "performance" / "performance.json"
    performance_path.write_text(json.dumps(performance), encoding="utf-8")
    artifacts = payload["artifacts"]
    assert isinstance(artifacts, dict)
    performance_descriptor = artifacts["performance"]
    assert isinstance(performance_descriptor, dict)
    performance_descriptor["sha256"] = hashlib.sha256(
        performance_path.read_bytes()
    ).hexdigest()
    payload_path.write_text(json.dumps(payload), encoding="utf-8")


def test_candidate_preflight_rejects_non_full_sha_before_touching_a_worktree(
    tmp_path: Path,
) -> None:
    collector = _load_collector()

    with pytest.raises(collector.EvidenceCollectionError, match="40-character full SHA"):
        collector._resolve_candidate(tmp_path / "missing", "deadbeef", [])


def test_evidence_collector_requires_an_explicit_candidate_sha(tmp_path: Path) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(COLLECTOR_PATH),
            "--output",
            str(tmp_path / "performance.json"),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode != 0
    assert "--candidate" in completed.stderr


@pytest.mark.parametrize("forbidden_root", ("candidate", "evaluator"))
def test_main_rejects_forbidden_output_before_any_failure_manifest_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, forbidden_root: str
) -> None:
    collector = _load_collector()
    candidate_root = tmp_path / "candidate"
    evaluator_root = tmp_path / "evaluator"
    candidate_root.mkdir()
    evaluator_root.mkdir()
    monkeypatch.setattr(collector, "_evaluator_root", lambda: evaluator_root)
    output_root = candidate_root if forbidden_root == "candidate" else evaluator_root
    output = output_root / "evidence.json"
    artifact_root = output.parent / "evidence.artifacts"

    exit_code = collector.main(
        [
            "--candidate",
            "a" * 40,
            "--candidate-worktree",
            str(candidate_root),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    assert not output.exists()
    assert not artifact_root.exists()


def test_main_rejects_a_derived_artifact_root_inside_the_candidate_before_writes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    collector = _load_collector()
    candidate_root = tmp_path / "candidate"
    evaluator_root = tmp_path / "evaluator"
    output = tmp_path / "outside" / "evidence.json"
    candidate_root.mkdir()
    evaluator_root.mkdir()
    monkeypatch.setattr(collector, "_evaluator_root", lambda: evaluator_root)
    monkeypatch.setattr(
        collector,
        "_evidence_artifact_root",
        lambda _output: candidate_root / "evidence.artifacts",
    )

    exit_code = collector.main(
        [
            "--candidate",
            "a" * 40,
            "--candidate-worktree",
            str(candidate_root),
            "--output",
            str(output),
        ]
    )

    assert exit_code == 1
    assert not output.exists()
    assert not (candidate_root / "evidence.artifacts").exists()


def test_main_reserves_output_before_collecting_and_releases_it_after_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    collector = _load_collector()
    candidate_root = tmp_path / "candidate"
    evaluator_root = tmp_path / "evaluator"
    output = tmp_path / "outside" / "evidence.json"
    candidate_root.mkdir()
    evaluator_root.mkdir()
    monkeypatch.setattr(collector, "_evaluator_root", lambda: evaluator_root)
    observed_reservations: list[bool] = []

    def fail_collect(**_kwargs: object) -> dict[str, object]:
        observed_reservations.append(collector._output_reservation_path(output).is_file())
        raise collector.EvidenceCollectionError("simulated collection failure")

    monkeypatch.setattr(collector, "_collect", fail_collect)

    assert collector.main(
        [
            "--candidate",
            "a" * 40,
            "--candidate-worktree",
            str(candidate_root),
            "--output",
            str(output),
        ]
    ) == 1
    assert observed_reservations == [True]
    assert not collector._output_reservation_path(output).exists()
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "failed"


def test_output_reservation_and_manifest_writer_do_not_clobber_existing_evidence(
    tmp_path: Path,
) -> None:
    collector = _load_collector()
    output = tmp_path / "evidence.json"
    reservation = collector._reserve_output(output)
    try:
        with pytest.raises(collector.EvidenceCollectionError, match="already reserved"):
            collector._reserve_output(output)
    finally:
        reservation.release()

    output.write_text("existing evidence\n", encoding="utf-8")
    with pytest.raises(collector.EvidenceCollectionError, match="overwrite"):
        collector._write_json(output, {"status": "passed"})
    assert output.read_text(encoding="utf-8") == "existing evidence\n"


def test_failed_evidence_records_the_supplied_candidate_sha() -> None:
    collector = _load_collector()

    payload = collector.build_failure_payload(
        requested_candidate="candidate-sha",
        error="candidate rejected",
        duration_seconds=1.25,
        command_records=[],
    )

    assert payload["requested_candidate"] == "candidate-sha"


def test_candidate_preflight_rejects_a_wrong_full_sha(tmp_path: Path) -> None:
    collector = _load_collector()
    root, _contract_lock = _candidate_repo(tmp_path)

    with pytest.raises(collector.EvidenceCollectionError, match="does not resolve to a commit"):
        collector._resolve_candidate(root, "a" * 40, [])


def test_evaluator_preflight_rejects_a_dirty_evaluator_worktree(tmp_path: Path) -> None:
    collector = _load_collector()
    evaluator_root, _ = _candidate_repo(tmp_path)
    (evaluator_root / "uncommitted-evaluator-change.txt").write_text(
        "dirty\n", encoding="utf-8"
    )

    with pytest.raises(collector.EvidenceCollectionError, match="evaluator worktree is dirty"):
        collector._preflight_evaluator(evaluator_root, [])


def test_candidate_preflight_rejects_the_contract_lock_itself(tmp_path: Path) -> None:
    collector = _load_collector()
    root, contract_lock = _candidate_repo(tmp_path)
    collector.CONTRACT_LOCK_COMMIT = contract_lock

    with pytest.raises(collector.EvidenceCollectionError, match="must be after contract lock"):
        collector._resolve_candidate(root, contract_lock, [])


def test_candidate_preflight_rejects_a_dirty_worktree(tmp_path: Path) -> None:
    collector = _load_collector()
    root, contract_lock = _candidate_repo(tmp_path)
    collector.CONTRACT_LOCK_COMMIT = contract_lock
    feature = root / "backend" / "workbench" / "engine" / "packs" / "linear_mixed_effects" / "feature.py"
    feature.parent.mkdir(parents=True)
    feature.write_text("FEATURE = True\n", encoding="utf-8")
    candidate = _commit(root, "candidate feature")
    (root / "uncommitted.txt").write_text("dirty\n", encoding="utf-8")

    with pytest.raises(collector.EvidenceCollectionError, match="dirty"):
        collector._resolve_candidate(root, candidate, [])


def test_candidate_preflight_rejects_a_protected_fixture_change(tmp_path: Path) -> None:
    collector = _load_collector()
    root, contract_lock = _candidate_repo(tmp_path)
    collector.CONTRACT_LOCK_COMMIT = contract_lock
    fixture = root / "tests" / "fixtures" / "models" / "linear_mixed_effects" / "known_truth.csv"
    fixture.write_text("participant_id,score\nP1,999\n", encoding="utf-8")
    candidate = _commit(root, "mutate locked fixture")

    with pytest.raises(collector.EvidenceCollectionError, match="protected paths"):
        collector._resolve_candidate(root, candidate, [])


def test_protected_paths_cover_c1_contracts_fixtures_and_central_adapters() -> None:
    collector = _load_collector()

    required = {
        "backend/workbench/contracts",
        "tests/fixtures/models/linear_mixed_effects",
        "backend/workbench/analysis_loop/adapters.py",
        "backend/workbench/analysis_loop/compare.py",
        "backend/workbench/analysis_loop/validation.py",
        "backend/workbench/narrative",
        "backend/workbench/validation.py",
    }

    assert required.issubset(set(collector.PROTECTED_PATHS))


def test_integration_tip_mode_requires_the_clean_named_integration_head(
    tmp_path: Path,
) -> None:
    collector = _load_collector()
    root, contract_lock = _candidate_repo(tmp_path)
    collector.CONTRACT_LOCK_COMMIT = contract_lock
    _git(root, "branch", "-M", "integration/v1.7.3")
    feature = (
        root
        / "backend"
        / "workbench"
        / "engine"
        / "packs"
        / "linear_mixed_effects"
        / "feature.py"
    )
    feature.parent.mkdir(parents=True)
    feature.write_text("FEATURE = True\n", encoding="utf-8")
    candidate = _commit(root, "integration candidate")

    assert collector._resolve_candidate(
        root,
        candidate,
        [],
        candidate_mode=collector.INTEGRATION_TIP_CANDIDATE_MODE,
    ) == candidate

    _git(root, "branch", "-M", "feature/not-an-integration-tip")
    with pytest.raises(collector.EvidenceCollectionError, match="integration/v1.7.3"):
        collector._resolve_candidate(
            root,
            candidate,
            [],
            candidate_mode=collector.INTEGRATION_TIP_CANDIDATE_MODE,
        )


def test_post_execution_audit_rejects_fixture_mutation(tmp_path: Path) -> None:
    collector = _load_collector()
    root, contract_lock = _candidate_repo(tmp_path)
    collector.CONTRACT_LOCK_COMMIT = contract_lock
    feature = (
        root
        / "backend"
        / "workbench"
        / "engine"
        / "packs"
        / "linear_mixed_effects"
        / "feature.py"
    )
    feature.parent.mkdir(parents=True)
    feature.write_text("FEATURE = True\n", encoding="utf-8")
    candidate = _commit(root, "candidate feature")
    records: list[dict[str, object]] = []
    preflight = collector._preflight_candidate(root, candidate, records)
    fixture = root / "tests" / "fixtures" / "models" / "linear_mixed_effects" / "known_truth.csv"
    fixture.write_text("participant_id,score\nP1,mutated-after-evaluation\n", encoding="utf-8")

    with pytest.raises(collector.EvidenceCollectionError, match="fixture content changed"):
        collector._post_execution_audit(root, candidate, preflight, records)


def test_collector_runs_the_strict_subprocess_before_performance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    collector = _load_collector()
    root = tmp_path / "candidate"
    root.mkdir()
    fixture_sha256 = _write_candidate_fixture(root)
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()
    observed: list[list[str]] = []

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        observed.append(command)
        artifact_dir = Path(command[command.index("--artifact-dir") + 1])
        _write_passing_strict_payload(
            artifact_dir,
            candidate_root=root,
            candidate_sha="a" * 40,
            fixture_sha256=fixture_sha256,
        )
        return subprocess.CompletedProcess(
            command,
            0,
            "simulated-parent-stream-secret",
            "simulated-parent-stream-secret",
        )

    monkeypatch.setattr(collector.subprocess, "run", fake_run)
    records: list[dict[str, object]] = []

    payload = collector._run_strict_candidate_evaluation(
        root=root,
        candidate_sha="a" * 40,
        evaluator_root=REPO_ROOT,
        artifact_root=artifact_root,
        command_records=records,
    )

    assert payload["status"] == "passed"
    assert observed and Path(observed[0][1]).name == "strict_runner.py"
    assert str(REPO_ROOT / "tests" / "evaluation" / "linear_mixed_effects") not in observed[0]
    assert records[0]["exit_code"] == 0
    assert (artifact_root / "strict-runner.output.json").is_file()
    assert not (artifact_root / "strict-runner.stdout.txt").exists()
    assert not (artifact_root / "strict-runner.stderr.txt").exists()
    assert all(
        b"simulated-parent-stream-secret" not in path.read_bytes()
        for path in artifact_root.rglob("*")
        if path.is_file()
    )


@pytest.mark.parametrize(
    ("mutate", "error"),
    [
        (lambda performance: performance.clear(), "invalid schema"),
        (lambda performance: performance.update({"warmups": []}), "warmups"),
        (
            lambda performance: performance["cold_fits"][0].update(
                {"duration_seconds": float("nan")}
            ),
            "strict JSON",
        ),
        (
            lambda performance: performance["hot_fits"][0].update(
                {"duration_seconds": float("inf")}
            ),
            "strict JSON",
        ),
        (
            lambda performance: performance["cold_fits"][0].update(
                {"artifact_path": "/tmp/foreign-contract.json"}
            ),
            "artifact path",
        ),
        (
            lambda performance: performance["hot_fits"][0].update(
                {"artifact_sha256": "0" * 64}
            ),
            "artifact is incomplete",
        ),
        (
            lambda performance: performance["summary"].update(
                {"cold_p50_seconds": 999.0}
            ),
            "summary",
        ),
    ],
)
def test_collector_rejects_incomplete_or_incoherent_performance_evidence(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    mutate: object,
    error: str,
) -> None:
    collector = _load_collector()
    root = tmp_path / "candidate"
    root.mkdir()
    fixture_sha256 = _write_candidate_fixture(root)
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        artifact_dir = Path(command[command.index("--artifact-dir") + 1])
        _write_passing_strict_payload(
            artifact_dir,
            candidate_root=root,
            candidate_sha="a" * 40,
            fixture_sha256=fixture_sha256,
        )
        _rewrite_performance_evidence(artifact_dir, mutate)
        return subprocess.CompletedProcess(command, 0, "strict stdout", "strict stderr")

    monkeypatch.setattr(collector.subprocess, "run", fake_run)

    with pytest.raises(collector.EvidenceCollectionError, match=error):
        collector._run_strict_candidate_evaluation(
            root=root,
            candidate_sha="a" * 40,
            evaluator_root=REPO_ROOT,
            artifact_root=artifact_root,
            command_records=[],
        )


def test_collector_rejects_a_passing_strict_payload_from_the_wrong_candidate_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    collector = _load_collector()
    root = tmp_path / "candidate"
    root.mkdir()
    fixture_sha256 = _write_candidate_fixture(root)
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        artifact_dir = Path(command[command.index("--artifact-dir") + 1])
        _write_passing_strict_payload(
            artifact_dir,
            candidate_root=tmp_path / "foreign-candidate",
            candidate_sha="a" * 40,
            fixture_sha256=fixture_sha256,
        )
        return subprocess.CompletedProcess(command, 0, "strict stdout", "strict stderr")

    monkeypatch.setattr(collector.subprocess, "run", fake_run)

    with pytest.raises(collector.EvidenceCollectionError, match="candidate_root"):
        collector._run_strict_candidate_evaluation(
            root=root,
            candidate_sha="a" * 40,
            evaluator_root=REPO_ROOT,
            artifact_root=artifact_root,
            command_records=[],
        )


def test_collector_rejects_a_passing_strict_payload_with_unparseable_junit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    collector = _load_collector()
    root = tmp_path / "candidate"
    root.mkdir()
    fixture_sha256 = _write_candidate_fixture(root)
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        artifact_dir = Path(command[command.index("--artifact-dir") + 1])
        _write_passing_strict_payload(
            artifact_dir,
            candidate_root=root,
            candidate_sha="a" * 40,
            fixture_sha256=fixture_sha256,
            junit_contents="<testsuite>",
        )
        return subprocess.CompletedProcess(command, 0, "strict stdout", "strict stderr")

    monkeypatch.setattr(collector.subprocess, "run", fake_run)

    with pytest.raises(collector.EvidenceCollectionError, match="JUnit summary"):
        collector._run_strict_candidate_evaluation(
            root=root,
            candidate_sha="a" * 40,
            evaluator_root=REPO_ROOT,
            artifact_root=artifact_root,
            command_records=[],
        )


def test_collector_rejects_a_claimed_pass_with_a_nonzero_full_suite(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    collector = _load_collector()
    root = tmp_path / "candidate"
    root.mkdir()
    fixture_sha256 = _write_candidate_fixture(root)
    artifact_root = tmp_path / "artifacts"
    artifact_root.mkdir()

    def fake_run(command: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        artifact_dir = Path(command[command.index("--artifact-dir") + 1])
        _write_passing_strict_payload(
            artifact_dir,
            candidate_root=root,
            candidate_sha="a" * 40,
            fixture_sha256=fixture_sha256,
        )
        strict_payload = json.loads((artifact_dir / "strict-suite.json").read_text())
        strict_payload["suite_exit_code"] = 1
        (artifact_dir / "strict-suite.json").write_text(json.dumps(strict_payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "strict stdout", "strict stderr")

    monkeypatch.setattr(collector.subprocess, "run", fake_run)

    with pytest.raises(collector.EvidenceCollectionError, match="non-passing pytest suite"):
        collector._run_strict_candidate_evaluation(
            root=root,
            candidate_sha="a" * 40,
            evaluator_root=REPO_ROOT,
            artifact_root=artifact_root,
            command_records=[],
        )


def test_passed_manifest_keeps_strict_provenance_but_not_acceptance(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    collector = _load_collector()
    candidate_sha = "c" * 40
    required_results = {
        "contract_validation": "passed",
        "known_truth": "passed",
        "fault_injection": "passed",
        "agent_boundaries": "passed",
        "compare_restrictions": "passed",
        "deterministic_overclaim_checks": "passed",
    }
    output_metadata_path = tmp_path / "strict-suite.output.json"
    output_metadata = {
        "schema_version": "v173_lmm_strict_output_metadata_v1",
        "capture_policy": "raw pytest stdout and stderr are discarded; hashes cover complete streams",
        "max_reported_bytes": 65536,
        "stdout_sha256": "a" * 64,
        "stderr_sha256": "b" * 64,
        "stdout_bytes_observed": 0,
        "stderr_bytes_observed": 0,
        "stdout_truncated": False,
        "stderr_truncated": False,
    }
    output_metadata_path.write_text(json.dumps(output_metadata), encoding="utf-8")
    strict_payload = {
        "status": "passed",
        "suite_exit_code": 0,
        "suite_command": ["python", "-m", "pytest"],
        "suite_duration_seconds": 0.25,
        "results": required_results,
        "performance": {
            "status": "passed",
            "environment": {
                "python_version": "3.test",
                "statsmodels_version": "test",
                "node_version": "not_run",
                "os_family": "TestOS",
                "dependency_lock_hash": "d" * 64,
            },
        },
        "strict_isolation": {"network_guard": "blocked", "provider_environment": "cleared"},
        "artifacts": {
            "output_metadata": {
                "path": str(output_metadata_path),
                "sha256": hashlib.sha256(output_metadata_path.read_bytes()).hexdigest(),
            },
            "junit_summary": {"sha256": "c" * 64},
        },
    }
    preflight = {
        "candidate_commit": candidate_sha,
        "fixture_hashes": {"tests/fixtures/models/linear_mixed_effects/known_truth.csv": "f" * 64},
    }
    evaluator_preflight = {"evaluator_commit": "h" * 40}
    audit_calls: list[str] = []
    monkeypatch.setattr(
        collector,
        "_preflight_evaluator",
        lambda *_args, **_kwargs: audit_calls.append("pre") or evaluator_preflight,
    )
    monkeypatch.setattr(collector, "_preflight_candidate", lambda *_args, **_kwargs: preflight)
    monkeypatch.setattr(
        collector, "_run_strict_candidate_evaluation", lambda **_kwargs: strict_payload
    )
    monkeypatch.setattr(collector, "_post_execution_audit", lambda *_args, **_kwargs: preflight)
    monkeypatch.setattr(
        collector,
        "_post_execution_evaluator_audit",
        lambda *_args, **_kwargs: audit_calls.append("post") or evaluator_preflight,
    )

    payload = collector._collect(
        root=tmp_path / "candidate",
        candidate=candidate_sha,
        output=tmp_path / "evidence.json",
        command_records=[],
    )

    assert payload["status"] == "passed"
    assert payload["evaluated_commit"] == candidate_sha
    assert payload["candidate_mode"] == "feature_lane"
    assert payload["integration_evidence_policy"] is None
    assert payload["environment"]["dependency_lock_hash"] == "d" * 64
    assert payload["evaluation_harness_commit"] == "h" * 40
    assert audit_calls == ["pre", "post"]
    assert payload["results"]["performance_collection"] == "passed"
    assert payload["results"]["browser_acceptance"] == "not_run"
    assert payload["acceptance"] == {
        "accepted": False,
        "reason": "browser acceptance has not been supplied; strict evidence alone cannot accept a candidate",
    }
    assert payload["inner_pytest"] == {
        "command": ["python", "-m", "pytest"],
        "exit_code": 0,
        "duration_seconds": 0.25,
        "stdout_sha256": "a" * 64,
        "stderr_sha256": "b" * 64,
        "junit_summary_sha256": "c" * 64,
    }
    assert datetime.fromisoformat(payload["generated_at"]).tzinfo is not None


def test_collector_runs_the_real_full_suite_before_it_can_fail_a_candidate(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    collector = _load_collector()
    root, contract_lock = _candidate_repo(tmp_path)
    monkeypatch.setattr(collector, "CONTRACT_LOCK_COMMIT", contract_lock)
    feature = root / "backend" / "workbench" / "engine" / "packs" / "linear_mixed_effects" / "feature.py"
    feature.parent.mkdir(parents=True)
    feature.write_text("FEATURE = True\n", encoding="utf-8")
    candidate = _commit(root, "candidate feature")
    output = tmp_path / "evidence.json"
    monkeypatch.setattr(
        collector,
        "_preflight_evaluator",
        lambda *_args, **_kwargs: {"evaluator_commit": "h" * 40},
    )
    monkeypatch.setattr(
        collector,
        "_post_execution_evaluator_audit",
        lambda *_args, **_kwargs: {"evaluator_commit": "h" * 40},
    )

    with pytest.raises(collector.EvidenceCollectionError, match="strict candidate evaluation failed"):
        collector._collect(
            root=root,
            candidate=candidate,
            output=output,
            command_records=[],
        )

    strict_result = json.loads(
        (tmp_path / "evidence.artifacts" / "strict-suite" / "strict-suite.json").read_text(
            encoding="utf-8"
        )
    )
    assert strict_result["status"] == "failed"
    assert strict_result["suite_exit_code"] != 0
    assert str(
        REPO_ROOT
        / "tests"
        / "evaluation"
        / "linear_mixed_effects"
        / "test_contract_compatibility.py"
    ) in strict_result["suite_command"]
    assert (
        tmp_path
        / "evidence.artifacts"
        / "strict-suite"
        / "strict-suite.junit.summary.json"
    ).is_file()
