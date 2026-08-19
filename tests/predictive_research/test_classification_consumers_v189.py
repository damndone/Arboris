from __future__ import annotations

from copy import deepcopy
import json

import pandas as pd
import pytest

from workbench.canonical import sha256_canonical
from workbench.contracts.prediction.holdout import HoldoutMetricBundleStoreV1, HoldoutSealStoreV1
from workbench.prediction import run_classification_model_v189
from workbench.providers.catalog import load_builtin_catalog
from workbench.predictive_research.classification_explanations import (
    compute_permutation_explanations,
    summarize_shift,
)
from workbench.predictive_research.classification_adapters import classification_runtime_registry
from workbench.predictive_research.classification_contracts import (
    ClassificationTaskSpecV1,
    FeatureAvailabilityContractV1,
    LabelDefinitionV1,
    build_classification_clarification,
)
from workbench.predictive_research.consumer_projection import project_classification_evidence
from workbench.predictive_research.graph_persistence import classification_graph_nodes
from workbench.predictive_research.persistence import classification_artifact_id, persist_classification_artifacts
from workbench.predictive_research.schema import default_v1_prediction_registry
from workbench.predictive_research.contracts import ContractError, StructureSpecV1


def _evidence_packet() -> dict[str, object]:
    return {
        "payload_schema": "workbench.prediction.classification-evidence",
        "schema_version": 1,
        "status": "validated",
        "task": {"task_type": "binary", "positive_class": "yes", "class_support": {"no": 4, "yes": 4}, "task_hash": "sha256:" + "t" * 64},
        "split": {"profile": "iid_stratified", "split_hash": "sha256:" + "a" * 64},
        "metrics": {"accuracy": {"point_estimate": 0.75, "validation_level": "validated"}},
        "calibration": {"status": "descriptive", "brier": 0.19},
        "baselines": [{"model_id": "majority", "accuracy": 0.5}],
        "controls": [{"control": "permuted_target", "status": "computed"}],
        "comparison": {"selected_model": "logistic_regression", "same_split": True},
        "explanations": {"permutation_importance": [{"feature": "x1", "importance": 0.2}]},
        "stability": {"folds": 2, "importance_rank_range": {"x1": [1, 2]}},
        "shift": {"status": "descriptive", "features": []},
        "decision_policy": {"selection_status": "SCENARIOS_ONLY", "holdout": "sealed"},
        "blocked_reasons": [],
        "holdout": {
            "status": "sealed",
            "model_id": "logistic_regression",
            "release_plan_hash": "sha256:" + "c" * 64,
            "release_plan": {
                "plan_hash": "sha256:" + "c" * 64,
                "task_hash": "sha256:" + "t" * 64,
                "split_hash": "sha256:" + "a" * 64,
                "model_id": "logistic_regression",
                "model_hash": "sha256:" + "m" * 64,
            },
        },
        "evidence_refs": {
            "task": "classification-task:sha256:" + "t" * 64,
            "split": "classification-split:sha256:" + "a" * 64,
            "model": "classification-model:logistic_regression:sha256:" + "m" * 64,
            "holdout": "classification-holdout:sha256:" + "c" * 64,
            "release_plan": "classification-release-plan:sha256:" + "c" * 64,
        },
    }


def _packet_with_c0(packet: dict[str, object], *, status: str = "validated") -> dict[str, object]:
    from workbench.prediction import _build_classification_c0_evidence

    enriched = deepcopy(packet)
    enriched["status"] = status
    envelope, projection = _build_classification_c0_evidence(
        status=status,
        task_hash=enriched["task"]["task_hash"],  # type: ignore[index]
        split_hash=enriched["split"]["split_hash"],  # type: ignore[index]
        holdout=enriched["holdout"],  # type: ignore[arg-type]
        evidence=enriched,
        blocked_reasons=["CLASSIFICATION_EVIDENCE_DEGRADED"] if status != "validated" else [],
    )
    enriched["c0_evidence_envelope"] = envelope
    enriched["c0_consumer_projection"] = projection
    enriched["foundation_status"] = {
        "execution_status": envelope["execution_status"],
        "availability": envelope["availability"],
        "completeness_status": envelope["completeness_status"],
        "producer_status": status,
    }
    return enriched


