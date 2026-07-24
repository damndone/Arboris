"""Gate 1 Task 1 — RunFamily as a first-class persisted identity (DEC-NB-002).

A RunFamily may exist before any Run exists, so its identity must not encode a
run id. These tests assert the identity *shape* and the absence of any run-derived
component, not merely that a record was written.
"""
import inspect
import re
from pathlib import Path

import pytest

from workbench.lineage.run_family import RunFamilyStore

_NEW_FAMILY_ID = re.compile(r"^run-family:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def test_new_family_id_is_a_uuid_and_encodes_no_run(tmp_path: Path) -> None:
    store = RunFamilyStore(tmp_path)

    family = store.create_family(project_id="proj_a", created_by="notebook", origin="notebook")

    assert _NEW_FAMILY_ID.match(family.run_family_id), family.run_family_id
    assert family.origin == "notebook"
    assert family.legacy_anchor_run_id is None
    assert family.project_id == "proj_a"
    assert family.created_at.endswith("+00:00")


def test_new_family_id_contains_no_run_id_substring(tmp_path: Path) -> None:
    """The failure this guards against: deriving the family id from a root run."""
    store = RunFamilyStore(tmp_path)
    run_id = "20260722_101500_000000_deadbeef"

    family = store.create_family(project_id="proj_a", created_by="notebook", origin="notebook")

    assert run_id not in family.run_family_id
    assert "legacy-family:" not in family.run_family_id


def test_create_family_signature_accepts_no_run_id(tmp_path: Path) -> None:
    """create_family() must be structurally incapable of deriving id from a run."""
    parameters = set(inspect.signature(RunFamilyStore.create_family).parameters)

    assert not {name for name in parameters if "run_id" in name or name == "run"} - {
        "legacy_anchor_run_id"
    }


def test_two_families_in_one_project_get_distinct_ids(tmp_path: Path) -> None:
    store = RunFamilyStore(tmp_path)

    first = store.create_family(project_id="proj_a", created_by="notebook", origin="notebook")
    second = store.create_family(project_id="proj_a", created_by="notebook", origin="notebook")

    assert first.run_family_id != second.run_family_id


def test_origin_is_required_and_validated(tmp_path: Path) -> None:
    store = RunFamilyStore(tmp_path)

    with pytest.raises(TypeError):
        store.create_family(project_id="proj_a", created_by="notebook")  # type: ignore[call-arg]

    with pytest.raises(ValueError):
        store.create_family(project_id="proj_a", created_by="notebook", origin="invented")


def test_family_round_trips_through_the_store(tmp_path: Path) -> None:
    store = RunFamilyStore(tmp_path)
    created = store.create_family(project_id="proj_a", created_by="notebook", origin="notebook")

    reread = RunFamilyStore(tmp_path).get(created.run_family_id)

    assert reread == created


def test_legacy_family_is_adopted_verbatim(tmp_path: Path) -> None:
    """Migration must keep the exact legacy string; no regeneration, no prefixing."""
    store = RunFamilyStore(tmp_path)
    legacy_id = "legacy-family:20260722_101500_000000_deadbeef"

    family = store.adopt_legacy_family(
        run_family_id=legacy_id,
        project_id="proj_a",
        created_by="migration",
        legacy_anchor_run_id="20260722_101500_000000_deadbeef",
    )

    assert family.run_family_id == legacy_id
    assert family.origin == "legacy_migration"
    assert family.legacy_anchor_run_id == "20260722_101500_000000_deadbeef"
    assert RunFamilyStore(tmp_path).get(legacy_id).run_family_id == legacy_id
