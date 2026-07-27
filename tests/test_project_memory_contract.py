from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.domain_memory.project_index_contract import (
    ProjectContextFact,
    ProjectContextIndex,
    ProjectIndexError,
    SourceManifestEntry,
)


def _source(kind: str = "graph", ref: str = "graph_1", revision: int = 1) -> SourceManifestEntry:
    return SourceManifestEntry(
        kind=kind,
        source_ref=ref,
        revision=revision,
        content_hash="a" * 64,
    )


def _fact() -> ProjectContextFact:
    return ProjectContextFact(
        fact_id="fact_1",
        kind="graph_summary",
        summary="The current analysis graph has one accepted branch.",
        source_refs=("graph_1",),
        attributes={"status": "accepted", "count": 1},
    )


def _index() -> ProjectContextIndex:
    return ProjectContextIndex(
        index_id="index_1",
        profile_id="profile_1",
        project_id="project_1",
        project_revision=1,
        project_identity_hash="b" * 64,
        run_family_id="run-family_1",
        revision=1,
        source_manifest=(_source(),),
        facts=(_fact(),),
        built_at="2026-07-27T09:00:00Z",
    )


def test_project_index_is_content_addressed_and_round_trips() -> None:
    index = _index()
    payload = index.to_dict()
    restored = ProjectContextIndex.from_dict(payload)

    assert payload["contract_version"] == "project-context-index/v1"
    assert payload["content_hash"] == index.content_hash
    assert restored == index
    assert restored.source_cursor_digest == index.source_cursor_digest


def test_index_hash_binds_identity_sources_and_facts() -> None:
    index = _index()
    changed_source = replace(index, source_manifest=(_source(revision=2),))
    changed_fact = replace(index, facts=(replace(_fact(), summary="A different bounded summary."),))
    changed_scope = replace(index, run_family_id="run-family_2")

    assert changed_source.content_hash != index.content_hash
    assert changed_fact.content_hash != index.content_hash
    assert changed_scope.content_hash != index.content_hash


def test_contract_rejects_raw_or_unbounded_values() -> None:
    with pytest.raises(ProjectIndexError, match="source kind"):
        _source(kind="dataset_rows")
    with pytest.raises(ProjectIndexError, match="summary"):
        replace(_fact(), summary="x" * 513)
    with pytest.raises(ProjectIndexError, match="attribute"):
        replace(_fact(), attributes={"raw": ["not", "allowed"]})
    with pytest.raises(ProjectIndexError, match="source_refs"):
        replace(_fact(), source_refs=tuple(f"source_{n}" for n in range(9)))


def test_contract_rejects_unknown_fields_and_tampered_hash() -> None:
    payload = _index().to_dict()
    payload["unexpected"] = "no"
    with pytest.raises(ProjectIndexError):
        ProjectContextIndex.from_dict(payload)

    payload = _index().to_dict()
    payload["content_hash"] = "c" * 64
    with pytest.raises(ProjectIndexError, match="content hash"):
        ProjectContextIndex.from_dict(payload)
