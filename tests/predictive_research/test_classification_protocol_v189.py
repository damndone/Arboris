from __future__ import annotations

from dataclasses import replace
import math

import numpy as np
import pandas as pd
import pytest
import workbench.predictive_research.classification_metrics as classification_metrics_module

from workbench.predictive_research.classification_adapters import (
    adapter_registry,
    get_classification_adapter,
)
from workbench.predictive_research.consumer_projection import project_classification_evidence
from workbench.predictive_research.classification_explanations import (
    compute_permutation_explanations,
    summarize_shift,
)
from workbench.predictive_research.classification_contracts import (
    ClassificationDiagnosticsPlanV1,
    ClassificationTaskSpecV1,
    DecisionPolicyV1,
    FeatureAvailabilityContractV1,
    LabelDefinitionV1,
)
from workbench.predictive_research.classification_metrics import (
    classification_metric_bundle,
    compute_calibration_bins,
    select_threshold_from_oof,
    threshold_curve,
)
from workbench.predictive_research.classification_protocol import HoldoutSealV1, run_classification_protocol
from workbench.predictive_research.contracts import ContractError, StructureSpecV1


def _binary_training_data() -> tuple[pd.DataFrame, pd.Series]:
    return (
        pd.DataFrame(
            {
                "signal": [-2.0, -1.5, -1.0, -0.5, 0.7, 1.0, 1.5, 2.0],
                "noise": [1.0, 0.2, -0.4, 0.8, -0.3, 0.1, -0.8, 0.5],
            }
        ),
        pd.Series([0, 0, 0, 0, 1, 1, 1, 1], name="target"),
    )


def _validation_data() -> tuple[pd.DataFrame, pd.Series]:
    return (
        pd.DataFrame(
            {
                "signal": [-2.0, -1.0, -0.4, 0.4, 1.0, 2.0, -1.6, 1.6],
                "noise": [0.1, 0.8, -0.2, 0.4, -0.6, 0.2, 0.3, -0.4],
            }
        ),
        pd.Series([0, 0, 0, 1, 1, 1, 0, 1], name="target"),
    )


def test_registry_exposes_one_typed_seam_with_explicit_bounds_and_weight_support() -> None:
    registry = adapter_registry()

    assert set(registry) == {"logistic_regression", "random_forest"}
    for declaration in registry.values():
        assert declaration.model_id in registry
        assert declaration.version == "1.0"
        assert declaration.supports_weight is True
        assert declaration.resource_bounds["max_cpu_seconds"] > 0
        assert declaration.parameter_schema


def test_logistic_and_random_forest_have_deterministic_class_order_probabilities_and_weights() -> None:
    frame, target = _binary_training_data()
    weights = np.array([1.0, 2.0, 1.0, 1.0, 1.0, 3.0, 1.0, 2.0])

    for model_id in ("logistic_regression", "random_forest"):
        first = get_classification_adapter(
            model_id,
            seed=13,
            class_order=(0, 1),
            parameters={"max_cpu_seconds": 10},
        )
        second = get_classification_adapter(
            model_id,
            seed=13,
            class_order=(0, 1),
            parameters={"max_cpu_seconds": 10},
        )
        first.fit(frame, target, sample_weight=weights)
        second.fit(frame, target, sample_weight=weights)

        first_probability = first.predict_proba(frame)
        second_probability = second.predict_proba(frame)
        assert first.class_order == (0, 1)
        assert first_probability.shape == (len(frame), 2)
        assert np.allclose(first_probability.sum(axis=1), 1.0)
        assert np.allclose(first_probability, second_probability)
        assert first.metadata["class_order"] == [0, 1]
        assert first.predict_at_threshold(frame, threshold=0.5, positive_class=1).shape == (len(frame),)


def test_adapter_parameters_are_explicit_and_unknown_models_fail_closed() -> None:
    with pytest.raises(ContractError) as error:
        get_classification_adapter("logistic_regression", parameters={"solver": "liblinear"})
    assert error.value.code == "CLASSIFICATION_PARAMETER_UNKNOWN"

    with pytest.raises(ContractError) as error:
        get_classification_adapter("random_forest", parameters={"n_estimators": 501})
    assert error.value.code == "CLASSIFICATION_PARAMETER_OUT_OF_BOUNDS"

    with pytest.raises(ContractError) as error:
        get_classification_adapter("xgboost")
    assert error.value.code == "CLASSIFICATION_ADAPTER_UNKNOWN"


def test_adapter_rejects_class_order_drift_non_numeric_input_and_zero_weight_fit() -> None:
    frame, target = _binary_training_data()
    adapter = get_classification_adapter("logistic_regression", class_order=(0, 1))

    with pytest.raises(ContractError) as error:
        adapter.fit(frame, target, class_order=(1, 0))
    assert error.value.code == "CLASSIFICATION_CLASS_ORDER_MISMATCH"

    with pytest.raises(ContractError) as error:
        adapter.fit(frame.assign(bad=["x"] * len(frame)), target)
    assert error.value.code == "CLASSIFICATION_FEATURE_TYPE_BLOCKED"

    with pytest.raises(ContractError) as error:
        adapter.fit(frame, target, sample_weight=np.zeros(len(target)))
    assert error.value.code == "CLASSIFICATION_WEIGHT_INVALID"


