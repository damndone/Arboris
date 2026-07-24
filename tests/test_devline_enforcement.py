"""E1 — the gate refuses feature changes not covered by a started devline.

This is the mechanism that would have stopped this very version's biggest
failure: I changed feature code with no devline, and nothing asked. The rule is
deliberately absence-triggered — it fires because a devline is *missing*, not
because one was already touched.
"""
import json
import subprocess
from pathlib import Path

import pytest

from workbench.development_control.enforcement import (
    feature_surface_paths,
    require_devline_for_changes,
)


def _start_line(repo: Path, line: str, affected: list[str]) -> None:
    obj = repo / "docs" / f"{line}-objective.md"
    obj.parent.mkdir(parents=True, exist_ok=True)
    obj.write_text(f"# {line}\n\nobjective for {line}.\n")
    baseline = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"]).decode().strip()
    args = [
        ".venv/bin/python", "scripts/devline_control.py", "start",
        "--line", line, "--objective", obj.relative_to(repo).as_posix(),
        "--baseline-sha", baseline,
    ]
    for p in affected:
        args += ["--affected-path", p]
    subprocess.run(args, cwd=repo, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A throwaway git repo with the control plane initialised."""
    root = tmp_path / "proj"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    # Bring the CLI + package into the throwaway repo by symlinking the real ones.
    real = Path(__file__).resolve().parents[1]
    (root / "scripts").mkdir()
    (root / "scripts" / "devline_control.py").symlink_to(real / "scripts" / "devline_control.py")
    (root / "backend").symlink_to(real / "backend")
    (root / ".venv").symlink_to(real / ".venv")
    (root / "seed.txt").write_text("seed\n")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "seed"], cwd=root, check=True)
    return root


def test_feature_surface_filters_to_product_code() -> None:
    changed = [
        "backend/workbench/agent/notebook/store.py",   # feature
        "frontend/src/notebook/OptionCard.tsx",        # feature
        "backend/workbench/development_control/promotion.py",  # governance, not feature
        "tests/test_notebook_store.py",                # test, not feature
        "docs/superpowers/plans/x.md",                 # doc, not feature
        ".agent/devlines/x/events.jsonl",              # control plane, not feature
    ]

    surface = feature_surface_paths(changed)

    assert surface == [
        "backend/workbench/agent/notebook/store.py",
        "frontend/src/notebook/OptionCard.tsx",
    ]


def test_a_feature_change_without_a_covering_devline_is_a_violation(repo: Path) -> None:
    violations = require_devline_for_changes(repo, ["backend/workbench/agent/notebook/store.py"])

    assert len(violations) == 1
    assert "backend/workbench/agent/notebook/store.py" in violations[0]
    assert "devline_control.py start" in violations[0]


def test_a_covering_devline_clears_the_change(repo: Path) -> None:
    _start_line(repo, "notebook-line", ["backend/workbench/agent/notebook/"])

    violations = require_devline_for_changes(repo, ["backend/workbench/agent/notebook/store.py"])

    assert violations == []


def test_coverage_requires_a_real_prefix_not_a_substring(repo: Path) -> None:
    """A devline claiming .../notebook/ must not accidentally cover .../notebook_evil/."""
    _start_line(repo, "notebook-line", ["backend/workbench/agent/notebook/"])

    violations = require_devline_for_changes(repo, ["backend/workbench/agent/notebook_evil/x.py"])

    assert len(violations) == 1


def test_non_feature_changes_never_require_a_devline(repo: Path) -> None:
    violations = require_devline_for_changes(
        repo,
        [
            "docs/superpowers/plans/x.md",
            "tests/test_notebook_store.py",
            "backend/workbench/development_control/promotion.py",
        ],
    )

    assert violations == []


def test_a_tampered_devline_does_not_count_as_coverage(repo: Path) -> None:
    """Coverage requires an intact event chain, not just a claiming manifest."""
    _start_line(repo, "notebook-line", ["backend/workbench/agent/notebook/"])
    events = repo / ".agent" / "devlines" / "notebook-line" / "events.jsonl"
    events.write_text(events.read_text() + '{"tampered": true}\n')

    violations = require_devline_for_changes(repo, ["backend/workbench/agent/notebook/store.py"])

    assert len(violations) == 1
    assert "notebook" in violations[0]
