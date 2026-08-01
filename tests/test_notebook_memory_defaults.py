"""B1 contract tests for server-owned Notebook memory defaults."""

from __future__ import annotations

import pytest

from workbench.agent.notebook.memory_defaults import (
    DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
    MemoryDefaultApplicationError,
    apply_memory_defaults,
)
from workbench.agent.notebook.proposal import TypedProposal


PROJECT_SCOPE_REF = "scope-project"
GLOBAL_SCOPE_REF = "scope-global"


def _projection(*entries: dict[str, object]) -> dict[str, object]:
    return {
        "contract_version": "domain-memory-context-input/v3",
        "retrieval_ref": "retrieval-b1",
        "scope_ref": PROJECT_SCOPE_REF,
        "outcome": "used" if entries else "empty",
        "reason": "approved hint",
        "entries": list(entries),
        "omissions": [],
        "bounded": True,
        "preference_ref": "preferences-b1",
        "memory_authority": "non_authoritative",
    }


def _entry(
    *,
    memory_id: str,
    target_ref: str,
    source_scope_ref: str = PROJECT_SCOPE_REF,
    vocabulary_version: str = DOMAIN_MEMORY_DEFAULT_VOCABULARY_VERSION,
) -> dict[str, object]:
    return {
        "memory_id": memory_id,
        "revision": 1,
        "content_hash": "a" * 64,
        "memory_kind": "project_domain_fact",
        "domain_tags": ["analysis"],
        "compact_lesson": "Use the independently reviewed default only in its declared scope.",
        "recommended_effect_kind": "assumption_check_hint",
        "recommended_target_refs": [target_ref],
        "source_summary_refs": ["summary-b1"],
        "match_reason": ["analysis_family"],
        "apply_mode": "suggest_default",
        "apply_mode_reason": "verifier_current",
        "vocabulary_version": vocabulary_version,
        "source_scope_ref": source_scope_ref,
        "memory_source": {"memory_id": memory_id, "revision": 1},
        "memory_authority": "non_authoritative_hint",
    }


def _proposal(*, model_type: str, entity_col: str | None = None) -> TypedProposal:
    model_params: dict[str, object] = {
        "model_type": model_type,
        "y": "outcome",
        "x": ["exposure"],
    }
    if entity_col is not None:
        model_params["entity_col"] = entity_col
    return TypedProposal(
        proposal_id="proposal-b1",
        operation_id="model.genesis",
        target={"dataset_source_id": "upload-b1"},
        preconditions={"context_version": "node-operation-context/v1"},
        changes={"model_params": model_params},
    )


def test_panel_clustered_default_requires_entity_and_applies_only_when_registered() -> None:
    projection = _projection(
        _entry(
            memory_id="memory-panel-clustered",
            target_ref="model.genesis.panel_ols.covariance.clustered",
        )
    )

    with pytest.raises(MemoryDefaultApplicationError, match="entity_col"):
        apply_memory_defaults(_proposal(model_type="panel_ols"), projection)

    defaulted = apply_memory_defaults(
        _proposal(model_type="panel_ols", entity_col="firm"),
        projection,
    )

    assert defaulted.changes["model_options"] == {"covariance": "clustered"}
    assert defaulted.memory_default_sources[0].target_ref == (
        "model.genesis.panel_ols.covariance.clustered"
    )


def test_current_project_memory_wins_over_global_memory_without_hidden_ordering() -> None:
    projection = _projection(
        _entry(
            memory_id="memory-project",
            target_ref="model.genesis.ols.covariance.robust",
        ),
        _entry(
            memory_id="memory-global",
            target_ref="model.genesis.ols.covariance.unadjusted",
            source_scope_ref=GLOBAL_SCOPE_REF,
        ),
    )

    defaulted = apply_memory_defaults(_proposal(model_type="ols"), projection)

    assert defaulted.changes["model_options"] == {"covariance": "robust"}
    assert [source.memory_id for source in defaulted.memory_default_sources] == ["memory-project"]


def test_same_layer_conflict_and_vocabulary_mismatch_never_modify_a_draft() -> None:
    proposal = _proposal(model_type="ols")
    conflict = _projection(
        _entry(memory_id="memory-project-a", target_ref="model.genesis.ols.covariance.robust"),
        _entry(memory_id="memory-project-b", target_ref="model.genesis.ols.covariance.unadjusted"),
    )
    mismatch = _projection(
        _entry(
            memory_id="memory-wrong-vocabulary",
            target_ref="model.genesis.ols.covariance.robust",
            vocabulary_version="notebook-memory-defaults-v0",
        )
    )
    unregistered = _projection(
        _entry(memory_id="memory-unregistered", target_ref="model.genesis.ols.unknown.setting")
    )

    assert apply_memory_defaults(proposal, conflict) == proposal
    assert apply_memory_defaults(proposal, mismatch) == proposal
    assert apply_memory_defaults(proposal, unregistered) == proposal


def test_explicit_current_request_and_legacy_projection_never_receive_a_default() -> None:
    proposal = _proposal(model_type="ols")
    suggestion = _projection(
        _entry(memory_id="memory-robust", target_ref="model.genesis.ols.covariance.robust")
    )
    explicit = TypedProposal(
        proposal_id=proposal.proposal_id,
        operation_id=proposal.operation_id,
        target=proposal.target,
        preconditions=proposal.preconditions,
        changes={
            **proposal.changes,
            "model_options": {"covariance": "unadjusted"},
        },
    )
    legacy_projection = _projection(
        _entry(memory_id="memory-legacy", target_ref="model.genesis.ols.covariance.robust")
    )
    legacy_projection["contract_version"] = "domain-memory-context-input/v2"
    for entry in legacy_projection["entries"]:
        entry.pop("vocabulary_version")
        entry.pop("source_scope_ref")

    assert apply_memory_defaults(explicit, suggestion) == explicit
    assert apply_memory_defaults(proposal, legacy_projection) == proposal


def test_explicit_choice_precedes_a_memory_target_precondition() -> None:
    proposal = _proposal(model_type="panel_ols")
    explicit = TypedProposal(
        proposal_id=proposal.proposal_id,
        operation_id=proposal.operation_id,
        target=proposal.target,
        preconditions=proposal.preconditions,
        changes={
            **proposal.changes,
            "model_options": {"covariance": "robust"},
        },
    )
    clustered_memory = _projection(
        _entry(
            memory_id="memory-panel-clustered",
            target_ref="model.genesis.panel_ols.covariance.clustered",
        )
    )

    assert apply_memory_defaults(explicit, clustered_memory) == explicit