def test_known_answer_binary_metrics_keep_denominators_and_calibration_evidence() -> None:
    bundle = classification_metric_bundle(
        actual=[0, 0, 1, 1],
        probabilities=[0.1, 0.2, 0.8, 0.9],
        predictions=[0, 0, 1, 1],
        class_order=(0, 1),
        positive_class=1,
        threshold=0.5,
        sample_scope="outer_validation",
        evaluation_design="known_answer",
        numerical_method="sklearn_1.x",
        inference_basis="descriptive",
        validation_level="validated",
    )

    assert bundle["confusion_matrix"] == {"labels": [0, 1], "values": [[2.0, 0.0], [0.0, 2.0]]}
    assert bundle["metrics"]["accuracy"]["point_estimate"] == 1.0
    assert bundle["metrics"]["balanced_accuracy"]["point_estimate"] == 1.0
    assert bundle["metrics"]["precision"]["point_estimate"] == 1.0
    assert bundle["metrics"]["recall"]["point_estimate"] == 1.0
    assert bundle["metrics"]["f1"]["point_estimate"] == 1.0
    assert bundle["metrics"]["roc_auc"]["point_estimate"] == 1.0
    assert bundle["metrics"]["pr_auc"]["point_estimate"] == 1.0
    assert bundle["metrics"]["log_loss"]["point_estimate"] == pytest.approx(
        -(math.log(0.9) + math.log(0.8)) / 2
    )
    assert bundle["metrics"]["brier_score"]["point_estimate"] == pytest.approx(0.025)
    assert bundle["metrics"]["accuracy"]["row_count"] == 4
    assert bundle["metrics"]["accuracy"]["weight_sum"] == 4.0
    assert bundle["per_class"]["0"]["support"] == 2
    assert bundle["per_class"]["1"]["support"] == 2
    assert bundle["calibration"]["status"] == "computed"
    assert bundle["threshold"] == {"value": 0.5, "scope": "outer_validation", "status": "declared"}
    for metric in bundle["metrics"].values():
        assert metric["metric_definition"]
        assert metric["definition_version"] == "classification-metric.v1"
        assert metric["denominator"]["status"] == "declared"
        assert metric["denominator"]["value"] is not None
        assert metric["weighted"] is False
        assert metric["weighted_status"] == "unweighted"
        assert metric["point_estimate"] is not None
        assert metric["numerical_method"] == "sklearn_1.x"
        assert metric["inference_basis"] == "descriptive"
        assert metric["evaluation_design"] == "known_answer"
        assert metric["validation_level"] == "validated"
        assert metric["evidence_basis"] == {
            "kind": "known_answer",
            "independent_oracle": False,
        }
        assert metric["independent_oracle"] is False


def test_metrics_preserve_weighted_confusion_and_never_turn_undefined_into_zero() -> None:
    weighted = classification_metric_bundle(
        actual=[0, 0, 1, 1],
        probabilities=[0.9, 0.8, 0.2, 0.1],
        predictions=[1, 0, 1, 0],
        class_order=(0, 1),
        positive_class=1,
        threshold=0.5,
        sample_scope="outer_validation",
        evaluation_design="weighted_known_answer",
        numerical_method="known_answer",
        inference_basis="descriptive",
        validation_level="validated",
        sample_weight=[1.0, 3.0, 2.0, 4.0],
    )
    assert weighted["weight_sum"] == 10.0
    assert weighted["confusion_matrix"]["values"] == [[3.0, 1.0], [4.0, 2.0]]
    assert weighted["metrics"]["accuracy"]["point_estimate"] == pytest.approx(0.5)
    assert weighted["metrics"]["accuracy"]["weighted"] is True
    assert weighted["metrics"]["accuracy"]["weighted_status"] == "weighted"
    assert weighted["metrics"]["accuracy"]["denominator"] == {
        "kind": "total_weight",
        "status": "declared",
        "value": 10.0,
    }

    undefined = classification_metric_bundle(
        actual=[0, 0, 0],
        probabilities=[0.1, 0.2, 0.3],
        predictions=[0, 0, 0],
        class_order=(0, 1),
        positive_class=1,
        threshold=0.5,
        sample_scope="outer_validation",
        evaluation_design="insufficient_support",
        numerical_method="known_answer",
        inference_basis="descriptive",
        validation_level="insufficient",
    )
    for name in ("precision", "recall", "f1", "roc_auc", "pr_auc"):
        assert undefined["metrics"][name]["status"] == "undefined"
        assert undefined["metrics"][name]["point_estimate"] is None
        assert undefined["metrics"][name]["reason"]


def test_same_library_regression_is_marked_without_independent_oracle_claim() -> None:
    bundle = classification_metric_bundle(
        actual=[0, 0, 1, 1],
        probabilities=[0.1, 0.2, 0.8, 0.9],
        predictions=[0, 0, 1, 1],
        class_order=(0, 1),
        positive_class=1,
        sample_scope="outer_validation",
        evaluation_design="same_library_regression",
        numerical_method="sklearn_1.x",
        inference_basis="descriptive",
        validation_level="regression",
    )

    evidence = bundle["metrics"]["roc_auc"]
    assert evidence["evidence_basis"] == {
        "kind": "same_library_regression",
        "independent_oracle": False,
    }
    assert evidence["independent_oracle"] is False


