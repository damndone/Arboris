from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import write_json
from workbench.predictive_research.contracts import ContractError
from workbench.predictive_research.preprocessing import (
    FoldPreprocessingKernel,
    PreprocessingStepV1,
)
from workbench.prediction import run_prediction_model_v186


class _MeanEstimator:
    def fit(self, features: pd.DataFrame, target: pd.Series) -> "_MeanEstimator":
        self.mean_ = float(target.mean())
        return self

    def predict(self, features: pd.DataFrame) -> list[float]:
        return [self.mean_] * len(features)


def _run_root(tmp_path: Path) -> Path:
    root = tmp_path / "run"
    root.mkdir()
    write_json(root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    return root


def _frame_with_missing_features() -> pd.DataFrame:
    frame = pd.DataFrame(
        {
            "y": [float(index * 2 + 1) for index in range(12)],
            "x": [float(index) for index in range(12)],
            "x2": [float(index % 4) for index in range(12)],
        }
    )
    frame.loc[[1, 7], "x"] = float("nan")
    frame.loc[[3, 9], "x2"] = float("nan")
    return frame


def test_prediction_mice_packet_records_disjoint_development_fit_scopes(tmp_path: Path) -> None:
    result = run_prediction_model_v186(
        _frame_with_missing_features(),
        _run_root(tmp_path),
        y="y",
        x=["x", "x2"],
        model_type="test_mean",
        model_id="prediction_test_mean_1",
        final_holdout_fraction=0.25,
        cv_folds=3,
        shuffle=True,
        random_seed=9,
        data_structure="iid",
        estimator_factory=_MeanEstimator,
        imputation_method="mice",
        imputation_max_iter=2,
    )

    preprocessing = result["prediction_packet"]["preprocessing"]
    assert preprocessing["fit_scope"] == "fold_local"
    for scope in preprocessing["folds"]:
        assert scope["fit_partition"] == "development_only"
        assert set(scope["fit_row_refs"]).isdisjoint(scope["apply_row_refs"])
    final_scope = preprocessing["final_holdout"]
    assert final_scope["fit_partition"] == "development_only"
    assert set(final_scope["fit_row_refs"]).isdisjoint(final_scope["apply_row_refs"])


def test_prediction_mice_rejects_a_pre_split_imputed_artifact(tmp_path: Path) -> None:
    with pytest.raises(ContractError, match="prediction MICE") as caught:
        run_prediction_model_v186(
            pd.DataFrame({"y": [1.0, 2.0, 3.0, 4.0], "x": [1.0, 2.0, 3.0, 4.0]}),
            _run_root(tmp_path),
            y="y",
            x=["x"],
            model_type="test_mean",
            model_id="prediction_test_mean_1",
            final_holdout_fraction=0.25,
            cv_folds=2,
            shuffle=True,
            random_seed=9,
            data_structure="iid",
            estimator_factory=_MeanEstimator,
            inputs=["imputed_dataset"],
            imputation_method="mice",
        )

    assert caught.value.code == "PREDICTION_FULL_TABLE_IMPUTATION_UNSUPPORTED"


def test_period_fitted_kernel_supports_fold_local_mice_transform() -> None:
    frame = pd.DataFrame(
        {
            "x": [1.0, 2.0, float("nan"), 4.0],
            "z": [10.0, float("nan"), 30.0, 40.0],
        },
        index=["train-0", "train-1", "apply-0", "apply-1"],
    )
    kernel = FoldPreprocessingKernel(
        steps=(
            PreprocessingStepV1(
                transform_id="mice",
                transform_version=1,
                fit_semantics="period_fitted",
                columns=("x", "z"),
            ),
        )
    )

    fitted = kernel.fit(frame.loc[["train-0", "train-1"]], fit_scope="development_fold_1")
    transformed = fitted.apply(frame.loc[["apply-0", "apply-1"]])

    assert fitted.fit_scope == "development_fold_1"
    assert transformed["x"].notna().all()
    assert transformed["z"].notna().all()
