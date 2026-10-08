#!/usr/bin/env python3
"""Bound what one version adds to the repository (V1812-REPO-EVIDENCE-POLICY).

Compares the index (committed plus staged) with the latest release tag
reachable from HEAD and reports, by path:

* net growth of tracked bytes over ``BUDGET["net_growth_bytes"]``;
* more than ``BUDGET["added_files"]`` added files;
* any added or grown file over ``BUDGET["file_bytes"]`` that is not listed,
  with a reason and a size cap, in scripts/repo_evidence_allowlist.json;
* any added file under a frozen evaluation root: v1.8.10/v1.8.11 evaluation
  evidence stays where it is (user decision, 2026-10-07), and new evaluation
  sources go to evaluations/<version>/ with large raw output in local/.

Calibration (net growth, added files, largest added file): v1.8.9 1.3 MiB,
113, 0.09 MiB; v1.8.10 2.0 MiB, 343, 0.09 MiB; v1.8.11 52.4 MiB, 6461,
2.7 MiB.

Usage: python3 scripts/repo_evidence_budget.py [--repo PATH]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

KIB = 1024
MIB = 1024 * KIB
BUDGET = {"net_growth_bytes": 5 * MIB, "added_files": 1000, "file_bytes": 512 * KIB}
FROZEN_EVALUATION_ROOTS = (
    "tests/eval_v1810/",
    "tests/eval_v1811/",
    "tests/fixtures/eval_v1810/",
    "tests/fixtures/eval_v1811/",
    "tests/fixtures/agent_live_eval_v1811/",
)
ALLOWLIST = "scripts/repo_evidence_allowlist.json"
_LISTED = 8


class NoReleaseBaseline(RuntimeError):
    """No release tag is reachable, so a version's additions cannot be measured."""


@dataclass
class Report:
    base: str
    violations: list[str] = field(default_factory=list)


def _git(repo: Path, *args: str, input: str | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, input=input, capture_output=True, text=True, check=True
    ).stdout


def _size(value: int) -> str:
    return f"{value / MIB:.1f} MiB" if value >= MIB else f"{value / KIB:.1f} KiB"


def _release_tag(repo: Path) -> str:
    try:
        return _git(repo, "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*", "HEAD").strip()
    except subprocess.CalledProcessError as exc:
        raise NoReleaseBaseline("no release tag (v*) is reachable from HEAD") from exc


def _base_sizes(repo: Path, tag: str) -> dict[str, int]:
    sizes = {}
    for line in _git(repo, "ls-tree", "-r", "-l", "-z", tag).split("\0"):
        if not line:
            continue
        meta, path = line.split("\t", 1)
        kind, size = meta.split()[1], meta.split()[3]
        if kind == "blob":
            sizes[path] = int(size)
    return sizes


def _index_sizes(repo: Path) -> dict[str, int]:
    entries = []
    for line in _git(repo, "ls-files", "-s", "-z").split("\0"):
        if not line:
            continue
        meta, path = line.split("\t", 1)
        mode, blob = meta.split()[:2]
        if mode != "160000":  # submodule commits have no blob
            entries.append((path, blob))
    batch = _git(repo, "cat-file", "--batch-check=%(objectsize)", input="".join(blob + "\n" for _, blob in entries))
    return {path: int(size) for (path, _), size in zip(entries, batch.split())}


def _allowlist(repo: Path, violations: list[str]) -> dict[str, int]:
    path = repo / ALLOWLIST
    if not path.is_file():
        return {}
    allowed = {}
    for name, entry in json.loads(path.read_text(encoding="utf-8")).get("files", {}).items():
        if not str(entry.get("reason", "")).strip() or not isinstance(entry.get("max_bytes"), int):
            violations.append(f"{ALLOWLIST}: {name} needs a reason and an integer max_bytes")
            continue
        allowed[name] = entry["max_bytes"]
    return allowed


def check(repo: Path) -> Report:
    repo = Path(repo)
    tag = _release_tag(repo)
    report = Report(base=tag)
    before, now = _base_sizes(repo, tag), _index_sizes(repo)
    added = sorted(path for path in now if path not in before)
    grown = sorted(((now[path] - before.get(path, 0), path) for path in now if now[path] > before.get(path, 0)), reverse=True)

    growth = sum(now.values()) - sum(before.values())
    if growth > BUDGET["net_growth_bytes"]:
        largest = ", ".join(f"{path} (+{_size(delta)})" for delta, path in grown[:_LISTED])
        report.violations.append(
            f"net growth {_size(growth)} since {tag} exceeds {_size(BUDGET['net_growth_bytes'])}; largest: {largest}"
        )
    if len(added) > BUDGET["added_files"]:
        directories: dict[str, int] = {}
        for path in added:
            parent = path.rsplit("/", 1)[0] if "/" in path else "."
            directories[parent] = directories.get(parent, 0) + 1
        busiest = ", ".join(f"{name} ({count})" for name, count in sorted(directories.items(), key=lambda item: -item[1])[:_LISTED])
        report.violations.append(
            f"{len(added)} files added since {tag} (limit {BUDGET['added_files']}); most in: {busiest}"
        )
    allowed = _allowlist(repo, report.violations)
    for path in sorted(set(allowed) - set(now)):
        report.violations.append(f"{ALLOWLIST}: {path} is not in the repository; remove or update the exception")
    for delta, path in grown:
        if now[path] > BUDGET["file_bytes"] and now[path] > allowed.get(path, 0):
            cap = f"listed cap {_size(allowed[path])}" if path in allowed else f"limit {_size(BUDGET['file_bytes'])}"
            report.violations.append(f"{path}: {_size(now[path])} exceeds the per-file {cap}; keep raw output in local/ and commit a manifest with its hash")
    for path in added:
        root = next((root for root in FROZEN_EVALUATION_ROOTS if path.startswith(root)), None)
        if root:
            report.violations.append(
                f"{path}: new file under the frozen evaluation root {root}; put new evaluation sources in evaluations/<version>/ and raw output in local/"
            )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check what this version adds to the repository.")
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    report = check(args.repo)
    if report.violations:
        print(f"repository evidence budget exceeded since {report.base}:", file=sys.stderr)
        for item in report.violations:
            print("  - " + item, file=sys.stderr)
        return 1
    print(f"within the repository evidence budget since {report.base}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
