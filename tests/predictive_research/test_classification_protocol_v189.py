from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from workbench.predictive_research.classification_adapters import (
    adapter_registry,
    get_classification_adapter,
)
from workbench.predictive_research.classification_metrics import (
    classification_metric_bundle,
    compute_calibration_bins,
    threshold_curve,
)
from workbench.predictive_research.classification_protocol import (
    BoundedSearchV1,
    HoldoutSealGuardV1,
    run_classification_protocol,
    select_threshold_from_oof,
)
from workbench.predictive_research.contracts import ContractError


def _training_data() -> tuple[pd.DataFrame, pd.Series]:
    return (
        pd.DataFrame({"x1": [0.0, 0.2, 0.9, 1.1, 0.1, 1.0, 0.3, 0.8], "x2": [1, 2, 1, 2, 1, 2, 1, 2]}),
        pd.Series([0, 0, 1, 1, 0, 1, 0, 1], name="target"),
    )


def _derangement_blocked_training_data() -> tuple[pd.DataFrame, pd.Series]:
    return (
        pd.DataFrame(
            {
                "x1": [float(index) for index in range(12)],
                "x2": [float(index % 3) for index in range(12)],
            }
        ),
        pd.Series([0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1], name="target"),
    )


def test_logistic_and_random_forest_share_typed_adapter_contract() -> None:
    frame, target = _training_data()
    for model_id in ("logistic_regression", "random_forest"):
        adapter = get_classification_adapter(model_id, seed=13)
        adapter.fit(frame, target, sample_weight=np.ones(len(target)))
        probabilities = adapter.predict_proba(frame)

        assert probabilities.shape == (len(frame), 2)
        assert adapter.predict_at_threshold(frame, threshold=0.5).shape == (len(frame),)
        assert adapter.metadata["model_id"] == model_id
        assert adapter.metadata["random_seed"] == 13
        assert adapter.supports_weight is True
        assert adapter.feature_names == ("x1", "x2")
        assert adapter.resource_estimate["resource_class"] in {"small", "bounded"}


def test_unknown_adapter_does_not_fallback_to_another_estimator() -> None:
    with pytest.raises(ContractError) as exc_info:
        get_classification_adapter("xgboost")

    assert exc_info.value.code == "CLASSIFICATION_ADAPTER_UNKNOWN"
    assert set(adapter_registry()) == {"logistic_regression", "random_forest"}


def test_adapter_rejects_single_class_fit_and_probability_class_order_mismatch() -> None:
    frame, _ = _training_data()
    adapter = get_classification_adapter("logistic_regression")

    with pytest.raises(ContractError) as exc_info:
        adapter.fit(frame, pd.Series([1] * len(frame)))

    assert exc_info.value.code == "CLASSIFICATION_SINGLE_CLASS"


def test_metrics_preserve_undefined_reason_and_evidence_axes() -> None:
    bundle = classification_metric_bundle(
        actual=[0, 0, 1, 1],
        probabilities=[0.1, 0.4, 0.7, 0.9],
        predictions=[0, 0, 1, 1],
        positive_class=1,
        threshold=0.5,
        sample_scope="outer_validation",
        evaluation_design="stratified_holdout",
        numerical_method="known_answer",
        inference_basis="descriptive",
        validation_level="validated",
    )

    assert bundle["metrics"]["accuracy"]["point_estimate"] == 1.0
    assert bundle["metrics"]["roc_auc"]["point_estimate"] == 1.0
    assert bundle["metrics"]["accuracy"]["row_count"] == 4
    assert bundle["metrics"]["accuracy"]["sample_scope"] == "outer_validation"

    undefined = classification_metric_bundle(
        actual=[0, 0, 0],
        probabilities=[0.1, 0.2, 0.3],
        predictions=[0, 0, 0],
        positive_class=1,
        threshold=0.5,
        sample_scope="outer_validation",
        evaluation_design="iid",
        numerical_method="known_answer",
        inference_basis="descriptive",
        validation_level="validated",
    )
    assert undefined["metrics"]["roc_auc"]["status"] == "undefined"
    assert "class" in undefined["metrics"]["roc_auc"]["reason"]


def test_calibration_and_threshold_curves_are_explicitly_scoped() -> None:
    bins = compute_calibration_bins([0, 0, 1, 1], [0.1, 0.4, 0.7, 0.9], n_bins=2)
    curve = threshold_curve([0, 0, 1, 1], [0.1, 0.4, 0.7, 0.9], thresholds=(0.25, 0.5, 0.75))

    assert bins["method"] == "uniform_probability_bins"
    assert bins["sample_scope"] == "development_oof"
    assert [row["threshold"] for row in curve] == [0.25, 0.5, 0.75]


