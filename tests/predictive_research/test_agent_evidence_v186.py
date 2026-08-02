from __future__ import annotations

from pathlib import Path

import pandas as pd

from workbench.artifacts import write_json
from workbench.agent.context_tools import read_prediction_research_evidence
from workbench.prediction import run_prediction_model_v186


class MeanEstimator:
    def fit(self, features: pd.DataFrame, target: pd.Series) -> "MeanEstimator":
        self.mean_ = float(target.mean())
        return self

    def predict(self, features: pd.DataFrame) -> list[float]:
        return [self.mean_] * len(features)


def test_agent_reads_only_hash_and_schema_verified_prediction_evidence(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    run_prediction_model_v186(
        pd.DataFrame({"y": [float(i + 1) for i in range(10)], "x": [float(i) for i in range(10)]}),
        run_root,
        y="y",
        x=["x"],
        model_type="test_mean",
        model_id="prediction_test_mean_1",
        final_holdout_fraction=0.2,
        cv_folds=2,
        shuffle=True,
        random_seed=3,
        data_structure="iid",
        estimator_factory=MeanEstimator,
    )

    projection = read_prediction_research_evidence(run_root, consumer="agent")

    assert projection["status"] == "validated"
    assert projection["model_id"] == "prediction_test_mean_1"
