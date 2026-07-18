from __future__ import annotations

from pathlib import Path
from typing import Any

import workbench.analysis_loop.validation as validation
from workbench.analysis_loop.contracts import SourceRunContract
from workbench.analysis_loop.plan import build_plan_diff
from workbench.analysis_loop.storage import ValidationPacketStore


def _source() -> SourceRunContract:
    return SourceRunContract(
        run_id="run-source",
        status="completed",
        model="ols",
        covariance="unadjusted",
        result_artifact={
            "artifact_id": "ols-result",
            "stable_result_ids": ["coef:treatment"],
        },
        run_inputs={"form": {"model_type": "ols", "covariance": "unadjusted"}},
        lineage={"node_ref": "model:ols", "source_run_id": "run-source"},
        contract_version="ols_result_contract_v1",
        result_ids=("coef:treatment",),
        primary_estimand={
            "result_id": "coef:treatment",
            "role": "primary",
            "label": "Treatment",
        },
        dataset_schema={"firm_id": {"dtype": "string"}},
        analysis_row_ids=("r1", "r2", "r3", "r4"),
    )


def _plan() -> Any:
    source = _source()
    return build_plan_diff(
        source=source,
        intent={
            "action_id": "ols.use_clustered_covariance_v1",
            "patch": {"covariance": "clustered", "cluster_variable": "firm_id"},
        },
        requested_result_id="coef:treatment",
        cluster_values=["a", "a", "b", "b"],
        model_row_ids=["r1", "r2", "r3", "r4"],
        source_context_fingerprint="ctx:source-v1",
        source_identity={
            "run_id": source.run_id,
            "node_ref": "model:ols",
            "node_hash": "node-hash-source",
        },
    )


def _child() -> dict[str, Any]:
    return {
        "run_id": "run-child",
        "status": "completed",
        "source_run_id": "run-source",
        "lineage": {"source_run_id": "run-source", "child_run_id": "run-child"},
    }


def _execution(plan: Any, **overrides: Any) -> dict[str, Any]:
    evidence = {
        "operation_id": "model.rerun",
        "execution_key": "exec-analysis-1",
        "confirmed_payload_hash": "payload-hash-1",
        "executed_payload_hash": "payload-hash-1",
        "plan_hash": plan.plan_hash,
        "executed_plan_hash": plan.plan_hash,
        "canonical_patch_hash": plan.canonical_patch_hash,
        "executed_canonical_patch_hash": plan.canonical_patch_hash,
        "effect_status": "committed",
        "projection_status": "complete",
        "child_terminal": True,
    }
    evidence.update(overrides)
    return evidence


def _model() -> dict[str, Any]:
    return {
        "fit": "pass",
        "convergence": "pass",
        "singular": "pass",
        "collinearity": "pass",
        "standard_errors": "pass",
        "nobs": "pass",
    }


def _artifacts() -> dict[str, Any]:
    return {
        "manifest_hash": "manifest-hash-1",
        "complete": True,
        "terminal_state": "complete",
    }


def _comparison() -> dict[str, Any]:
    fingerprints = {
        "dataset_snapshot": "dataset-1",
        "analysis_sample": "sample-1",
        "point_estimation": "point-1",
        "coefficient_schema": "schema-1",
    }
    return {
        "source_run_id": "run-source",
        "child_run_id": "run-child",
        "source_result_ids": ["coef:treatment"],
        "child_result_ids": ["coef:treatment"],
        "primary_target_id": "coef:treatment",
        "source_fingerprints": fingerprints,
        "child_fingerprints": dict(fingerprints),
        "expected_inference_config": {"covariance": "clustered", "entity_col": "firm_id"},
        "observed_inference_config": {"covariance": "clustered", "entity_col": "firm_id"},
    }


def _observe(
    store: ValidationPacketStore,
    *,
    execution: dict[str, Any] | None = None,
) -> Any:
    adapter = getattr(validation, "build_and_store_validation_packet", None)
    assert callable(adapter), "validation adapter entry point is not implemented"
    plan = _plan()
    return adapter(
        store=store,
        source=_source(),
        child=_child(),
        plan_diff=plan,
        execution_evidence=_execution(plan, **(execution or {})),
        model_evidence=_model(),
        artifact_evidence=_artifacts(),
        comparison_evidence=_comparison(),
    )


def test_build_and_store_validation_packet_persists_terminal_complete_observation(
    tmp_path: Path,
) -> None:
    store = ValidationPacketStore(tmp_path)

    packet = _observe(store)

    assert packet.status == "complete"
    assert packet.terminal is True
    assert store.get_terminal_packet(packet.logical_key) == packet


def test_build_and_store_validation_packet_keeps_projection_pending_without_terminal(
    tmp_path: Path,
) -> None:
    store = ValidationPacketStore(tmp_path)

    packet = _observe(
        store,
        execution={"projection_status": "pending", "child_terminal": False},
    )

    assert packet.status == "pending"
    assert packet.terminal is False
    assert store.get_terminal_packet(packet.logical_key) is None
    assert store.list_build_attempts(logical_key=packet.logical_key)[0]["status"] == "pending"


def test_build_and_store_validation_packet_reuses_same_terminal_packet_on_retry(
    tmp_path: Path,
) -> None:
    store = ValidationPacketStore(tmp_path)

    first = _observe(store)
    second = _observe(store)

    assert second == first
    assert store.get_terminal_packet(first.logical_key) == first
    assert len(store.list_terminal_packets()) == 1
    assert [
        attempt["status"] for attempt in store.list_build_attempts(logical_key=first.logical_key)
    ] == ["completed", "reused"]
