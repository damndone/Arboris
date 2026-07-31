"""Graph-first Notebook projection identity is durable and source-bound."""
from __future__ import annotations

import gc
import json
import time
import weakref
from pathlib import Path
from threading import Barrier, Lock, Thread

import pytest

from workbench.agent.notebook import NotebookService
from workbench.agent.notebook import service as notebook_service
from workbench.agent.notebook import store as notebook_store
from workbench.agent.notebook.store import Notebook, NotebookStore
from workbench.lineage.run_family import (
    RunFamilyStore,
    bind_run_to_family,
    migrate_project_families,
    resolve_run_family,
)
from workbench.lineage.upload_store import store_upload_bytes

from tests.test_notebook_support import make_project, make_run


def _dataset_ref(sha256: str) -> dict[str, object]:
    return {
        "kind": "dataset",
        "upload_sha256": sha256,
        "filename": "observations.csv",
        "sheet_names": [],
    }


def test_default_run_projection_is_idempotent_for_one_persisted_source(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    make_run(project, "run_001")
    migrate_project_families(project, created_by="test")
    service = NotebookService(project)

    assert callable(getattr(service, "ensure_default_projection", None))
    first = service.ensure_default_projection(from_run_id="run_001", created_by="ui")
    second = service.ensure_default_projection(from_run_id="run_001", created_by="ui")

    assert second.notebook_id == first.notebook_id
    assert first.run_family_id == resolve_run_family(project, "run_001").run_family_id
    assert first.projection_key == f"default-projection:{first.run_family_id}"
    assert first.projection_source is not None
    assert first.projection_source.to_dict() == {"kind": "run", "run_id": "run_001"}
    assert first.active_head_run_id == "run_001"
    assert first.focused_run_id == "run_001"

    make_run(project, "run_002", rerun_of="run_001")
    migrate_project_families(project, created_by="test")
    with pytest.raises(ValueError, match="projection"):
        service.ensure_default_projection(from_run_id="run_002", created_by="ui")

    assert [item.notebook_id for item in service.list_notebooks()] == [first.notebook_id]


def test_run_projection_reuses_the_unique_family_default_before_project_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(tmp_path)
    run_root = make_run(project, "run_001")
    family = RunFamilyStore(project).create_family(
        project_id=project.name,
        created_by="test",
        origin="notebook",
    )
    bind_run_to_family(run_root, run_family_id=family.run_family_id, bound_by="test")
    existing = Notebook(
        notebook_id="nb_existing",
        project_id=project.name,
        run_family_id=family.run_family_id,
        title="Existing analysis",
        created_by="test",
        created_at="2026-07-30T00:00:00+00:00",
        projection_key=f"default-projection:{family.run_family_id}",
        projection_source=notebook_store.ProjectionSource.from_dict(_dataset_ref("upload_001")),
    )
    service = NotebookService(project)
    service.store.create_notebook(existing)

    def migration_must_not_run(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("a persisted family default must be reused before migration")

    monkeypatch.setattr(notebook_service, "migrate_project_families", migration_must_not_run)

    resolved = service.ensure_default_projection(from_run_id="run_001", created_by="ui")

    assert resolved.notebook_id == existing.notebook_id
    assert resolved.projection_source == existing.projection_source


def test_post_cutover_unbound_run_fails_without_legacy_fallback(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    migrate_project_families(project, created_by="test")
    make_run(project, "run_unbound")
    service = NotebookService(project)

    with pytest.raises(Exception) as excinfo:
        service.ensure_default_projection(from_run_id="run_unbound", created_by="ui")

    assert "persisted run family" in str(excinfo.value)
    assert service.list_notebooks() == []
    assert RunFamilyStore(project, create=False).list_families() == []


def test_verified_dataset_projection_creates_one_persisted_prerun_family(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sha256 = store_upload_bytes(
        project, b"outcome,predictor\n1,2\n", filename="observations.csv"
    )
    service = NotebookService(project)

    projection = service.ensure_default_projection(dataset=_dataset_ref(sha256), created_by="ui")
    repeated = service.ensure_default_projection(dataset=_dataset_ref(sha256), created_by="ui")

    assert repeated.notebook_id == projection.notebook_id
    assert projection.projection_key == f"default-projection:{projection.run_family_id}"
    assert projection.projection_source is not None
    assert projection.projection_source.to_dict() == _dataset_ref(sha256)
    assert projection.active_head_run_id is None
    assert projection.focused_run_id is None
    assert list((project / "runs").iterdir()) == []
    families = RunFamilyStore(project, create=False).list_families()
    assert [family.run_family_id for family in families] == [projection.run_family_id]
    assert families[0].origin == "notebook"


def test_dataset_default_projection_is_atomic_across_store_instances(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(tmp_path)
    sha256 = store_upload_bytes(
        project, b"outcome,predictor\n1,2\n", filename="observations.csv"
    )
    original_create_family = RunFamilyStore.create_family

    def delayed_create_family(self: RunFamilyStore, **kwargs: object):
        time.sleep(0.05)
        return original_create_family(self, **kwargs)

    monkeypatch.setattr(RunFamilyStore, "create_family", delayed_create_family)
    start = Barrier(2)
    notebook_ids: list[str] = []
    errors: list[BaseException] = []

    def ensure_projection() -> None:
        service = NotebookService(project)
        try:
            start.wait(timeout=2)
            notebook_ids.append(
                service.ensure_default_projection(dataset=_dataset_ref(sha256), created_by="ui").notebook_id
            )
        except BaseException as error:
            errors.append(error)

    threads = [Thread(target=ensure_projection), Thread(target=ensure_projection)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert not [thread for thread in threads if thread.is_alive()]
    assert not errors, errors
    assert len(set(notebook_ids)) == 1
    assert len(NotebookService(project).list_notebooks()) == 1
    assert len(RunFamilyStore(project, create=False).list_families()) == 1


def test_run_default_projection_is_atomic_across_services_during_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project = make_project(tmp_path)
    make_run(project, "run_001")
    original_migrate = notebook_service.migrate_project_families
    migration_count = 0
    migration_count_lock = Lock()

    def delayed_migrate(*args: object, **kwargs: object):
        nonlocal migration_count
        with migration_count_lock:
            migration_count += 1
        time.sleep(0.05)
        return original_migrate(*args, **kwargs)

    monkeypatch.setattr(notebook_service, "migrate_project_families", delayed_migrate)
    start = Barrier(2)
    notebook_ids: list[str] = []
    errors: list[BaseException] = []

    def ensure_projection() -> None:
        service = NotebookService(project)
        try:
            start.wait(timeout=2)
            notebook_ids.append(
                service.ensure_default_projection(from_run_id="run_001", created_by="ui").notebook_id
            )
        except BaseException as error:
            errors.append(error)

    threads = [Thread(target=ensure_projection), Thread(target=ensure_projection)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=2)

    assert not [thread for thread in threads if thread.is_alive()]
    assert not errors, errors
    assert migration_count == 1
    assert len(set(notebook_ids)) == 1
    notebook = NotebookService(project).list_notebooks()[0]
    resolved = resolve_run_family(project, "run_001", check_consistency=True)
    assert resolved.source == "persisted"
    assert notebook.run_family_id == resolved.run_family_id
    assert [family.run_family_id for family in RunFamilyStore(project, create=False).list_families()] == [
        resolved.run_family_id
    ]


def test_project_lock_holder_is_shared_and_reclaimable(tmp_path: Path) -> None:
    first = NotebookStore(tmp_path)
    second = NotebookStore(tmp_path)
    holder = getattr(first, "_lock_holder", None)

    assert holder is not None
    assert holder is getattr(second, "_lock_holder", None)
    holder_ref = weakref.ref(holder)
    del first
    del second
    del holder
    gc.collect()

    assert holder_ref() is None


def test_malformed_same_source_default_key_fails_closed(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    sha256 = store_upload_bytes(
        project, b"outcome,predictor\n1,2\n", filename="observations.csv"
    )
    family = RunFamilyStore(project).create_family(
        project_id=project.name,
        created_by="test",
        origin="notebook",
    )
    malformed = Notebook(
        notebook_id="nb_malformed",
        project_id=project.name,
        run_family_id=family.run_family_id,
        title="Malformed",
        created_by="test",
        created_at="2026-07-23T00:00:00+00:00",
    ).to_dict()
    malformed["projection_key"] = f"default-projection:{family.run_family_id}-wrong"
    malformed["projection_source"] = _dataset_ref(sha256)
    malformed_path = project / "notebooks" / "nb_malformed" / "notebook.jsonl"
    malformed_path.parent.mkdir(parents=True)
    malformed_path.write_text(json.dumps(malformed) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="projection_key"):
        NotebookService(project).ensure_default_projection(
            dataset=_dataset_ref(sha256), created_by="ui"
        )

    assert len(RunFamilyStore(project, create=False).list_families()) == 1


def test_explicit_and_legacy_notebooks_coexist_without_rebinding(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    make_run(project, "run_001")
    service = NotebookService(project)
    explicit = service.create_notebook(title="Explicit", created_by="ui", from_run_id="run_001")

    legacy = Notebook(
        notebook_id="nb_legacy",
        project_id=project.name,
        run_family_id=explicit.run_family_id,
        title="Legacy",
        created_by="old-ui",
        created_at="2026-07-23T00:00:00+00:00",
    ).to_dict()
    legacy.pop("projection_key", None)
    legacy.pop("projection_source", None)
    legacy.pop("supersedes_notebook_id", None)
    legacy_path = project / "notebooks" / "nb_legacy" / "notebook.jsonl"
    legacy_path.parent.mkdir(parents=True)
    legacy_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")

    default = service.ensure_default_projection(from_run_id="run_001", created_by="ui")
    reloaded_legacy = service.get_notebook("nb_legacy")

    assert {item.notebook_id for item in service.list_notebooks()} == {
        explicit.notebook_id,
        "nb_legacy",
        default.notebook_id,
    }
    assert default.notebook_id not in {explicit.notebook_id, "nb_legacy"}
    assert explicit.projection_key is None
    assert reloaded_legacy.projection_key is None
    assert reloaded_legacy.projection_source is None
    assert reloaded_legacy.run_family_id == explicit.run_family_id


def test_invalid_dataset_or_source_xor_leaves_no_projection_state(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    service = NotebookService(project)
    missing = _dataset_ref("0" * 64)

    with pytest.raises(FileNotFoundError):
        service.ensure_default_projection(dataset=missing, created_by="ui")
    with pytest.raises(ValueError, match="exactly one"):
        service.ensure_default_projection(created_by="ui")
    with pytest.raises(ValueError, match="exactly one"):
        service.ensure_default_projection(
            from_run_id="run_001", dataset=missing, created_by="ui"
        )
    with pytest.raises(ValueError, match="projection_source"):
        service.ensure_default_projection(
            dataset={**missing, "run_id": "run_001"}, created_by="ui"
        )

    assert service.list_notebooks() == []
    assert RunFamilyStore(project, create=False).list_families() == []


def test_projection_source_parser_is_strict_and_normalizes_absent_sheet_names() -> None:
    projection_source = getattr(notebook_store, "ProjectionSource", None)

    assert projection_source is not None
    run = projection_source.from_dict({"kind": "run", "run_id": "run_001"})
    dataset = projection_source.from_dict(
        {
            "kind": "dataset",
            "upload_sha256": "abc123",
            "filename": "observations.csv",
        }
    )

    assert run.to_dict() == {"kind": "run", "run_id": "run_001"}
    assert dataset.sheet_names == ()
    assert dataset.to_dict() == {
        "kind": "dataset",
        "upload_sha256": "abc123",
        "filename": "observations.csv",
        "sheet_names": [],
    }

    for invalid in (
        {"kind": "run", "run_id": "run_001", "upload_sha256": "abc123"},
        {"kind": "run", "run_id": "../run_001"},
        {
            "kind": "dataset",
            "upload_sha256": "abc123",
            "filename": "../observations.csv",
            "sheet_names": [],
        },
        {
            "kind": "dataset",
            "upload_sha256": "abc123",
            "filename": "observations.csv",
            "sheet_names": ["Sheet1", ""],
        },
        {
            "kind": "dataset",
            "upload_sha256": "abc123",
            "filename": "observations.csv",
            "sheet_names": None,
        },
    ):
        with pytest.raises(ValueError):
            projection_source.from_dict(invalid)


def test_default_projection_key_source_collision_fails_closed(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    make_run(project, "run_001")
    migrate_project_families(project, created_by="test")
    family_id = resolve_run_family(project, "run_001", check_consistency=True).run_family_id
    collision = Notebook(
        notebook_id="nb_collision",
        project_id=project.name,
        run_family_id=family_id,
        title="Collision",
        created_by="test",
        created_at="2026-07-23T00:00:00+00:00",
    ).to_dict()
    collision["projection_key"] = f"default-projection:{family_id}"
    collision["projection_source"] = _dataset_ref("collision-upload")
    collision_path = project / "notebooks" / "nb_collision" / "notebook.jsonl"
    collision_path.parent.mkdir(parents=True)
    collision_path.write_text(json.dumps(collision) + "\n", encoding="utf-8")

    service = NotebookService(project)
    with pytest.raises(ValueError, match="projection key"):
        service.ensure_default_projection(from_run_id="run_001", created_by="ui")

    assert [item.notebook_id for item in service.list_notebooks()] == ["nb_collision"]
    assert [
        family.run_family_id for family in RunFamilyStore(project, create=False).list_families()
    ] == [family_id]
