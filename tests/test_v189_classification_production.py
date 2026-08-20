from __future__ import annotations

import json
import hashlib
import shutil
from dataclasses import replace

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.prediction import run_classification_model_v189
from workbench.canonical import canonical_json_v1, sha256_canonical
from workbench.predictive_research.classification_contracts import (
    ClassificationTaskSpecV1,
    DecisionPolicyV1,
    FeatureAvailabilityContractV1,
    LabelDefinitionV1,
)
from workbench.predictive_research.contracts import StructureSpecV1
from workbench.predictive_research.preprocessing import ClassificationPreprocessingStepV1
from workbench.predictive_research.contracts import ContractError
from workbench.predictive_research.consumer_projection import (
    _project_classification_evidence,
    project_classification_evidence,
    read_classification_artifacts_wrapper_from_run_root,
    read_classification_evidence_from_run_root,
)
from workbench.api_errors import WorkbenchAPIError
from workbench.http import runs_routes


def _rewrite_indexed_classification_artifact(run_root, mutate, *, update_outer_id: bool = False) -> dict:
    path = run_root / "classification_artifacts.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload), encoding="utf-8")
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record = next(item for item in index["artifacts"] if item.get("artifact_type") == "classification_artifacts")
    record["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    if update_outer_id:
        record["artifact_id"] = payload["artifact_id"]
    index_path.write_text(json.dumps(index), encoding="utf-8")
    return payload


def _canonical_artifact_record(**overrides: object) -> dict[str, object]:
    return {
        "artifact_id": "artifact:data",
        "path": "data.json",
        "artifact_type": "data",
        "step": "ingest",
        "sha256": "a" * 64,
        "inputs": [],
        "config_hash": "",
        "code_version": "1.8.9",
        **overrides,
    }


def _production_dependencies(*, include_holdout: bool = True) -> dict[str, object]:
    from workbench.contracts.prediction.holdout import HoldoutMetricBundleStoreV1, HoldoutSealStoreV1

    dependencies: dict[str, object] = {}
    if include_holdout:
        dependencies.update(
            {
                "holdout_seal_store": HoldoutSealStoreV1(metric_bundle_store=HoldoutMetricBundleStoreV1()),
                "holdout_principal_ref": "principal:test",
                "holdout_access_id": "access:test",
            }
        )
    return dependencies


def _grouped_task() -> ClassificationTaskSpecV1:
    return ClassificationTaskSpecV1(
        target_column="target",
        task_type="binary",
        class_mapping={0: "negative", 1: "positive"},
        positive_class="positive",
        feature_columns=("x1", "x2"),
        feature_availability=tuple(
            FeatureAvailabilityContractV1(
                feature_name=column,
                observed_at="observed_at",
                available_at="available_at",
                prediction_origin="prediction_origin",
                source_recipe=f"raw:{column}",
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
        structure=StructureSpecV1(kind="grouped", group_column="entity"),
        primary_metric="roc_auc",
        secondary_metrics=("log_loss", "brier_score"),
        split_profile="group_holdout",
        seed=17,
        resource_budget={"max_trials": 1, "max_seconds": 30},
    )


def test_task_split_profile_drives_group_invariant_without_row_position_fallback(tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "target": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1, 0, 1],
            "x1": [0.0, 1.0, 0.1, 1.1, 0.2, 1.2, 0.3, 1.3, 0.4, 1.4, 0.5, 1.5],
            "x2": [1.0, 0.0, 1.1, 0.1, 1.2, 0.2, 1.3, 0.3, 1.4, 0.4, 1.5, 0.5],
            "entity": ["a"] * 3 + ["b"] * 3 + ["c"] * 3 + ["d"] * 3,
        }
    )
    run_root = tmp_path
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )

    result = run_classification_model_v189(
        frame,
        run_root,
        task=_grouped_task(),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    assert result["split"]["profile"] == "group_holdout"
    assignments = {item["row_ref"]: item["partition"] for item in result["split"]["assignments"]}
    entity_by_ref = dict(zip((f"r{index}" for index in range(len(frame))), frame["entity"], strict=True))
    development_entities = {
        entity_by_ref[row_ref]
        for row_ref, partition in assignments.items()
        if partition == "development"
    }
    holdout_entities = {
        entity_by_ref[row_ref]
        for row_ref, partition in assignments.items()
        if partition == "final_holdout"
    }
    assert development_entities.isdisjoint(holdout_entities)


def test_task_weight_is_consumed_by_fit_and_metrics_instead_of_rejected(tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "target": [0, 1, 0, 1] * 4,
            "x1": [0.0, 1.0, 0.1, 1.1] * 4,
            "x2": [1.0, 0.0, 1.1, 0.1] * 4,
            "weight": [1.0, 1.0, 1.0, 5.0] * 4,
        }
    )
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    task = replace(
        _grouped_task(),
        structure=StructureSpecV1(kind="iid"),
        split_profile="iid_stratified",
        weights="weight",
    )

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=task,
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    model = result["models"]["logistic_regression"]
    assert model["weights"]["column"] == "weight"
    assert model["oof_metrics"]["weight_sum"] != model["oof_metrics"]["row_count"]


