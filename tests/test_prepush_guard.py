"""V1812-PREPUSH-GUARD: the pre-push guard is versioned, installable and tested.

The guard (scripts/git_hooks/pre-push) refuses pushes that would publish
private refs, the v1.8.11 branches whose history carries Stata license values,
a newly added license header value, or the real hash of a withheld raw log.
scripts/install_git_hooks.py writes only <common git dir>/hooks/pre-push.

Each case pushes for real from a temporary clone to a temporary bare remote,
with the user's global and system git configuration excluded.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / "scripts" / "git_hooks" / "pre-push"
INSTALLER = REPO / "scripts" / "install_git_hooks.py"


def _env(home: Path) -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(
        HOME=str(home),
        GIT_CONFIG_GLOBAL=os.devnull,
        GIT_CONFIG_NOSYSTEM="1",
        GIT_AUTHOR_NAME="guard-test",
        GIT_AUTHOR_EMAIL="guard@test.invalid",
        GIT_COMMITTER_NAME="guard-test",
        GIT_COMMITTER_EMAIL="guard@test.invalid",
    )
    return env


def _git(cwd: Path, env, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, env=env, capture_output=True, text=True, check=check)


@pytest.fixture
def clone(tmp_path):
    env = _env(tmp_path)
    remote = tmp_path / "remote.git"
    _git(tmp_path, env, "init", "--bare", "-b", "main", str(remote))
    work = tmp_path / "work"
    _git(tmp_path, env, "clone", str(remote), str(work))
    _git(work, env, "checkout", "-b", "main")
    (work / "README.md").write_text("start\n")
    _git(work, env, "add", "README.md")
    _git(work, env, "commit", "-m", "start")
    _git(work, env, "push", "origin", "main")
    installed = subprocess.run(
        [sys.executable, str(INSTALLER)], cwd=work, env=env, capture_output=True, text=True
    )
    assert installed.returncode == 0, installed.stderr
    return work, env


def _commit(work: Path, env, name: str, text: str) -> None:
    (work / name).write_text(text)
    _git(work, env, "add", name)
    _git(work, env, "commit", "-m", f"add {name}")


def _push(work: Path, env, *refspec: str) -> subprocess.CompletedProcess:
    return _git(work, env, "push", "origin", *refspec, check=False)


def test_installer_writes_exactly_the_versioned_hook(clone):
    work, env = clone
    hooks = Path(_git(work, env, "rev-parse", "--git-common-dir").stdout.strip())
    hook = (work / hooks if not hooks.is_absolute() else hooks) / "hooks" / "pre-push"
    assert hook.read_bytes() == SOURCE.read_bytes()
    assert os.access(hook, os.X_OK)
    again = subprocess.run([sys.executable, str(INSTALLER)], cwd=work, env=env, capture_output=True, text=True)
    assert again.returncode == 0 and "already installed" in again.stdout


def test_installer_refuses_to_replace_a_different_hook_without_force(clone):
    work, env = clone
    hook = work / ".git" / "hooks" / "pre-push"
    hook.write_text("#!/bin/sh\necho custom\n")
    refused = subprocess.run([sys.executable, str(INSTALLER)], cwd=work, env=env, capture_output=True, text=True)
    assert refused.returncode != 0
    assert hook.read_text() == "#!/bin/sh\necho custom\n"
    forced = subprocess.run([sys.executable, str(INSTALLER), "--force"], cwd=work, env=env, capture_output=True, text=True)
    assert forced.returncode == 0, forced.stderr
    assert hook.read_bytes() == SOURCE.read_bytes()


def test_an_ordinary_push_is_allowed(clone):
    work, env = clone
    _commit(work, env, "notes.md", "Serial number: [REDACTED]\nordinary text\n")
    result = _push(work, env, "main")
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "refspec",
    [
        "HEAD:refs/private/v1.8.11-full-history",
        "HEAD:refs/heads/workbench-v1.8.11",
        "HEAD:refs/heads/lane/v1811-script-export",
        "HEAD:refs/heads/codex/v1811-review",
    ],
)
def test_private_and_license_bearing_refs_are_refused(clone, refspec):
    work, env = clone
    result = _push(work, env, refspec)
    assert result.returncode != 0
    assert "private or license-bearing ref" in result.stderr


def test_a_local_only_archive_tag_is_refused(clone):
    work, env = clone
    _git(work, env, "tag", "archive/local-only/x")
    result = _push(work, env, "refs/tags/archive/local-only/x")
    assert result.returncode != 0
    assert "private or license-bearing ref" in result.stderr


@pytest.mark.parametrize("header", ["Serial number: 4012345678", "Licensed to:  Example University"])
def test_an_added_license_header_value_is_refused(clone, header):
    work, env = clone
    _commit(work, env, "analysis.log", f"Stata 18\n{header}\n")
    result = _push(work, env, "main")
    assert result.returncode != 0
    assert "license header value added" in result.stderr


def test_a_withheld_raw_log_hash_is_refused(clone):
    work, env = clone
    digest = "ab" * 32
    withheld = work / "local" / "evidence"
    withheld.mkdir(parents=True)
    (withheld / "withheld-hash-map.json").write_text(json.dumps({"withheld": {"raw.log": {"sha256": digest}}}))
    _commit(work, env, "manifest.json", json.dumps({"raw_sha256": digest}))
    result = _push(work, env, "main")
    assert result.returncode != 0
    assert "withheld raw-log hash" in result.stderr


def test_deleting_a_remote_branch_is_allowed(clone):
    work, env = clone
    assert _push(work, env, "HEAD:refs/heads/topic").returncode == 0
    result = _push(work, env, ":refs/heads/topic")
    assert result.returncode == 0, result.stderr


def test_the_installed_guard_in_this_checkout_matches_the_versioned_source():
    common = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.strip()
    installed = (REPO / common if not Path(common).is_absolute() else Path(common)) / "hooks" / "pre-push"
    if not installed.exists():
        pytest.skip("guard not installed in this checkout; run scripts/install_git_hooks.py")
    assert installed.read_bytes() == SOURCE.read_bytes(), "installed guard differs; reinstall it"
