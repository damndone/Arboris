from __future__ import annotations

import numpy as np
import pytest

import workbench.predictive_research.classification_metrics as classification_metrics_module
from workbench.predictive_research.classification_contracts import (
    ClassificationDiagnosticsPlanV1,
    ClassificationSplitSpecV1,
    ClassificationTaskSpecV1,
    DecisionPolicyV1,
    FeatureAvailabilityContractV1,
    LabelDefinitionV1,
    StageCapabilityV1,
    validate_weight_support,
)
from workbench.predictive_research.contracts import ContractError, StructureSpecV1


def _temporal_task(
    *,
    availability: tuple[FeatureAvailabilityContractV1, ...],
    **overrides: object,
) -> ClassificationTaskSpecV1:
    values: dict[str, object] = {
        "target_column": "label",
        "task_type": "binary",
        "class_mapping": {0: "negative", 1: "positive"},
        "positive_class": "positive",
        "feature_columns": ("age", "balance"),
        "feature_availability": availability,
        "label_definition": LabelDefinitionV1(
            target_construction="event_within_horizon",
            event_time="event_at",
            horizon="30d",
            purge_gap="30d",
            revision_policy="as_of_prediction_origin",
        ),
        "structure": StructureSpecV1(kind="temporal", time_column="observed_at"),
        "primary_metric": "roc_auc",
        "secondary_metrics": ("log_loss", "brier_score"),
        "split_profile": "temporal_rolling",
        "seed": 7,
        "resource_budget": {"max_trials": 4, "max_seconds": 30},
    }
    values.update(overrides)
    return ClassificationTaskSpecV1(**values)


def _validated_temporal_features() -> tuple[FeatureAvailabilityContractV1, ...]:
    return (
        FeatureAvailabilityContractV1(
            feature_name="age",
            observed_at="age_observed_at",
            available_at="age_available_at",
            prediction_origin="prediction_at",
            source_recipe="profile.age.v1",
            leakage_status="validated",
        ),
        FeatureAvailabilityContractV1(
            feature_name="balance",
            observed_at="balance_observed_at",
            available_at="balance_available_at",
            prediction_origin="prediction_at",
            source_recipe="profile.balance.v1",
            leakage_status="validated",
        ),
    )


def test_temporal_task_fails_closed_when_information_set_is_incomplete() -> None:
    task = _temporal_task(
        availability=(
            FeatureAvailabilityContractV1(
                feature_name="age",
                observed_at="age_observed_at",
                available_at=None,
                prediction_origin="prediction_at",
                source_recipe="profile.age.v1",
            ),
            FeatureAvailabilityContractV1(
                feature_name="balance",
                observed_at="balance_observed_at",
                available_at="balance_available_at",
                prediction_origin="prediction_at",
                source_recipe=None,
            ),
        )
    )

    with pytest.raises(ContractError) as exc_info:
        task.validate()

    assert exc_info.value.code == "CLASSIFICATION_INFORMATION_SET_INCOMPLETE"


def test_iid_unknown_availability_is_exploration_only_and_not_deployment_safe() -> None:
    task = ClassificationTaskSpecV1(
        target_column="label",
        task_type="binary",
        class_mapping={"no": "negative", "yes": "positive"},
        positive_class="positive",
        feature_columns=("x1",),
        feature_availability=(
            FeatureAvailabilityContractV1(
                feature_name="x1",
                observed_at=None,
                available_at=None,
                prediction_origin=None,
                source_recipe=None,
                leakage_status="unknown",
            ),
        ),
        label_definition=LabelDefinitionV1(
            target_construction="observed_label",
            event_time=None,
            horizon=None,
            purge_gap=None,
            revision_policy="fixed_snapshot",
        ),
        structure=StructureSpecV1(kind="iid"),
        primary_metric="balanced_accuracy",
        secondary_metrics=(),
        split_profile="iid_stratified",
        seed=11,
        resource_budget={"max_trials": 1},
        allow_exploration=True,
    )

    task.validate()

    assert task.deployment_safe is False
    assert task.availability_status == "UNKNOWN_EXPLORATION_ONLY"


