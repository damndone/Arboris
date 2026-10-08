"""V1812-REPO-EVIDENCE-POLICY: what a version adds to the repository is bounded.

The repository grew from 32 MB to 84 MB in v1.8.11 (6461 added files, 52 MiB
net), against 1.3-2.0 MiB and 113-343 files for v1.8.9 and v1.8.10, whose
largest added file was under 0.1 MiB. The guard compares the index (committed
plus staged) with the latest release tag and fails, naming the paths, when a
version exceeds the budget, adds an oversized file, or adds files to the frozen
v1.8.10/v1.8.11 evaluation roots. Large raw evidence belongs in the ignored
local/; the repository keeps manifests and hashes (docs/superpowers/README.md).
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from scripts.repo_evidence_budget import BUDGET, FROZEN_EVALUATION_ROOTS, NoReleaseBaseline, check

REPO = Path(__file__).resolve().parents[1]
KIB = 1024


def _env(home: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(HOME=str(home), GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t.invalid")
    return env


@pytest.fixture
def repo(tmp_path, monkeypatch):
    for key in [key for key in os.environ if key.startswith("GIT_")]:
        monkeypatch.delenv(key)
    for key, value in _env(tmp_path).items():
        monkeypatch.setenv(key, value)
    root = tmp_path / "repo"
    root.mkdir()
    git = lambda *args: subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True)
    git("init", "-b", "main")
    (root / "tests" / "eval_v1811").mkdir(parents=True)
    (root / "tests" / "eval_v1811" / "review.py").write_text("x = 1\n")
    (root / "README.md").write_text("start\n")
    git("add", "-A")
    git("commit", "-m", "release")
    git("tag", "v0.1.0")
    return root, git


def _write(root: Path, relative: str, size: int) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(os.urandom(size))


def test_an_ordinary_version_passes(repo):
    root, git = repo
    _write(root, "backend/module.py", 20 * KIB)
    git("add", "-A")
    git("commit", "-m", "work")
    report = check(root)
    assert report.base == "v0.1.0"
    assert report.violations == []


def test_an_oversized_file_fails_and_names_its_path(repo):
    root, git = repo
    _write(root, "tests/fixtures/big/evidence.json", 600 * KIB)
    git("add", "-A")
    report = check(root)  # staged is enough: the guard reads the index
    assert any("tests/fixtures/big/evidence.json" in item and "600.0 KiB" in item for item in report.violations), report.violations


def test_a_listed_exception_needs_a_reason_and_holds_its_size(repo):
    root, git = repo
    _write(root, "tests/fixtures/oracle/large.json", 600 * KIB)
    allowlist = {"files": {"tests/fixtures/oracle/large.json": {"max_bytes": 700 * KIB, "reason": "R oracle output, reviewed"}}}
    (root / "scripts").mkdir()
    (root / "scripts" / "repo_evidence_allowlist.json").write_text(json.dumps(allowlist))
    git("add", "-A")
    assert check(root).violations == []
    _write(root, "tests/fixtures/oracle/large.json", 800 * KIB)
    git("add", "-A")
    assert any("tests/fixtures/oracle/large.json" in item for item in check(root).violations)
    allowlist["files"]["tests/fixtures/oracle/large.json"]["reason"] = ""
    (root / "scripts" / "repo_evidence_allowlist.json").write_text(json.dumps(allowlist))
    git("add", "-A")
    assert any("reason" in item for item in check(root).violations)


def test_a_listed_exception_for_a_file_that_is_gone_is_reported(repo):
    root, git = repo
    allowlist = {"files": {"frontend/src/generated/renamed.ts": {"max_bytes": 1024 * KIB, "reason": "generated"}}}
    (root / "scripts").mkdir()
    (root / "scripts" / "repo_evidence_allowlist.json").write_text(json.dumps(allowlist))
    git("add", "-A")
    assert any(
        "frontend/src/generated/renamed.ts" in item and "not in the repository" in item
        for item in check(root).violations
    )


def test_the_generated_api_types_are_listed_with_a_reason_and_a_1_mib_cap():
    allowlist = json.loads((REPO / "scripts" / "repo_evidence_allowlist.json").read_text(encoding="utf-8"))
    entry = allowlist["files"]["frontend/src/generated/api-schema.ts"]
    assert entry["max_bytes"] == 1024 * KIB
    assert entry["reason"].strip()
    assert (REPO / "frontend/src/generated/api-schema.ts").stat().st_size <= entry["max_bytes"]


def test_net_growth_over_budget_fails_and_lists_the_largest_additions(repo):
    root, git = repo
    count = BUDGET["net_growth_bytes"] // (400 * KIB) + 1
    for index in range(count):
        _write(root, f"docs/evidence/part_{index:02d}.bin", 400 * KIB)
    git("add", "-A")
    violations = check(root).violations
    growth = [item for item in violations if item.startswith("net growth")]
    assert growth and "docs/evidence/part_" in growth[0], violations


def test_too_many_added_files_fail(repo):
    root, git = repo
    for index in range(BUDGET["added_files"] + 1):
        path = root / "tests" / "fixtures" / "many" / f"{index:05d}.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(index))
    git("add", "-A")
    violations = check(root).violations
    assert any(item.startswith(f"{BUDGET['added_files'] + 1} files added") for item in violations), violations
    assert any("tests/fixtures/many" in item for item in violations)


def test_frozen_evaluation_roots_accept_edits_but_not_new_files(repo):
    root, git = repo
    (root / "tests" / "eval_v1811" / "review.py").write_text("x = 2\n")
    git("add", "-A")
    assert check(root).violations == []
    (root / "tests" / "eval_v1811" / "new_review.py").write_text("y = 1\n")
    git("add", "-A")
    violations = check(root).violations
    assert any("tests/eval_v1811/new_review.py" in item and "evaluations/" in item for item in violations), violations


def test_a_repository_without_a_release_tag_is_an_error(tmp_path, monkeypatch):
    for key, value in _env(tmp_path).items():
        monkeypatch.setenv(key, value)
    subprocess.run(["git", "init", "-b", "main", str(tmp_path / "r")], check=True, capture_output=True)
    (tmp_path / "r" / "a.txt").write_text("a")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path / "r", check=True)
    subprocess.run(["git", "commit", "-m", "a"], cwd=tmp_path / "r", check=True, capture_output=True)
    with pytest.raises(NoReleaseBaseline):
        check(tmp_path / "r")


def test_frozen_roots_are_the_v1810_and_v1811_evaluation_trees():
    assert set(FROZEN_EVALUATION_ROOTS) == {
        "tests/eval_v1810/",
        "tests/eval_v1811/",
        "tests/fixtures/eval_v1810/",
        "tests/fixtures/eval_v1811/",
        "tests/fixtures/agent_live_eval_v1811/",
    }


def test_this_version_is_within_budget():
    report = check(REPO)
    assert report.violations == [], "\n".join([f"since {report.base}:"] + report.violations)
