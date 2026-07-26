from dataclasses import FrozenInstanceError

import pytest

from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.identity.contracts import (
    LOCAL_PROFILE_IDENTITY_CONTRACT,
    LOCAL_PROFILE_IDENTITY_REVISION_CONTRACT,
    PROJECT_IDENTITY_REVISION_CONTRACT,
    IdentityContractError,
    LocalProfileIdentity,
    LocalProfileIdentityRevision,
    ProjectIdentityRevision,
)


ROOT_BINDING = {
    "binding_key": "fs:1:42",
    "canonical_path": "/srv/workbench/project",
    "device": 1,
    "inode": 42,
}


def test_local_profile_identity_is_immutable_and_canonical() -> None:
    identity = LocalProfileIdentity(profile_id="profile_abc")

    assert identity.to_dict() == {
        "contract_version": LOCAL_PROFILE_IDENTITY_CONTRACT,
        "profile_id": "profile_abc",
    }
    assert identity.canonical_json == canonical_json_v1(identity.to_dict())
    assert identity.content_hash == sha256_canonical(identity.to_dict())
    with pytest.raises(FrozenInstanceError):
        identity.profile_id = "profile_forged"  # type: ignore[misc]


def test_project_identity_revision_is_immutable_and_hashes_root_binding() -> None:
    revision = ProjectIdentityRevision(
        project_id="project_abc",
        profile_id="profile_abc",
        revision=1,
        root_binding=ROOT_BINDING,
    )

    assert revision.to_dict() == {
        "contract_version": PROJECT_IDENTITY_REVISION_CONTRACT,
        "previous_revision": None,
        "profile_id": "profile_abc",
        "project_id": "project_abc",
        "revision": 1,
        "root_binding": ROOT_BINDING,
    }
    assert revision.content_hash == sha256_canonical(revision.to_dict())
    revision_dict = revision.to_dict()
    revision_dict["root_binding"]["canonical_path"] = "/elsewhere"
    assert revision.root_binding["canonical_path"] == ROOT_BINDING["canonical_path"]


def test_contract_round_trip_is_strict_and_rejects_client_identity_fields() -> None:
    profile = LocalProfileIdentity(profile_id="profile_abc")
    project = ProjectIdentityRevision(
        project_id="project_abc",
        profile_id=profile.profile_id,
        revision=1,
        root_binding=ROOT_BINDING,
    )

    assert LocalProfileIdentity.from_dict(profile.to_dict()) == profile
    assert ProjectIdentityRevision.from_dict(project.to_dict()) == project

    forged = profile.to_dict()
    forged["display_name"] = "trusted-looking client value"
    with pytest.raises(IdentityContractError):
        LocalProfileIdentity.from_dict(forged)

    forged_project = project.to_dict()
    forged_project["project_name"] = "client supplied name"
    with pytest.raises(IdentityContractError):
        ProjectIdentityRevision.from_dict(forged_project)

    forged_binding = project.to_dict()
    forged_binding["root_binding"]["binding_key"] = "client-controlled-binding"
    with pytest.raises(IdentityContractError):
        ProjectIdentityRevision.from_dict(forged_binding)


def test_local_profile_lifecycle_revision_is_a_separate_contract() -> None:
    identity = LocalProfileIdentity(profile_id="profile_abc")
    lifecycle = LocalProfileIdentityRevision(
        profile_id=identity.profile_id,
        revision=1,
        identity_hash=identity.content_hash,
        previous_revision=None,
    )

    assert "revision" not in identity.to_dict()
    assert lifecycle.to_dict() == {
        "contract_version": LOCAL_PROFILE_IDENTITY_REVISION_CONTRACT,
        "identity_hash": identity.content_hash,
        "previous_revision": None,
        "profile_id": "profile_abc",
        "revision": 1,
    }
    assert LocalProfileIdentityRevision.from_dict(lifecycle.to_dict()) == lifecycle


def test_contract_hash_changes_for_revision_or_binding_but_not_mapping_order() -> None:
    first = ProjectIdentityRevision(
        project_id="project_abc",
        profile_id="profile_abc",
        revision=1,
        root_binding=ROOT_BINDING,
    )
    reordered = ProjectIdentityRevision(
        project_id="project_abc",
        profile_id="profile_abc",
        revision=1,
        root_binding={key: ROOT_BINDING[key] for key in reversed(ROOT_BINDING)},
    )
    second = ProjectIdentityRevision(
        project_id="project_abc",
        profile_id="profile_abc",
        revision=2,
        previous_revision=1,
        root_binding=ROOT_BINDING,
    )

    assert first.content_hash == reordered.content_hash
    assert first.content_hash != second.content_hash


def test_identity_package_exposes_one_authority_surface(tmp_path) -> None:
    import workbench.identity as identity

    authority = identity.IdentityAuthority(tmp_path / "authority")
    project_root = tmp_path / "project"
    project_root.mkdir()

    profile = authority.get_local_profile_identity()
    project = authority.get_project_identity(project_root)

    assert profile == authority.local_profile_store.get_or_create()
    assert project == authority.project_identity_store.get_or_create(project_root)
    assert identity.LocalProfileIdentity is LocalProfileIdentity
    assert identity.ProjectIdentityRevision is ProjectIdentityRevision
    assert "IdentityAuthority" in identity.__all__
