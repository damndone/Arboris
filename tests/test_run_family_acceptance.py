"""Gate 1 Task 6 Step 1 — spec §9.1 acceptance, one test per numbered criterion.

Criterion 1 needs the Notebook object, which Gate 1 does not build. It is marked
`xfail(strict=True)` rather than quietly omitted: if a later gate makes it pass,
the suite fails until someone removes the marker, so the deferral cannot rot into
a silently skipped requirement.
"""
import json
from pathlib import Path

import pytest

from workbench.lineage.run_family import (
    RunFamilyMismatch,
    RunFamilyStore,
    assert_run_in_family,
    bind_run_to_family,
    ensure_run_family_binding,
    legacy_family_anchor,
    migrate_project_families,
    resolve_run_family,
)


def _make_run(runs_dir: Path, run_id: str, *, rerun_of: str | None = None) -> Path:
    run_root = runs_dir / run_id
    run_root.mkdir(parents=True)
    (run_root / "run_inputs.json").write_text(
        json.dumps({"run_input_schema_version": 1, "rerun_of": rerun_of, "form": {}})
    )
    (run_root / "node_index.json").write_text(json.dumps({}))
    return run_root


@pytest.mark.xfail(strict=True, reason="Gate 1 builds no Notebook object; criterion 1 is Gate 4")
def test_criterion_1_notebook_without_run_persists_family_and_null_head() -> None:
    from workbench.notebooks import Notebook  # type: ignore[import-not-found]  # noqa: F401

    raise AssertionError("unreachable until the Notebook object exists")


def test_criterion_2_new_run_inherits_the_declared_family(tmp_path: Path) -> None:
    """Stand-in for "first option execution": the caller declares the family."""
    project = tmp_path / "proj"
    runs = project / "runs"
    runs.mkdir(parents=True)
    store = RunFamilyStore(project)
    family = store.create_family(project_id="proj", created_by="notebook", origin="notebook")
    run_root = _make_run(runs, "run_001")

    bound = ensure_run_family_binding(
        project, run_root, rerun_of=None, created_by="notebook", run_family_id=family.run_family_id
    )

    assert bound == family.run_family_id
    assert resolve_run_family(project, "run_001").run_family_id == family.run_family_id


def test_criterion_3_rerun_child_keeps_the_same_family(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    runs = project / "runs"
    _make_run(runs, "run_001")
    migrate_project_families(project, created_by="test")
    parent_family = resolve_run_family(project, "run_001").run_family_id

    child_root = _make_run(runs, "run_002", rerun_of="run_001")
    bound = ensure_run_family_binding(
        project, child_root, rerun_of="run_001", created_by="rerun"
    )

    assert bound == parent_family
    assert resolve_run_family(project, "run_002").run_family_id == parent_family


def test_criterion_4_cross_family_head_is_refused(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    runs = project / "runs"
    store = RunFamilyStore(project)
    mine = store.create_family(project_id="proj", created_by="notebook", origin="notebook")
    theirs = store.create_family(project_id="proj", created_by="notebook", origin="notebook")
    bind_run_to_family(_make_run(runs, "run_001"), run_family_id=mine.run_family_id, bound_by="t")
    bind_run_to_family(_make_run(runs, "run_002"), run_family_id=theirs.run_family_id, bound_by="t")

    with pytest.raises(RunFamilyMismatch):
        assert_run_in_family(project, run_family_id=mine.run_family_id, run_id="run_002")


def test_criterion_5_migration_preserves_the_legacy_string(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    runs = project / "runs"
    _make_run(runs, "run_001")
    _make_run(runs, "run_002", rerun_of="run_001")
    before = {r: legacy_family_anchor(runs, r) for r in ("run_001", "run_002")}

    migrate_project_families(project, created_by="test")

    for run_id, expected in before.items():
        assert resolve_run_family(project, run_id).run_family_id == expected
    assert before["run_002"] == "legacy-family:run_001"


def test_criterion_6_conflict_prefers_persisted_and_reports(tmp_path: Path) -> None:
    project = tmp_path / "proj"
    runs = project / "runs"
    _make_run(runs, "run_001")
    child = _make_run(runs, "run_002", rerun_of="run_001")
    store = RunFamilyStore(project)
    store.adopt_legacy_family(
        run_family_id="legacy-family:run_777",
        project_id="proj",
        created_by="test",
        legacy_anchor_run_id="run_777",
    )
    bind_run_to_family(child, run_family_id="legacy-family:run_777", bound_by="test")
    before = (child / "run_family.json").read_bytes()

    resolved = resolve_run_family(project, "run_002", check_consistency=True)

    assert resolved.run_family_id == "legacy-family:run_777"
    assert resolved.derived_run_family_id == "legacy-family:run_001"
    assert resolved.consistency_error is not None
    assert (child / "run_family.json").read_bytes() == before
