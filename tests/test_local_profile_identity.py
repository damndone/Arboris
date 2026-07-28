from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import shutil
from threading import Thread

import pytest

from workbench.identity.local_profile import (
    IdentityClientClaimError,
    IdentityCollisionError,
    IdentityRecordCorruptError,
    IdentityStoreError,
    LocalProfileIdentityStore,
)


def test_local_profile_is_stable_across_store_restart_and_content_addressed(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    first_store = LocalProfileIdentityStore(authority_root)
    first = first_store.get_or_create()
    record_bytes_before = first_store.read_record_bytes(first)
    index_bytes_before = first_store.read_records_log_bytes()

    second = LocalProfileIdentityStore(authority_root).get_or_create()

    assert second == first
    assert first_store.record_name(first) == first.content_hash + ".json"
    assert record_bytes_before == first_store.read_record_bytes(first)
    assert index_bytes_before == first_store.read_records_log_bytes()


def test_local_profile_creation_rejects_client_identity_claims(
    tmp_path: Path,
) -> None:
    store = LocalProfileIdentityStore(tmp_path / "server-authority")

    with pytest.raises(IdentityClientClaimError):
        store.get_or_create(profile_id="profile-client-forgery")

    with pytest.raises(IdentityClientClaimError):
        store.get_or_create(client_profile_id="profile-client-forgery")


def test_default_reads_do_not_create_an_empty_authority(tmp_path: Path) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)

    assert store.get_current() is None
    assert store.read_records_log_bytes() == b""
    assert store.content_addressed_record_names() == ()
    assert not authority_root.exists()


