from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from workbench.analysis_loop.contracts import SourceRunContract
from workbench.analysis_loop.plan import build_plan_diff
from workbench.analysis_loop.validation import (
    ValidationPacket,
    build_validation_packet,
    validation_packet_logical_key,
)


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
        "draft_hash": "draft-hash-1",
        "executed_draft_hash": "draft-hash-1",
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


def _model(**overrides: Any) -> dict[str, Any]:
    evidence = {
        "fit": "pass",
        "convergence": "pass",
        "singular": "pass",
        "collinearity": "pass",
        "standard_errors": "pass",
        "nobs": "pass",
    }
    evidence.update(overrides)
    return evidence


def _artifacts(**overrides: Any) -> dict[str, Any]:
    evidence = {
        "manifest_hash": "manifest-hash-1",
        "complete": True,
        "terminal_state": "complete",
    }
    evidence.update(overrides)
    return evidence


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


def _build(**kwargs: Any) -> ValidationPacket:
    source = _source()
    plan = _plan()
    return build_validation_packet(
        source=source,
        child=_child(),
        plan_diff=plan,
        execution_evidence=_execution(plan, **kwargs.pop("execution", {})),
        model_evidence=kwargs.pop("model", _model()),
        artifact_evidence=kwargs.pop("artifacts", _artifacts()),
        comparison_evidence=kwargs.pop("comparison", _comparison()),
        **kwargs,
    )


def _check(packet: ValidationPacket, check_id: str):
    return next(check for check in packet.checks if check.check_id == check_id)


def test_build_validation_packet_returns_immutable_complete_packet_for_terminal_child() -> None:
    packet = _build()

    assert packet.status == "complete"
    assert packet.overall_status == "passed"
    assert packet.logical_key == validation_packet_logical_key(
        child_run_id="run-child",
        executed_payload_hash="payload-hash-1",
        artifact_manifest_hash="manifest-hash-1",
        validation_policy_version=packet.validation_policy_version,
        schema_version=packet.schema_version,
    )
    assert _check(packet, "execution.confirmed_payload_hash").status == "pass"
    assert _check(packet, "model.fit").status == "pass"
    assert _check(packet, "comparison.analysis_sample_fingerprint").status == "pass"
    restored = ValidationPacket.from_dict(packet.to_dict())
    assert restored == packet
    with pytest.raises(TypeError):
        packet.checks[0].observed["mutate"] = True  # type: ignore[index]


def test_projection_pending_keeps_validation_packet_pending() -> None:
    packet = _build(
        execution={"projection_status": "pending", "child_terminal": False}
    )

    assert packet.status == "pending"
    assert packet.terminal is False
    assert packet.overall_status in {"unknown", "failed"}
    assert _check(packet, "execution.projection_complete").status == "unknown"


def test_fit_failure_is_a_complete_business_validation_packet() -> None:
    packet = _build(model=_model(fit="fail"))

    assert packet.status == "complete"
    assert packet.terminal is True
    assert packet.overall_status == "failed"
    assert _check(packet, "model.fit").status == "fail"
    assert _check(packet, "model.fit").reason_code == "MODEL_FIT_FAILED"


def test_confirmed_and_executed_payload_hash_mismatch_blocks_validation() -> None:
    packet = _build(execution={"executed_payload_hash": "payload-hash-other"})

    assert packet.status == "blocked"
    assert packet.overall_status == "failed"
    check = _check(packet, "execution.confirmed_payload_hash")
    assert check.status == "fail"
    assert check.reason_code == "CONFIRMED_EXECUTED_PAYLOAD_HASH_MISMATCH"


def test_validation_packet_logical_key_changes_with_each_identity_component() -> None:
    values = {
        "child_run_id": "child-1",
        "executed_payload_hash": "payload-1",
        "artifact_manifest_hash": "manifest-1",
        "validation_policy_version": "policy-1",
        "schema_version": "schema-1",
    }
    baseline = validation_packet_logical_key(**values)

    for field in values:
        assert validation_packet_logical_key(
            **{**values, field: f"changed-{field}"}
        ) != baseline
