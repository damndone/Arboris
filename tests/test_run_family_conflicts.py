"""Gate 1 Task 4 — conflicts are reported, never silently repaired.

Two runs disagreeing about which analysis line they belong to is a data
integrity problem. Picking a winner on the read path would make the problem
invisible and, worse, would let a read rewrite lineage that other records point
at. Persisted always wins; the divergence is surfaced; nothing is mutated.
"""
import json
from pathlib import Path

import pytest

from workbench.lineage.run_family import (
    RunFamilyMismatch,
    RunFamilyStore,
    assert_run_in_family,
    bind_run_to_family,
    resolve_run_family,
    verify_project_families,
)


def _make_run(runs_dir: Path, run_id: str, *, rerun_of: str | None = None) -> Path:
    run_root = runs_dir / run_id
    run_root.mkdir(parents=True)
    (run_root / "run_inputs.json").write_text(
        json.dumps({"run_input_schema_version": 1, "rerun_of": rerun_of, "form": {}})
    )
    (run_root / "node_index.json").write_text(json.dumps({}))
    return run_root


@pytest.fixture()
def diverged(tmp_path: Path) -> Path:
    """A child bound to a family that disagrees with its ancestry."""
    project = tmp_path / "proj"
    runs = project / "runs"
    _make_run(runs, "run_001")
    child = _make_run(runs, "run_002", rerun_of="run_001")
    store = RunFamilyStore(project)
    store.adopt_legacy_family(
        run_family_id="legacy-family:run_999",
        project_id="proj",
        created_by="test",
        legacy_anchor_run_id="run_999",
    )
    bind_run_to_family(child, run_family_id="legacy-family:run_999", bound_by="test")
    return project


def test_persisted_wins_and_the_divergence_is_reported(diverged: Path) -> None:
    resolved = resolve_run_family(diverged, "run_002", check_consistency=True)

    assert resolved.run_family_id == "legacy-family:run_999"  # persisted, not derived
    assert resolved.derived_run_family_id == "legacy-family:run_001"
    assert resolved.consistency_error is not None
    assert "NOT rewritten" in resolved.consistency_error


def test_reading_a_diverged_run_mutates_nothing(diverged: Path) -> None:
    before = {
        path: path.read_bytes()
        for path in sorted(diverged.rglob("*"))
        if path.is_file()
    }

    resolve_run_family(diverged, "run_002", check_consistency=True)
    verify_project_families(diverged)

    after = {
        path: path.read_bytes()
        for path in sorted(diverged.rglob("*"))
        if path.is_file()
    }
    assert after == before


def test_verify_reports_every_diverged_run(diverged: Path) -> None:
    errors = verify_project_families(diverged)

    assert len(errors) == 1
    assert "run_002" in errors[0]


def test_cross_family_run_is_refused_as_an_active_head(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    runs = project / "runs"
    run_a = _make_run(runs, "run_001")
    run_b = _make_run(runs, "run_002")
    store = RunFamilyStore(project)
    family_a = store.create_family(project_id="proj", created_by="test", origin="notebook")
    family_b = store.create_family(project_id="proj", created_by="test", origin="notebook")
    bind_run_to_family(run_a, run_family_id=family_a.run_family_id, bound_by="test")
    bind_run_to_family(run_b, run_family_id=family_b.run_family_id, bound_by="test")

    assert_run_in_family(project, run_family_id=family_a.run_family_id, run_id="run_001")

    with pytest.raises(RunFamilyMismatch) as excinfo:
        assert_run_in_family(project, run_family_id=family_a.run_family_id, run_id="run_002")

    assert excinfo.value.code == "RUN_FAMILY_MISMATCH"
    assert family_a.run_family_id in str(excinfo.value)
    assert family_b.run_family_id in str(excinfo.value)