def test_concurrent_first_creation_has_one_server_issued_profile_record(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"

    def create() -> str:
        return LocalProfileIdentityStore(authority_root).get_or_create().profile_id

    with ThreadPoolExecutor(max_workers=12) as executor:
        profile_ids = list(executor.map(lambda _index: create(), range(32)))

    assert set(profile_ids) == {profile_ids[0]}
    store = LocalProfileIdentityStore(authority_root)
    assert len(store.content_addressed_record_names()) == 1
    assert len(store.read_records_log_bytes().splitlines()) == 1


def test_profile_storage_rejects_symlinked_records_and_pointer(tmp_path: Path) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    identity = store.get_or_create()
    records_path = authority_root / "identity" / "local_profile" / "records"
    current_path = authority_root / "identity" / "local_profile" / "current.json"

    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.copy2(current_path, outside / "current.json")
    records_path.rename(tmp_path / "records.saved")
    records_path.symlink_to(outside, target_is_directory=True)
    with pytest.raises(IdentityRecordCorruptError):
        LocalProfileIdentityStore(authority_root).get_or_create()

    records_path.unlink()
    (tmp_path / "records.saved").rename(records_path)
    record_path = records_path / f"{identity.content_hash}.json"
    record_path.write_bytes(store.read_record_bytes(identity))
    pointer = current_path
    pointer.unlink()
    pointer.symlink_to(outside / "current.json")
    with pytest.raises(IdentityRecordCorruptError):
        LocalProfileIdentityStore(authority_root).get_or_create()


def test_profile_storage_rejects_a_symlinked_content_record(tmp_path: Path) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    identity = store.get_or_create()
    records_path = authority_root / "identity" / "local_profile" / "records"
    outside = tmp_path / "outside-record.json"
    outside.write_bytes(store.read_record_bytes(identity))
    extra_record = records_path / ("0" * 64 + ".json")
    extra_record.symlink_to(outside)

    with pytest.raises(IdentityRecordCorruptError):
        store.content_addressed_record_names()


def test_profile_creation_recovers_a_complete_record_after_pointer_fault(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.identity.local_profile as module

    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    original_pointer = module._create_pointer

    def fail_pointer(*args: object, **kwargs: object) -> bool:
        raise OSError("injected pointer crash")

    monkeypatch.setattr(module, "_create_pointer", fail_pointer)
    with pytest.raises(OSError, match="injected pointer crash"):
        store.get_or_create()
    monkeypatch.setattr(module, "_create_pointer", original_pointer)

    recovered = LocalProfileIdentityStore(authority_root).get_or_create()
    assert recovered.profile_id.startswith("profile_")
    assert len(LocalProfileIdentityStore(authority_root).content_addressed_record_names()) == 1


def test_profile_creation_rejects_a_partial_derived_pointer(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    identity = store.get_or_create()
    current_path = authority_root / "identity" / "local_profile" / "current.json"
    current_path.write_bytes(b'{"identity_hash":')

    with pytest.raises(IdentityRecordCorruptError):
        LocalProfileIdentityStore(authority_root).get_or_create()
    assert current_path.read_bytes() == b'{"identity_hash":'


def test_profile_creation_rejects_noncanonical_derived_pointer(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    store.get_or_create()
    current_path = authority_root / "identity" / "local_profile" / "current.json"
    canonical = current_path.read_bytes()
    current_path.write_bytes(b" " + canonical)

    with pytest.raises(IdentityRecordCorruptError):
        LocalProfileIdentityStore(authority_root).get_or_create()
    assert current_path.read_bytes() == b" " + canonical


def test_profile_get_current_is_read_only_by_default(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    identity = store.get_or_create()
    current_path = authority_root / "identity" / "local_profile" / "current.json"
    current_path.unlink()

    with pytest.raises(IdentityRecordCorruptError):
        LocalProfileIdentityStore(authority_root).get_current()
    assert not current_path.exists()
    assert LocalProfileIdentityStore(authority_root).get_current(recover=True) == identity


def test_profile_store_reports_unsupported_host_without_fcntl(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import workbench.identity.local_profile as module

    monkeypatch.setattr(module, "fcntl", None)
    with pytest.raises(IdentityStoreError, match="unsupported"):
        LocalProfileIdentityStore(tmp_path / "server-authority").get_or_create()


@pytest.mark.parametrize("special_file", ["current", "log", "record"])
def test_profile_storage_rejects_fifo_without_blocking(
    tmp_path: Path, special_file: str
) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    identity = store.get_or_create()
    paths = {
        "current": authority_root / "identity" / "local_profile" / "current.json",
        "log": authority_root / "identity" / "local_profile" / "records.jsonl",
        "record": authority_root
        / "identity"
        / "local_profile"
        / "records"
        / f"{identity.content_hash}.json",
    }
    special_path = paths[special_file]
    special_path.unlink()
    os.mkfifo(special_path)
    errors: list[BaseException] = []

    def read_store() -> None:
        try:
            LocalProfileIdentityStore(authority_root).get_or_create()
        except BaseException as exc:  # pragma: no cover - assertion target below
            errors.append(exc)

    worker = Thread(target=read_store, daemon=True)
    worker.start()
    worker.join(timeout=1.0)
    assert not worker.is_alive(), f"FIFO {special_file} read blocked"
    assert errors and isinstance(errors[0], IdentityRecordCorruptError)


def test_profile_lifecycle_rejects_a_different_profile_scope(
    tmp_path: Path,
) -> None:
    from workbench.canonical import canonical_json_v1
    from workbench.identity.contracts import LocalProfileIdentityRevision

    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    identity = store.get_or_create()
    forged = LocalProfileIdentityRevision(
        profile_id="profile_forged",
        revision=1,
        identity_hash=identity.content_hash,
    )
    lifecycle_path = authority_root / "identity" / "local_profile" / "records.jsonl"
    lifecycle_path.write_bytes(
        (canonical_json_v1(forged.to_dict()) + "\n").encode("utf-8")
    )
    pointer_path = authority_root / "identity" / "local_profile" / "current.json"
    pointer_path.write_bytes(
        (
            canonical_json_v1(
                {
                    "identity_hash": identity.content_hash,
                    "revision": 1,
                    "revision_record_hash": forged.content_hash,
                }
            )
            + "\n"
        ).encode("utf-8")
    )

    with pytest.raises(IdentityCollisionError):
        LocalProfileIdentityStore(authority_root).get_or_create()


def test_profile_public_raw_reads_fail_closed_on_corrupt_record(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    identity = store.get_or_create()
    record_path = (
        authority_root
        / "identity"
        / "local_profile"
        / "records"
        / f"{identity.content_hash}.json"
    )
    record_path.write_bytes(b"{}\n")

    with pytest.raises(IdentityRecordCorruptError):
        store.read_record_bytes(identity)
    with pytest.raises(IdentityRecordCorruptError):
        store.read_records_log_bytes()
    with pytest.raises(IdentityRecordCorruptError):
        store.content_addressed_record_names()


def test_profile_public_raw_log_rejects_noncanonical_json(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    store.get_or_create()
    log_path = authority_root / "identity" / "local_profile" / "records.jsonl"
    log_path.write_bytes(b" " + store.read_records_log_bytes())

    with pytest.raises(IdentityRecordCorruptError):
        store.read_records_log_bytes()


def test_profile_public_raw_reads_reject_invalid_orphan_record(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    store.get_or_create()
    orphan_path = (
        authority_root
        / "identity"
        / "local_profile"
        / "records"
        / ("0" * 64 + ".json")
    )
    orphan_path.write_bytes(b"{}\n")

    with pytest.raises(IdentityRecordCorruptError):
        store.content_addressed_record_names()
