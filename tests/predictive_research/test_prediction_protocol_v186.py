from __future__ import annotations

import pandas as pd
import pytest

from workbench.predictive_research.contracts import (
    AvailabilitySpecV1,
    SampleSpecV1,
    SamplingSpecV1,
    SplitPlanV1,
    StructureSpecV1,
)
from workbench.predictive_research.prediction_protocol import run_oos_prediction
from workbench.predictive_research.split_kernel import build_split_plan


class RecordingMeanEstimator:
    fits: list[tuple[tuple[str, ...], tuple[float, ...]]] = []

    def fit(self, features: pd.DataFrame, target: pd.Series) -> "RecordingMeanEstimator":
        self.__class__.fits.append((tuple(features.index.astype(str)), tuple(target.astype(float))))
        self.mean_ = float(target.mean())
        return self

    def predict(self, features: pd.DataFrame) -> list[float]:
        return [self.mean_] * len(features)


def test_oos_prediction_uses_one_split_for_cv_final_and_baseline() -> None:
    RecordingMeanEstimator.fits.clear()
    frame = pd.DataFrame(
        {"x": [float(index) for index in range(12)], "y": [float(index * 2 + 1) for index in range(12)]},
        index=[f"row-{index}" for index in range(12)],
    )
    split = build_split_plan(
        row_refs=tuple(frame.index),
        strategy="iid",
        final_holdout_fraction=0.25,
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
        estimator_factory=RecordingMeanEstimator,
        model_id="test_mean",
    )

    final_rows = {assignment.row_ref for assignment in split.assignments if assignment.partition == "final_holdout"}
    assert set(result.prediction_packet["row_predictions"]) == final_rows
    assert result.prediction_packet["n_by_partition"]["final_holdout"] == len(final_rows)
    assert result.evaluation_packet["split_plan_hash"] == split.content_hash
    assert result.evaluation_packet["baseline"]["model_id"] == "mean_regressor"
    assert result.evaluation_packet["oos"]["n"] == len(final_rows)
    assert all(not (set(fitted_rows) & final_rows) for fitted_rows, _ in RecordingMeanEstimator.fits)


def test_oos_prediction_rejects_split_receipt_that_does_not_match_frame() -> None:
    frame = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0], "y": [2.0, 4.0, 6.0, 8.0]}, index=["row-1", "row-2", "row-3", "row-4"])
    split = build_split_plan(
        row_refs=("row-1", "row-2", "row-3", "row-other"),
        strategy="iid",
            final_holdout_fraction=0.25,
        cv_folds=2,
        shuffle=False,
        random_seed=1,
    )
    sample_spec = SampleSpecV1(
        dataset_sha256="b" * 64,
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

    with pytest.raises(ValueError, match="split binding"):
        run_oos_prediction(
            frame=frame,
            target="y",
            features=("x",),
            sample_spec=sample_spec,
            split_receipt=split,
            estimator_factory=RecordingMeanEstimator,
            model_id="test_mean",
        )


def test_temporal_oos_cv_trains_only_on_prior_development_rows() -> None:
    RecordingMeanEstimator.fits.clear()
    frame = pd.DataFrame(
        {"x": [float(index) for index in range(10)], "y": [float(index) for index in range(10)]},
        index=[f"row-{index}" for index in range(10)],
    )
    split = build_split_plan(
        row_refs=tuple(frame.index),
        strategy="temporal",
        time_values=tuple(f"2024-01-{index + 1:02d}" for index in range(10)),
        final_holdout_fraction=0.2,
        cv_folds=2,
        shuffle=True,
        random_seed=3,
    )
    sample_spec = SampleSpecV1(
        dataset_sha256="c" * 64,
        sampling=SamplingSpecV1(),
        split_plan=SplitPlanV1(
            strategy="temporal",
            profile_id="temporal_holdout_rolling",
            profile_version=1,
            effective_parameters=split.effective_parameters,
        ),
        structure=StructureSpecV1(
            kind="temporal", time_column="period", provenance="user_confirmed"
        ),
        availability=AvailabilitySpecV1(kind="declared", reservation_policy="fail_closed"),
    )

    run_oos_prediction(
        frame=frame,
        target="y",
        features=("x",),
        sample_spec=sample_spec,
        split_receipt=split,
        estimator_factory=RecordingMeanEstimator,
        model_id="temporal_mean",
    )

    assert set(RecordingMeanEstimator.fits[0][0]) == {"row-0"}
    assert all(int(row.removeprefix("row-")) <= 4 for row in RecordingMeanEstimator.fits[1][0])
