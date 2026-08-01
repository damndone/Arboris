"""B1 contract tests for server-owned Notebook memory defaults."""

from __future__ import annotations

import pytest

from workbench.agent.notebook.memory_defaults import (
    DEFAULT_TARGET_CONTRACTS,
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


def _recipe_proposal(
    *,
    model_type: str,
    include_time_column: bool = True,
    include_value_column: bool = True,
) -> TypedProposal:
    options: dict[str, object] = {}
    if include_time_column:
        options["time_column"] = "when"
    if include_value_column:
        options["value_column"] = "value"
    return TypedProposal(
        proposal_id=f"proposal-{model_type}",
        operation_id="model.genesis",
        target={"dataset_source_id": "upload-b2"},
        preconditions={"context_version": "node-operation-context/v1"},
        changes={
            "model_params": {
                "model_type": model_type,
                "model_options": options,
            }
        },
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


@pytest.mark.parametrize(
    ("model_type", "target_ref", "time_semantics"),
    (
        (
            "time_series.ets",
            "model.genesis.time_series.ets.time_index_semantics.observation_order",
            "observation_order",
        ),
        (
            "time_series.arma_garch",
            "model.genesis.time_series.arma_garch.time_index_semantics.business_or_trading_observations",
            "business_or_trading_observations",
        ),
    ),
)
def test_recipe_time_index_defaults_are_registered_provenanced_and_input_bound(
    model_type: str,
    target_ref: str,
    time_semantics: str,
) -> None:
    assert target_ref in DEFAULT_TARGET_CONTRACTS
    projection = _projection(_entry(memory_id=f"memory-{model_type}", target_ref=target_ref))

    defaulted = apply_memory_defaults(_recipe_proposal(model_type=model_type), projection)

    assert defaulted.changes["model_params"]["model_options"] == {
        "time_column": "when",
        "value_column": "value",
        "time_index_semantics": time_semantics,
    }
    assert defaulted.memory_default_sources[0].target_ref == target_ref

    with pytest.raises(MemoryDefaultApplicationError, match="time_column"):
        apply_memory_defaults(
            _recipe_proposal(model_type=model_type, include_time_column=False), projection
        )
    with pytest.raises(MemoryDefaultApplicationError, match="value_column"):
        apply_memory_defaults(
            _recipe_proposal(model_type=model_type, include_value_column=False), projection
        )


def test_recipe_explicit_time_index_semantics_precedes_memory_default() -> None:
    target_ref = "model.genesis.time_series.ets.time_index_semantics.observation_order"
    projection = _projection(_entry(memory_id="memory-ets", target_ref=target_ref))
    proposal = _recipe_proposal(model_type="time_series.ets")
    explicit = TypedProposal(
        proposal_id=proposal.proposal_id,
        operation_id=proposal.operation_id,
        target=proposal.target,
        preconditions=proposal.preconditions,
        changes={
            "model_params": {
                "model_type": "time_series.ets",
                "model_options": {
                    "time_column": "when",
                    "value_column": "value",
                    "time_index_semantics": "regular_calendar",
                },
            }
        },
    )

    assert apply_memory_defaults(explicit, projection) == explicit


def test_recipe_memory_cannot_write_orders_or_other_unpublished_fields() -> None:
    proposal = _recipe_proposal(model_type="time_series.arma_garch")
    unregistered = _projection(
        _entry(
            memory_id="memory-order",
            target_ref="model.genesis.time_series.arma_garch.arma.p.1",
        )
    )
    old_artifact_field = _projection(
        _entry(
            memory_id="memory-old-artifact",
            target_ref="model.genesis.time_series.arma_garch.result.time_index_semantics.observation_order",
        )
    )
    conflict = _projection(
        _entry(
            memory_id="memory-calendar",
            target_ref="model.genesis.time_series.arma_garch.time_index_semantics.regular_calendar",
        ),
        _entry(
            memory_id="memory-observation-order",
            target_ref="model.genesis.time_series.arma_garch.time_index_semantics.observation_order",
        ),
    )

    assert apply_memory_defaults(proposal, unregistered) == proposal
    assert apply_memory_defaults(proposal, old_artifact_field) == proposal
    assert apply_memory_defaults(proposal, conflict) == proposal
