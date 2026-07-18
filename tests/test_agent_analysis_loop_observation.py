from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from workbench.analysis_loop.compare import ComparePacket
from workbench.analysis_loop.observation import build_and_store_analysis_loop_packets
from workbench.analysis_loop.plan import build_plan_diff
from workbench.analysis_loop.resolver import (
    resolve_analysis_loop_inputs,
    resolve_analysis_loop_run,
)
from workbench.analysis_loop.storage import (
    ComparePacketStore,
    PlanDiffStore,
    ValidationPacketStore,
)
from workbench.agent.events import AgentEventStream
from workbench.agent.operations import OperationRecord
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository
from workbench.econometrics.runner import run_ols
from workbench.lineage.run_inputs import update_run_inputs_metadata, write_run_inputs


def _write_run(
    project_root: Path,
    run_id: str,
    frame: pd.DataFrame,
    *,
    covariance: str,
    rerun_of: str | None = None,
    workbench_context: dict[str, str] | None = None,
) -> dict:
    run_root = project_root / "runs" / run_id
    (run_root / "model_results").mkdir(parents=True)
    (run_root / "processed").mkdir(parents=True)
    result, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=covariance != "unadjusted",
        covariance=covariance,
        covariance_explicit=True,
        cluster_col="company_id" if covariance == "clustered" else None,
        model_id="ols_1",
        row_ids=[str(index) for index in frame.index],
        dataset_snapshot={
            "upload_sha256": "a" * 64,
            "model_input_artifact": "cleaned_dataset",
        },
    )
    (run_root / "model_results" / "ols_1.json").write_text(
        json.dumps(result), encoding="utf-8"
    )
    frame.to_parquet(run_root / "processed" / "cleaned_dataset.parquet", index=False)
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "status": "completed",
                "source_run_id": rerun_of,
            }
        ),
        encoding="utf-8",
    )
    form = {
        "model_type": "ols",
        "covariance": covariance,
        "y": "y",
        "x": "x",
    }
    if covariance == "clustered":
        form["entity_col"] = "company_id"
    write_run_inputs(
        run_root,
        form=form,
        upload={"sha256": "a" * 64, "filename": "source.csv"},
        rerun_of=rerun_of,
        from_node="model:ols" if rerun_of else None,
        rerun_reason="analysis_loop" if rerun_of else "initial",
        override_hash="override-hash" if rerun_of else None,
        dag_hash="b" * 64,
        source_lineage={"source_run_id": rerun_of, "from_node": "model:ols" if rerun_of else None},
        workbench_context=workbench_context,
    )
    return result