def test_fold_local_preprocessing_receipt_excludes_validation_and_holdout_rows(tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "target": [0, 1, 0, 1] * 4,
            "x1": [0.0, 1.0, None, 1.1] * 4,
            "x2": [1.0, 0.0, 1.1, 0.1] * 4,
        }
    )
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=replace(_grouped_task(), structure=StructureSpecV1(kind="iid"), split_profile="iid_stratified"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        preprocessing_steps=(
            ClassificationPreprocessingStepV1(
                step_id="numeric_mean_scale",
                kind="mean_impute",
                columns=("x1",),
                supports_weight=True,
            ),
        ),
        **_production_dependencies(),
    )

    model = result["models"]["logistic_regression"]
    assignments = result["split"]["assignments"]
    for fold in model["preprocessing"]["folds"]:
        validation_refs = {
            item["row_ref"]
            for item in assignments
            if item["partition"] == "development" and item["cv_fold"] == fold["fold"]
        }
        fit_refs = set(fold["receipt"]["fit_row_refs"])
        assert fit_refs.isdisjoint(validation_refs)
        assert fit_refs.isdisjoint({item["row_ref"] for item in assignments if item["partition"] == "final_holdout"})
        assert fold["receipt"]["split_hash"] == result["comparison"]["split_hash"]


def test_string_features_are_typed_blocked_instead_of_coerced_to_numeric(tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "target": [0, 1, 0, 1] * 3,
            "x1": ["0", "1", "0", "1"] * 3,
            "x2": [1.0, 0.0, 1.0, 0.0] * 3,
        }
    )
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )

    with pytest.raises(ContractError) as exc_info:
        run_classification_model_v189(
            frame,
            tmp_path,
            task=replace(_grouped_task(), structure=StructureSpecV1(kind="iid"), split_profile="iid_stratified"),
            row_refs=tuple(f"r{index}" for index in range(len(frame))),
            model_ids=("logistic_regression",),
            final_holdout_fraction=0.25,
            cv_folds=2,
            **_production_dependencies(),
        )

    assert exc_info.value.code == "CLASSIFICATION_FEATURE_TYPE_BLOCKED"


def _ordered_task(*, structure_kind: str, split_profile: str) -> ClassificationTaskSpecV1:
    structure = (
        StructureSpecV1(kind="temporal", time_column="period")
        if structure_kind == "temporal"
        else StructureSpecV1(kind="panel", entity_column="entity", time_column="period")
    )
    availability = tuple(
        FeatureAvailabilityContractV1(
            feature_name=column,
            observed_at="feature_observed_at",
            available_at="feature_available_at",
            prediction_origin="prediction_origin",
            source_recipe=f"raw:{column}",
            leakage_status="validated",
        )
        for column in ("x1", "x2")
    )
    return ClassificationTaskSpecV1(
        target_column="target",
        task_type="binary",
        class_mapping={0: "negative", 1: "positive"},
        positive_class="positive",
        feature_columns=("x1", "x2"),
        feature_availability=availability,
        label_definition=LabelDefinitionV1(
            target_construction="event_within_horizon",
            event_time="event_at",
            horizon="1 period",
            purge_gap=None,
            revision_policy="as_of_prediction_origin",
        ),
        structure=structure,
        primary_metric="roc_auc",
        secondary_metrics=("log_loss", "brier_score"),
        split_profile=split_profile,
        seed=23,
        resource_budget={"max_trials": 1, "max_seconds": 30},
    )


def _ordered_frame(periods: list[int], entities: list[str] | None = None) -> pd.DataFrame:
    rows = len(periods)
    target = [index % 2 for index in range(rows)]
    return pd.DataFrame(
        {
            "target": target,
            "x1": [float(period) + 0.1 * label for period, label in zip(periods, target, strict=True)],
            "x2": [float(1 - label) for label in target],
            "period": periods,
            "feature_observed_at": periods,
            "feature_available_at": periods,
            "prediction_origin": [period + 1 for period in periods],
            **({} if entities is None else {"entity": entities}),
        }
    )


def test_temporal_production_training_roles_are_strictly_before_validation_and_holdout(tmp_path) -> None:
    periods = [period for period in range(8) for _ in range(2)]
    frame = _ordered_frame(periods)
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    assignments = {item["row_ref"]: item for item in result["split"]["assignments"]}
    period_by_ref = {f"r{index}": period for index, period in enumerate(periods)}
    holdout_periods = {
        period_by_ref[ref]
        for ref, assignment in assignments.items()
        if assignment["partition"] == "final_holdout"
    }
    development_periods = {
        period_by_ref[ref]
        for ref, assignment in assignments.items()
        if assignment["partition"] == "development"
    }
    assert min(holdout_periods) > max(development_periods)
    for fold in result["models"]["logistic_regression"]["preprocessing"]["folds"]:
        validation_periods = {period_by_ref[ref] for ref in fold["validation_row_refs"]}
        training_periods = {period_by_ref[ref] for ref in fold["training_row_refs"]}
        assert max(training_periods) < min(validation_periods)


def test_panel_new_entity_production_keeps_entity_identity_out_of_holdout_overlap(tmp_path) -> None:
    periods = [period for period in range(4) for _ in range(2)] + [4, 4, 5, 5]
    entities = ["a", "b"] * 4 + ["c"] * 4
    frame = _ordered_frame(periods, entities)
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="panel", split_profile="panel_new_entity"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=1 / 3,
        cv_folds=2,
        **_production_dependencies(),
    )

    assignments = {item["row_ref"]: item["partition"] for item in result["split"]["assignments"]}
    entity_by_ref = dict(zip((f"r{index}" for index in range(len(frame))), entities, strict=True))
    development_entities = {entity_by_ref[ref] for ref, part in assignments.items() if part == "development"}
    holdout_entities = {entity_by_ref[ref] for ref, part in assignments.items() if part == "final_holdout"}
    assert development_entities.isdisjoint(holdout_entities)