def test_unknown_availability_without_exploration_is_blocked_for_iid() -> None:
    task = ClassificationTaskSpecV1(
        target_column="label",
        task_type="binary",
        class_mapping={0: "negative", 1: "positive"},
        positive_class="positive",
        feature_columns=("x1",),
        feature_availability=(FeatureAvailabilityContractV1("x1", None, None, None, None),),
        label_definition=LabelDefinitionV1("observed_label", None, None, None, "fixed_snapshot"),
        structure=StructureSpecV1(kind="iid"),
        primary_metric="accuracy",
        secondary_metrics=(),
        split_profile="iid_stratified",
        seed=1,
        resource_budget={},
    )

    with pytest.raises(ContractError) as exc_info:
        task.validate()

    assert exc_info.value.code == "CLASSIFICATION_INFORMATION_SET_INCOMPLETE"


def test_class_mapping_requires_explicit_positive_class_for_binary_tasks() -> None:
    task = _temporal_task(availability=_validated_temporal_features())
    invalid = task.__class__(**{**task.__dict__, "positive_class": None})

    with pytest.raises(ContractError) as exc_info:
        invalid.validate()

    assert exc_info.value.code == "CLASSIFICATION_POSITIVE_CLASS_REQUIRED"


def test_class_mapping_rejects_duplicate_canonical_labels() -> None:
    task = _temporal_task(
        availability=_validated_temporal_features(),
        class_mapping={0: "same", 1: "same"},
    )

    with pytest.raises(ContractError) as exc_info:
        task.validate()

    assert exc_info.value.code == "CLASSIFICATION_CLASS_MAPPING_INVALID"


def test_weight_declaration_fails_when_any_learned_stage_does_not_support_weights() -> None:
    stages = (
        StageCapabilityV1(stage_id="preprocess", stage_kind="preprocessing", supports_weight=True),
        StageCapabilityV1(stage_id="selector", stage_kind="feature_selection", supports_weight=False),
    )

    with pytest.raises(ContractError) as exc_info:
        validate_weight_support(stages, declared_weight="analysis_weight")

    assert exc_info.value.code == "CLASSIFICATION_WEIGHT_UNSUPPORTED"


def test_unknown_decision_costs_produce_scenarios_only_not_selected_policy() -> None:
    policy = DecisionPolicyV1(
        cost_matrix=None,
        capacity=None,
        abstain_allowed=True,
        manual_review_allowed=True,
        threshold_scope="development_oof",
        threshold_method="expected_utility",
        policy_version="1.0",
        population="all",
        time_validity="not_declared",
    )

    policy.validate()

    assert policy.selection_status == "SCENARIOS_ONLY"
    assert policy.selected_threshold is None


def test_empty_decision_costs_are_unknown_scenarios_not_a_selected_policy() -> None:
    policy = DecisionPolicyV1(
        cost_matrix={},
        capacity=10,
        abstain_allowed=False,
        manual_review_allowed=False,
        threshold_scope="development_oof",
        threshold_method="expected_utility",
        policy_version="1.0",
        population="all",
        time_validity="not_declared",
    )

    policy.validate()

    assert policy.selection_status == "SCENARIOS_ONLY"


def test_split_contract_requires_explicit_embargo_basis() -> None:
    split = ClassificationSplitSpecV1(
        profile="temporal_rolling",
        final_holdout_fraction=0.2,
        cv_folds=3,
        random_seed=4,
        embargo=1,
        embargo_basis=None,
    )

    with pytest.raises(ContractError) as exc_info:
        split.validate()

    assert exc_info.value.code == "CLASSIFICATION_EMBARGO_BASIS_REQUIRED"


def test_selected_threshold_requires_known_cost_and_capacity() -> None:
    policy = DecisionPolicyV1(
        cost_matrix=None,
        capacity=None,
        abstain_allowed=False,
        manual_review_allowed=False,
        threshold_scope="development_oof",
        threshold_method="fixed",
        policy_version="1.0",
        population="all",
        time_validity="not_declared",
        selected_threshold=0.5,
    )

    with pytest.raises(ContractError) as exc_info:
        policy.validate()

    assert exc_info.value.code == "CLASSIFICATION_POLICY_COSTS_REQUIRED"


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("statistics", ("p_value",)),
        ("multiplicity_policy", "bonferroni_not_implemented"),
    ),
)
def test_diagnostics_plan_rejects_undeclared_or_unimplemented_evidence_semantics(
    field: str,
    value: object,
) -> None:
    plan = ClassificationDiagnosticsPlanV1(**{field: value})

    with pytest.raises(ContractError) as exc_info:
        plan.validate()

    assert exc_info.value.code == "CLASSIFICATION_DIAGNOSTICS_PLAN_INVALID"


