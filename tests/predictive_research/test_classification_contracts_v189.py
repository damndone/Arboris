from __future__ import annotations

import pytest

from workbench.predictive_research.classification_contracts import (
    ClassificationTaskSpecV1,
    DecisionPolicyV1,
    FeatureAvailabilityContractV1,
    LabelDefinitionV1,
    StageCapabilityV1,
    validate_weight_support,
)
from workbench.predictive_research.contracts import ContractError, StructureSpecV1


def _temporal_task(*, availability: tuple[FeatureAvailabilityContractV1, ...]) -> ClassificationTaskSpecV1:
    return ClassificationTaskSpecV1(
        target_column="label",
        task_type="binary",
        class_mapping={0: "negative", 1: "positive"},
        positive_class="positive",
        feature_columns=("age", "balance"),
        feature_availability=availability,
        label_definition=LabelDefinitionV1(
            target_construction="event_within_horizon",
            event_time="event_at",
            horizon="30d",
            purge_gap="30d",
            revision_policy="as_of_prediction_origin",
        ),
        structure=StructureSpecV1(kind="temporal", time_column="observed_at"),
        primary_metric="roc_auc",
        secondary_metrics=("log_loss", "brier_score"),
        split_profile="temporal_rolling",
        seed=7,
        resource_budget={"max_trials": 4, "max_seconds": 30},
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


def test_class_mapping_requires_explicit_positive_class_for_binary_tasks() -> None:
    task = _temporal_task(
        availability=(
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
    )
    invalid = task.__class__(**{**task.__dict__, "positive_class": None})

    with pytest.raises(ContractError) as exc_info:
        invalid.validate()

    assert exc_info.value.code == "CLASSIFICATION_POSITIVE_CLASS_REQUIRED"


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