def test_production_calibration_threshold_and_evidence_consumer_are_explicitly_separated(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    model = result["models"]["logistic_regression"]
    calibration = model["calibration"]
    assert calibration["status"] == "computed"
    assert set(calibration["fit_row_refs"]).isdisjoint(calibration["evaluation_row_refs"])
    assert model["threshold"]["status"] == "unavailable"
    assert model["selection_threshold"]["status"] == "unavailable"
    assert "threshold" not in model["threshold"]
    assert set(calibration["fit_row_refs"]).isdisjoint(result["holdout"]["row_refs"])
    plan = result["holdout"]["release_plan"]
    assert plan["task_hash"] == result["task"]["task_hash"]
    assert plan["split_hash"] == result["comparison"]["split_hash"]
    assert plan["calibration_hash"].startswith("sha256:")
    assert plan["policy_hash"].startswith("sha256:")
    assert result["holdout"]["status"] == "sealed"
    assert result["holdout"]["release_count"] == 0
    projected = read_classification_evidence_from_run_root(tmp_path, consumer="report")
    assert projected["status"] == "degraded"
    assert isinstance(projected["baselines"], list)
    assert projected["explanations"]["shap"]["status"] == "unavailable"
    from workbench.contracts.evidence.envelope import ConsumerProjectionV1, EvidenceEnvelopeV1

    envelope = EvidenceEnvelopeV1.from_dict(result["evidence"]["c0_evidence_envelope"])
    projection = ConsumerProjectionV1.from_dict(result["evidence"]["c0_consumer_projection"])
    assert envelope.result_identity["task_hash"] == result["task_hash"]
    assert projection.payload.projection_status == "available"


def test_unimplemented_calibration_mode_is_not_reported_as_calibrated_or_validated(tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "target": [0, 1, 0, 1] * 4,
            "x1": [0.0, 1.0, 0.1, 1.1] * 4,
            "x2": [1.0, 0.0, 1.1, 0.1] * 4,
        }
    )
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=replace(_grouped_task(), structure=StructureSpecV1(kind="iid"), split_profile="iid_stratified"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        calibration_method="none",
        **_production_dependencies(),
    )

    assert result["status"] == "degraded"
    assert result["evidence"]["calibration"]["status"] == "not_applied"
    assert "CLASSIFICATION_CALIBRATION_NOT_APPLIED" in result["evidence"]["blocked_reasons"]


