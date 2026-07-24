"""Gate 2 Task 4 — same inputs, same bytes (spec §12.4).

Determinism is not a nicety here: `generation_context_hash` is what a stored
option revision pins. If compiling twice produced two hashes, every option would
appear to have been generated against a context that no longer exists, and no
trace could ever be replayed.
"""
import json
import shutil
from pathlib import Path

import pytest

from workbench.agent.context_compiler import (
    compile_notebook_planning_context,
    freshness_dependency_fingerprint,
    generation_context_hash,
)

FIXTURE = Path(__file__).parent / "fixtures" / "run_family"
ROOT_RUN = "20260722_043309_451505_f0d8672b"


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    project_root = tmp_path / "vix-dofile-repro"
    runs = project_root / "runs"
    runs.mkdir(parents=True)
    for run_dir in sorted(FIXTURE.iterdir()):
        shutil.copytree(run_dir, runs / run_dir.name)
    return project_root


def _compile(project: Path, **overrides):
    kwargs = dict(
        notebook_id="nb_0001",
        run_family_id="run-family:11111111-1111-4111-8111-111111111111",
        active_head_run_id=ROOT_RUN,
        analysis_contract={"objective": "VIX volatility", "revision": 3},
        user_focus={"selected_text": "persistent conditional variance"},
    )
    kwargs.update(overrides)
    return compile_notebook_planning_context(project, **kwargs)


def test_two_compilations_are_byte_identical(project: Path) -> None:
    first = _compile(project)
    second = _compile(project)

    assert first.canonical_json() == second.canonical_json()
    assert generation_context_hash(first) == generation_context_hash(second)
    assert freshness_dependency_fingerprint(first) == freshness_dependency_fingerprint(second)


def test_context_id_and_timestamp_still_differ(project: Path) -> None:
    """The bundles are interchangeable; the compilation events are not."""
    first = _compile(project)
    second = _compile(project)

    assert first.context_id != second.context_id


def test_moving_the_project_does_not_change_the_hash(project: Path, tmp_path: Path) -> None:
    """No absolute path may enter the payload."""
    original = generation_context_hash(_compile(project))

    moved = tmp_path / "somewhere" / "else" / "vix-dofile-repro"
    moved.parent.mkdir(parents=True)
    shutil.copytree(project, moved)

    assert generation_context_hash(_compile(moved)) == original


def test_no_absolute_path_appears_in_the_payload(project: Path) -> None:
    payload = _compile(project).canonical_json()

    assert str(project) not in payload
    assert str(project.parent) not in payload
    assert "/private/var" not in payload
    assert "/Users/" not in payload


def test_reordering_the_sources_on_disk_changes_nothing(project: Path) -> None:
    """Key order inside the source files must not leak into the bundle."""
    original = generation_context_hash(_compile(project))

    shuffled = project.parent / "shuffled"
    shutil.copytree(project, shuffled)
    graph_path = shuffled / "runs" / ROOT_RUN / "graph.json"
    graph = json.loads(graph_path.read_text())
    graph["nodes"] = dict(reversed(list(graph["nodes"].items())))
    graph_path.write_text(json.dumps(graph))

    assert generation_context_hash(_compile(shuffled)) == original
