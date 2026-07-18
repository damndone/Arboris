from __future__ import annotations

from pathlib import Path

import pytest

from workbench.analysis_loop.contracts import SourceRunContract
from workbench.analysis_loop.lifecycle import build_analysis_loop_proposal
from workbench.analysis_loop.plan import PlanValidationError, validate_confirmation_binding
from workbench.analysis_loop.storage import PlanDiffStore


ACTION_ID = "ols.use_clustered_covariance_v1"


def _source() -> SourceRunContract:
    return SourceRunContract(
        run_id="run-source",
        status="completed",
        model="ols",
        covariance="unadjusted",
        result_artifact={
            "artifact_id": "ols-result",
            "stable_result_ids": ["coef:treatment", "coef:control"],
        },
        run_inputs={
            "form": {"model_type": "ols", "covariance": "unadjusted"},
            "payload_hash": "payload-source",
        },
        lineage={"node_ref": "model:ols", "source_run_id": "run-source"},
        contract_version="ols_result_contract_v1",
        result_ids=("coef:treatment", "coef:control"),
        primary_estimand={
            "result_id": "coef:treatment",
            "role": "primary",
            "label": "Treatment",
        },
        result_labels={
            "coef:treatment": "Treatment",
            "coef:control": "Control",
        },
        dataset_schema={"firm_id": {"dtype": "string"}},
        analysis_row_ids=("r1", "r2", "r3", "r4"),
    )


def _intent() -> dict[str, object]:
    return {
        "action_id": ACTION_ID,
        "patch": {"covariance": "clustered", "cluster_variable": "firm_id"},
    }


def _build(store: PlanDiffStore):
    return build_analysis_loop_proposal(
        plan_store=store,
        source=_source(),
        intent=_intent(),
        cluster_values=["a", "a", "b", "b"],
        model_row_ids=["r1", "r2", "r3", "r4"],
        source_context_fingerprint="ctx:source-v1",
        source_identity={
            "run_id": "run-source",
            "node_ref": "model:ols",
            "node_hash": "node-hash-source",
            "forest_node_key": "node-hash-source",
        },
        active_head_run_id="run-source",
        owner_resolution="active_head_contains_node",
    )


def test_build_analysis_loop_proposal_returns_existing_proposal_kwargs_and_binding(
    tmp_path: Path,
) -> None:
    store = PlanDiffStore(tmp_path)

    spec = _build(store)
    binding = spec.preconditions["analysis_loop"]

    assert spec.operation_id == "model.rerun"
    assert spec.target == {
        "run_id": "run-source",
        "node_ref": "model:ols",
        "node_hash": "node-hash-source",
        "forest_node_key": "node-hash-source",
        "target_hash": spec.plan_diff.target_identity["target_hash"],
    }
    assert spec.changes == {"covariance": "clustered", "entity_col": "firm_id"}
    assert binding["plan_hash"] == spec.plan_diff.plan_hash
    assert binding["canonical_patch_hash"] == spec.plan_diff.canonical_patch_hash
    assert binding["source_context_fingerprint"] == spec.plan_diff.source_context_fingerprint
    assert binding["target_hash"] == spec.plan_diff.target_identity["target_hash"]
    assert binding["confirmed_payload_hash"] == spec.confirmed_payload_hash
    assert spec.to_proposal_kwargs(chain_id="chain-a")["operation_id"] == "model.rerun"
    assert store.get_terminal_packet(spec.plan_diff.logical_key).plan_diff == spec.plan_diff

    validate_confirmation_binding(
        spec.plan_diff,
        bound_plan_hash=spec.plan_diff.plan_hash,
        bound_canonical_patch_hash=spec.plan_diff.canonical_patch_hash,
        bound_target_hash=spec.plan_diff.target_identity["target_hash"],
        bound_source_context_fingerprint=spec.plan_diff.source_context_fingerprint,
        current_source_context_fingerprint=spec.plan_diff.source_context_fingerprint,
        confirmed_payload_hash=spec.confirmed_payload_hash,
        **{
            "proposal_id": spec.proposal_id,
            "revision": 1,
            "operation_version": "v1",
            "target": spec.target,
            "preconditions": spec.preconditions,
            "changes": spec.changes,
        },
    )


def test_build_analysis_loop_proposal_reuses_one_plan_and_one_proposal_identity(
    tmp_path: Path,
) -> None:
    store = PlanDiffStore(tmp_path)

    first = _build(store)
    second = _build(store)

    assert second.proposal_id == first.proposal_id
    assert second.confirmed_payload_hash == first.confirmed_payload_hash
    assert second.plan_diff == first.plan_diff
    assert len(store.list_terminal_packets()) == 1


def test_build_analysis_loop_proposal_rejects_before_plan_persistence(
    tmp_path: Path,
) -> None:
    store = PlanDiffStore(tmp_path)

    with pytest.raises(PlanValidationError) as exc_info:
        build_analysis_loop_proposal(
            plan_store=store,
            source=_source(),
            intent={
                "action_id": ACTION_ID,
                "patch": {"covariance": "clustered", "entity_col": "firm_id"},
            },
            cluster_values=["a", "a", "b", "b"],
            model_row_ids=["r1", "r2", "r3", "r4"],
            source_context_fingerprint="ctx:source-v1",
            source_identity={
                "run_id": "run-source",
                "node_ref": "model:ols",
                "node_hash": "node-hash-source",
                "forest_node_key": "node-hash-source",
            },
        )

    assert exc_info.value.code == "ENTITY_COL_GUESS_FORBIDDEN"
    assert store.list_terminal_packets() == []