def _task_spec() -> ClassificationTaskSpecV1:
    return ClassificationTaskSpecV1(
        target_column="target",
        task_type="binary",
        class_mapping={0: "no", 1: "yes"},
        positive_class="yes",
        feature_columns=("x1", "x2"),
        feature_availability=tuple(
            FeatureAvailabilityContractV1(
                feature_name=column,
                observed_at="t0",
                available_at="t0",
                prediction_origin="t1",
                source_recipe="raw_snapshot",
                leakage_status="validated",
            )
            for column in ("x1", "x2")
        ),
        label_definition=LabelDefinitionV1(
            target_construction="observed_binary_target",
            event_time=None,
            horizon=None,
            purge_gap=None,
            revision_policy="frozen",
        ),
        structure=StructureSpecV1(kind="iid", provenance="user_confirmed"),
        primary_metric="roc_auc",
        secondary_metrics=("log_loss", "brier_score"),
        split_profile="iid_stratified",
        seed=11,
        resource_budget={"max_seconds": 30},
    )


def test_explanations_are_model_agnostic_and_record_validation_scope() -> None:
    frame = pd.DataFrame({"x1": [0.0, 0.1, 1.0, 1.1], "x2": [1.0, 1.0, 1.0, 1.0]})
    target = pd.Series([0, 0, 1, 1])

    explanation = compute_permutation_explanations(
        frame,
        target,
        model_id="logistic_regression",
        predict_proba=lambda values: values["x1"].to_numpy(),
        validation_row_refs=("v1", "v2", "v3", "v4"),
        feature_mapping={"x1": "x1", "x2": "x2"},
        seed=3,
        repeats=2,
    )

    assert explanation["causal_interpretation"] == "not_causal"
    assert explanation["sample_scope"] == "outer_validation"
    assert explanation["validation_row_refs"] == ["v1", "v2", "v3", "v4"]
    assert {row["feature"] for row in explanation["importance"]} == {"x1", "x2"}


def test_shift_summary_is_descriptive_and_subgroup_support_is_bounded() -> None:
    shift = summarize_shift(
        development=pd.DataFrame({"x": [0, 1, 2, 3]}),
        validation=pd.DataFrame({"x": [10, 11, 12, 13]}),
        subgroup_values={"small": [0, 1], "unsupported": [1]},
        minimum_support=2,
    )

    assert shift["interpretation"] == "descriptive_not_deployment_safety"
    assert shift["features"][0]["feature"] == "x"
    assert shift["subgroups"]["unsupported"]["status"] == "insufficient_support"


def test_classification_projection_exposes_evidence_without_recomputing() -> None:
    projection = project_classification_evidence(_packet_with_c0(_evidence_packet()), consumer="report")

    assert projection["status"] == "validated"
    assert projection["metrics"]["accuracy"]["point_estimate"] == 0.75
    assert projection["decision_policy"]["selection_status"] == "SCENARIOS_ONLY"
    assert projection["evidence_refs"]["holdout"] == "classification-holdout:sha256:" + "c" * 64


def test_classification_projection_rejects_missing_evidence_instead_of_fabricating_accuracy() -> None:
    packet = _evidence_packet()
    packet.pop("calibration")

    with pytest.raises(ContractError) as exc_info:
        project_classification_evidence(packet, consumer="agent")

    assert exc_info.value.code == "CLASSIFICATION_EVIDENCE_INCOMPLETE"