def test_terminal_observation_builds_validation_and_compare_packets_once(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, 1.5, 3.0, 2.5, 4.0],
            "x": [0.0, 1.0, 0.5, 2.0, 1.5, 3.0],
            "company_id": ["a", "a", "b", "b", "c", "c"],
        }
    )
    source_result = _write_run(project_root, "run-source", frame, covariance="unadjusted")
    child_result = _write_run(
        project_root,
        "run-child",
        frame,
        covariance="clustered",
        rerun_of="run-source",
        workbench_context={
            "confirmed_payload_hash": "payload-hash-1",
            "plan_hash": "plan-hash-1",
            "canonical_patch_hash": "patch-hash-1",
        },
    )

    resolved = resolve_analysis_loop_inputs(
        project_root,
        run_id="run-source",
        cluster_variable="company_id",
    )
    source_run = resolve_analysis_loop_run(
        project_root,
        run_id="run-source",
        require_result=True,
    )
    child_run = resolve_analysis_loop_run(project_root, run_id="run-child")
    target_result_id = source_result["stable_result_ids"][1]
    plan = build_plan_diff(
        source=resolved.source,
        intent={
            "action_id": "ols.use_clustered_covariance_v1",
            "patch": {"covariance": "clustered", "cluster_variable": "company_id"},
        },
        requested_result_id=target_result_id,
        cluster_values=resolved.cluster_values,
        model_row_ids=resolved.model_row_ids,
        source_context_fingerprint="ctx:source-v1",
        source_identity={
            "run_id": "run-source",
            "node_ref": "model:ols",
            "node_hash": "node-hash-source",
            "forest_node_key": "node-hash-source",
        },
    )
    execution = {
        "confirmed_payload_hash": "payload-hash-1",
        "executed_payload_hash": "payload-hash-1",
        "draft_hash": plan.plan_hash,
        "executed_draft_hash": plan.plan_hash,
        "plan_hash": plan.plan_hash,
        "executed_plan_hash": plan.plan_hash,
        "canonical_patch_hash": plan.canonical_patch_hash,
        "executed_canonical_patch_hash": plan.canonical_patch_hash,
        "effect_status": "committed",
        "projection_status": "complete",
        "child_terminal": True,
    }
    validation_store = ValidationPacketStore(project_root / "workbench")
    compare_store = ComparePacketStore(project_root / "workbench")

    first = build_and_store_analysis_loop_packets(
        source=resolved.source,
        source_run=source_run,
        child_run=child_run,
        plan=plan,
        execution_evidence=execution,
        validation_store=validation_store,
        compare_store=compare_store,
    )
    second = build_and_store_analysis_loop_packets(
        source=resolved.source,
        source_run=source_run,
        child_run=child_run,
        plan=plan,
        execution_evidence=execution,
        validation_store=validation_store,
        compare_store=compare_store,
    )

    assert first.validation.status == "complete"
    unknown_checks = [
        (check.check_id, check.status, check.reason_code)
        for check in first.validation.checks
        if check.status == "unknown"
    ]
    assert not unknown_checks, unknown_checks
    assert isinstance(first.compare, ComparePacket)
    assert first.compare.compare_status in {"complete", "partial"}, first.compare.integrity_findings
    assert first.compare.conclusion_diff["status"] == "complete"
    assert first.validation == second.validation
    assert first.compare == second.compare
    assert first.timings_ms is not None
    assert first.timings_ms["validation_packet_ms"] >= 0
    assert first.timings_ms["compare_packet_ms"] >= 0
    assert len(validation_store.list_terminal_packets()) == 1
    assert len(compare_store.list_terminal_packets()) == 1
    assert child_result["covariance_wire"] == "clustered"


def test_failed_child_without_result_still_materializes_failed_validation_and_not_comparable(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, 1.5, 3.0, 2.5, 4.0],
            "x": [0.0, 1.0, 0.5, 2.0, 1.5, 3.0],
            "company_id": ["a", "a", "b", "b", "c", "c"],
        }
    )
    _write_run(project_root, "run-source", frame, covariance="unadjusted")
    _write_run(
        project_root,
        "run-child-failed",
        frame,
        covariance="clustered",
        rerun_of="run-source",
    )
    child_root = project_root / "runs" / "run-child-failed"
    (child_root / "model_results" / "ols_1.json").unlink()
    (child_root / "run_manifest.json").write_text(
        json.dumps({"run_id": "run-child-failed", "status": "failed", "source_run_id": "run-source"}),
        encoding="utf-8",
    )

    resolved = resolve_analysis_loop_inputs(
        project_root,
        run_id="run-source",
        cluster_variable="company_id",
    )
    source_run = resolve_analysis_loop_run(
        project_root,
        run_id="run-source",
        require_result=True,
    )
    child_run = resolve_analysis_loop_run(
        project_root,
        run_id="run-child-failed",
        require_result=False,
    )
    plan = build_plan_diff(
        source=resolved.source,
        intent={
            "action_id": "ols.use_clustered_covariance_v1",
            "patch": {"covariance": "clustered", "cluster_variable": "company_id"},
        },
        requested_result_id=resolved.source.result_ids[0],
        cluster_values=resolved.cluster_values,
        model_row_ids=resolved.model_row_ids,
        source_context_fingerprint="ctx:source-v1",
        source_identity={"run_id": "run-source"},
    )
    observation = build_and_store_analysis_loop_packets(
        source=resolved.source,
        source_run=source_run,
        child_run=child_run,
        plan=plan,
        execution_evidence={
            "confirmed_payload_hash": "payload-hash-failed",
            "executed_payload_hash": "payload-hash-failed",
            "executed_plan_hash": plan.plan_hash,
            "executed_canonical_patch_hash": plan.canonical_patch_hash,
            "effect_status": "failed",
            "projection_status": "failed",
            "child_terminal": True,
        },
        validation_store=ValidationPacketStore(project_root / "workbench"),
        compare_store=ComparePacketStore(project_root / "workbench"),
    )

    assert observation.validation.status == "complete"
    assert observation.validation.overall_status == "failed"
    assert any(
        check.reason_code == "MODEL_FIT_FAILED"
        for check in observation.validation.checks
    )
    assert observation.compare is not None
    assert observation.compare.compare_status == "not_comparable"
    assert "PRIMARY_TARGET_MISSING" in observation.compare.integrity_findings