def test_explicit_reverse_class_order_controls_probability_columns_and_log_loss() -> None:
    bundle = classification_metric_bundle(
        actual=[1, 0, 1, 0],
        probabilities=[0.9, 0.2, 0.8, 0.1],
        predictions=[1, 0, 1, 0],
        class_order=(1, 0),
        positive_class=1,
        threshold=0.5,
        sample_scope="outer_validation",
        evaluation_design="class_order_known_answer",
        numerical_method="known_answer",
        inference_basis="descriptive",
        validation_level="validated",
    )

    assert bundle["class_order"] == [1, 0]
    assert bundle["metrics"]["roc_auc"]["point_estimate"] == 1.0
    assert bundle["metrics"]["log_loss"]["point_estimate"] == pytest.approx(
        -(math.log(0.9) + math.log(0.8) + math.log(0.8) + math.log(0.9)) / 4
    )


def test_multiclass_metrics_report_per_class_support_and_macro_scores() -> None:
    bundle = classification_metric_bundle(
        actual=["a", "b", "c", "c"],
        probabilities=[
            [0.8, 0.1, 0.1],
            [0.1, 0.2, 0.7],
            [0.2, 0.6, 0.2],
            [0.1, 0.7, 0.2],
        ],
        predictions=["a", "c", "c", "b"],
        class_order=("a", "b", "c"),
        positive_class=None,
        threshold=0.5,
        sample_scope="outer_validation",
        evaluation_design="multiclass_known_answer",
        numerical_method="sklearn_1.x",
        inference_basis="descriptive",
        validation_level="validated",
        averaging="macro",
    )

    assert bundle["metrics"]["accuracy"]["point_estimate"] == 0.5
    assert bundle["metrics"]["balanced_accuracy"]["point_estimate"] == pytest.approx(0.5)
    assert bundle["metrics"]["precision"]["point_estimate"] == pytest.approx((1 + 0 + 0.5) / 3)
    assert bundle["per_class"]["a"]["support"] == 1
    assert bundle["per_class"]["b"]["support"] == 1
    assert bundle["per_class"]["c"]["support"] == 2
    assert bundle["metrics"]["roc_auc"]["status"] == "computed"


def test_calibration_and_threshold_selection_are_scoped_to_development_oof() -> None:
    calibration = compute_calibration_bins([0, 1, 0, 1], [0.1, 0.9, 0.2, 0.8], n_bins=2)
    assert calibration["status"] == "computed"
    assert calibration["sample_scope"] == "development_oof"
    assert calibration["expected_calibration_error"] == pytest.approx(0.15)

    curve = threshold_curve(
        [0, 0, 1, 1],
        [0.1, 0.4, 0.7, 0.9],
        thresholds=(0.25, 0.5, 0.75),
        positive_class=1,
    )
    assert [row["threshold"] for row in curve] == [0.25, 0.5, 0.75]
    selected = select_threshold_from_oof(
        actual=[0, 0, 1, 1],
        probabilities=[0.1, 0.4, 0.7, 0.9],
        method="max_f1",
        scope="development_oof",
        positive_class=1,
    )
    assert selected["status"] == "frozen_development_choice"
    assert selected["scope"] == "development_oof"
    with pytest.raises(ContractError) as error:
        select_threshold_from_oof(
            actual=[0, 1],
            probabilities=[0.2, 0.8],
            method="max_f1",
            scope="outer_validation",
            positive_class=1,
        )
    assert error.value.code == "CLASSIFICATION_THRESHOLD_SCOPE_INVALID"


def test_expected_utility_threshold_applies_declared_costs_and_rate_capacity() -> None:
    selected = select_threshold_from_oof(
        actual=[0, 0, 1, 1],
        probabilities=[0.1, 0.4, 0.7, 0.9],
        method="expected_utility",
        scope="development_oof",
        positive_class=1,
        thresholds=(0.25, 0.5, 0.75),
        cost_matrix={
            "true_positive": 0,
            "true_negative": 0,
            "false_positive": 5,
            "false_negative": 1,
        },
        capacity=0.5,
        capacity_unit="rate",
    )

    assert selected["status"] == "frozen_development_choice"
    assert selected["threshold"] == 0.5
    assert selected["capacity_constraint"]["status"] == "applied"
    assert selected["selection_basis"]["cost_matrix"] == {
        "false_negative": 1.0,
        "false_positive": 5.0,
        "true_negative": 0.0,
        "true_positive": 0.0,
    }


def test_decision_policy_rejects_non_numeric_costs_and_ambiguous_capacity_units() -> None:
    with pytest.raises(ContractError) as error:
        DecisionPolicyV1(
            cost_matrix={"false_positive": "unknown", "false_negative": 1},
            capacity=0.5,
            abstain_allowed=False,
            manual_review_allowed=False,
            threshold_scope="development_oof",
            threshold_method="expected_utility",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ).validate()
    assert error.value.code == "CLASSIFICATION_POLICY_COSTS_INVALID"

    with pytest.raises(ContractError) as error:
        DecisionPolicyV1(
            cost_matrix={"false_positive": 5, "false_negative": 1},
            capacity=0.5,
            capacity_unit="ambiguous",
            abstain_allowed=False,
            manual_review_allowed=False,
            threshold_scope="development_oof",
            threshold_method="expected_utility",
            policy_version="1.0",
            population="snapshot",
            time_validity="snapshot",
        ).validate()
    assert error.value.code == "CLASSIFICATION_POLICY_CAPACITY_INVALID"