def test_classification_projection_requires_explicit_c0_envelope_and_projection() -> None:
    with pytest.raises(ContractError) as exc_info:
        project_classification_evidence(_evidence_packet(), consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_EVIDENCE_C0_REQUIRED"


@pytest.mark.parametrize("reference_key", ("task", "split", "model", "holdout", "release_plan"))
def test_classification_projection_rejects_stale_task_split_model_holdout_and_release_refs(reference_key: str) -> None:
    packet = _packet_with_c0(_evidence_packet())
    refs = dict(packet["evidence_refs"])
    refs[reference_key] = f"stale:{reference_key}"
    packet["evidence_refs"] = refs

    with pytest.raises(ContractError) as exc_info:
        project_classification_evidence(packet, consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_EVIDENCE_IDENTITY_INVALID"


def test_classification_projection_rejects_validated_status_when_c0_is_degraded() -> None:
    packet = _packet_with_c0(_evidence_packet(), status="degraded")
    packet["status"] = "validated"

    with pytest.raises(ContractError) as exc_info:
        project_classification_evidence(packet, consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_EVIDENCE_C0_STATUS_INVALID"


def test_classification_projection_rejects_unavailable_c0_with_available_projection() -> None:
    packet = _packet_with_c0(_evidence_packet(), status="unavailable")
    projection = deepcopy(packet["c0_consumer_projection"])
    projection["payload"]["projection_status"] = "available"  # type: ignore[index]
    packet["c0_consumer_projection"] = projection

    with pytest.raises(ContractError) as exc_info:
        project_classification_evidence(packet, consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_EVIDENCE_C0_STATUS_INVALID"


def test_artifact_identity_changes_when_task_model_or_policy_changes(tmp_path) -> None:
    base = {
        "task_hash": "task-a",
        "split_hash": "split-a",
        "preprocessing_hash": "prep-a",
        "model_hash": "model-a",
        "prediction_hash": "pred-a",
        "evaluation_hash": "eval-a",
        "control_hash": "control-a",
        "comparison_hash": "comparison-a",
        "explanation_hash": "explanation-a",
        "policy_hash": "policy-a",
    }
    first = classification_artifact_id(**base)
    changed = classification_artifact_id(**{**base, "model_hash": "model-b"})
    assert first != changed

    result = persist_classification_artifacts(tmp_path, {"evidence": _evidence_packet(), "task": base})
    assert result["status"] == "persisted"
    assert (tmp_path / "classification_artifacts.json").is_file()
    assert json.loads((tmp_path / "classification_artifacts.json").read_text())["evidence"]["task"]["task_type"] == "binary"


def test_graph_projection_has_separate_selection_and_holdout_operation_records() -> None:
    nodes = classification_graph_nodes(
        task_ref="task-1",
        split_ref="split-1",
        preprocessing_ref="prep-1",
        candidate_refs=("candidate-logistic", "candidate-rf"),
        comparison_ref="comparison-1",
        selected_model_ref="model-rf",
        policy_ref="policy-1",
        holdout_ref="holdout-1",
    )

    assert ("classification:comparison", "classification:selected_model") in nodes["edges"]
    assert ("classification:selected_model", "classification:holdout_evaluation") in nodes["edges"]
    assert nodes["operations"]["selection"]["operation_kind"] == "selection"
    assert nodes["operations"]["holdout"]["operation_kind"] == "holdout_evaluation"


def test_classification_evidence_is_registered_as_a_typed_payload() -> None:
    validated = default_v1_prediction_registry().validate(_evidence_packet())
    assert validated["payload_schema"] == "workbench.prediction.classification-evidence"


def test_package_local_clarification_records_missing_information_without_fallback() -> None:
    provider = next(item for item in load_builtin_catalog().providers if item.provider_id == "workbench.classification_ml")
    clarification = build_classification_clarification(
        {"analysis": "classify churn", "target": None, "primary_metric": "roc_auc"},
        provider_id=provider.provider_id,
        provider_digest=sha256_canonical(provider.to_dict()),
        contract_digests=tuple(ref.contract_digest for ref in provider.contract_refs),
    )

    assert clarification.status == "clarification_required"
    assert {"positive_class", "time_horizon", "availability", "cost_policy"}.issubset(clarification.missing_fields)
    assert clarification.provider_id == "workbench.classification_ml"
    assert clarification.contract_digests


def test_additive_classification_entrypoint_requires_typed_task_and_persists_packet(tmp_path) -> None:
    frame = pd.DataFrame({
        "target": [0, 0, 1, 1] * 4,
        "x1": [0.0, 0.2, 0.8, 1.0] * 4,
        "x2": [1.0, 0.9, 0.1, 0.0] * 4,
    })
    task = _task_spec()
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=task,
        row_refs=tuple(f"r{i}" for i in range(len(frame))),
        model_ids=("logistic_regression", "random_forest"),
        final_holdout_fraction=0.25,
        cv_folds=2,
        runtime_registry=classification_runtime_registry(),
        holdout_seal_store=HoldoutSealStoreV1(metric_bundle_store=HoldoutMetricBundleStoreV1()),
        holdout_principal_ref="principal:test",
        holdout_access_id="access:test",
    )

    assert result["status"] == "degraded"
    assert result["evidence"]["blocked_reasons"]
    assert result["evidence"]["calibration"]["status"] == "computed"
    assert result["evidence"]["baselines"] and isinstance(result["evidence"]["baselines"], list)
    assert result["evidence"]["explanations"]["shap"]["status"] == "unavailable"
    assert result["task"]["task_hash"] == task.content_hash
    assert result["artifact"]["status"] == "persisted"
    assert (tmp_path / "classification_artifacts.json").is_file()
    index = json.loads((tmp_path / "artifacts_index.json").read_text(encoding="utf-8"))
    record = next(
        item
        for item in index["artifacts"]
        if item["artifact_id"] == result["artifact"]["artifact_id"]
    )
    assert record["path"] == "classification_artifacts.json"
    assert record["artifact_type"] == "classification_artifacts"
    assert record["sha256"] == result["artifact"]["sha256"]
    assert record["payload_contract"] == {
        "payload_schema": "workbench.prediction.classification-artifacts",
        "schema_version": 1,
    }
