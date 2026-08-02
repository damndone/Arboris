from __future__ import annotations

import numpy as np
import pandas as pd

from workbench.predictive_research.contracts import (
    AvailabilitySpecV1,
    SampleSpecV1,
    SamplingSpecV1,
    SplitPlanV1,
    StructureSpecV1,
)
from workbench.predictive_research.prediction_protocol import run_oos_prediction
from workbench.predictive_research.split_kernel import build_split_plan


class LinearEstimator:
    def fit(self, features: pd.DataFrame, target: pd.Series) -> "LinearEstimator":
        design = np.column_stack([np.ones(len(features)), features.to_numpy(dtype=float)])
        self.coef_ = np.linalg.lstsq(design, target.to_numpy(dtype=float), rcond=None)[0]
        return self

    def predict(self, features: pd.DataFrame) -> list[float]:
        design = np.column_stack([np.ones(len(features)), features.to_numpy(dtype=float)])
        return (design @ self.coef_).tolist()


def test_negative_controls_produce_comparable_metrics_for_each_control() -> None:
    frame = pd.DataFrame(
        {
            "x": [float(index) for index in range(30)],
            "y": [3.0 * index + 2.0 for index in range(30)],
        },
        index=[f"row-{index}" for index in range(30)],
    )
    split = build_split_plan(
        row_refs=tuple(frame.index),
        strategy="iid",
        final_holdout_fraction=0.2,
        cv_folds=3,
        shuffle=True,
        random_seed=17,
    )
    sample_spec = SampleSpecV1(
        dataset_sha256="a" * 64,
        sampling=SamplingSpecV1(),
        split_plan=SplitPlanV1(
            strategy="iid",
            profile_id="iid_holdout_kfold",
            profile_version=1,
            effective_parameters=split.effective_parameters,
        ),
        structure=StructureSpecV1(kind="iid", provenance="user_confirmed"),
        availability=AvailabilitySpecV1(kind="declared", reservation_policy="fail_closed"),
    )

    result = run_oos_prediction(
        frame=frame,
        target="y",
        features=("x",),
        sample_spec=sample_spec,
        split_receipt=split,
        estimator_factory=LinearEstimator,
        model_id="linear_control_test",
        control_seed=41,
    )

    controls = result.control_packet["controls"]
    assert {control["control"] for control in controls} == {
        "permuted_target",
        "seeded_noise_features",
    }
    assert all(set(control["metrics"]) == {"r2", "rmse"} for control in controls)
    assert all(control["n_evaluation"] > 0 for control in controls)
    assert result.evaluation_packet["controls"] == controls
    permutation = next(control for control in controls if control["control"] == "permuted_target")
    assert permutation["observed_development_cv"]
    assert permutation["permuted_target_cv"]
    assert set(permutation["metric_gap"]) == {"r2", "rmse"}
    noise = next(control for control in controls if control["control"] == "seeded_noise_features")
    assert noise["status"] == "NOISE_NOT_STABLE"
    assert noise["fold_importance"]