def test_permutation_explanations_are_validation_only_seeded_and_non_causal() -> None:
    frame, target = _validation_data()

    def predict_proba(validation_frame: pd.DataFrame) -> np.ndarray:
        signal = validation_frame["signal"].to_numpy(dtype=float)
        positive = 1.0 / (1.0 + np.exp(-signal))
        return np.column_stack((1.0 - positive, positive))

    first = compute_permutation_explanations(
        frame,
        target,
        model_id="logistic_regression",
        predict_proba=predict_proba,
        validation_row_refs=tuple(f"v{i}" for i in range(len(frame))),
        feature_mapping={"signal": "signal", "noise": "noise"},
        seed=19,
        repeats=4,
        class_order=(0, 1),
        positive_class=1,
        sample_scope="outer_validation",
        minimum_support=4,
    )
    second = compute_permutation_explanations(
        frame,
        target,
        model_id="logistic_regression",
        predict_proba=predict_proba,
        validation_row_refs=tuple(f"v{i}" for i in range(len(frame))),
        feature_mapping={"signal": "signal", "noise": "noise"},
        seed=19,
        repeats=4,
        class_order=(0, 1),
        positive_class=1,
        sample_scope="outer_validation",
        minimum_support=4,
    )

    assert first == second
    assert first["causal_interpretation"] == "not_causal"
    assert first["sample_scope"] == "outer_validation"
    assert first["support"]["status"] == "adequate"
    assert {row["feature"] for row in first["importance"]} == {"signal", "noise"}
    assert all("stability_std" in row and "repeats" in row for row in first["importance"])

    with pytest.raises(ContractError) as error:
        compute_permutation_explanations(
            frame,
            target,
            model_id="logistic_regression",
            predict_proba=predict_proba,
            validation_row_refs=tuple(f"v{i}" for i in range(len(frame))),
            feature_mapping={"signal": "signal", "noise": "noise"},
            seed=19,
            sample_scope="training",
        )
    assert error.value.code == "CLASSIFICATION_EXPLANATION_SCOPE_INVALID"


def test_explanations_and_shift_claims_mark_low_support_without_causal_inference() -> None:
    frame, target = _validation_data()

    def predict_proba(validation_frame: pd.DataFrame) -> np.ndarray:
        positive = np.full(len(validation_frame), 0.5)
        return np.column_stack((1.0 - positive, positive))

    result = compute_permutation_explanations(
        frame.iloc[:3],
        target.iloc[:3],
        model_id="random_forest",
        predict_proba=predict_proba,
        validation_row_refs=("v0", "v1", "v2"),
        feature_mapping={"signal": "signal", "noise": "noise"},
        seed=1,
        repeats=2,
        class_order=(0, 1),
        positive_class=1,
        sample_scope="outer_validation",
        minimum_support=4,
    )
    assert result["status"] == "insufficient_support"
    assert result["support"]["status"] == "insufficient_support"
    assert result["causal_interpretation"] == "not_causal"
    assert result["importance"] == []

    shift = summarize_shift(
        development=pd.DataFrame({"x": [1.0, 2.0], "z": ["a", "b"]}),
        validation=pd.DataFrame({"x": [2.0, 3.0], "z": ["c", "d"]}),
        subgroup_values={"small": ["a", "b"]},
        minimum_support=3,
    )
    assert shift["interpretation"] == "descriptive_not_deployment_safety"
    assert shift["causal_interpretation"] == "not_causal"
    assert shift["subgroups"]["small"]["status"] == "insufficient_support"


def _probability_calibrator_kwargs(method: str) -> dict[str, object]:
    return {
        "method": method,
        "fit_probabilities": [0.02, 0.08, 0.18, 0.31, 0.62, 0.77, 0.91, 0.98],
        "fit_labels": [0, 0, 0, 0, 1, 1, 1, 1],
        "fit_scope": "development_oof",
        "fit_row_refs": tuple(f"oof-{index}" for index in range(8)),
        "seed": 23,
        "recipe": {
            "recipe_id": "classification.probability-calibration",
            "version": "1.0",
            "method": method,
        },
        "evidence_receipt": {
            "receipt_id": "receipt:calibration:1",
            "source_artifacts": ["artifact:development-oof"],
            "validation_level": "validated",
        },
        "class_order": (0, 1),
        "positive_class": 1,
    }


def test_probability_calibrator_identity_is_typed_and_transforms_oof_and_holdout() -> None:
    calibrator = classification_metrics_module.fit_probability_calibrator(**_probability_calibrator_kwargs("none"))

    assert isinstance(calibrator, classification_metrics_module.ProbabilityCalibratorV1)
    assert np.allclose(
        calibrator.transform([0.0, 0.25, 1.0], sample_scope="development_oof"),
        [0.0, 0.25, 1.0],
    )
    assert np.allclose(
        calibrator.transform([0.1, 0.5, 0.9], sample_scope="outer_holdout"),
        [0.1, 0.5, 0.9],
    )

    evidence = calibrator.evidence()
    assert evidence["method"] == "none"
    assert evidence["fit_scope"] == "development_oof"
    assert evidence["fit_row_refs"] == [f"oof-{index}" for index in range(8)]
    assert evidence["seed"] == 23
    assert evidence["recipe"]["recipe_id"] == "classification.probability-calibration"
    assert evidence["evidence_receipt"]["receipt_id"] == "receipt:calibration:1"
    assert evidence["numerical_method"] == "identity"
    assert evidence["independent_oracle"] is False


