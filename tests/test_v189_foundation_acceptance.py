from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from workbench.qa.v189_foundation_acceptance import (
    AcceptanceStatus,
    CandidateIdentityError,
    build_acceptance_matrix,
    candidate_integrity_status,
    inspect_candidate,
    provider_mode_status,
    write_sidecar_once,
)
from scripts.v189_foundation_acceptance_runner import RunnerError, _ensure_sidecar_root


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def _candidate_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "candidate"
    (repo / "backend/workbench").mkdir(parents=True)
    (repo / "frontend/src").mkdir(parents=True)
    (repo / ".gitignore").write_text(
        ".venv/\nfrontend/node_modules/\nbackend/workbench/__pycache__/\n",
        encoding="utf-8",
    )
    (repo / "backend/workbench/__init__.py").write_text(
        "candidate = True\n", encoding="utf-8"
    )
    (repo / "frontend/src/index.ts").write_text(
        "export const candidate = true;\n", encoding="utf-8"
    )
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "acceptance@example.invalid")
    _git(repo, "config", "user.name", "Acceptance Harness")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def test_matrix_retains_a_row_when_projection_is_missing() -> None:
    paths = [
        {
            "provider_id": "provider.a",
            "provider_version": "1.0.0",
            "path_id": "path.a",
            "operation_version": "1.0.0",
            "capability_ref": "capability:a",
            "consumers": [{"consumer_id": "report", "projection_ref": "projection:a"}],
        }
    ]

    covered = build_acceptance_matrix(
        paths,
        [
            {
                "provider_id": "provider.a",
                "path_id": "path.a",
                "consumer_id": "report",
                "status": "covered",
                "reason": "registered",
            }
        ],
    )
    blocked = build_acceptance_matrix(paths, [])

    assert covered.rows[0].status == AcceptanceStatus.COVERED
    assert blocked.rows[0].status == AcceptanceStatus.BLOCKED
    assert blocked.rows[0].reason == "projection_missing"
    assert blocked.row_count == covered.row_count == 1
    assert blocked.matrix_digest != covered.matrix_digest


def test_candidate_identity_requires_exact_clean_sha_and_allows_dependencies(
    tmp_path: Path,
) -> None:
    repo, sha = _candidate_repo(tmp_path)
    (repo / ".venv").mkdir()
    (repo / ".venv/marker").write_text("dependency\n", encoding="utf-8")
    (repo / "frontend/node_modules").mkdir()
    (repo / "frontend/node_modules/marker").write_text("dependency\n", encoding="utf-8")

    identity = inspect_candidate(repo, sha, interpreter=sys.executable)
    assert identity.commit_sha == sha
    assert identity.backend_source == (repo / "backend").resolve()

    (repo / "backend/workbench/dirty.py").write_text("dirty = True\n", encoding="utf-8")
    with pytest.raises(CandidateIdentityError, match="dirty"):
        inspect_candidate(repo, sha, interpreter=sys.executable)

    clean_repo, clean_sha = _candidate_repo(tmp_path / "clean")
    with pytest.raises(CandidateIdentityError, match="SHA"):
        inspect_candidate(clean_repo, "0" * 40, interpreter=sys.executable)


def test_provider_mode_never_promotes_deterministic_fallback() -> None:
    result = provider_mode_status(provider_requested=True, provider_configured=False)

    assert result.status is AcceptanceStatus.NOT_VERIFIED
    assert result.provider_called is False
    assert "configured" in result.reason


def test_post_run_integrity_rejects_new_ignored_source_state(tmp_path: Path) -> None:
    repo, sha = _candidate_repo(tmp_path)

    clean = candidate_integrity_status(repo, sha, interpreter=sys.executable)
    assert clean == {"status": AcceptanceStatus.PASS.value, "reason": "candidate remained unchanged"}

    (repo / ".pytest_cache").mkdir()
    (repo / ".pytest_cache/CACHEDIR.TAG").write_text("generated\n", encoding="utf-8")

    dirty = candidate_integrity_status(repo, sha, interpreter=sys.executable)
    assert dirty["status"] == AcceptanceStatus.FAIL.value
    assert "dirty" in dirty["reason"]


def test_sidecar_is_write_once(tmp_path: Path) -> None:
    path = tmp_path / "manifest.json"
    payload = {"candidate_sha": "a" * 40, "status": "BLOCKED"}

    write_sidecar_once(path, payload)

    assert json.loads(path.read_text(encoding="utf-8")) == payload
    with pytest.raises(FileExistsError):
        write_sidecar_once(path, payload)


def test_runner_rejects_sidecar_output_inside_candidate(tmp_path: Path) -> None:
    repo, _sha = _candidate_repo(tmp_path)
    identity = inspect_candidate(repo, _sha)

    with pytest.raises(RunnerError, match="outside"):
        _ensure_sidecar_root(repo / "evidence", identity)
