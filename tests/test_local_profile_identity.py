from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import shutil

import pytest

from workbench.identity.local_profile import (
    IdentityClientClaimError,
    IdentityRecordCorruptError,
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
    with pytest.raises(Exception):
        LocalProfileIdentityStore(authority_root).get_or_create()

    records_path.unlink()
    (tmp_path / "records.saved").rename(records_path)
    record_path = records_path / f"{identity.content_hash}.json"
    record_path.write_bytes(store.read_record_bytes(identity))
    pointer = current_path
    pointer.unlink()
    pointer.symlink_to(outside / "current.json")
    with pytest.raises(Exception):
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
        LocalProfileIdentityStore(authority_root).get_or_create()


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


def test_profile_creation_recovers_a_partial_derived_pointer(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    store = LocalProfileIdentityStore(authority_root)
    identity = store.get_or_create()
    current_path = authority_root / "identity" / "local_profile" / "current.json"
    current_path.write_bytes(b'{"identity_hash":')

    assert LocalProfileIdentityStore(authority_root).get_or_create() == identity
