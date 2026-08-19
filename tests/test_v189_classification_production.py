from __future__ import annotations

import json
from dataclasses import replace

import pandas as pd
import pytest

from workbench.prediction import run_classification_model_v189
from workbench.predictive_research.classification_contracts import (
    ClassificationTaskSpecV1,
    FeatureAvailabilityContractV1,
    LabelDefinitionV1,
)
from workbench.predictive_research.contracts import StructureSpecV1
from workbench.predictive_research.preprocessing import ClassificationPreprocessingStepV1
from workbench.predictive_research.contracts import ContractError
from workbench.predictive_research.consumer_projection import project_classification_evidence


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
    )

    model = result["models"]["logistic_regression"]
    calibration = model["calibration"]
    assert calibration["status"] == "computed"
    assert set(calibration["fit_row_refs"]).isdisjoint(calibration["evaluation_row_refs"])
    assert model["threshold"]["scope"] == "development_oof"
    assert model["threshold"]["input_scope"] == "development_calibration_eval"
    assert set(model["threshold"]["row_refs"]) == set(calibration["evaluation_row_refs"])
    assert set(calibration["fit_row_refs"]).isdisjoint(result["holdout"]["row_refs"])
    plan = result["holdout"]["release_plan"]
    assert plan["task_hash"] == result["task"]["task_hash"]
    assert plan["split_hash"] == result["comparison"]["split_hash"]
    assert plan["calibration_hash"].startswith("sha256:")
    assert plan["policy_hash"].startswith("sha256:")
    projected = project_classification_evidence(result["evidence"], consumer="report")
    assert projected["status"] == "blocked"
    assert isinstance(projected["baselines"], list)
    assert projected["explanations"]["shap"]["status"] == "unavailable"


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
        )

    assert exc_info.value.code == "CLASSIFICATION_INFORMATION_SET_VIOLATION"