def test_holdout_guard_allows_one_complete_release_and_rejects_reopen_or_partial_reads() -> None:
    guard = HoldoutSealGuardV1(
        holdout_labels=[0, 1],
        holdout_probabilities=[0.2, 0.8],
        holdout_predictions=[0, 1],
        metric_release_plan={"metrics": ["accuracy", "log_loss"]},
    )

    with pytest.raises(ContractError) as exc_info:
        guard.read_labels()
    assert exc_info.value.code == "CLASSIFICATION_HOLDOUT_SEALED"

    released = guard.release(authorization="one-time")
    assert set(released["metrics"]) == {"accuracy", "log_loss"}

    with pytest.raises(ContractError) as exc_info:
        guard.release(authorization="one-time")
    assert exc_info.value.code == "CLASSIFICATION_HOLDOUT_RELEASE_REPEATED"


def test_holdout_release_plan_rejects_unknown_metric_instead_of_returning_none() -> None:
    with pytest.raises(ContractError) as exc_info:
        HoldoutSealGuardV1(
            holdout_labels=[0, 1],
            holdout_probabilities=[0.2, 0.8],
            holdout_predictions=[0, 1],
            metric_release_plan={"metrics": ["accuracy", "unknown_metric"]},
        )

    assert exc_info.value.code == "CLASSIFICATION_METRIC_RELEASE_PLAN_INVALID"


def test_bounded_search_rejects_unknown_parameter_and_holdout_access() -> None:
    search = BoundedSearchV1(
        candidates=("logistic_regression",),
        search_space={"C": (0.1, 1.0)},
        primary_metric="log_loss",
        max_trials=2,
        max_seconds=30,
        max_cpu_seconds=30,
        seed=7,
    )
    search.validate(allowed_parameters={"C"})
    with pytest.raises(ContractError) as exc_info:
        search.validate_candidate({"solver": "liblinear"}, allowed_parameters={"C"})
    assert exc_info.value.code == "CLASSIFICATION_SEARCH_PARAMETER_UNKNOWN"


def test_threshold_selection_uses_development_oof_only() -> None:
    selected = select_threshold_from_oof(
        actual=[0, 0, 1, 1],
        probabilities=[0.1, 0.4, 0.7, 0.9],
        method="max_f1",
        scope="development_oof",
    )
    assert 0 <= selected["threshold"] <= 1
    assert selected["scope"] == "development_oof"


def test_protocol_runs_both_adapters_without_exposing_holdout_labels() -> None:
    frame, target = _training_data()
    result = run_classification_protocol(
        frame,
        target,
        row_refs=tuple(f"r{i}" for i in range(len(frame))),
        model_ids=("logistic_regression", "random_forest"),
        final_holdout_fraction=0.25,
        cv_folds=2,
        seed=17,
    )

    assert set(result["models"]) == {"logistic_regression", "random_forest"}
    assert result["holdout"]["status"] == "released_once"
    assert "holdout_labels" not in result
    assert result["comparison"]["same_split"] is True
    for model in result["models"].values():
        assert model["calibration"]["status"] == "descriptive"
    assert result["baselines"]["majority"]["sample_scope"] == "development"
    assert result["controls"][0]["status"] == "computed"


def test_permuted_target_control_blocks_when_fold_support_cannot_derange() -> None:
    frame, target = _derangement_blocked_training_data()

    result = run_classification_protocol(
        frame,
        target,
        row_refs=tuple(f"skewed-r{i}" for i in range(len(frame))),
        model_ids=("logistic_regression",),
        final_holdout_fraction=0.25,
        cv_folds=2,
        seed=17,
    )

    assert result["status"] == "validated"
    assert len(result["controls"]) == 1
    control = result["controls"][0]
    assert control["control"] == "permuted_target"
    assert control["model_id"] == "logistic_regression"
    assert control["status"] == "blocked"
    assert control["reason_code"] == "CLASSIFICATION_CONTROL_DERANGEMENT_INSUFFICIENT_SUPPORT"
    assert control["evidence_level"] == "insufficient"
    assert control["exchangeability_unit"] == "row_within_development_fold"
    assert control["fold"] == 0
    assert control["fold_row_count"] == 5
    assert control["sample_scope"] == "development_oof"
    assert control["split_hash"].startswith("sha256:")