def test_temporal_availability_violation_is_typed_before_any_model_fit(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    frame.loc[0, "feature_available_at"] = 99
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    with pytest.raises(ContractError) as exc_info:
        run_classification_model_v189(
            frame,
            tmp_path,
            task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
            row_refs=tuple(f"r{index}" for index in range(len(frame))),
            model_ids=("logistic_regression",),
            final_holdout_fraction=0.25,
            cv_folds=2,
            **_production_dependencies(),
        )

    assert exc_info.value.code == "CLASSIFICATION_INFORMATION_SET_VIOLATION"


def test_temporal_metadata_red_probe_rejects_safe_arrays_that_mask_frame_columns(tmp_path) -> None:
    periods = [period for period in range(8) for _ in range(2)]
    frame = _ordered_frame(periods)
    frame.loc[0, "feature_available_at"] = 99
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    with pytest.raises(ContractError) as exc_info:
        run_classification_model_v189(
            frame,
            tmp_path,
            task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
            row_refs=tuple(f"r{index}" for index in range(len(frame))),
            model_ids=("logistic_regression",),
            final_holdout_fraction=0.25,
            cv_folds=2,
            feature_available_at=tuple(periods),
            prediction_origins=tuple(period + 1 for period in periods),
            **_production_dependencies(),
        )

    assert exc_info.value.code == "CLASSIFICATION_INFORMATION_SET_METADATA_MISMATCH"


def _selectable_policy(*, selected_threshold: float | None = None, method: str = "max_f1") -> DecisionPolicyV1:
    return DecisionPolicyV1(
        cost_matrix={"false_positive": 1.0, "false_negative": 2.0},
        capacity=10,
        abstain_allowed=False,
        manual_review_allowed=False,
        threshold_scope="development_oof",
        threshold_method=method,
        policy_version="1.0",
        population="all",
        time_validity="declared",
        selected_threshold=selected_threshold,
    )


def test_production_holdout_red_probe_requires_c0_server_owned_store(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    with pytest.raises(ContractError) as exc_info:
        run_classification_model_v189(
            frame,
            tmp_path,
            task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
            row_refs=tuple(f"r{index}" for index in range(len(frame))),
            model_ids=("logistic_regression",),
            final_holdout_fraction=0.25,
            cv_folds=2,
            decision_policy=_selectable_policy(selected_threshold=0.73),
            **_production_dependencies(include_holdout=False),
        )

    assert exc_info.value.code == "CLASSIFICATION_HOLDOUT_SERVER_STORE_REQUIRED"


def test_provider_join_red_probe_requires_runtime_contribution_identity() -> None:
    from workbench.predictive_research import classification_adapters

    factory = getattr(classification_adapters, "classification_runtime_registry", None)
    assert callable(factory)
    registry = factory()
    contribution = registry.require("executor:workbench.classification_ml.adapter")
    assert contribution.provider_id == "workbench.classification_ml"
    assert contribution.adapter_id == "workbench.classification_ml.adapter"


def test_provider_join_red_probe_rejects_same_identity_malicious_executor_before_dispatch(tmp_path) -> None:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistry
    from workbench.prediction import run_classification_model_v189_test_seam
    from workbench.predictive_research.classification_adapters import classification_runtime_registry

    trusted = classification_runtime_registry()
    trusted_contribution = trusted.require("executor:workbench.classification_ml.adapter")
    calls: list[object] = []

    def malicious_executor(context, request):
        calls.append((context, request))
        return {
            "provider_id": trusted_contribution.provider_id,
            "adapter_id": trusted_contribution.adapter_id,
            "executor_ref": trusted_contribution.executor_ref,
            "production_entrypoint": "workbench.prediction.run_classification_model_v189",
            "model_id": "logistic_regression",
        }

    fake_registry = TrustedExecutorRegistry((replace(trusted_contribution, executor=malicious_executor),))
    fake_registry._bound_catalog_digest = trusted._bound_catalog_digest
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    with pytest.raises(ContractError) as exc_info:
        run_classification_model_v189_test_seam(
            frame,
            tmp_path,
            task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
            row_refs=tuple(f"r{index}" for index in range(len(frame))),
            model_ids=("logistic_regression",),
            final_holdout_fraction=0.25,
            cv_folds=2,
            **{
                **_production_dependencies(),
                "runtime_registry": fake_registry,
            },
        )

    assert exc_info.value.code == "CLASSIFICATION_PROVIDER_RUNTIME_JOIN_MISMATCH"
    assert calls == []


def test_production_entrypoint_has_no_caller_registry_seam_and_never_dispatches_it(tmp_path) -> None:
    from workbench.agent.trusted_executor_registry import TrustedExecutorRegistry
    from workbench.predictive_research.classification_adapters import classification_runtime_registry

    trusted = classification_runtime_registry()
    trusted_contribution = trusted.require("executor:workbench.classification_ml.adapter")
    calls: list[object] = []

    def malicious_executor(context, request):
        calls.append((context, request))
        return {"provider_id": trusted_contribution.provider_id}

    fake_registry = TrustedExecutorRegistry((replace(trusted_contribution, executor=malicious_executor),))
    fake_registry._bound_catalog_digest = trusted._bound_catalog_digest
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    with pytest.raises(TypeError):
        run_classification_model_v189(
            frame,
            tmp_path,
            task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
            row_refs=tuple(f"r{index}" for index in range(len(frame))),
            model_ids=("logistic_regression",),
            final_holdout_fraction=0.25,
            cv_folds=2,
            runtime_registry=fake_registry,
            **_production_dependencies(),
        )

    assert calls == []


def test_each_persisted_cv_fold_receipt_contains_auditable_class_support(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    labels = dict(zip((f"r{index}" for index in range(len(frame))), frame["target"], strict=True))
    for fold in result["models"]["logistic_regression"]["preprocessing"]["folds"]:
        receipt = fold["receipt"]
        support = receipt["class_support"]
        assert set(support) == {"class_labels", "training", "validation"}
        assert set(support["class_labels"]) == {"negative", "positive"}
        for scope, ref_key in (("training", "training_row_refs"), ("validation", "validation_row_refs")):
            expected = {"negative": 0, "positive": 0}
            for ref in fold[ref_key]:
                expected["positive" if labels[ref] == 1 else "negative"] += 1
            assert support[scope] == expected


def test_persisted_classification_artifact_reloads_auditable_models_fit_and_evaluation(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    persisted = json.loads((tmp_path / "classification_artifacts.json").read_text(encoding="utf-8"))
    assert set(persisted) >= {"artifact_id", "identity", "models", "fit", "evaluation", "evidence"}
    assert persisted["artifact_id"] == result["artifact"]["artifact_id"]
    assert persisted["models"]["logistic_regression"] == result["models"]["logistic_regression"]
    assert persisted["fit"]["models"]["logistic_regression"]["fold_receipts"]
    assert persisted["evaluation"]["comparison"] == result["comparison"]
    assert persisted["evidence"]["task"]["task_hash"] == result["task_hash"]

    projected = project_classification_evidence(tmp_path, consumer="report")
    assert projected["status"] == result["evidence"]["status"]
    assert projected["comparison"]["selected_model"] == "logistic_regression"
    reloaded = read_classification_evidence_from_run_root(tmp_path, consumer="report")
    assert reloaded["comparison"]["selected_model"] == "logistic_regression"


def test_persisted_classification_artifact_rejects_copy_into_foreign_project_run(tmp_path) -> None:
    source_root = tmp_path / "project-source" / "runs" / "run-source"
    foreign_root = tmp_path / "project-foreign" / "runs" / "run-foreign"
    source_root.mkdir(parents=True)
    foreign_root.mkdir(parents=True)
    (source_root / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )

    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    run_classification_model_v189(
        frame,
        source_root,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )
    shutil.copy2(source_root / "classification_artifacts.json", foreign_root / "classification_artifacts.json")
    shutil.copy2(source_root / "artifacts_index.json", foreign_root / "artifacts_index.json")

    with pytest.raises(ContractError) as exc_info:
        read_classification_evidence_from_run_root(foreign_root, consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_SERVER_IDENTITY_MISMATCH"


def test_classification_consumer_rejects_in_memory_evidence_bypass(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    with pytest.raises(ContractError) as exc_info:
        project_classification_evidence(result["evidence"], consumer="agent")

    assert exc_info.value.code == "CLASSIFICATION_PERSISTED_RECEIPT_REQUIRED"


def test_public_classification_consumer_rejects_complete_persisted_mapping(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )
    persisted = json.loads((tmp_path / "classification_artifacts.json").read_text(encoding="utf-8"))

    with pytest.raises(ContractError) as exc_info:
        project_classification_evidence(persisted, consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_PERSISTED_RECEIPT_REQUIRED"


def test_shared_classification_artifacts_wrapper_contains_server_receipt_and_content_digests(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    wrapper = read_classification_artifacts_wrapper_from_run_root(tmp_path)

    assert wrapper["payload_schema"] == "workbench.prediction.classification-artifacts-wrapper"
    assert wrapper["receipt_path"] == "classification_receipt.json"
    assert wrapper["receipt"]["receipt_digest"] == wrapper["receipt_digest"]
    assert wrapper["receipt"]["content_digests"] == wrapper["content_digests"]
    assert wrapper["index"]["artifact_id"] == wrapper["artifact_id"]


def test_runs_artifact_route_serves_classification_only_as_validated_wrapper(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-classification"
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    run_classification_model_v189(
        frame,
        run_root,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )
    artifact_id = next(
        item["artifact_id"]
        for item in json.loads((run_root / "artifacts_index.json").read_text(encoding="utf-8"))["artifacts"]
        if item.get("artifact_type") == "classification_artifacts"
    )

    response = runs_routes.download_artifact_endpoint(
        "run-classification",
        artifact_id,
        str(project_root),
    )

    assert response.__class__.__name__ == "JSONResponse"
    served = json.loads(response.body)
    assert served["payload_schema"] == "workbench.prediction.classification-artifacts-wrapper"
    assert served["receipt"]["receipt_digest"] == served["receipt_digest"]
    assert served["content_digests"]["evidence.metrics"]

    listed = runs_routes.list_artifacts_endpoint("run-classification", str(project_root))
    listed_item = next(
        item
        for group in listed["groups"]
        for item in group["items"]
        if item.get("artifact_id") == artifact_id
    )
    assert listed_item["payload_contract"] == {
        "payload_schema": "workbench.prediction.classification-artifacts",
        "schema_version": 1,
    }
    assert listed_item["receipt_path"] == "classification_receipt.json"
    assert listed_item["receipt_sha256"] == served["receipt_sha256"]
    assert listed_item["server_identity"] == served["server_identity"]


@pytest.mark.parametrize(
    ("index_state", "expected_code"),
    (
        ("missing", "ARTIFACTS_INDEX_UNAVAILABLE"),
        ("malformed_json", "ARTIFACTS_INDEX_INVALID"),
    ),
)
def test_runs_artifact_list_red_probe_rejects_missing_or_malformed_index(
    tmp_path, index_state: str, expected_code: str
) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-artifacts-list"
    run_root.mkdir(parents=True)
    if index_state == "malformed_json":
        (run_root / "artifacts_index.json").write_text("{", encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc_info:
        runs_routes.list_artifacts_endpoint("run-artifacts-list", str(project_root))

    assert exc_info.value.code == expected_code


@pytest.mark.parametrize(
    ("index_state", "expected_status", "expected_code"),
    (
        ("missing", 503, "ARTIFACTS_INDEX_UNAVAILABLE"),
        ("malformed_json", 500, "ARTIFACTS_INDEX_INVALID"),
    ),
)
def test_runs_artifact_list_http_boundary_returns_typed_error_without_raw_exception(
    tmp_path, index_state: str, expected_status: int, expected_code: str
) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-artifacts-http"
    run_root.mkdir(parents=True)
    if index_state == "malformed_json":
        (run_root / "artifacts_index.json").write_text("{", encoding="utf-8")

    response = TestClient(app, raise_server_exceptions=False).get(
        "/runs/run-artifacts-http/artifacts",
        params={"project_root": str(project_root)},
    )
    body = response.json()

    assert response.status_code == expected_status
    assert body["error"]["code"] == expected_code
    assert "JSONDecodeError" not in response.text


@pytest.mark.parametrize(
    "mutation",
    (
        "missing_artifacts",
        "null_artifacts",
        "unknown_record_type",
        "missing_required_field",
        "null_path",
        "null_digest",
        "duplicate_id",
        "path_escape",
        "invalid_digest",
        "tampered_structure",
    ),
)
def test_runs_artifact_list_rejects_noncanonical_index_records_with_exact_invalid_code(
    tmp_path, mutation: str
) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-artifact-schema"
    run_root.mkdir(parents=True)
    (run_root / "data.json").write_text("{}", encoding="utf-8")
    index: dict[str, object] = {
        "schema_version": 1,
        "artifacts": [_canonical_artifact_record()],
    }
    if mutation == "missing_artifacts":
        index.pop("artifacts")
    elif mutation == "null_artifacts":
        index["artifacts"] = None
    elif mutation == "unknown_record_type":
        index["artifacts"][0]["record_type"] = "unknown"  # type: ignore[index]
    elif mutation == "missing_required_field":
        index["artifacts"][0].pop("inputs")  # type: ignore[index]
    elif mutation == "null_path":
        index["artifacts"][0]["path"] = None  # type: ignore[index]
    elif mutation == "null_digest":
        index["artifacts"][0]["sha256"] = None  # type: ignore[index]
    elif mutation == "duplicate_id":
        index["artifacts"].append(_canonical_artifact_record(path="second.json"))  # type: ignore[union-attr]
    elif mutation == "path_escape":
        index["artifacts"][0]["path"] = "../outside.json"  # type: ignore[index]
    elif mutation == "invalid_digest":
        index["artifacts"][0]["sha256"] = "not-a-digest"  # type: ignore[index]
    elif mutation == "tampered_structure":
        index["artifacts"][0]["inputs"] = {"artifact_id": "forged"}  # type: ignore[index]
    (run_root / "artifacts_index.json").write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc_info:
        runs_routes.list_artifacts_endpoint("run-artifact-schema", str(project_root))

    assert exc_info.value.code == "ARTIFACTS_INDEX_INVALID"


def test_runs_artifact_list_http_boundary_rejects_tampered_record_without_raw_exception(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-artifact-http-schema"
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text(
        json.dumps({
            "schema_version": 1,
            "artifacts": [{
                **_canonical_artifact_record(),
                "path": "../../etc/passwd",
            }],
        }),
        encoding="utf-8",
    )

    response = TestClient(app, raise_server_exceptions=False).get(
        "/runs/run-artifact-http-schema/artifacts",
        params={"project_root": str(project_root)},
    )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == "ARTIFACTS_INDEX_INVALID"
    assert "JSONDecodeError" not in response.text


def test_runs_artifact_route_rejects_classification_contract_alias_returning_another_wrapper(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-classification"
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    run_classification_model_v189(
        frame,
        run_root,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    canonical_record = next(item for item in index["artifacts"] if item.get("artifact_type") == "classification_artifacts")
    index["artifacts"].append({
        **canonical_record,
        "artifact_id": "classification-alias",
        "artifact_type": "classification_evidence",
        "payload_contract": {"payload_schema": "workbench.prediction.classification-artifacts", "schema_version": 1},
    })
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkbenchAPIError) as exc_info:
        runs_routes.download_artifact_endpoint("run-classification", "classification-alias", str(project_root))

    assert exc_info.value.code == "CLASSIFICATION_ARTIFACT_IDENTITY_MISMATCH"


@pytest.mark.parametrize("mutation", ("wrapper", "wrapper_index"))
def test_runs_artifact_route_rejects_each_wrapper_identity_mismatch_with_exact_code(tmp_path, monkeypatch, mutation: str) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-classification"
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    run_classification_model_v189(
        frame,
        run_root,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )
    artifact_id = next(
        item["artifact_id"]
        for item in json.loads((run_root / "artifacts_index.json").read_text(encoding="utf-8"))["artifacts"]
        if item.get("artifact_type") == "classification_artifacts"
    )
    wrapper = read_classification_artifacts_wrapper_from_run_root(run_root)
    if mutation == "wrapper":
        mutated_wrapper = {**wrapper, "artifact_id": "classification-wrapper-alias"}
    else:
        mutated_wrapper = {**wrapper, "index": {**wrapper["index"], "artifact_id": "classification-wrapper-alias"}}
    monkeypatch.setattr(runs_routes, "read_classification_artifacts_wrapper_from_run_root", lambda _run_root: mutated_wrapper)

    with pytest.raises(WorkbenchAPIError) as exc_info:
        runs_routes.download_artifact_endpoint("run-classification", artifact_id, str(project_root))

    assert exc_info.value.code == "CLASSIFICATION_ARTIFACT_IDENTITY_MISMATCH"


def test_runs_artifact_route_does_not_treat_generic_alias_id_as_classification_wrapper(tmp_path) -> None:
    project_root = tmp_path / "project"
    run_root = project_root / "runs" / "run-generic-alias"
    run_root.mkdir(parents=True)
    payload_path = run_root / "generic.json"
    payload_path.write_text('{"kind":"generic"}', encoding="utf-8")
    payload_sha256 = hashlib.sha256(payload_path.read_bytes()).hexdigest()
    (run_root / "artifacts_index.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "artifacts": [
                    _canonical_artifact_record(
                        artifact_id="classification_artifacts",
                        artifact_type="generic_result",
                        path="generic.json",
                        sha256=payload_sha256,
                    )
                ],
            }
        ),
        encoding="utf-8",
    )

    response = runs_routes.download_artifact_endpoint("run-generic-alias", "classification_artifacts", str(project_root))

    assert response.__class__.__name__ == "FileResponse"


def test_classification_canonical_unicode_vector_matches_backend_contract() -> None:
    value = {
        "text": "e\u0301",
        "composed": "é",
        "emoji": "🧪",
        "nested": {"ключ": "क"},
        "number": 1.25,
        "zero": -0.0,
    }

    assert canonical_json_v1(value) == '{"composed":"é","emoji":"🧪","nested":{"ключ":"क"},"number":1.25,"text":"é","zero":0}'
    assert sha256_canonical(value) == "d064d3a0678569cd737b9304f5151b8752ffb506ce48dc78795c3549dd0250ba"


def test_classification_server_identity_unicode_digest_uses_canonical_contract(tmp_path) -> None:
    from workbench.predictive_research.persistence import classification_server_identity

    identity = classification_server_identity(tmp_path / "项目" / "runs" / "run-é")
    base = {key: identity[key] for key in ("schema_version", "project_id", "run_id", "namespace")}

    assert identity["digest"] == "sha256:" + sha256_canonical(base)


@pytest.mark.parametrize(
    ("index_state", "expected_code"),
    (
        ("missing", "CLASSIFICATION_ARTIFACTS_INDEX_UNAVAILABLE"),
        ("malformed_json", "CLASSIFICATION_ARTIFACTS_INDEX_INVALID"),
        ("malformed_schema", "CLASSIFICATION_ARTIFACTS_INDEX_INVALID"),
    ),
)
def test_agent_and_notebook_classification_consumers_return_stable_typed_index_unavailable(tmp_path, index_state: str, expected_code: str) -> None:
    from workbench.agent.context_tools import read_classification_evidence_for_agent
    from workbench.agent.notebook.evidence import read_classification_evidence_for_notebook

    run_root = tmp_path / "run"
    run_root.mkdir()
    if index_state == "malformed_json":
        (run_root / "artifacts_index.json").write_text("{", encoding="utf-8")
    elif index_state == "malformed_schema":
        (run_root / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": {}}), encoding="utf-8")

    shared_projection = read_classification_evidence_from_run_root(run_root, consumer="report")
    agent_projection = read_classification_evidence_for_agent(run_root)
    notebook_projection = read_classification_evidence_for_notebook(run_root)

    expected_shared = {
        "payload_schema": "workbench.prediction.classification-evidence.unavailable",
        "schema_version": 1,
        "status": "unavailable",
        "consumer": "report",
        "code": expected_code,
    }
    expected_agent = {**expected_shared, "consumer": "agent"}
    expected_notebook = {**expected_shared, "consumer": "notebook"}
    assert shared_projection == expected_shared
    assert agent_projection == expected_agent
    assert notebook_projection == expected_notebook


def test_shared_wrapper_rejects_metrics_tamper_even_when_raw_artifact_index_hash_is_rewritten(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    _rewrite_indexed_classification_artifact(
        tmp_path,
        lambda payload: payload["evidence"]["metrics"].update({"forged": 0}),
        update_outer_id=True,
    )

    with pytest.raises(ContractError) as exc_info:
        read_classification_artifacts_wrapper_from_run_root(tmp_path)

    assert exc_info.value.code == "CLASSIFICATION_PERSISTED_RECEIPT_INVALID"


@pytest.mark.parametrize(
    "mutation",
    (
        "zero",
        "missing",
        "negative",
        "huge",
        "sum_mismatch",
        "duplicate_classes",
    ),
)
def test_index_hash_and_outer_artifact_updates_cannot_self_sign_invalid_fold_support(tmp_path, mutation: str) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    def mutate(payload: dict) -> None:
        fold = payload["fit"]["models"]["logistic_regression"]["fold_receipts"][0]
        support = fold["receipt"]["class_support"]
        if mutation == "zero":
            support["validation"]["positive"] = 0
        elif mutation == "missing":
            del support["validation"]["positive"]
        elif mutation == "negative":
            support["validation"]["positive"] = -1
        elif mutation == "huge":
            support["validation"]["positive"] = payload["evidence"]["task"]["class_support"]["positive"] + 1
        elif mutation == "sum_mismatch":
            support["training"]["positive"] += 1
        else:
            support["class_labels"].append("positive")

    _rewrite_indexed_classification_artifact(tmp_path, mutate, update_outer_id=True)

    with pytest.raises(ContractError) as exc_info:
        read_classification_evidence_from_run_root(tmp_path, consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_PERSISTED_RECEIPT_INVALID"


def test_content_level_receipt_binding_rejects_metrics_and_model_metadata_tampering(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    def mutate(payload: dict) -> None:
        payload["evidence"]["metrics"]["oof"]["metrics"]["accuracy"] = 0.0
        payload["evaluation"]["metrics"]["oof"]["metrics"]["accuracy"] = 0.0
        payload["models"]["logistic_regression"]["metadata"]["warnings"].append("forged-warning")

    _rewrite_indexed_classification_artifact(tmp_path, mutate)

    with pytest.raises(ContractError) as exc_info:
        read_classification_evidence_from_run_root(tmp_path, consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_PERSISTED_RECEIPT_INVALID"


def test_classification_notebook_consumer_reads_the_same_persisted_receipt(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    projection = read_classification_evidence_from_run_root(tmp_path, consumer="notebook")

    assert projection["consumer"] == "notebook"
    assert projection["comparison"]["selected_model"] == "logistic_regression"


def test_agent_and_notebook_classification_consumers_share_the_indexed_wrapper(tmp_path) -> None:
    from workbench.agent.context_tools import read_classification_evidence_for_agent
    from workbench.agent.notebook.evidence import read_classification_evidence_for_notebook

    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(
        json.dumps({"schema_version": 1, "artifacts": []}),
        encoding="utf-8",
    )
    run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    agent_projection = read_classification_evidence_for_agent(tmp_path)
    notebook_projection = read_classification_evidence_for_notebook(tmp_path)

    assert agent_projection["server_identity"] == notebook_projection["server_identity"]
    assert agent_projection["comparison"] == notebook_projection["comparison"]


def test_persisted_classification_artifact_rejects_tampered_fold_support(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )
    persisted = json.loads((tmp_path / "classification_artifacts.json").read_text(encoding="utf-8"))
    persisted["fit"]["models"]["logistic_regression"]["fold_receipts"][0]["receipt"]["class_support"]["training"]["positive"] += 1

    with pytest.raises(ContractError) as exc_info:
        _project_classification_evidence(persisted, consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_PERSISTED_FOLD_RECEIPTS_INVALID"


def test_persisted_classification_artifact_rejects_degraded_evidence_promoted_to_validated(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )
    persisted = json.loads((tmp_path / "classification_artifacts.json").read_text(encoding="utf-8"))
    persisted["evidence"]["status"] = "validated"

    with pytest.raises(ContractError) as exc_info:
        _project_classification_evidence(persisted, consumer="report")

    assert exc_info.value.code == "CLASSIFICATION_EVIDENCE_C0_STATUS_INVALID"


def test_group_validation_fold_red_probe_rejects_single_class_validation_support(tmp_path) -> None:
    entities = [entity for entity in ("a", "b", "c", "d", "e") for _ in range(2)]
    labels = [0, 0, 1, 1, 0, 1, 0, 0, 1, 1]
    frame = pd.DataFrame(
        {
            "target": labels,
            "x1": [float(index) for index in range(len(labels))],
            "x2": [float(index % 2) for index in range(len(labels))],
            "entity": entities,
        }
    )
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    with pytest.raises(ContractError) as exc_info:
        run_classification_model_v189(
            frame,
            tmp_path,
            task=_grouped_task(),
            row_refs=tuple(f"r{index}" for index in range(len(frame))),
            model_ids=("logistic_regression",),
            final_holdout_fraction=0.2,
            cv_folds=3,
            random_seed=0,
            **_production_dependencies(),
        )

    assert exc_info.value.code == "CLASSIFICATION_SPLIT_VALIDATION_CLASS_SUPPORT"


def test_temporal_label_window_red_probe_fails_closed_on_development_fold_overlap(tmp_path) -> None:
    periods = [period for period in range(8) for _ in range(2)]
    frame = _ordered_frame(periods)
    label_windows = [
        (0, 10) if period < 6 else (100 + index, 101 + index)
        for index, period in enumerate(periods)
    ]
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    with pytest.raises(ContractError) as exc_info:
        run_classification_model_v189(
            frame,
            tmp_path,
            task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
            row_refs=tuple(f"r{index}" for index in range(len(frame))),
            model_ids=("logistic_regression",),
            final_holdout_fraction=0.25,
            cv_folds=2,
            label_windows=label_windows,
            purge_gap=0,
            **_production_dependencies(),
        )

    assert exc_info.value.code == "CLASSIFICATION_PURGE_WINDOW_TRAIN_VALIDATION_OVERLAP"


def test_scenarios_only_red_probe_does_not_release_holdout_or_selected_threshold(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        **_production_dependencies(),
    )

    assert result["holdout"]["status"] == "sealed"
    assert result["holdout"]["release_count"] == 0
    assert result["models"]["logistic_regression"]["threshold"]["status"] == "unavailable"


def test_selected_threshold_red_probe_is_consumed_by_final_evaluation(tmp_path) -> None:
    frame = _ordered_frame([period for period in range(8) for _ in range(2)])
    (tmp_path / "artifacts_index.json").write_text(json.dumps({"schema_version": 1, "artifacts": []}), encoding="utf-8")

    result = run_classification_model_v189(
        frame,
        tmp_path,
        task=_ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        row_refs=tuple(f"r{index}" for index in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        decision_policy=_selectable_policy(selected_threshold=0.73),
        **_production_dependencies(),
    )

    assert result["decision_policy"]["consumed_threshold"] == 0.73
    assert result["models"]["logistic_regression"]["threshold"]["threshold"] == 0.73
    assert result["holdout"]["status"] == "released_once"
    assert result["holdout"]["release_count"] == 1
    decision = result["holdout"]["c0"]["decision"]
    assert decision["allowed"] is True
    assert decision["reason"] == "HOLDOUT_RELEASE_ALLOWED"
    assert decision["status"] == "closed"
    assert len(decision["ledger"]) == 1
    assert result["holdout"]["release_plan"]["task_hash"] == result["task_hash"]
    assert result["holdout"]["release_plan"]["split_hash"] == result["split_hash"]


def test_threshold_red_probe_uses_log_loss_and_precision_constraint() -> None:
    from workbench.predictive_research.classification_protocol import select_threshold_from_oof

    log_loss_choice = select_threshold_from_oof(
        actual=[0, 1, 1, 1],
        probabilities=[0.1, 0.4, 0.6, 0.7],
        method="min_log_loss",
        scope="development_oof",
    )
    expected = min(log_loss_choice["curve"], key=lambda row: row["log_loss"])
    assert log_loss_choice["threshold"] == expected["threshold"]
    assert log_loss_choice["threshold"] != 0.5

    constrained = select_threshold_from_oof(
        actual=[0, 1, 0, 1],
        probabilities=[0.8, 0.7, 0.6, 0.5],
        method="max_recall_at_precision",
        scope="development_oof",
        minimum_precision=0.9,
    )
    assert constrained["status"] == "unavailable"
    assert constrained["reason_code"] == "CLASSIFICATION_THRESHOLD_NO_FEASIBLE_CANDIDATE"


def test_c0_evidence_red_probe_preserves_degraded_status_and_required_identity() -> None:
    from workbench.predictive_research.consumer_projection import _project_classification_evidence

    payload = {
        "payload_schema": "workbench.prediction.classification-evidence",
        "schema_version": 1,
        "status": "degraded",
        "task": {"task_hash": "sha256:" + "a" * 64},
        "split": {"split_hash": "sha256:" + "b" * 64},
        "metrics": {},
        "holdout": {
            "status": "sealed",
            "model_id": "logistic_regression",
            "release_plan_hash": "sha256:" + "c" * 64,
            "release_plan": {
                "plan_hash": "sha256:" + "c" * 64,
                "task_hash": "sha256:" + "a" * 64,
                "split_hash": "sha256:" + "b" * 64,
                "model_id": "logistic_regression",
                "model_hash": "sha256:" + "m" * 64,
            },
        },
        "calibration": {"status": "computed"},
        "baselines": [],
        "controls": [],
        "comparison": {"selected_model": "logistic_regression"},
        "explanations": {"status": "unavailable"},
        "stability": {"status": "unavailable"},
        "shift": {"status": "unavailable"},
        "decision_policy": {"selection_status": "SCENARIOS_ONLY"},
        "blocked_reasons": ["CLASSIFICATION_POLICY_SCENARIO_ONLY"],
        "evidence_refs": {
            "task": "classification-task:sha256:" + "a" * 64,
            "split": "classification-split:sha256:" + "b" * 64,
            "model": "classification-model:logistic_regression:sha256:" + "m" * 64,
            "holdout": "classification-holdout:sha256:" + "c" * 64,
            "release_plan": "classification-release-plan:sha256:" + "c" * 64,
        },
    }

    from workbench.prediction import _build_classification_c0_evidence

    envelope, projection = _build_classification_c0_evidence(
        status="degraded",
        task_hash=payload["task"]["task_hash"],  # type: ignore[index]
        split_hash=payload["split"]["split_hash"],  # type: ignore[index]
        holdout=payload["holdout"],  # type: ignore[arg-type]
        evidence=payload,
        blocked_reasons=payload["blocked_reasons"],  # type: ignore[arg-type]
    )
    payload["c0_evidence_envelope"] = envelope
    payload["c0_consumer_projection"] = projection
    payload["foundation_status"] = {
        "execution_status": envelope["execution_status"],
        "availability": envelope["availability"],
        "completeness_status": envelope["completeness_status"],
        "producer_status": "degraded",
    }

    projected = _project_classification_evidence(payload, consumer="report")
    assert projected["status"] == "degraded"
    assert projected["task_hash"] == payload["task"]["task_hash"]
    assert projected["split_hash"] == payload["split"]["split_hash"]
    assert projected["holdout"]["release_plan"]["plan_hash"] == payload["holdout"]["release_plan"]["plan_hash"]
