"""Gate 1 Task 2 — run <-> family membership is persisted, never re-derived.

The load-bearing test here is `test_post_cutover_run_without_family_is_refused`:
once a project has been migrated, an unbound run MUST fail loudly instead of
quietly falling back to ancestry scanning. If that fallback stays reachable on
the write path, every new run keeps deriving its family and the migration was
pointless.
"""
import json
from pathlib import Path

import pytest

from workbench.lineage import run_family as run_family_module
from workbench.lineage.run_family import (
    RunFamilyRequired,
    RunFamilyStore,
    bind_run_to_family,
    read_run_family_membership,
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


def test_membership_round_trips_byte_for_byte(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_root = _make_run(runs, "run_001")
    store = RunFamilyStore(tmp_path)
    family = store.create_family(project_id="p", created_by="notebook", origin="notebook")

    bind_run_to_family(run_root, run_family_id=family.run_family_id, bound_by="create_run")

    membership = read_run_family_membership(run_root)
    assert membership is not None
    assert membership["run_family_id"] == family.run_family_id
    assert membership["run_id"] == "run_001"
    assert membership["bound_by"] == "create_run"


def test_persisted_read_never_scans_ancestry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A bound run must resolve without touching the rerun forest at all."""
    runs = tmp_path / "runs"
    run_root = _make_run(runs, "run_001")
    store = RunFamilyStore(tmp_path)
    family = store.create_family(project_id="p", created_by="notebook", origin="notebook")
    bind_run_to_family(run_root, run_family_id=family.run_family_id, bound_by="create_run")

    def _explode(*args: object, **kwargs: object) -> str:
        raise AssertionError("resolve must not fall back to ancestry for a bound run")

    monkeypatch.setattr(run_family_module, "legacy_family_anchor", _explode)

    resolved = resolve_run_family(tmp_path, "run_001")

    assert resolved.run_family_id == family.run_family_id
    assert resolved.source == "persisted"
    assert resolved.warning is None


def test_unmigrated_legacy_run_falls_back_with_a_warning(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _make_run(runs, "run_001")
    _make_run(runs, "run_002", rerun_of="run_001")

    resolved = resolve_run_family(tmp_path, "run_002")

    assert resolved.run_family_id == "legacy-family:run_001"
    assert resolved.source == "legacy_fallback"
    assert resolved.warning is not None


def test_post_cutover_run_without_family_is_refused(tmp_path: Path) -> None:
    """The 命门: fallback must not become a write path for newly created runs."""
    runs = tmp_path / "runs"
    old_run = _make_run(runs, "run_001")
    store = RunFamilyStore(tmp_path)
    store.adopt_legacy_family(
        run_family_id="legacy-family:run_001",
        project_id="p",
        created_by="migration",
        legacy_anchor_run_id="run_001",
    )
    bind_run_to_family(old_run, run_family_id="legacy-family:run_001", bound_by="legacy_migration")
    store.mark_migrated(["run_001"])

    # A run created after the cutover that declared no family.
    _make_run(runs, "run_002", rerun_of="run_001")

    with pytest.raises(RunFamilyRequired) as excinfo:
        resolve_run_family(tmp_path, "run_002")

    assert excinfo.value.code == "RUN_FAMILY_REQUIRED"
    assert "run_002" in str(excinfo.value)


def test_migrated_run_still_resolves_after_cutover(tmp_path: Path) -> None:
    """Cutover must not turn already-migrated runs into errors."""
    runs = tmp_path / "runs"
    old_run = _make_run(runs, "run_001")
    store = RunFamilyStore(tmp_path)
    store.adopt_legacy_family(
        run_family_id="legacy-family:run_001",
        project_id="p",
        created_by="migration",
        legacy_anchor_run_id="run_001",
    )
    bind_run_to_family(old_run, run_family_id="legacy-family:run_001", bound_by="legacy_migration")
    store.mark_migrated(["run_001"])

    resolved = resolve_run_family(tmp_path, "run_001")

    assert resolved.run_family_id == "legacy-family:run_001"
    assert resolved.source == "persisted"


def test_binding_is_immutable(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    run_root = _make_run(runs, "run_001")
    bind_run_to_family(run_root, run_family_id="legacy-family:run_001", bound_by="create_run")

    with pytest.raises(ValueError):
        bind_run_to_family(run_root, run_family_id="run-family:other", bound_by="create_run")

    # Rebinding to the same family is a no-op, not an error (idempotent migration).
    bind_run_to_family(run_root, run_family_id="legacy-family:run_001", bound_by="create_run")
    assert read_run_family_membership(run_root)["run_family_id"] == "legacy-family:run_001"
