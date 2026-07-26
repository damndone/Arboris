from concurrent.futures import ThreadPoolExecutor
import multiprocessing
from pathlib import Path
import shutil

import pytest

from workbench.identity.contracts import LocalProfileIdentity, ProjectIdentityRevision
from workbench.identity.local_profile import (
    IdentityClientClaimError,
    IdentityCollisionError,
    IdentityRecordCorruptError,
    IdentityStoreError,
    LocalProfileIdentityStore,
)
from workbench.identity.project_identity import ProjectIdentityStore
from workbench.identity.root import InvalidProjectRootError, ProjectRootRelocatedError


def _create_project_identity_in_process(
    authority_root: str, project_root: str, result_queue: object
) -> None:
    try:
        identity = ProjectIdentityStore(authority_root).get_or_create(Path(project_root))
        result_queue.put((identity.project_id, identity.revision, None))  # type: ignore[attr-defined]
    except BaseException as exc:  # pragma: no cover - assertion target below
        result_queue.put((None, None, repr(exc)))  # type: ignore[attr-defined]


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


def test_cross_process_first_project_creation_is_serialized_by_flock(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project"
    project_root.mkdir()
    context = multiprocessing.get_context("spawn")
    result_queue = context.Queue()
    processes = [
        context.Process(
            target=_create_project_identity_in_process,
            args=(str(authority_root), str(project_root), result_queue),
        )
        for _ in range(2)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=10)
        if process.is_alive():
            process.terminate()
            process.join()
        assert not process.is_alive()
        assert process.exitcode == 0

    results = [result_queue.get(timeout=5) for _ in processes]
    assert all(result[2] is None for result in results), results
    assert {result[:2] for result in results} == {(results[0][0], 1)}
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


@pytest.mark.parametrize("invalid_project_id", ["", None, 42])
def test_get_invalid_project_id_still_fails_closed_on_corrupt_storage(
    tmp_path: Path, invalid_project_id: object
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
        store.get(invalid_project_id)  # type: ignore[arg-type]


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

    with pytest.raises(IdentityRecordCorruptError):
        ProjectIdentityStore(authority_root).get_current(project_root)
    with pytest.raises(IdentityRecordCorruptError):
        ProjectIdentityStore(authority_root).content_addressed_record_names()


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


def test_project_store_rejects_a_profile_store_from_another_authority(
    tmp_path: Path,
) -> None:
    with pytest.raises(IdentityStoreError):
        ProjectIdentityStore(
            tmp_path / "project-authority",
            profile_store=LocalProfileIdentityStore(tmp_path / "other-authority"),
        )


def test_project_get_current_is_read_only_by_default(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = ProjectIdentityStore(authority_root)
    identity = store.get_or_create(project_root)
    log_path = authority_root / "identity" / "projects" / "records.jsonl"
    log_bytes = log_path.read_bytes()
    log_path.unlink()

    with pytest.raises(IdentityRecordCorruptError):
        ProjectIdentityStore(authority_root).get_current(project_root)
    assert not log_path.exists()
    assert ProjectIdentityStore(authority_root).get_current(
        project_root, recover=True
    ) == identity
    assert log_path.read_bytes() == log_bytes


def test_project_public_raw_reads_fail_closed_on_corrupt_record(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = ProjectIdentityStore(authority_root)
    revision = store.get_or_create(project_root)
    record_path = (
        authority_root
        / "identity"
        / "projects"
        / "records"
        / f"{revision.content_hash}.json"
    )
    record_path.write_bytes(b"{}\n")

    with pytest.raises(IdentityRecordCorruptError):
        store.read_record_bytes(revision)
    with pytest.raises(IdentityRecordCorruptError):
        store.read_records_log_bytes()
    with pytest.raises(IdentityRecordCorruptError):
        store.content_addressed_record_names()


def test_project_public_raw_log_rejects_noncanonical_json(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = ProjectIdentityStore(authority_root)
    store.get_or_create(project_root)
    log_path = authority_root / "identity" / "projects" / "records.jsonl"
    log_path.write_bytes(b" " + store.read_records_log_bytes())

    with pytest.raises(IdentityRecordCorruptError):
        store.read_records_log_bytes()


def test_project_public_raw_reads_reject_invalid_orphan_record(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    project_root = tmp_path / "project"
    project_root.mkdir()
    store = ProjectIdentityStore(authority_root)
    store.get_or_create(project_root)
    orphan_path = (
        authority_root
        / "identity"
        / "projects"
        / "records"
        / ("0" * 64 + ".json")
    )
    orphan_path.write_bytes(b"{}\n")

    with pytest.raises(IdentityRecordCorruptError):
        store.content_addressed_record_names()
