from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

import pytest

from workbench.identity.contracts import LocalProfileIdentity, ProjectIdentityRevision
from workbench.identity.local_profile import (
    IdentityClientClaimError,
    IdentityCollisionError,
)
from workbench.identity.project_identity import ProjectIdentityStore
from workbench.identity.root import InvalidProjectRootError, ProjectRootRelocatedError


def test_project_identity_is_stable_across_restart_and_does_not_use_path_as_id(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project-a"
    project_root.mkdir()
    first_store = ProjectIdentityStore(authority_root)

    first = first_store.get_or_create(project_root)
    second = ProjectIdentityStore(authority_root).get_or_create(project_root)

    assert second == first
    assert first.revision == 1
    assert first.project_id != project_root.name
    assert first.project_id not in first.root_binding["canonical_path"]
    assert first.profile_id == LocalProfileIdentity(profile_id=first.profile_id).profile_id


def test_renamed_root_gets_a_new_revision_but_keeps_project_identity(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    original = tmp_path / "project-a"
    original.mkdir()
    store = ProjectIdentityStore(authority_root)
    first = store.get_or_create(original)
    first_record_bytes = store.read_record_bytes(first)

    moved = tmp_path / "project-moved"
    original.rename(moved)
    relocated = store.get_or_create(moved)

    assert relocated.project_id == first.project_id
    assert relocated.profile_id == first.profile_id
    assert relocated.revision == 2
    assert relocated.previous_revision == 1
    assert relocated.root_binding["canonical_path"] == str(moved)
    assert store.read_record_bytes(first) == first_record_bytes
    assert len(store.content_addressed_record_names()) == 2
    assert len(store.read_records_log_bytes().splitlines()) == 2


def test_different_directory_with_same_contents_does_not_reuse_identity(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    first_root = tmp_path / "project-a"
    second_root = tmp_path / "project-b"
    first_root.mkdir()
    second_root.mkdir()
    (first_root / "same.txt").write_text("same", encoding="utf-8")
    (second_root / "same.txt").write_text("same", encoding="utf-8")

    store = ProjectIdentityStore(authority_root)
    first = store.get_or_create(first_root)
    second = store.get_or_create(second_root)

    assert second.project_id != first.project_id
    assert second.root_binding["canonical_path"] != first.root_binding["canonical_path"]


def test_replacing_a_bound_path_with_a_different_directory_is_rejected(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project-a"
    project_root.mkdir()
    store = ProjectIdentityStore(authority_root)
    store.get_or_create(project_root)
    project_root.rmdir()
    project_root.mkdir()

    with pytest.raises(ProjectRootRelocatedError):
        store.get_or_create(project_root)


def test_project_identity_rejects_invalid_root_and_client_claims(tmp_path: Path) -> None:
    store = ProjectIdentityStore(tmp_path / "server-authority")
    with pytest.raises(InvalidProjectRootError):
        store.get_or_create(tmp_path / "missing")

    project_root = tmp_path / "project"
    project_root.mkdir()
    with pytest.raises(IdentityClientClaimError):
        store.get_or_create(project_root, project_id="project-client-forgery")
    with pytest.raises(IdentityClientClaimError):
        store.get_or_create(project_root, profile_id="profile-client-forgery")


def test_concurrent_first_project_creation_has_one_revision(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project"
    project_root.mkdir()

    def create() -> tuple[str, int]:
        identity = ProjectIdentityStore(authority_root).get_or_create(project_root)
        return identity.project_id, identity.revision

    with ThreadPoolExecutor(max_workers=12) as executor:
        identities = list(executor.map(lambda _index: create(), range(32)))

    assert set(identities) == {(identities[0][0], 1)}
    store = ProjectIdentityStore(authority_root)
    assert len(store.content_addressed_record_names()) == 1
    assert len(store.read_records_log_bytes().splitlines()) == 1


def test_same_filesystem_binding_with_two_project_ids_is_a_collision(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = ProjectIdentityStore(authority_root)
    first = store.get_or_create(project_root)
    forged_second = ProjectIdentityRevision(
        project_id="project_collision",
        profile_id=first.profile_id,
        revision=1,
        root_binding=first.root_binding,
    )
    store._persist(forged_second)  # type: ignore[attr-defined]

    with pytest.raises(IdentityCollisionError):
        store.get_or_create(project_root)
    with pytest.raises(IdentityCollisionError):
        store.get_current(project_root)
    with pytest.raises(IdentityCollisionError):
        store.get(first.project_id)


def test_project_storage_rejects_symlinked_records_directory(tmp_path: Path) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = ProjectIdentityStore(authority_root)
    store.get_or_create(project_root)
    outside = tmp_path / "outside"
    outside.mkdir()
    records_path = authority_root / "identity" / "projects" / "records"
    records_path.rename(tmp_path / "records.saved")
    records_path.symlink_to(outside, target_is_directory=True)

    with pytest.raises(Exception):
        ProjectIdentityStore(authority_root).get_current(project_root)


def test_project_creation_recovers_complete_record_after_log_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.identity.project_identity as module

    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = ProjectIdentityStore(authority_root)
    original_append = module._append_jsonl

    def fail_log(*args: object, **kwargs: object) -> None:
        raise OSError("injected log crash")

    monkeypatch.setattr(module, "_append_jsonl", fail_log)
    with pytest.raises(OSError, match="injected log crash"):
        store.get_or_create(project_root)
    monkeypatch.setattr(module, "_append_jsonl", original_append)

    recovered = ProjectIdentityStore(authority_root).get_or_create(project_root)
    assert recovered.revision == 1
    assert len(ProjectIdentityStore(authority_root).content_addressed_record_names()) == 1
    assert len(ProjectIdentityStore(authority_root).read_records_log_bytes().splitlines()) == 1