def test_diagnostics_plan_freezes_sequence_inputs_before_hashing() -> None:
    subgroup_columns = ["segment"]
    statistics = ["mean", "distribution"]
    plan = ClassificationDiagnosticsPlanV1(
        subgroup_columns=subgroup_columns,
        statistics=statistics,
    )

    subgroup_columns.append("unexpected")
    statistics.clear()

    assert plan.subgroup_columns == ("segment",)
    assert plan.statistics == ("mean", "distribution")
    assert plan.content_hash.startswith("sha256:")


def test_valid_task_serializes_explicit_mapping_and_availability_status() -> None:
    task = _temporal_task(availability=_validated_temporal_features(), weights="analysis_weight")

    task.validate()
    payload = task.to_dict()

    assert payload["class_mapping"] == {"0": "negative", "1": "positive"}
    assert payload["weights"] == "analysis_weight"
    assert payload["availability_status"] == "VALIDATED"
    assert task.content_hash.startswith("sha256:")


def _calibrator_kwargs(method: str) -> dict[str, object]:
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
            "receipt_id": "receipt:calibration:weights",
            "source_artifacts": ["artifact:development-oof"],
            "validation_level": "validated",
        },
        "class_order": (0, 1),
        "positive_class": 1,
    }


@pytest.mark.parametrize("method", ["platt", "isotonic"])
def test_probability_calibrator_passes_sample_weight_to_sklearn_and_records_weight_evidence(
    method: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[np.ndarray | None] = []
    if method == "platt":
        original_fit = classification_metrics_module.LogisticRegression.fit

        def capture_fit(model: object, features: object, labels: object, sample_weight: object = None, **kwargs: object) -> object:
            observed.append(None if sample_weight is None else np.asarray(sample_weight, dtype=float))
            return original_fit(model, features, labels, sample_weight=sample_weight, **kwargs)

        monkeypatch.setattr(classification_metrics_module.LogisticRegression, "fit", capture_fit)
    else:
        original_fit = classification_metrics_module.IsotonicRegression.fit

        def capture_fit(model: object, features: object, labels: object, sample_weight: object = None, **kwargs: object) -> object:
            observed.append(None if sample_weight is None else np.asarray(sample_weight, dtype=float))
            return original_fit(model, features, labels, sample_weight=sample_weight, **kwargs)

        monkeypatch.setattr(classification_metrics_module.IsotonicRegression, "fit", capture_fit)

    weights = np.asarray([1, 2, 1, 3, 2, 4, 1, 5], dtype=float)
    kwargs = _calibrator_kwargs(method)
    kwargs["sample_weight"] = weights
    calibrator = classification_metrics_module.fit_probability_calibrator(**kwargs)

    assert len(observed) == 1
    assert np.array_equal(observed[0], weights)
    evidence = calibrator.evidence()
    assert evidence["weighted_fit"] is True
    assert evidence["weight_sum"] == pytest.approx(float(weights.sum()))
    assert evidence["effective_sample_size"] == pytest.approx(float(weights.sum() ** 2 / np.square(weights).sum()))


def test_probability_calibrator_none_keeps_identity_with_explicit_weights() -> None:
    kwargs = _calibrator_kwargs("none")
    kwargs["sample_weight"] = [1.0, 2.0, 1.0, 3.0, 2.0, 4.0, 1.0, 5.0]
    calibrator = classification_metrics_module.ProbabilityCalibratorV1.fit(**kwargs)

    assert np.array_equal(
        calibrator.transform([0.0, 0.25, 1.0], sample_scope="outer_holdout"),
        np.asarray([0.0, 0.25, 1.0]),
    )
    evidence = calibrator.evidence()
    assert evidence["weighted_fit"] is True
    assert evidence["weight_sum"] == pytest.approx(19.0)
    assert evidence["effective_sample_size"] == pytest.approx(19.0**2 / 61.0)


@pytest.mark.parametrize(
    "sample_weight",
    [
        [-1.0] + [1.0] * 7,
        [0.0] * 8,
        [1.0, np.nan, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        [1.0, np.inf, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        [1e308] * 8,
        ["bad"] * 8,
        [1.0, 1.0],
    ],
)
def test_probability_calibrator_rejects_invalid_sample_weight(sample_weight: object) -> None:
    kwargs = _calibrator_kwargs("none")
    kwargs["sample_weight"] = sample_weight

    with pytest.raises(ContractError) as exc_info:
        classification_metrics_module.fit_probability_calibrator(**kwargs)

    assert exc_info.value.code == "CLASSIFICATION_WEIGHT_INVALID"
