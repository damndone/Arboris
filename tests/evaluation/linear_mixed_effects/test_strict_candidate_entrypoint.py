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
    assert payload["unexpected_skips"] == []
    assert str(REPO_ROOT / "tests" / "evaluation" / "linear_mixed_effects") in payload[
        "suite_command"
    ]


def test_strict_entrypoint_rejects_a_non_full_sha_before_candidate_import(tmp_path) -> None:
    candidate_root = tmp_path / "candidate"
    (candidate_root / "backend").mkdir(parents=True)
    artifact_dir = tmp_path / "strict-artifacts"

    completed = _run_strict_entrypoint(candidate_root, artifact_dir, "deadbeef")

    payload = json.loads((artifact_dir / "strict-suite.json").read_text())
    assert completed.returncode == 1
    assert "40-character full lowercase SHA" in payload["suite_error"]
    assert payload["suite_exit_code"] == 1


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
    output = (artifact_dir / "strict-suite.stdout.txt").read_text(encoding="utf-8")
    assert completed.returncode == 1
    assert payload["strict_isolation"]["provider_environment"] == "cleared before candidate imports"
    assert "network access is forbidden before and during strict candidate evaluation" in output
    assert "provider canary leaked" not in output
    assert "sentinel-provider-key" not in output
