from __future__ import annotations

import importlib.util
import hashlib
import json
import os
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
    stdout = artifact_dir / "strict-suite.stdout.txt"
    stderr = artifact_dir / "strict-suite.stderr.txt"
    junit = artifact_dir / "strict-suite.junit.xml"
    performance = artifact_dir / "performance" / "performance.json"
    stdout.write_text("pytest output\n", encoding="utf-8")
    stderr.write_text("", encoding="utf-8")
    junit.write_text(
        junit_contents
        if junit_contents is not None
        else "<testsuite>"
        + "".join(
            "<testcase classname=\"tests.evaluation.linear_mixed_effects."
            f"test_{name}\" name=\"candidate_case\"/>"
            for name in (
                "contract_compatibility",
                "known_truth",
                "fault_injection",
                "agent_boundaries",
                "compare_restrictions",
                "report_claims",
            )
        )
        + "</testsuite>",
        encoding="utf-8",
    )
    performance.parent.mkdir(parents=True)
    performance.write_text("{}\n", encoding="utf-8")
    artifacts = {
        "stdout": {"path": str(stdout), "sha256": _sha256_text("pytest output\n")},
        "stderr": {"path": str(stderr), "sha256": _sha256_text("")},
        "junit": {"path": str(junit), "sha256": hashlib.sha256(junit.read_bytes()).hexdigest()},
        "performance": {
            "path": str(performance),
            "sha256": hashlib.sha256(performance.read_bytes()).hexdigest(),
        },
    }
    payload = {
        "schema_version": "v173_lmm_strict_candidate_evaluation_v3",
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
        "performance": {
            "status": "passed",
            "environment": {},
            "fixture": {
                "path": "tests/fixtures/models/linear_mixed_effects/known_truth.csv",
                "sha256": fixture_sha256,
                "rows": 1,
                "subjects": 1,
            },
            "warmups": [],
            "cold_fits": [],
            "hot_fits": [],
            "summary": {},
        },
        "strict_isolation": {"limitations": "scoped guard"},
        "artifacts": artifacts,
        "generated_at": "2026-07-19T00:00:00+00:00",
    }
    (artifact_dir / "strict-suite.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


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
        return subprocess.CompletedProcess(command, 0, "strict stdout", "strict stderr")

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
    assert (artifact_root / "strict-runner.stdout.txt").is_file()


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

    with pytest.raises(collector.EvidenceCollectionError, match="JUnit"):
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
            "stdout": {"sha256": "a" * 64},
            "stderr": {"sha256": "b" * 64},
            "junit": {"sha256": "c" * 64},
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
        "junit_sha256": "c" * 64,
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
    assert (tmp_path / "evidence.artifacts" / "strict-suite" / "strict-suite.junit.xml").is_file()
