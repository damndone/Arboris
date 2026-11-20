"""Evidence is keyed to the tree, environment and builds that were actually tested.

2026-11-06 risk review, finding 11: the gate summary recorded only HEAD, so the same HEAD with
other uncommitted edits, another dependency set or another native build gave the same-looking
evidence, and nothing checked that the tree stayed put while the tests ran.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(SCRIPTS))
    return module


identity = _load("evidence_identity")


def _git(repo, *arguments):
    subprocess.run(["git", *arguments], cwd=repo, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "a.py").write_text("x = 1\n")
    (root / ".gitignore").write_text("ignored/\n")
    _git(root, "add", ".")
    _git(root, "commit", "-qm", "base")
    return root


def test_uncommitted_edits_change_the_tree_but_not_head(repo):
    clean = identity.source_tree(repo)
    assert not clean["dirty"]
    (repo / "a.py").write_text("x = 2\n")
    unstaged = identity.source_tree(repo)
    _git(repo, "add", "a.py")
    staged = identity.source_tree(repo)
    (repo / "new.py").write_text("y = 1\n")
    untracked = identity.source_tree(repo)
    assert len({clean["head"], unstaged["head"], staged["head"], untracked["head"]}) == 1
    assert clean["sha256"] != unstaged["sha256"] == staged["sha256"] != untracked["sha256"]
    assert untracked["files"] == clean["files"] + 1


def test_ignored_files_leave_the_tree_alone(repo):
    before = identity.source_tree(repo)
    (repo / "ignored").mkdir()
    (repo / "ignored" / "scratch.bin").write_bytes(b"x")
    assert identity.source_tree(repo)["sha256"] == before["sha256"]


def test_a_deleted_tracked_file_is_counted_as_missing(repo):
    (repo / "a.py").unlink()
    tree = identity.source_tree(repo)
    assert tree["missing_files"] == 1 and tree["dirty"]


def test_installed_versions_are_compared_with_the_lock(tmp_path):
    probe = identity.environment(sys.executable, tmp_path)
    assert probe["lock"] == {"path": str(identity.LOCK_PATH), "matches": False, "error": "lock_missing"}
    installed = {name: entry["version"] for name, entry in probe["distributions"].items()
                 if not identity._local_directory(entry)}
    name = sorted(installed)[0]
    lock = tmp_path / identity.LOCK_PATH
    lock.parent.mkdir()
    pins = {**installed, name: installed[name] + ".post999", "not-installed-anywhere": "1.0"}
    lock.write_text("".join(f"{key}=={value}\n" for key, value in pins.items()))
    drift = identity.environment(sys.executable, tmp_path)["lock"]
    assert drift["matches"] is False and drift["missing"] == ["not-installed-anywhere"]
    assert drift["different"] == {name: {"locked": pins[name], "installed": installed[name]}}
    lock.write_text("".join(f"{key}=={value}\n" for key, value in installed.items()))
    assert identity.environment(sys.executable, tmp_path)["lock"]["matches"] is True


def test_the_key_changes_with_the_tree_and_the_test_selection(repo):
    first = identity.evidence_key(repo, python=sys.executable, scope="gate:full", test_selection={"tests": 1})
    other_selection = identity.evidence_key(repo, python=sys.executable, scope="gate:full", test_selection={"tests": 2})
    (repo / "a.py").write_text("x = 3\n")
    other_tree = identity.evidence_key(repo, python=sys.executable, scope="gate:full", test_selection={"tests": 1})
    assert len({first["key_sha256"], other_selection["key_sha256"], other_tree["key_sha256"]}) == 3
    assert first["source_tree"]["head"] == other_tree["source_tree"]["head"]


def test_an_unverified_native_build_is_reported(repo):
    module = repo / "backend" / "workbench"
    module.mkdir(parents=True)
    (module / "__init__.py").write_text("")
    (module / "native_build.py").write_text(
        "MODULES = {'io_writers': ('native-io',)}\n"
        "def variants(path):\n    return ('row-exact',)\n"
        "def verify_build(module, out, *, variant):\n    raise ValueError('manifest inputs are stale')\n")
    receipts = identity.native_receipts(sys.executable, repo)
    assert receipts["io_writers:row-exact"] == {"error": "ValueError: manifest inputs are stale"}
    assert receipts["error"] == "unverified native builds: io_writers:row-exact"


def _metrics(repo, *arguments):
    return subprocess.run([sys.executable, str(SCRIPTS / "gate_metrics.py"), *map(str, arguments)], cwd=repo,
                          capture_output=True, text=True)


def test_a_tree_changed_during_the_gate_fails_it(repo):
    directory = Path(_metrics(repo, "init", "full").stdout.strip())
    (repo / "a.py").write_text("x = 4\n")
    finished = _metrics(repo, "finish", directory, 0, sys.executable)
    summary = json.loads((directory / "summary.json").read_text())
    assert finished.returncode != 0
    assert summary["status"] == "failed" and summary["evidence_status"] == "invalidated"
    assert summary["invalidated_reason"] == "source_tree_changed_during_run"


def test_an_unchanged_tree_keeps_the_verdict_and_records_the_key(repo):
    directory = Path(_metrics(repo, "init", "quick").stdout.strip())
    (repo / "ignored").mkdir()
    (repo / "ignored" / "log.txt").write_text("written by a test\n")
    assert _metrics(repo, "finish", directory, 0, sys.executable).returncode == 0
    summary = json.loads((directory / "summary.json").read_text())
    key = summary["evidence_key"]
    assert summary["status"] == "passed"
    assert key["source_tree"]["sha256"] == summary["source_tree_at_start"]["sha256"]
    assert key["scope"] == "gate:quick" and key["test_selection"]["mode"] == "quick"
    assert key["environment"]["executable"] == sys.executable
    assert summary["evidence_status"] == "incomplete"  # this throwaway repo has no lock file
