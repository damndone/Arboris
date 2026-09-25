from __future__ import annotations

from dataclasses import replace

from workbench.predictive_research.classification_contracts import DecisionPolicyV1
from workbench.predictive_research.classification_protocol import run_classification_protocol
from workbench.predictive_research.classification_search import BoundedSearchV1
from workbench.predictive_research.contracts import StructureSpecV1

from test_v189_classification_production import (
    _ordered_frame,
    _ordered_task,
    _production_dependencies,
)


def _search_result(*, threshold_method: str, minimum_precision: float | None = None) -> dict:
    task = replace(
        _ordered_task(structure_kind="temporal", split_profile="temporal_rolling"),
        primary_metric="accuracy",
        structure=StructureSpecV1(kind="iid"),
        split_profile="iid_stratified",
    )
    cost_matrix = {"false_positive": 1.0, "false_negative": 2.0}
    if minimum_precision is not None:
        cost_matrix["minimum_precision"] = minimum_precision
    policy = DecisionPolicyV1(
        cost_matrix=cost_matrix,
        capacity=10,
        abstain_allowed=False,
        manual_review_allowed=False,
        threshold_scope="development_oof",
        threshold_method=threshold_method,
        policy_version="1.0",
        population="all",
        time_validity="declared",
    )
    return run_classification_protocol(
        _ordered_frame([period for period in range(8) for _ in range(2)]),
        task=task,
        row_refs=tuple(f"r{index}" for index in range(16)),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        seed=7,
        decision_policy=policy,
        bounded_search=BoundedSearchV1(
            candidates=("logistic_regression",),
            search_space={"C": (0.5,)},
            primary_metric="accuracy",
            max_trials=1,
            max_seconds=30,
            max_cpu_seconds=30,
            seed=7,
        ),
        **_production_dependencies(),
    )


def test_bounded_search_and_model_comparison_share_max_f1_threshold_rule() -> None:
    result = _search_result(threshold_method="max_f1")

    trial_metric = result["search"]["trials"][0]["metric"]
    model_metric = result["models"]["logistic_regression"]["oof_metrics"]["metrics"]["accuracy"]["point_estimate"]

    assert trial_metric == model_metric
    assert result["search"]["selection_scope"] == "development_oof"
    assert result["holdout"]["release_count"] == 1


def test_bounded_search_and_model_comparison_share_precision_constrained_rule() -> None:
    result = _search_result(threshold_method="max_recall_at_precision", minimum_precision=0.5)

    trial_metric = result["search"]["trials"][0]["metric"]
    model_metric = result["models"]["logistic_regression"]["oof_metrics"]["metrics"]["accuracy"]["point_estimate"]

    assert trial_metric == model_metric
    assert result["search"]["selection_scope"] == "development_oof"
    assert result["holdout"]["release_count"] == 1