@pytest.mark.parametrize("method", ["platt", "isotonic"])
def test_probability_calibrator_sklearn_methods_transform_without_holdout_labels(method: str) -> None:
    calibrator = classification_metrics_module.fit_probability_calibrator(**_probability_calibrator_kwargs(method))

    oof_output = calibrator.transform([0.05, 0.35, 0.65, 0.95], sample_scope="development_oof")
    holdout_output = calibrator.transform([0.01, 0.5, 0.99], sample_scope="outer_holdout")

    assert oof_output.shape == (4,)
    assert holdout_output.shape == (3,)
    assert np.isfinite(oof_output).all()
    assert np.isfinite(holdout_output).all()
    assert ((oof_output >= 0) & (oof_output <= 1)).all()
    assert ((holdout_output >= 0) & (holdout_output <= 1)).all()
    assert calibrator.evidence()["numerical_method"] == "sklearn_1.x"
    assert calibrator.evidence()["independent_oracle"] is False


def test_probability_calibrator_rejects_unknown_method_wrong_scope_non_binary_and_duplicate_refs() -> None:
    with pytest.raises(ContractError) as error:
        classification_metrics_module.fit_probability_calibrator(**_probability_calibrator_kwargs("beta"))
    assert error.value.code == "CLASSIFICATION_CALIBRATOR_METHOD_INVALID"

    wrong_scope = _probability_calibrator_kwargs("none")
    wrong_scope["fit_scope"] = "final_holdout"
    with pytest.raises(ContractError) as error:
        classification_metrics_module.fit_probability_calibrator(**wrong_scope)
    assert error.value.code == "CLASSIFICATION_CALIBRATOR_SCOPE_INVALID"

    non_binary = _probability_calibrator_kwargs("none")
    non_binary["fit_probabilities"] = [0.1, 0.2, 0.3]
    non_binary["fit_labels"] = [0, 1, 2]
    non_binary["fit_row_refs"] = ("oof-0", "oof-1", "oof-2")
    with pytest.raises(ContractError) as error:
        classification_metrics_module.fit_probability_calibrator(**non_binary)
    assert error.value.code == "CLASSIFICATION_CALIBRATOR_LABEL_INVALID"

    duplicate_refs = _probability_calibrator_kwargs("none")
    duplicate_refs["fit_row_refs"] = ("oof-0", "oof-0", "oof-2", "oof-3", "oof-4", "oof-5", "oof-6", "oof-7")
    with pytest.raises(ContractError) as error:
        classification_metrics_module.fit_probability_calibrator(**duplicate_refs)
    assert error.value.code == "CLASSIFICATION_CALIBRATOR_FIT_REFS_INVALID"


@pytest.mark.parametrize("bad_probability", [[0.1, None, 0.9], [0.1, np.nan, 0.9], [0.1, np.inf, 0.9]])
def test_probability_calibrator_rejects_missing_or_non_finite_fit_probabilities(bad_probability: list[object]) -> None:
    invalid = _probability_calibrator_kwargs("none")
    invalid["fit_probabilities"] = bad_probability
    invalid["fit_labels"] = [0, 1, 1]
    invalid["fit_row_refs"] = ("oof-0", "oof-1", "oof-2")

    with pytest.raises(ContractError) as error:
        classification_metrics_module.fit_probability_calibrator(**invalid)
    assert error.value.code == "CLASSIFICATION_CALIBRATOR_INPUT_INVALID"


def test_probability_calibrator_transform_rejects_holdout_labels_by_contract_and_invalid_scope() -> None:
    calibrator = classification_metrics_module.fit_probability_calibrator(**_probability_calibrator_kwargs("none"))

    with pytest.raises(TypeError):
        calibrator.transform([0.1, 0.9], sample_scope="outer_holdout", labels=[0, 1])

    with pytest.raises(ContractError) as error:
        calibrator.transform([0.1, 0.9], sample_scope="training")
    assert error.value.code == "CLASSIFICATION_CALIBRATOR_TRANSFORM_SCOPE_INVALID"

    with pytest.raises(ContractError) as error:
        calibrator.transform([0.1, np.nan], sample_scope="outer_holdout")
    assert error.value.code == "CLASSIFICATION_CALIBRATOR_TRANSFORM_INPUT_INVALID"


def _protocol_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 3,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 3,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 3,
        }
    )


def test_protocol_releases_predeclared_holdout_subgroups_and_shift_evidence() -> None:
    frame = pd.DataFrame(
        {
            "signal": [-2.0, -1.5, -1.0, -0.5, 0.5, 1.0, 1.5, 2.0] * 5,
            "noise": [0.1, -0.2, 0.4, 0.8, -0.3, 0.2, -0.6, 0.5] * 5,
            "segment": ["A"] * 20 + ["B"] * 20,
            "target": [0, 0, 0, 0, 1, 1, 1, 1] * 5,
        }
    )
    plan = ClassificationDiagnosticsPlanV1(
        subgroup_columns=("segment",),
        shift_columns=("signal", "noise"),
        minimum_support=2,
        bins=4,
    )

    result = run_classification_protocol(
        frame,
        task=_protocol_task(),
        model_ids=("logistic_regression",),
        decision_policy=_protocol_policy(),
        calibration_method="none",
        diagnostics_plan=plan,
    )

    diagnostics = result["evaluation"]["diagnostics"]
    assert diagnostics["status"] == "computed"
    assert diagnostics["plan_hash"] == plan.content_hash
    assert diagnostics["plan"]["bins"] == 4
    assert diagnostics["plan"]["statistics"] == ["mean", "distribution"]
    assert {row["column"] for row in diagnostics["subgroups"]} == {"segment"}
    assert {row["value"] for row in diagnostics["subgroups"]} == {"A", "B"}
    assert all(row["sample_scope"] == "final_holdout_subgroup" for row in diagnostics["subgroups"])
    assert diagnostics["shift"]["status"] == "descriptive"
    assert diagnostics["shift"]["bin_count"] == 4
    assert result["holdout_boundary"]["access_count"] == 1
    assert result["artifact_refs"]["diagnostics"].startswith("artifact:diagnostics:")
    projected = project_classification_evidence(result, consumer="report")
    assert projected["evaluation"]["diagnostics"] == diagnostics
    assert projected["derived_from_raw_rows"] is False