def test_orchestrator_terminal_observer_reuses_packets_after_reconcile(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, 1.5, 3.0, 2.5, 4.0],
            "x": [0.0, 1.0, 0.5, 2.0, 1.5, 3.0],
            "company_id": ["a", "a", "b", "b", "c", "c"],
        }
    )
    _write_run(project_root, "run-source", frame, covariance="unadjusted")
    _write_run(
        project_root,
        "run-child",
        frame,
        covariance="clustered",
        rerun_of="run-source",
        workbench_context={
            "confirmed_payload_hash": "payload-hash-1",
            "plan_hash": "plan-hash-1",
            "canonical_patch_hash": "patch-hash-1",
        },
    )
    resolved = resolve_analysis_loop_inputs(
        project_root,
        run_id="run-source",
        cluster_variable="company_id",
    )
    plan = build_plan_diff(
        source=resolved.source,
        intent={
            "action_id": "ols.use_clustered_covariance_v1",
            "patch": {"covariance": "clustered", "cluster_variable": "company_id"},
        },
        requested_result_id=resolved.source.result_ids[0],
        cluster_values=resolved.cluster_values,
        model_row_ids=resolved.model_row_ids,
        source_context_fingerprint="ctx:source-v1",
        source_identity={
            "run_id": "run-source",
            "node_ref": "model:ols",
            "node_hash": "node-hash-source",
            "forest_node_key": "node-hash-source",
        },
    )
    PlanDiffStore(project_root / "workbench").persist_terminal_plan(plan)
    update_run_inputs_metadata(
        project_root / "runs" / "run-child",
        workbench_context={
            "confirmed_payload_hash": "payload-hash-1",
            "plan_hash": plan.plan_hash,
            "canonical_patch_hash": plan.canonical_patch_hash,
        },
    )
    binding = {
        "plan_logical_key": plan.logical_key,
        "confirmed_payload_hash": "payload-hash-1",
    }
    repository = JsonlSessionRepository(project_root / "workbench")
    repository.create_session("main-session", chain_id="project", role="main")
    events = AgentEventStream(project_root / "workbench")
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
    )
    record = OperationRecord(
        record_id="operation-analysis-1",
        operation_id="model.rerun",
        operation_version="v1",
        proposal_id="proposal-analysis-1",
        proposal_revision=1,
        proposal_fingerprint="proposal-fingerprint-1",
        agent_session_id="main-session",
        chain_id="chain-a",
        command_id=None,
        target={
            "run_id": "run-source",
            "node_ref": "model:ols",
            "node_hash": "node-hash-source",
            "forest_node_key": "node-hash-source",
        },
        preconditions={
            "confirmed_payload_hash": "payload-hash-1",
            "analysis_loop": binding,
        },
        actor_type="user",
        status="completed",
        confirmation={},
        execution={
            "execution_key": "exec-analysis-1",
            "bindings": {"child_run_id": "run-child"},
        },
        outputs={"target_run_id": "run-child"},
        effect_status="committed",
        projection_status="complete",
        created_at="2026-07-17T00:00:00Z",
        updated_at="2026-07-17T00:00:00Z",
    )

    first = orchestrator.observe_analysis_loop_terminal(
        record,
        project_root=project_root,
    )
    second = orchestrator.observe_analysis_loop_terminal(
        record,
        project_root=project_root,
    )

    assert first == second
    assert first["analysis_loop"]["validation"]["status"] == "complete"
    assert first["analysis_loop"]["compare"]["compare_status"] in {
        "complete",
        "partial",
    }
    assert len(ValidationPacketStore(project_root / "workbench").list_terminal_packets()) == 1
    assert len(ComparePacketStore(project_root / "workbench").list_terminal_packets()) == 1
