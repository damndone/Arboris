from __future__ import annotations

from workbench.domain_memory.context_projection import (
    ProjectContextProjection,
    project_index_to_context,
)
from test_project_memory_contract import _index


def test_projection_is_deterministic_and_provenance_preserving() -> None:
    index = _index()
    first = project_index_to_context(index, max_facts=4, max_bytes=4096)
    second = project_index_to_context(index, max_facts=4, max_bytes=4096)

    assert isinstance(first, ProjectContextProjection)
    assert first == second
    assert first.to_dict()["index_hash"] == index.content_hash
    assert first.to_dict()["facts"][0]["source_refs"] == ["graph_1"]
    assert first.to_dict()["memory_authority"] == "non_authoritative"


def test_projection_reports_bounded_omission_and_truncation() -> None:
    index = _index()
    projected = project_index_to_context(index, max_facts=0, max_bytes=128)

    assert projected.facts == ()
    assert projected.omitted_count == 1
    assert projected.truncated is True
    assert projected.omissions[0].reason == "fact_budget"


def test_projection_rejects_unbounded_budgets_and_never_enables_memory() -> None:
    index = _index()
    try:
        project_index_to_context(index, max_facts=129, max_bytes=4097)
    except ValueError as error:
        assert "budget" in str(error)
    else:
        raise AssertionError("unbounded projection budgets were accepted")

    projection = project_index_to_context(index, max_facts=4, max_bytes=4096)
    assert projection.cross_project_memory_used is False
    assert projection.cross_project_memory_iteration is False
