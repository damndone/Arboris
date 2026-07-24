"""Gate 1 Task 3 — migrating existing runs must not change what anyone can see.

The fixture under tests/fixtures/run_family is a byte copy of two real runs from
the v1.8.0 machine acceptance (a root ARMA-GARCH run and a child forked at
`stage:ts-mean-selection`). Hand-written fixtures were ruled out by the plan:
they agree with whatever the implementation assumes, which is exactly the
failure mode this task is guarding against.
"""
import shutil
from pathlib import Path

import pytest

from workbench.lineage.run_family import (
    RunFamilyStore,
    legacy_family_anchor,
    migrate_project_families,
    resolve_run_family,
)

FIXTURE = Path(__file__).parent / "fixtures" / "run_family"
ROOT_RUN = "20260722_043309_451505_f0d8672b"
CHILD_RUN = "20260722_043812_924307_874cc62b"


@pytest.fixture()
def project(tmp_path: Path) -> Path:
    project_root = tmp_path / "vix-dofile-repro"
    runs = project_root / "runs"
    runs.mkdir(parents=True)
    for run_dir in sorted(FIXTURE.iterdir()):
        shutil.copytree(run_dir, runs / run_dir.name)
    return project_root


def test_migration_preserves_the_visible_id_byte_for_byte(project: Path) -> None:
    runs = project / "runs"
    before = {
        run_id: legacy_family_anchor(runs, run_id) for run_id in (ROOT_RUN, CHILD_RUN)
    }

    migrate_project_families(project, created_by="test")

    for run_id, expected in before.items():
        after = resolve_run_family(project, run_id).run_family_id
        assert after == expected  # byte-for-byte, not startswith
        assert resolve_run_family(project, run_id).source == "persisted"


def test_whole_family_shares_one_id_after_migration(project: Path) -> None:
    migrate_project_families(project, created_by="test")

    root = resolve_run_family(project, ROOT_RUN).run_family_id
    child = resolve_run_family(project, CHILD_RUN).run_family_id

    assert root == child == f"legacy-family:{ROOT_RUN}"


def test_migration_records_the_family_with_its_anchor(project: Path) -> None:
    migrate_project_families(project, created_by="test")

    families = RunFamilyStore(project).list_families()

    assert len(families) == 1
    family = families[0]
    assert family.run_family_id == f"legacy-family:{ROOT_RUN}"
    assert family.origin == "legacy_migration"
    assert family.legacy_anchor_run_id == ROOT_RUN
    assert family.project_id == "vix-dofile-repro"


def test_migration_is_idempotent(project: Path) -> None:
    first = migrate_project_families(project, created_by="test")
    snapshot = _snapshot(project)

    second = migrate_project_families(project, created_by="test")

    assert second["migrated_run_ids"] == first["migrated_run_ids"]
    assert second["created_families"] == []
    assert _snapshot(project) == snapshot  # no second record, no changed id


def test_migration_does_not_touch_run_payloads(project: Path) -> None:
    """Migration adds a membership file; it must not rewrite run evidence."""
    runs = project / "runs"
    before = {
        path.relative_to(runs): path.read_bytes()
        for path in sorted(runs.rglob("*.json"))
    }

    migrate_project_families(project, created_by="test")

    after = {
        path.relative_to(runs): path.read_bytes()
        for path in sorted(runs.rglob("*.json"))
        if path.name != "run_family.json"
    }
    assert after == before


def _snapshot(project: Path) -> dict[str, str]:
    """Family ids only — record timestamps legitimately differ between passes."""
    snapshot: dict[str, str] = {}
    runs = project / "runs"
    for run_dir in sorted(runs.iterdir()):
        snapshot[run_dir.name] = resolve_run_family(project, run_dir.name).run_family_id
    for family in RunFamilyStore(project).list_families():
        snapshot[f"family::{family.run_family_id}"] = str(family.legacy_anchor_run_id)
    return snapshot
