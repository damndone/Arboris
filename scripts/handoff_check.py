"""Mechanical check of a handoff ledger: what was asked, what was done, and whether it holds.

A handoff ledger (JSON) lists tasks with their allowed paths and their "done when" checks. The
person receiving the handoff fills only the top-level ``progress`` object. This script fails when:

- a task definition (anything outside ``progress``) differs from the version first committed;
- a commit after that version names no task id in its subject, or touches files outside the
  paths its tasks allow, or touches a forbidden path;
- a commit removes or changes lines of an existing test without a ``test_changes`` entry;
- a task marked done lacks its commits, a check command fails, or an evidence log is missing,
  failed, or was recorded on a commit that code changes have since superseded;
- the working tree has uncommitted changes.

Someone else working in the same branch meanwhile marks a commit ``(outside-handoff)`` in its subject.
It is listed in the report, and it fails when it touches a forbidden path, the ledger, or any path a
task allows: two writers never share a file.

Evidence logs are written by this script, so the exit code in them is the command's own (a
``cmd | tail`` pipeline reports tail's):

    .venv/bin/python scripts/handoff_check.py log <ledger> <task> <name> -- <command ...>
    .venv/bin/python scripts/handoff_check.py check <ledger> [--partial] [--no-run]
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUSES = {"open", "in_progress", "blocked", "done"}
TEST_FILE = re.compile(r"^(tests/.*\.py|frontend/src/.*\.test\.tsx?)$")


def git(*args: str, root: Path = ROOT) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _matches(path: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) or path == pattern for pattern in patterns)


def _definitions(ledger: dict) -> dict:
    return {key: value for key, value in ledger.items() if key != "progress"}


def _base_commit(ledger_path: str, root: Path) -> str:
    added = git("log", "--diff-filter=A", "--format=%H", "--", ledger_path, root=root).split()
    if not added:
        raise SystemExit(f"{ledger_path} is not committed; commit the ledger before handing it over")
    return added[-1]


def _log_path(ledger: dict, task: str, name: str, root: Path) -> Path:
    return root / "local" / "handoff" / ledger["handoff_id"] / task / f"{name}.log"


def _code_paths_changed(since: str, root: Path, ledger_path: str, evidence_only: list[str]) -> list[str]:
    changed = git("diff", "--name-only", since, "HEAD", root=root).split()
    return [path for path in changed if path != ledger_path and not _matches(path, evidence_only)]


def record_log(ledger_path: Path, task: str, name: str, command: list[str], root: Path = ROOT) -> int:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if task not in {item["id"] for item in ledger["tasks"]}:
        raise SystemExit(f"unknown task {task}")
    path = _log_path(ledger, task, name, root)
    path.parent.mkdir(parents=True, exist_ok=True)
    head = git("rev-parse", "HEAD", root=root).strip()
    clean = not git("status", "--porcelain", "--untracked-files=normal", root=root).strip()
    with path.open("w", encoding="utf-8") as stream:
        stream.write(f"commit={head}\ntree_clean={str(clean).lower()}\ncmd={json.dumps(command)}\n")
        stream.flush()
        code = subprocess.run(command, cwd=root, stdout=stream, stderr=subprocess.STDOUT).returncode
        stream.write(f"\nexit={code}\n")
    print(f"{path.relative_to(root)}: exit={code}" + ("" if clean else " (tree was not clean: not valid evidence)"))
    return code


def _check_log(ledger: dict, task: str, spec: dict, root: Path, ledger_path: str) -> list[str]:
    path = _log_path(ledger, task, spec["name"], root)
    label = f"{task} log {spec['name']}"
    if not path.exists():
        return [f"{label}: missing; record it with `handoff_check.py log {ledger_path} {task} {spec['name']} -- ...`"]
    text = path.read_text(encoding="utf-8", errors="replace")
    header = dict(line.split("=", 1) for line in text.splitlines()[:3] if "=" in line)
    problems = []
    if not text.rstrip().endswith("exit=0"):
        problems.append(f"{label}: the command did not exit 0")
    if header.get("tree_clean") != "true":
        problems.append(f"{label}: recorded with uncommitted changes")
    commit = header.get("commit", "")
    try:
        git("merge-base", "--is-ancestor", commit, "HEAD", root=root)
    except subprocess.CalledProcessError:
        return problems + [f"{label}: recorded on {commit[:8] or '?'}, which is not in this branch"]
    later = _code_paths_changed(commit, root, ledger_path, ledger.get("evidence_only_paths", []))
    if later:
        problems.append(f"{label}: recorded on {commit[:8]}; code changed since ({', '.join(later[:4])}); record it again")
    if spec.get("must_match") and not re.search(spec["must_match"], text, re.M):
        problems.append(f"{label}: output does not match /{spec['must_match']}/")
    if spec.get("must_not_match") and re.search(spec["must_not_match"], text, re.M):
        problems.append(f"{label}: output matches /{spec['must_not_match']}/")
    return problems


def _removed_test_lines(commit: str, root: Path) -> list[str]:
    files = []
    for line in git("show", "--format=", "--numstat", "--diff-filter=MRD", commit, root=root).splitlines():
        added, removed, path = line.split("\t", 2)
        path = path.split(" => ")[-1].rstrip("}")
        if TEST_FILE.match(path) and removed not in {"0", "-"}:
            files.append(path)
    return files


def check(ledger_path: Path, *, partial: bool, run: bool, root: Path = ROOT) -> tuple[list[str], list[str]]:
    relative = str(ledger_path.resolve().relative_to(root.resolve()))
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    base = _base_commit(relative, root)
    original = json.loads(git("show", f"{base}:{relative}", root=root))
    problems: list[str] = []
    report: list[str] = []
    if _definitions(ledger) != _definitions(original):
        problems.append("task definitions changed after the handoff; only `progress` may be edited")
    tasks = {task["id"]: task for task in original["tasks"]}
    progress = ledger.get("progress", {})
    for key, entry in progress.items():
        if key not in tasks:
            problems.append(f"progress names unknown task {key}")
        elif entry.get("status", "open") not in STATUSES:
            problems.append(f"{key}: status must be one of {sorted(STATUSES)}")

    tag = re.compile(r"\(([A-Z]\d+(?:,\s*[A-Z]\d+)*)\)")
    always = original.get("always_allowed", []) + [relative]
    forbidden = original.get("forbidden_paths", [])
    declared = {(task_id, change.get("path")) for task_id, entry in progress.items()
                for change in entry.get("test_changes", []) if change.get("reason", "").strip()}
    commits_by_task: dict[str, set[str]] = {task_id: set() for task_id in tasks}
    task_paths = [pattern for task in tasks.values() for pattern in task.get("allowed_paths", [])]
    for commit in git("rev-list", "--reverse", f"{base}..HEAD", root=root).split():
        subject = git("show", "-s", "--format=%s", commit, root=root).strip()
        files = git("show", "--format=", "--name-only", commit, root=root).split()
        named = [task_id.strip() for group in tag.findall(subject) for task_id in group.split(",")]
        named = [task_id for task_id in named if task_id in tasks]
        short = commit[:8]
        if "(outside-handoff)" in subject:
            report.append(f"outside the handoff: {short} {subject[:70]}")
            for path in files:
                if path == relative or _matches(path, forbidden) or _matches(path, task_paths):
                    problems.append(f"{short} (outside-handoff): {path} belongs to the handoff or is forbidden")
            continue
        if not named:
            if files and all(_matches(path, always) for path in files):
                continue
            problems.append(f"{short} '{subject[:60]}': name its task in the subject, for example (C1)")
            continue
        for task_id in named:
            commits_by_task[task_id].add(commit)
        allowed = always + [pattern for task_id in named for pattern in tasks[task_id].get("allowed_paths", [])]
        for path in files:
            if _matches(path, forbidden):
                problems.append(f"{short}: {path} is forbidden in this handoff")
            elif not _matches(path, allowed):
                problems.append(f"{short}: {path} is outside the paths {', '.join(named)} allow")
        for path in _removed_test_lines(commit, root):
            if not any((task_id, path) in declared for task_id in named):
                problems.append(f"{short}: changes existing lines of {path}; add a test_changes entry with the reason "
                                "to progress, or keep the old assertions and add new ones")

    if git("status", "--porcelain", "--untracked-files=normal", root=root).strip():
        problems.append("the working tree has uncommitted changes; commit them under their task id")

    for task_id, task in tasks.items():
        entry = progress.get(task_id, {})
        status = entry.get("status", "open")
        report.append(f"{task['priority']:<3} {task_id:<4} {status:<12} {task['title']}"
                      + (f"  [{entry.get('blocked_reason')}]" if status == "blocked" else ""))
        if status != "done":
            if not partial:
                problems.append(f"{task_id} is {status}")
            continue
        listed = set(entry.get("commits", []))
        resolved = set()
        for sha in listed:
            try:
                resolved.add(git("rev-parse", "--verify", f"{sha}^{{commit}}", root=root).strip())
            except subprocess.CalledProcessError:
                problems.append(f"{task_id}: commit {sha} does not exist")
        if task.get("allowed_paths") and not commits_by_task[task_id]:
            problems.append(f"{task_id}: done, but no commit names ({task_id})")
        if resolved - commits_by_task[task_id]:
            problems.append(f"{task_id}: progress lists commits that do not name ({task_id}) after the handoff")
        for spec in task.get("done_when", []):
            if spec["kind"] == "log":
                problems.extend(_check_log(original, task_id, spec, root, relative))
            elif spec["kind"] == "command" and run:
                command = spec["run"].replace("{python}", sys.executable)
                result = subprocess.run(command, cwd=root, shell=True, capture_output=True, text=True)
                if result.returncode != 0:
                    tail = (result.stdout + result.stderr).strip().splitlines()[-3:]
                    problems.append(f"{task_id}: `{spec['run']}` exited {result.returncode}: {' | '.join(tail)[:300]}")
            elif spec["kind"] == "devline":
                events = (root / spec["path"]).read_text(encoding="utf-8")
                if f"handoff:{original['handoff_id']}:{task_id}" not in events:
                    problems.append(f"{task_id}: no devline event links handoff:{original['handoff_id']}:{task_id}")
    return problems, report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="action", required=True)
    log = sub.add_parser("log", help="run a command and record its evidence log")
    log.add_argument("ledger", type=Path)
    log.add_argument("task")
    log.add_argument("name")
    log.add_argument("command", nargs=argparse.REMAINDER)
    checker = sub.add_parser("check", help="verify the ledger against the branch")
    checker.add_argument("ledger", type=Path)
    checker.add_argument("--partial", action="store_true", help="do not fail on tasks that are not done yet")
    checker.add_argument("--no-run", action="store_true", help="skip the quick check commands")
    args = parser.parse_args(argv)
    if args.action == "log":
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        if not command:
            parser.error("give the command after --")
        return record_log(args.ledger, args.task, args.name, command)
    problems, report = check(args.ledger, partial=args.partial, run=not args.no_run)
    print("\n".join(report))
    print()
    for problem in problems:
        print(f"FAIL {problem}")
    print(f"{len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