def test_diagnostics_plan_never_treats_declared_columns_as_model_features() -> None:
    frame = _protocol_frame().assign(segment=["A", "B"] * 12)
    plan = ClassificationDiagnosticsPlanV1(
        subgroup_columns=("segment",),
        shift_columns=("signal",),
        minimum_support=2,
    )

    result = run_classification_protocol(
        frame,
        task=_protocol_task(),
        model_ids=("logistic_regression",),
        decision_policy=_protocol_policy(),
        calibration_method="none",
        diagnostics_plan=plan,
    )

    assert result["task"]["feature_columns"] == ["signal", "noise"]
    assert result["artifact_refs"]["dataset"]
    assert result["evaluation"]["diagnostics"]["plan_hash"] == plan.content_hash


def test_holdout_seal_rejects_unplanned_diagnostic_fields() -> None:
    seal = HoldoutSealV1(
        data_hash="sha256:" + "a" * 64,
        split_hash="sha256:" + "b" * 64,
        metric_release_plan={
            "metrics": ["accuracy"],
            "sections": ["selected_model", "diagnostics"],
            "metrics_by_section": {"selected_model": ["accuracy"]},
            "section_fields": {"diagnostics": ["status", "plan_hash", "plan", "subgroups", "shift"]},
            "subgroups": [],
        },
    )

    with pytest.raises(ContractError) as error:
        seal.consume(
            {
                "selected_model": {"metrics": {"accuracy": {"point_estimate": 0.8}}},
                "diagnostics": {
                    "status": "computed",
                    "plan_hash": "sha256:" + "c" * 64,
                    "subgroups": [],
                    "shift": {"status": "descriptive"},
                    "unplanned": "must be rejected",
                },
            }
        )

    assert error.value.code == "CLASSIFICATION_HOLDOUT_RELEASE_PLAN_MISMATCH"


def _protocol_task(
    *,
    max_trials: int | None = 2,
    primary_metric: str = "roc_auc",
    resource_budget: dict[str, object] | None = None,
) -> ClassificationTaskSpecV1:
    budget = (
        {"max_trials": max_trials, "max_cpu_seconds": 30}
        if resource_budget is None and max_trials is not None
        else (resource_budget if resource_budget is not None else {"max_cpu_seconds": 30})
    )
    return ClassificationTaskSpecV1(
        target_column="target",
        task_type="binary",
        class_mapping={0: "negative", 1: "positive"},
        positive_class="positive",
        feature_columns=("signal", "noise"),
        feature_availability=(
            FeatureAvailabilityContractV1("signal", "t0", "t0", "t1", "recipe:signal", "validated"),
            FeatureAvailabilityContractV1("noise", "t0", "t0", "t1", "recipe:noise", "validated"),
        ),
        label_definition=LabelDefinitionV1("observed target", None, None, None, "frozen_snapshot"),
        structure=StructureSpecV1(kind="iid", provenance="user_confirmed"),
        primary_metric=primary_metric,
        secondary_metrics=("accuracy", "log_loss"),
        split_profile="iid_stratified",
        seed=17,
        resource_budget=budget,
    )


def _protocol_policy() -> DecisionPolicyV1:
    return DecisionPolicyV1(
        cost_matrix=None,
        capacity=None,
        abstain_allowed=True,
        manual_review_allowed=True,
        threshold_scope="development_oof",
        threshold_method="max_f1",
        policy_version="1.0",
        population="snapshot",
        time_validity="snapshot",
    )


def test_protocol_blocks_unvalidated_availability_before_any_holdout_or_model_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.predictive_research.classification_protocol as protocol_module

    task = replace(
        _protocol_task(),
        allow_exploration=True,
        feature_availability=(
            FeatureAvailabilityContractV1("signal", None, None, None, None, "unknown"),
            FeatureAvailabilityContractV1("noise", None, None, None, None, "unknown"),
        ),
    )

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("unvalidated availability must stop before this boundary")

    for name in (
        "_dataset_hash",
        "_fit_fold_transform",
        "build_classification_split_manifest",
        "get_classification_adapter",
    ):
        monkeypatch.setattr(protocol_module, name, forbidden)
    monkeypatch.setattr(protocol_module.HoldoutSealV1, "release", forbidden)

    result = run_classification_protocol(
        _protocol_frame(),
        task=task,
        model_ids=("logistic_regression",),
        decision_policy=_protocol_policy(),
        calibration_method="none",
    )

    assert result["status"] == "blocked"
    assert result["models"] == []
    assert result["selected_model"] is None
    assert result["evaluation"] == {"status": "unavailable", "metrics": {}}
    assert result["calibration"]["status"] == "unavailable"
    assert result["baselines"] == []
    assert result["controls"] == []
    assert result["comparison"]["status"] == "unavailable"
    assert result["explanations"]["status"] == "unavailable"
    assert result["holdout_boundary"]["status"] == "blocked"
    assert result["holdout_boundary"]["access_count"] == 0


