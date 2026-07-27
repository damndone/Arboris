"""Pure MEM1 builder over CORE identity and caller-supplied canonical facts."""

from __future__ import annotations

from typing import Iterable

from ..identity.contracts import LocalProfileIdentity, ProjectIdentityRevision
from .project_index_contract import (
    ProjectContextFact,
    ProjectContextIndex,
    ProjectIndexError,
    SourceManifestEntry,
)


class ProjectIndexBuildError(ProjectIndexError):
    """The requested project index cannot be built from the supplied facts."""


class ProjectContextIndexBuilder:
    """Build an index without reading project paths or creating new identities."""

    @staticmethod
    def build(
        *,
        profile_identity: LocalProfileIdentity,
        project_identity: ProjectIdentityRevision,
        run_family_id: str,
        index_id: str,
        revision: int,
        source_manifest: Iterable[SourceManifestEntry],
        facts: Iterable[ProjectContextFact],
        built_at: str,
        previous_index_hash: str | None = None,
    ) -> ProjectContextIndex:
        if not isinstance(profile_identity, LocalProfileIdentity):
            raise ProjectIndexBuildError("profile_identity must come from CORE")
        if not isinstance(project_identity, ProjectIdentityRevision):
            raise ProjectIndexBuildError("project_identity must come from CORE")
        if project_identity.profile_id != profile_identity.profile_id:
            raise ProjectIndexBuildError("project identity belongs to another profile")
        if not isinstance(source_manifest, Iterable) or isinstance(source_manifest, (str, bytes)):
            raise ProjectIndexBuildError("source_manifest must be an iterable of typed refs")
        if not isinstance(facts, Iterable) or isinstance(facts, (str, bytes)):
            raise ProjectIndexBuildError("facts must be an iterable of typed facts")
        try:
            return ProjectContextIndex(
                index_id=index_id,
                profile_id=profile_identity.profile_id,
                project_id=project_identity.project_id,
                project_revision=project_identity.revision,
                project_identity_hash=project_identity.content_hash,
                run_family_id=run_family_id,
                revision=revision,
                source_manifest=tuple(source_manifest),
                facts=tuple(facts),
                built_at=built_at,
                previous_index_hash=previous_index_hash,
            )
        except ProjectIndexError as error:
            raise ProjectIndexBuildError(str(error)) from error


__all__ = ["ProjectContextIndexBuilder", "ProjectIndexBuildError"]
