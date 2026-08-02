from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import write_json
from workbench.predictive_research.contracts import ContractError, SamplingSpecV1
from workbench.prediction import run_prediction_model_v186


class MeanEstimator:
    def fit(self, features: pd.DataFrame, target: pd.Series) -> "MeanEstimator":
        self.mean_ = float(target.mean())
        return self

    def predict(self, features: pd.DataFrame) -> list[float]:
        return [self.mean_] * len(features)


def make_run_root(tmp_path: Path) -> Path:
    run_root = tmp_path / "run"
    run_root.mkdir()
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    return run_root


def make_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"y": [float(index * 2 + 1) for index in range(12)], "x": [float(index) for index in range(12)]}
    )


def test_v186_entrypoint_persists_typed_prediction_evidence(tmp_path: Path) -> None:
    run_root = make_run_root(tmp_path)

    result = run_prediction_model_v186(
        make_frame(),
        run_root,
        y="y",
        x=["x"],
        model_type="test_mean",
        model_id="prediction_test_mean_1",
        final_holdout_fraction=0.25,
        cv_folds=3,
        shuffle=True,
        random_seed=9,
        data_structure="iid",
        estimator_factory=MeanEstimator,
    )

    assert result["protocol"] == "predictive_research_v1"
    assert len(result["sample_spec"]["dataset_ref"]["dataset_sha256"]) == 64
    assert set(result["sample_spec"]["dataset_ref"]["dataset_sha256"]) != {"0"}
    assert result["prediction_packet"]["payload_schema"] == "workbench.prediction.prediction-packet"
    assert result["evaluation_packet"]["payload_schema"] == "workbench.prediction.evaluation-packet"
    assert {control["control"] for control in result["prediction_packet"]["controls"]} == {
        "permuted_target",
        "seeded_noise_features",
    }
    assert (run_root / "prediction_results" / "prediction_test_mean_1.json").is_file()
    assert (run_root / "evaluation_results" / "prediction_test_mean_1.json").is_file()
    index = json.loads((run_root / "artifacts_index.json").read_text(encoding="utf-8"))
    assert {item["payload_contract"]["payload_schema"] for item in index["artifacts"]} >= {
        "workbench.prediction.sample-spec",
        "workbench.prediction.split-plan",
        "workbench.prediction.prediction-packet",
        "workbench.prediction.evaluation-packet",
        "workbench.prediction.negative-control-packet",
    }


def test_v186_entrypoint_blocks_unknown_structure_before_writing(tmp_path: Path) -> None:
    run_root = make_run_root(tmp_path)

    with pytest.raises(ContractError) as error:
        run_prediction_model_v186(
            make_frame(),
            run_root,
            y="y",
            x=["x"],
            model_type="test_mean",
            model_id="prediction_test_mean_1",
            final_holdout_fraction=0.25,
            cv_folds=3,
            shuffle=True,
            random_seed=9,
            data_structure="unknown",
            estimator_factory=MeanEstimator,
        )

    assert error.value.code == "PREDICTION_DATA_STRUCTURE_UNKNOWN"
    assert not (run_root / "prediction_results").exists()


def test_v186_entrypoint_executes_declared_temporal_profile(tmp_path: Path) -> None:
    run_root = make_run_root(tmp_path)
    frame = make_frame()
    frame["period"] = [f"2024-01-{index + 1:02d}" for index in range(len(frame))]

    result = run_prediction_model_v186(
        frame,
        run_root,
        y="y",
        x=["x"],
        model_type="test_mean",
        model_id="prediction_test_mean_1",
        final_holdout_fraction=0.25,
        cv_folds=2,
        shuffle=True,
        random_seed=9,
        data_structure="temporal",
        time_column="period",
        estimator_factory=MeanEstimator,
    )

    assert result["split_plan"]["strategy"] == "temporal"
    assert result["split_plan"]["effective_parameters"]["shuffle"] is False


def test_v186_entrypoint_rejects_unsupported_weight_semantics(tmp_path: Path) -> None:
    run_root = make_run_root(tmp_path)

    with pytest.raises(ContractError) as error:
        run_prediction_model_v186(
            make_frame(),
            run_root,
            y="y",
            x=["x"],
            model_type="test_mean",
            model_id="prediction_test_mean_1",
            final_holdout_fraction=0.25,
            cv_folds=3,
            shuffle=True,
            random_seed=9,
            sampling=SamplingSpecV1(analysis_weight="analysis_weight"),
            data_structure="iid",
            estimator_factory=MeanEstimator,
        )

    assert error.value.code == "PREDICTION_WEIGHT_UNSUPPORTED"


def test_v186_persistence_rejects_symlinked_packet_directory(tmp_path: Path) -> None:
    run_root = make_run_root(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (run_root / "prediction_splits").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ContractError) as error:
        run_prediction_model_v186(
            make_frame(),
            run_root,
            y="y",
            x=["x"],
            model_type="test_mean",
            model_id="prediction_test_mean_1",
            final_holdout_fraction=0.25,
            cv_folds=3,
            shuffle=True,
            random_seed=9,
            data_structure="iid",
            estimator_factory=MeanEstimator,
        )

    assert error.value.code == "PREDICTION_PERSISTENCE_PATH_INVALID"
    assert not list(outside.iterdir())