def test_protocol_fails_closed_when_selectable_threshold_selection_is_undefined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import workbench.predictive_research.classification_protocol as protocol_module

    def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("undefined threshold selection must stop before holdout release")

    monkeypatch.setattr(protocol_module.HoldoutSealV1, "release", forbidden)
    policy = replace(
        _protocol_policy(),
        cost_matrix={"false_positive": 1, "false_negative": 1},
        capacity=1.0,
        threshold_method="min_log_loss",
    )

    with pytest.raises(ContractError) as error:
        run_classification_protocol(
            _protocol_frame(),
            task=_protocol_task(),
            model_ids=("logistic_regression",),
            decision_policy=policy,
            calibration_method="none",
        )

    assert error.value.code == "CLASSIFICATION_THRESHOLD_SELECTION_UNDEFINED"


def test_protocol_emits_bounded_search_receipt_without_holdout_search() -> None:
    result = run_classification_protocol(
        _protocol_frame(),
        task=_protocol_task(),
        model_ids=("logistic_regression", "random_forest"),
        decision_policy=_protocol_policy(),
        calibration_method="none",
    )

    receipt = result["comparison"]["search_receipt"]
    assert receipt["candidate_model_ids"] == ["logistic_regression", "random_forest"]
    assert receipt["candidate_count"] == 2
    assert receipt["max_trials"] == 2
    assert receipt["trials_executed"] == 2
    assert receipt["seed"] == 17
    assert receipt["max_cpu_seconds"] == 30
    assert receipt["tuning_status"] == "not_requested"
    assert receipt["parameter_source"] == "adapter_defaults"
    assert receipt["search_scope"] == "development_only"
    assert receipt["holdout_access"] == "none"
    assert [trial["status"] for trial in receipt["trials"]] == ["completed", "completed"]
    assert all(trial["holdout_access"] == "none" for trial in receipt["trials"])


def test_search_receipt_declares_candidate_space_and_honest_cooperative_budget_policy() -> None:
    result = run_classification_protocol(
        _protocol_frame(),
        task=_protocol_task(),
        model_ids=("logistic_regression", "random_forest"),
        decision_policy=_protocol_policy(),
        calibration_method="none",
    )

    receipt = result["comparison"]["search_receipt"]

    assert receipt["candidate_space"] == {
        "kind": "model_adapters",
        "candidate_ids": ["logistic_regression", "random_forest"],
        "count": 2,
    }
    assert receipt["search_space"] == {
        "kind": "fixed_adapter_candidates",
        "model_ids": ["logistic_regression", "random_forest"],
        "parameter_search": "not_requested",
    }
    assert receipt["max_trials"] == 2
    assert receipt["max_cpu_seconds"] == 30
    assert receipt["seed"] == 17
    assert receipt["cancel_recovery_policy"] == {
        "cancel_mode": "cooperative_between_trials",
        "recovery_mode": "resume_from_last_completed_trial",
        "retry_policy": "no_automatic_retry",
    }
    assert receipt["resource_enforcement"] == {
        "status": "cooperative_bounded",
        "cpu_hard_kill": False,
        "reason": "no process-level CPU hard kill is implemented",
    }
    assert all(
        trial["status"] == "completed"
        and trial["cancel_recovery_status"] == "completed_without_recovery"
        for trial in receipt["trials"]
    )


def test_comparison_records_primary_oof_fold_distribution_without_fake_interval() -> None:
    result = run_classification_protocol(
        _protocol_frame(),
        task=_protocol_task(),
        model_ids=("logistic_regression",),
        decision_policy=_protocol_policy(),
        calibration_method="none",
    )

    candidate = result["comparison"]["candidates"][0]
    distribution = candidate["fold_distribution"]
    fold_scores = np.asarray(distribution["fold_scores"], dtype=float)

    assert candidate["model_id"] == "logistic_regression"
    assert candidate["primary_metric"] == "roc_auc"
    assert candidate["development_oof_score"] == result["models"][0]["selection_score"]
    assert distribution["count"] == len(fold_scores) == 3
    assert distribution["mean"] == pytest.approx(float(fold_scores.mean()))
    assert distribution["std"] == pytest.approx(float(fold_scores.std()))
    assert distribution["min"] == pytest.approx(float(fold_scores.min()))
    assert distribution["max"] == pytest.approx(float(fold_scores.max()))
    assert distribution["interval"]["status"] == "unavailable"
    assert distribution["interval"]["reason"]
    assert distribution["resampling_unit"] == "row"


