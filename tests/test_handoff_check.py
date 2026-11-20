"""The handoff checker catches the ways a handoff was found not done (2026-11-17)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import handoff_check  # noqa: E402

LEDGER = "docs/handoff.json"


def run(root: Path, *args: str) -> str:
    return subprocess.run(list(args), cwd=root, check=True, capture_output=True, text=True).stdout


def commit(root: Path, message: str, files: dict[str, str]) -> None:
    for name, text in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text)
    run(root, "git", "add", "-A")
    run(root, "git", "commit", "-q", "-m", message)


@pytest.fixture
def repo(tmp_path):
    run(tmp_path, "git", "init", "-q")
    run(tmp_path, "git", "config", "user.email", "t@example.invalid")
    run(tmp_path, "git", "config", "user.name", "t")
    (tmp_path / ".gitignore").write_text("/local/\n")
    ledger = {
        "handoff_id": "h1", "forbidden_paths": ["AGENTS.md"], "always_allowed": [],
        "evidence_only_paths": ["docs/*"],
        "tasks": [
            {"id": "C1", "priority": "P0", "title": "fix a", "allowed_paths": ["src/a.py", "tests/test_a.py", "docs/*"],
             "done_when": [{"kind": "command", "run": "test -f src/a.py"},
                           {"kind": "log", "name": "suite", "must_match": r"^ok$"}]},
            {"id": "C2", "priority": "P2", "title": "fix b", "allowed_paths": ["src/b.py"], "done_when": []},
        ],
        "progress": {},
    }
    commit(tmp_path, "base", {"AGENTS.md": "rules\n", "tests/test_a.py": "def test_a():\n    assert 1 == 1\n",
                              LEDGER: json.dumps(ledger)})
    return tmp_path


def set_progress(root: Path, progress: dict, message: str = "progress (handoff)") -> None:
    ledger = json.loads((root / LEDGER).read_text())
    ledger["progress"] = progress
    commit(root, message, {LEDGER: json.dumps(ledger)})


def check(root: Path, **kwargs):
    problems, _ = handoff_check.check(root / LEDGER, root=root, partial=kwargs.get("partial", True),
                                      run=kwargs.get("run", True))
    return problems


def head(root: Path) -> str:
    return run(root, "git", "rev-parse", "HEAD").strip()


def test_a_fresh_handoff_reports_every_task_open(repo):
    assert check(repo, partial=True) == []
    assert check(repo, partial=False) == ["C1 is open", "C2 is open"]


def test_editing_a_task_definition_is_caught(repo):
    ledger = json.loads((repo / LEDGER).read_text())
    ledger["tasks"][0]["done_when"] = []
    commit(repo, "relax (C1)", {LEDGER: json.dumps(ledger)})
    assert "task definitions changed after the handoff; only `progress` may be edited" in check(repo)


def test_untagged_commits_out_of_scope_files_and_forbidden_paths_are_caught(repo):
    commit(repo, "no tag", {"src/a.py": "x = 1\n"})
    commit(repo, "scope (C2)", {"src/a.py": "x = 2\n"})
    commit(repo, "rules (C1)", {"AGENTS.md": "new lesson\n"})
    problems = check(repo)
    assert any("name its task in the subject" in p for p in problems)
    assert any("src/a.py is outside the paths C2 allow" in p for p in problems)
    assert any("AGENTS.md is forbidden" in p for p in problems)


def test_changing_an_existing_assertion_needs_a_declared_reason(repo):
    commit(repo, "loosen (C1)", {"tests/test_a.py": "def test_a():\n    assert True\n"})
    assert any("changes existing lines of tests/test_a.py" in p for p in check(repo))
    set_progress(repo, {"C1": {"status": "in_progress", "test_changes": [
        {"path": "tests/test_a.py", "reason": "the old assertion pinned a removed default"}]}})
    assert check(repo) == []


def test_adding_a_test_without_touching_old_lines_needs_no_declaration(repo):
    commit(repo, "more (C1)", {"tests/test_a.py": "def test_a():\n    assert 1 == 1\n\n\ndef test_b():\n    assert 2\n"})
    assert check(repo) == []


def test_done_needs_commits_passing_checks_and_a_clean_current_log(repo):
    commit(repo, "fix a (C1)", {"src/a.py": "x = 1\n"})
    fix = head(repo)
    set_progress(repo, {"C1": {"status": "done", "commits": [fix]}})
    assert any("log suite: missing" in p for p in check(repo))

    assert handoff_check.record_log(repo / LEDGER, "C1", "suite", ["sh", "-c", "echo ok; exit 3"], root=repo) == 3
    assert any("did not exit 0" in p for p in check(repo))

    assert handoff_check.record_log(repo / LEDGER, "C1", "suite", ["sh", "-c", "echo ok"], root=repo) == 0
    assert check(repo) == []

    commit(repo, "docs only (C1)", {"docs/note.md": "evidence note\n"})
    assert check(repo) == [], "a docs-only commit after the log keeps it valid"
    commit(repo, "more code (C1)", {"src/a.py": "x = 2\n"})
    assert any("code changed since (src/a.py)" in p for p in check(repo))


def test_a_log_recorded_on_a_dirty_tree_is_not_evidence(repo):
    commit(repo, "fix a (C1)", {"src/a.py": "x = 1\n"})
    set_progress(repo, {"C1": {"status": "done", "commits": [head(repo)]}})
    (repo / "src/a.py").write_text("x = 'uncommitted'\n")
    handoff_check.record_log(repo / LEDGER, "C1", "suite", ["sh", "-c", "echo ok"], root=repo)
    problems = check(repo)
    assert any("recorded with uncommitted changes" in p for p in problems)
    assert any("uncommitted changes; commit them" in p for p in problems)


def test_a_failing_check_command_and_unknown_commits_are_reported(repo):
    set_progress(repo, {"C1": {"status": "done", "commits": ["deadbeef"]}})
    problems = check(repo)
    assert any("`test -f src/a.py` exited 1" in p for p in problems)
    assert any("commit deadbeef does not exist" in p for p in problems)
    assert any("no commit names (C1)" in p for p in problems)


def test_the_cli_records_the_command_exit_code_not_a_pipeline_tail(repo, monkeypatch):
    monkeypatch.setattr(handoff_check, "ROOT", repo)
    code = handoff_check.record_log(repo / LEDGER, "C1", "suite", ["sh", "-c", "echo 1 failed; exit 1"], root=repo)
    text = (repo / "local/handoff/h1/C1/suite.log").read_text()
    assert code == 1 and text.rstrip().endswith("exit=1") and text.startswith("commit=")


def test_outside_commits_are_listed_and_may_not_share_a_task_file(repo):
    commit(repo, "chore: unrelated tooling (outside-handoff)", {"tools/x.sh": "echo\n"})
    problems, report = handoff_check.check(repo / LEDGER, root=repo, partial=True, run=True)
    assert problems == [] and any("outside the handoff" in line for line in report)

    commit(repo, "fix: same file as C1 (outside-handoff)", {"src/a.py": "x = 3\n"})
    commit(repo, "docs: lesson (outside-handoff)", {"AGENTS.md": "lesson\n"})
    problems = check(repo)
    assert any("src/a.py belongs to the handoff or is forbidden" in p for p in problems)
    assert any("AGENTS.md belongs to the handoff or is forbidden" in p for p in problems)
