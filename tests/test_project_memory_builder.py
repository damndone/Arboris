from __future__ import annotations

from pathlib import Path

import pytest

from workbench.domain_memory.project_index_builder import (
    ProjectContextIndexBuilder,
    ProjectIndexBuildError,
)
from workbench.domain_memory.project_index_contract import ProjectContextFact, SourceManifestEntry
from workbench.identity.contracts import LocalProfileIdentity, ProjectIdentityRevision


def _identities() -> tuple[LocalProfileIdentity, ProjectIdentityRevision]:
    profile = LocalProfileIdentity(profile_id="profile_1")
    project = ProjectIdentityRevision(
        project_id="project_1",
        profile_id=profile.profile_id,
        revision=2,
        previous_revision=1,
        root_binding={
            "binding_key": "fs:1:2",
            "canonical_path": "/tmp/workbench-project",
            "device": 1,
            "inode": 2,
        },
    )
    return profile, project


def _sources() -> tuple[SourceManifestEntry, ...]:
    return (
        SourceManifestEntry("graph", "graph_1", 3, "a" * 64),
        SourceManifestEntry("trace", "trace_1", 4, "b" * 64),
    )


def _facts() -> tuple[ProjectContextFact, ...]:
    return (
        ProjectContextFact(
            fact_id="fact_1",
            kind="decision",
            summary="The user accepted a bounded model comparison plan.",
            source_refs=("trace_1",),
        ),
    )


def test_builder_consumes_core_identity_without_deriving_a_new_identity() -> None:
    profile, project = _identities()
    index = ProjectContextIndexBuilder.build(
        profile_identity=profile,
        project_identity=project,
        run_family_id="run-family_1",
        index_id="index_1",
        revision=1,
        source_manifest=_sources(),
        facts=_facts(),
        built_at="2026-07-27T09:00:00Z",
    )

    assert index.profile_id == profile.profile_id
    assert index.project_id == project.project_id
    assert index.project_revision == project.revision
    assert index.project_identity_hash == project.content_hash
    assert index.run_family_id == "run-family_1"


def test_builder_requires_contiguous_revision_and_matching_identity_scope() -> None:
    profile, project = _identities()
    with pytest.raises(ProjectIndexBuildError, match="previous_index_hash"):
        ProjectContextIndexBuilder.build(
            profile_identity=profile,
            project_identity=project,
            run_family_id="run-family_1",
            index_id="index_1",
            revision=2,
            source_manifest=_sources(),
            facts=_facts(),
            built_at="2026-07-27T09:00:00Z",
        )

    wrong_profile = LocalProfileIdentity(profile_id="profile_2")
    with pytest.raises(ProjectIndexBuildError, match="profile"):
        ProjectContextIndexBuilder.build(
            profile_identity=wrong_profile,
            project_identity=project,
            run_family_id="run-family_1",
            index_id="index_1",
            revision=1,
            source_manifest=_sources(),
            facts=_facts(),
            built_at="2026-07-27T09:00:00Z",
        )


def test_builder_does_not_read_paths_or_raw_data() -> None:
    profile, project = _identities()
    index = ProjectContextIndexBuilder.build(
        profile_identity=profile,
        project_identity=project,
        run_family_id="run-family_1",
        index_id="index_1",
        revision=1,
        source_manifest=_sources(),
        facts=_facts(),
        built_at="2026-07-27T09:00:00Z",
    )
    assert all("/" not in entry.source_ref for entry in index.source_manifest)
    assert all("/" not in fact.summary for fact in index.facts)
