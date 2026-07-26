from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from workbench.identity.local_profile import (
    IdentityClientClaimError,
    LocalProfileIdentityStore,
)


def test_local_profile_is_stable_across_store_restart_and_content_addressed(
    tmp_path: Path,
) -> None:
    authority_root = tmp_path / "server-authority"
    first_store = LocalProfileIdentityStore(authority_root)
    first = first_store.get_or_create()
    record_path = first_store.record_path(first)
    record_bytes_before = record_path.read_bytes()
    index_bytes_before = first_store.records_log_path.read_bytes()

    second = LocalProfileIdentityStore(authority_root).get_or_create()

    assert second == first
    assert record_path.name == first.content_hash + ".json"
    assert record_bytes_before == record_path.read_bytes()
    assert index_bytes_before == first_store.records_log_path.read_bytes()


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
    assert len(list(store.records_dir.glob("*.json"))) == 1
    assert len(store.records_log_path.read_text(encoding="utf-8").splitlines()) == 1
