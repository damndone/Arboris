"""Single public identity authority surface for Capability and Memory consumers."""

from __future__ import annotations

from pathlib import Path

from .contracts import (
    IDENTITY_CONTRACTS,
    LOCAL_PROFILE_IDENTITY_CONTRACT,
    PROJECT_IDENTITY_REVISION_CONTRACT,
    IdentityContractError,
    LocalProfileIdentity,
    ProjectIdentityRevision,
)
from .local_profile import (
    IdentityClientClaimError,
    IdentityCollisionError,
    IdentityRecordCorruptError,
    IdentityStoreError,
    LocalProfileIdentityStore,
    LocalProfileStore,
)
from .project_identity import ProjectIdentityRevisionStore, ProjectIdentityStore
from .root import (
    InvalidProjectRootError,
    ProjectRootError,
    ProjectRootRelocatedError,
    ValidatedProjectRoot,
    validate_project_root,
)


class IdentityAuthority:
    """The one façade shared by Capability and Memory consumers."""

    def __init__(self, authority_root: Path | str) -> None:
        self.local_profile_store = LocalProfileIdentityStore(authority_root)
        self.project_identity_store = ProjectIdentityStore(
            authority_root,
            profile_store=self.local_profile_store,
        )

    def get_local_profile_identity(self) -> LocalProfileIdentity:
        return self.local_profile_store.get_or_create()

    local_profile_identity = get_local_profile_identity
    local_profile = get_local_profile_identity

    def get_project_identity(
        self, project_root: Path | str
    ) -> ProjectIdentityRevision:
        return self.project_identity_store.get_or_create(project_root)

    project_identity = get_project_identity
    project = get_project_identity


__all__ = [
    "IDENTITY_CONTRACTS",
    "LOCAL_PROFILE_IDENTITY_CONTRACT",
    "PROJECT_IDENTITY_REVISION_CONTRACT",
    "IdentityAuthority",
    "IdentityClientClaimError",
    "IdentityCollisionError",
    "IdentityContractError",
    "IdentityRecordCorruptError",
    "IdentityStoreError",
    "InvalidProjectRootError",
    "LocalProfileIdentity",
    "LocalProfileIdentityStore",
    "LocalProfileStore",
    "ProjectIdentityRevision",
    "ProjectIdentityRevisionStore",
    "ProjectIdentityStore",
    "ProjectRootError",
    "ProjectRootRelocatedError",
    "ValidatedProjectRoot",
    "validate_project_root",
]
