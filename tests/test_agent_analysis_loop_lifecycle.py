from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import pytest

from workbench.analysis_loop.contracts import SourceRunContract
from workbench.agent.core import AgentCore
from workbench.agent.chains import RerunExecutionResult
from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository
from workbench.analysis_loop.lifecycle import (
    build_analysis_loop_proposal,
    confirm_analysis_loop_proposal,
    create_analysis_loop_proposal,
)
from workbench.analysis_loop.plan import (
    PlanBindingError,
    PlanValidationError,
    validate_confirmation_binding,
)
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


class _IdleAdapter:
    async def stream(self, request):
        if False:
            yield request


def _orchestrator(tmp_path: Path) -> WorkbenchOrchestrator:
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("main-session", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    events = AgentEventStream(tmp_path / "workbench")
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
    )
    orchestrator.register_chain(
        "chain-a",
        "chain-session",
        AgentCore(repository, events, _IdleAdapter(), session_id="chain-session"),
    )
    return orchestrator


def _adapter_kwargs(tmp_path: Path) -> dict[str, object]:
    return {
        "plan_store": PlanDiffStore(tmp_path / "workbench"),
        "source": _source(),
        "intent": _intent(),
        "cluster_values": ["a", "a", "b", "b"],
        "model_row_ids": ["r1", "r2", "r3", "r4"],
        "source_context_fingerprint": "ctx:source-v1",
        "source_identity": {
            "run_id": "run-source",
            "node_ref": "model:ols",
            "node_hash": "node-hash-source",
            "forest_node_key": "node-hash-source",
        },
        "active_head_run_id": "run-source",
        "owner_resolution": "active_head_contains_node",
    }


def test_create_analysis_loop_proposal_adapter_uses_existing_proposal_store_once(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    kwargs = _adapter_kwargs(tmp_path)

    first = create_analysis_loop_proposal(
        orchestrator=orchestrator,
        chain_id="chain-a",
        **kwargs,
    )
    second = create_analysis_loop_proposal(
        orchestrator=orchestrator,
        chain_id="chain-a",
        **kwargs,
    )

    assert first.proposal_id == second.proposal_id
    assert first.operation_id == "model.rerun"
    assert first.changes == {"covariance": "clustered", "entity_col": "firm_id"}
    assert first.preconditions["plan_hash"]
    assert first.preconditions["canonical_patch_hash"]
    assert first.preconditions["source_context_fingerprint"] == "ctx:source-v1"
    assert first.preconditions["target_hash"]
    assert first.preconditions["confirmed_payload_hash"]
    assert len(orchestrator.proposal_store.latest_revisions_for_session("chain-session")) == 1
    assert orchestrator.operation_store.list_records() == []


def test_create_analysis_loop_proposal_adapter_rejects_before_proposal_or_operation(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    kwargs = _adapter_kwargs(tmp_path)
    kwargs["intent"] = {
        "action_id": ACTION_ID,
        "patch": {"covariance": "clustered", "entity_col": "firm_id"},
    }

    with pytest.raises(PlanValidationError) as exc_info:
        create_analysis_loop_proposal(
            orchestrator=orchestrator,
            chain_id="chain-a",
            **kwargs,
        )

    assert exc_info.value.code == "ENTITY_COL_GUESS_FORBIDDEN"
    assert orchestrator.proposal_store.latest_revisions_for_session("chain-session") == []
    assert orchestrator.operation_store.list_records() == []


def test_confirm_analysis_loop_proposal_validates_binding_before_existing_confirmation(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    kwargs = _adapter_kwargs(tmp_path)
    proposal = create_analysis_loop_proposal(
        orchestrator=orchestrator,
        chain_id="chain-a",
        **kwargs,
    )
    plan = kwargs["plan_store"].get_terminal_packet(
        proposal.preconditions["plan_logical_key"]
    ).plan_diff

    with pytest.raises(PlanBindingError) as exc_info:
        confirm_analysis_loop_proposal(
            orchestrator=orchestrator,
            plan_store=kwargs["plan_store"],
            proposal_id=proposal.proposal_id,
            current_source=_source(),
            current_source_context_fingerprint=plan.source_context_fingerprint,
            current_active_head_run_id="run-source",
            revision=1,
            fingerprint=proposal.fingerprint,
            confirmed_payload_hash="wrong-payload-hash",
        )

    assert exc_info.value.code == "CONFIRMED_PAYLOAD_MISMATCH"
    assert orchestrator.proposal_store.latest_status(proposal.proposal_id) == "pending"
    assert orchestrator.operation_store.list_records() == []


def test_confirm_analysis_loop_proposal_rejects_changed_source_before_operation(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    kwargs = _adapter_kwargs(tmp_path)
    proposal = create_analysis_loop_proposal(
        orchestrator=orchestrator,
        chain_id="chain-a",
        **kwargs,
    )
    changed_source = replace(_source(), status="running")

    with pytest.raises(PlanBindingError) as exc_info:
        confirm_analysis_loop_proposal(
            orchestrator=orchestrator,
            plan_store=kwargs["plan_store"],
            proposal_id=proposal.proposal_id,
            current_source=changed_source,
            current_source_context_fingerprint=proposal.preconditions[
                "source_context_fingerprint"
            ],
            current_active_head_run_id="run-source",
            revision=1,
            fingerprint=proposal.fingerprint,
            confirmed_payload_hash=proposal.preconditions["confirmed_payload_hash"],
        )

    assert exc_info.value.code == "STALE_PLAN"
    assert orchestrator.operation_store.list_records() == []


def test_analysis_loop_execution_recomputes_and_persists_executed_proposal_hash(
    tmp_path: Path,
) -> None:
    orchestrator = _orchestrator(tmp_path)
    kwargs = _adapter_kwargs(tmp_path)
    proposal = create_analysis_loop_proposal(
        orchestrator=orchestrator,
        chain_id="chain-a",
        **kwargs,
    )
    record = confirm_analysis_loop_proposal(
        orchestrator=orchestrator,
        plan_store=kwargs["plan_store"],
        proposal_id=proposal.proposal_id,
        current_source=_source(),
        current_source_context_fingerprint=proposal.preconditions[
            "source_context_fingerprint"
        ],
        current_active_head_run_id="run-source",
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        confirmed_payload_hash=proposal.preconditions["confirmed_payload_hash"],
    )
    captured = []

    async def executor(request):
        captured.append(request)
        return RerunExecutionResult(
            target_run_id="run-child",
            outputs={"status": "completed"},
        )

    completed = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint=proposal.preconditions[
                "context_fingerprint"
            ],
            current_active_head_run_id="run-source",
            executor=executor,
        )
    )

    assert len(captured) == 1
    assert captured[0].executed_proposal_payload_hash == proposal.preconditions[
        "confirmed_payload_hash"
    ]
    assert completed.execution["executed_proposal_payload_hash"] == captured[
        0
    ].executed_proposal_payload_hash


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
