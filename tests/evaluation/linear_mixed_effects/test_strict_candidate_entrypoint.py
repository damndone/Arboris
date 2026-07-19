from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


if os.environ.get("WORKBENCH_EVALUATION_REQUIRE_CANDIDATE") == "1":
    pytest.skip(
        "strict entrypoint meta-tests run outside the candidate evaluation suite",
        allow_module_level=True,
    )


REPO_ROOT = Path(__file__).parents[3]
STRICT_ENTRYPOINT = (
    REPO_ROOT / "tests" / "evaluation" / "linear_mixed_effects" / "strict_runner.py"
)


def _run_strict_entrypoint(
    candidate_root: Path,
    artifact_dir: Path,
    candidate_sha: str,
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(STRICT_ENTRYPOINT),
            "--candidate-root",
            str(candidate_root),
            "--candidate-sha",
            candidate_sha,
            "--evaluator-root",
            str(REPO_ROOT),
            "--artifact-dir",
            str(artifact_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_strict_entrypoint_runs_the_full_suite_and_persists_a_rejection(tmp_path) -> None:
    candidate_root = tmp_path / "candidate"
    (candidate_root / "backend").mkdir(parents=True)
    artifact_dir = tmp_path / "strict-artifacts"

    completed = _run_strict_entrypoint(candidate_root, artifact_dir, "a" * 40)

    assert completed.returncode == 1
    payload = json.loads((artifact_dir / "strict-suite.json").read_text())
    assert payload["status"] == "failed"
    assert payload["candidate_sha"] == "a" * 40
    assert payload["suite_exit_code"] != 0
    assert set(payload["results"]) == {
        "contract_validation",
        "known_truth",
        "fault_injection",
        "agent_boundaries",
        "compare_restrictions",
        "deterministic_overclaim_checks",
    }
    assert set(payload["junit_test_counts"]) == set(payload["results"])
    suite_command = set(payload["suite_command"])
    assert {
        str(REPO_ROOT / "tests" / "evaluation" / "linear_mixed_effects" / filename)
        for filename in (
            "test_contract_compatibility.py",
            "test_known_truth.py",
            "test_fault_injection.py",
            "test_agent_boundaries.py",
            "test_compare_restrictions.py",
            "test_report_claims.py",
        )
    }.issubset(suite_command)
    assert not any("test_collector_guardrails" in item for item in suite_command)
    assert not any("test_strict_candidate_entrypoint" in item for item in suite_command)


def test_strict_entrypoint_rejects_a_non_full_sha_before_candidate_import(tmp_path) -> None:
    candidate_root = tmp_path / "candidate"
    (candidate_root / "backend").mkdir(parents=True)
    artifact_dir = tmp_path / "strict-artifacts"

    completed = _run_strict_entrypoint(candidate_root, artifact_dir, "deadbeef")

    payload = json.loads((artifact_dir / "strict-suite.json").read_text())
    assert completed.returncode == 1
    assert payload["suite_error"] == "INVALID_CANDIDATE_SHA"
    assert payload["suite_exit_code"] == 1


def test_strict_entrypoint_discards_raw_candidate_streams_from_durable_artifacts(
    tmp_path,
) -> None:
    candidate_root = tmp_path / "candidate"
    shutil.copytree(
        REPO_ROOT / "backend" / "workbench",
        candidate_root / "backend" / "workbench",
    )
    runner = (
        candidate_root
        / "backend"
        / "workbench"
        / "engine"
        / "packs"
        / "linear_mixed_effects"
        / "runner.py"
    )
    runner.parent.mkdir(parents=True)
    (runner.parent / "__init__.py").write_text("", encoding="utf-8")
    sentinel = "candidate-stream-sentinel"
    runner.write_text(
        f"print({sentinel!r})\n"
        f"raise RuntimeError({sentinel!r})\n",
        encoding="utf-8",
    )
    artifact_dir = tmp_path / "strict-artifacts"

    completed = _run_strict_entrypoint(candidate_root, artifact_dir, "e" * 40)

    assert completed.returncode == 1
    metadata = json.loads((artifact_dir / "strict-suite.output.json").read_text())
    assert metadata["capture_policy"] == (
        "raw pytest stdout and stderr are discarded; hashes cover complete streams"
    )
    assert metadata["stdout_bytes_observed"] > 0
    assert not (artifact_dir / "strict-suite.stdout.txt").exists()
    assert not (artifact_dir / "strict-suite.stderr.txt").exists()
    assert not (artifact_dir / "strict-suite.junit.xml").exists()
    assert all(
        sentinel.encode("utf-8") not in path.read_bytes()
        for path in artifact_dir.rglob("*")
        if path.is_file()
    )


def test_strict_entrypoint_blocks_network_and_clears_keys_before_import(
    tmp_path,
) -> None:
    candidate_root = tmp_path / "candidate"
    shutil.copytree(
        REPO_ROOT / "backend" / "workbench",
        candidate_root / "backend" / "workbench",
    )
    runner = (
        candidate_root
        / "backend"
        / "workbench"
        / "engine"
        / "packs"
        / "linear_mixed_effects"
        / "runner.py"
    )
    runner.parent.mkdir(parents=True)
    (runner.parent / "__init__.py").write_text("", encoding="utf-8")
    runner.write_text(
        "import os\n"
        "import socket\n"
        "if os.environ.get('OPENAI_API_KEY'):\n"
        "    raise RuntimeError('provider canary leaked')\n"
        "socket.create_connection(('127.0.0.1', 9))\n",
        encoding="utf-8",
    )
    artifact_dir = tmp_path / "strict-artifacts"
    environment = {**os.environ, "OPENAI_API_KEY": "sentinel-provider-key"}

    completed = _run_strict_entrypoint(
        candidate_root,
        artifact_dir,
        "b" * 40,
        env=environment,
    )

    payload = json.loads((artifact_dir / "strict-suite.json").read_text())
    metadata = json.loads((artifact_dir / "strict-suite.output.json").read_text())
    assert completed.returncode == 1
    assert payload["strict_isolation"]["provider_environment"] == "cleared before candidate imports"
    assert "no OS-level sandbox" in payload["strict_isolation"]["limitations"]
    assert metadata["stdout_bytes_observed"] > 0
    assert not (artifact_dir / "strict-suite.stdout.txt").exists()
    assert not (artifact_dir / "strict-suite.stderr.txt").exists()
    assert all(
        b"provider canary leaked" not in path.read_bytes()
        and b"sentinel-provider-key" not in path.read_bytes()
        for path in artifact_dir.rglob("*")
        if path.is_file()
    )


def test_strict_entrypoint_blocks_process_spawning_before_candidate_import(
    tmp_path,
) -> None:
    candidate_root = tmp_path / "candidate"
    shutil.copytree(
        REPO_ROOT / "backend" / "workbench",
        candidate_root / "backend" / "workbench",
    )
    runner = (
        candidate_root
        / "backend"
        / "workbench"
        / "engine"
        / "packs"
        / "linear_mixed_effects"
        / "runner.py"
    )
    runner.parent.mkdir(parents=True)
    (runner.parent / "__init__.py").write_text("", encoding="utf-8")
    runner.write_text(
        "import subprocess\n"
        "subprocess.Popen(['definitely-not-a-real-child-process'])\n",
        encoding="utf-8",
    )
    artifact_dir = tmp_path / "strict-artifacts"

    completed = _run_strict_entrypoint(candidate_root, artifact_dir, "c" * 40)

    payload = json.loads((artifact_dir / "strict-suite.json").read_text())
    metadata = json.loads((artifact_dir / "strict-suite.output.json").read_text())
    assert completed.returncode == 1
    assert metadata["stdout_bytes_observed"] > 0
    assert not (artifact_dir / "strict-suite.stdout.txt").exists()
    assert payload["strict_isolation"]["process_spawn_guard"].startswith(
        "Python-level"
    )


def test_strict_entrypoint_blocks_os_system_before_candidate_import(tmp_path) -> None:
    candidate_root = tmp_path / "candidate"
    shutil.copytree(
        REPO_ROOT / "backend" / "workbench",
        candidate_root / "backend" / "workbench",
    )
    runner = (
        candidate_root
        / "backend"
        / "workbench"
        / "engine"
        / "packs"
        / "linear_mixed_effects"
        / "runner.py"
    )
    runner.parent.mkdir(parents=True)
    (runner.parent / "__init__.py").write_text("", encoding="utf-8")
    runner.write_text(
        "import os\n"
        "os.system('definitely-not-a-real-child-process')\n",
        encoding="utf-8",
    )
    artifact_dir = tmp_path / "strict-artifacts"

    completed = _run_strict_entrypoint(candidate_root, artifact_dir, "d" * 40)

    metadata = json.loads((artifact_dir / "strict-suite.output.json").read_text())
    assert completed.returncode == 1
    assert metadata["stdout_bytes_observed"] > 0
    assert not (artifact_dir / "strict-suite.stdout.txt").exists()