def test_comparison_contains_paired_prediction_refs_uncertainty_state_and_descriptive_pareto_tradeoff() -> None:
    result = run_classification_protocol(
        _protocol_frame(),
        task=_protocol_task(),
        model_ids=("logistic_regression", "random_forest"),
        decision_policy=_protocol_policy(),
        calibration_method="none",
    )

    comparison = result["comparison"]
    paired = comparison["paired_prediction_refs"]

    assert comparison["resampling_unit"] == "row"
    assert paired["sample_scope"] == "development_oof"
    assert paired["holdout_access"] == "none"
    assert all("holdout" not in ref for ref in paired["row_refs"])
    assert paired["row_refs"] == result["models"][0]["oof_row_refs"]
    assert len(paired["row_prediction_refs"]) == len(paired["row_refs"])
    assert all(
        set(item["prediction_refs"]) == {"logistic_regression", "random_forest"}
        for item in paired["row_prediction_refs"]
    )
    assert len(paired["fold_prediction_refs"]) == 3
    assert all(item["resampling_unit"] == "row" for item in paired["fold_prediction_refs"])
    assert all(
        set(item["prediction_refs"]) == {"logistic_regression", "random_forest"}
        for item in paired["fold_prediction_refs"]
    )
    assert comparison["uncertainty"] == {
        "status": "unavailable",
        "reason": "no predeclared independent interval method is available for paired model comparison",
    }
    assert comparison["evidence_state"] == {
        "status": "sufficient",
        "insufficient_evidence": False,
        "reason": "paired development OOF row and fold prediction references are complete",
    }
    assert comparison["insufficient_evidence_state"] == {
        "status": "not_present",
        "reason": "paired development OOF row and fold prediction references are complete",
    }
    pareto = comparison["pareto_tradeoff"]
    assert pareto["status"] == "descriptive"
    assert pareto["causal_interpretation"] == "not_causal"
    assert {objective["metric"] for objective in pareto["objectives"]} >= {"roc_auc", "accuracy", "log_loss"}
    assert set(pareto["frontier_model_ids"]) <= {"logistic_regression", "random_forest"}
    assert len(pareto["tradeoffs"]) == 2


def test_protocol_fails_closed_when_candidates_exceed_or_omit_max_trials() -> None:
    with pytest.raises(ContractError) as overflow:
        run_classification_protocol(
            _protocol_frame(),
            task=_protocol_task(max_trials=1),
            model_ids=("logistic_regression", "random_forest"),
            decision_policy=_protocol_policy(),
            calibration_method="none",
        )
    assert overflow.value.code == "CLASSIFICATION_SEARCH_BUDGET_EXCEEDED"

    with pytest.raises(ContractError) as missing:
        run_classification_protocol(
            _protocol_frame(),
            task=_protocol_task(resource_budget={"max_cpu_seconds": 30}),
            model_ids=("logistic_regression",),
            decision_policy=_protocol_policy(),
            calibration_method="none",
        )
    assert missing.value.code == "CLASSIFICATION_SEARCH_MAX_TRIALS_MISSING"


def test_comparison_declares_ties_tolerance_and_multiple_comparison_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TiedAdapter:
        def __init__(
            self,
            *,
            seed: int = 0,
            parameters: object | None = None,
            class_order: tuple[int, ...] | None = None,
            resource_budget: object | None = None,
        ) -> None:
            self.seed = seed
            self._class_order = tuple(class_order or (0, 1))
            self.parameters = dict(parameters or {})

        @property
        def metadata(self) -> dict[str, object]:
            return {
                "model_id": "fixture",
                "version": "1.0",
                "random_seed": self.seed,
                "actual_parameters": dict(self.parameters),
                "class_order": list(self._class_order),
                "supports_weight": True,
                "resource_class": "fixture",
                "resource_bounds": {"max_cpu_seconds": 30},
                "warnings": [],
            }

        def fit(
            self,
            features: pd.DataFrame,
            target: object,
            *,
            sample_weight: object | None = None,
            class_order: tuple[int, ...] | None = None,
        ) -> "_TiedAdapter":
            self._class_order = tuple(class_order or self._class_order)
            return self

        def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
            return np.tile(np.asarray([0.5, 0.5]), (len(features), 1))

        def predict(self, features: pd.DataFrame) -> np.ndarray:
            return np.asarray([self._class_order[0]] * len(features), dtype=object)

        def predict_at_threshold(
            self,
            features: pd.DataFrame,
            *,
            threshold: float,
            positive_class: object,
        ) -> np.ndarray:
            return self.predict(features)

    import workbench.predictive_research.classification_protocol as protocol_module

    monkeypatch.setattr(
        protocol_module,
        "get_classification_adapter",
        lambda model_id, **kwargs: _TiedAdapter(**kwargs),
    )
    result = run_classification_protocol(
        _protocol_frame(),
        task=_protocol_task(),
        model_ids=("fixture_a", "fixture_b"),
        decision_policy=_protocol_policy(),
        calibration_method="none",
    )

    comparison = result["comparison"]
    assert comparison["selected_model_id"] == "fixture_a"
    assert comparison["tied_model_ids"] == ["fixture_a", "fixture_b"]
    assert comparison["tie_policy"]["tolerance"] > 0
    assert comparison["tie_policy"]["selection"] == "first_candidate_in_input_order"
    assert comparison["tie_freeze_gate"] == {
        "status": "frozen",
        "selected_model_id": "fixture_a",
        "tied_model_ids": ["fixture_a", "fixture_b"],
        "requires_manual_review": True,
        "reason": "primary metric tie is frozen; no unique winner is claimed",
    }
    assert comparison["multiple_comparison_warning"]["status"] == "warning"
    for candidate in comparison["candidates"]:
        assert candidate["direction"] == "higher_is_better"
        assert candidate["raw_difference_vs_selected"] == 0.0
        assert candidate["direction_aware_difference_vs_selected"] == 0.0
