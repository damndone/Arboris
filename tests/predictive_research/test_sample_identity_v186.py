from __future__ import annotations

from pathlib import Path

import pandas as pd

from workbench.artifacts import write_json
from workbench.predictive_research.contracts import (
    AvailabilitySpecV1,
    SampleSpecV1,
    SamplingSpecV1,
    SplitPlanV1,
    StructureSpecV1,
)
from workbench.prediction import run_prediction_model_v186


def _sample(*, split_seed: int, feature_recipe_ref: str | None = "recipe-a") -> SampleSpecV1:
    return SampleSpecV1(
        dataset_sha256="a" * 64,
        sampling=SamplingSpecV1(frequency_weight="freq"),
        split_plan=SplitPlanV1(
            strategy="iid",
            profile_id="iid_holdout_kfold",
            profile_version=1,
            effective_parameters={"random_seed": split_seed, "cv_folds": 3},
        ),
        structure=StructureSpecV1(kind="iid"),
        availability=AvailabilitySpecV1(kind="declared", validation_status="declared"),
        feature_recipe_ref=feature_recipe_ref,
        split_plan_ref=f"split-{split_seed}",
    )


def test_sample_identity_layers_keep_transform_identity_independent_of_split() -> None:
    first = _sample(split_seed=7)
    second = _sample(split_seed=11)

    assert first.transformation_hash == second.transformation_hash
    assert first.evaluation_hash != second.evaluation_hash


def test_sample_identity_changes_when_feature_recipe_changes() -> None:
    first = _sample(split_seed=7, feature_recipe_ref="recipe-a")
    second = _sample(split_seed=7, feature_recipe_ref="recipe-b")

    assert first.transformation_hash != second.transformation_hash


class _MeanEstimator:
    def fit(self, features: pd.DataFrame, target: pd.Series) -> "_MeanEstimator":
        self.mean_ = float(target.mean())
        return self

    def predict(self, features: pd.DataFrame) -> list[float]:
        return [self.mean_] * len(features)


class _GraphCapture:
    def __init__(self) -> None:
        self.nodes: list[dict[str, object]] = []

    def record_stage(self, node_id: str, display_label: str, **kwargs: object) -> None:
        self.nodes.append({"node_id": node_id, **kwargs})

    def record_model(self, node_id: str, display_label: str, **kwargs: object) -> None:
        self.nodes.append({"node_id": node_id, **kwargs})

    def record_edge(self, *args: object, **kwargs: object) -> None:
        return None


def test_prediction_packets_persist_layered_sample_identity(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    frame = pd.DataFrame({"y": [float(i) for i in range(12)], "x": [float(i) for i in range(12)]})

    result = run_prediction_model_v186(
        frame,
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
        estimator_factory=_MeanEstimator,
    )

    sample = result["sample_spec"]
    prediction = result["prediction_packet"]
    evaluation = result["evaluation_packet"]
    assert isinstance(sample["transformation_hash"], str)
    assert sample["evaluation_hash"] != sample["transformation_hash"]
    assert prediction["transformation_identity_hash"] == sample["transformation_hash"]
    assert prediction["evaluation_identity_hash"] == evaluation["evaluation_identity_hash"]
    assert prediction["evaluation_identity_hash"] == sample["evaluation_hash"]


def test_prediction_graph_nodes_expose_layered_identity(tmp_path: Path) -> None:
    run_root = tmp_path / "run"
    run_root.mkdir()
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    capture = _GraphCapture()
    frame = pd.DataFrame({"y": [float(i) for i in range(12)], "x": [float(i) for i in range(12)]})

    run_prediction_model_v186(
        frame,
        run_root,
        y="y",
        x=["x"],
        model_type="test_mean",
        model_id="prediction_test_mean_graph",
        final_holdout_fraction=0.25,
        cv_folds=3,
        shuffle=True,
        random_seed=9,
        data_structure="iid",
        estimator_factory=_MeanEstimator,
        graph_recorder=capture,
    )

    assert capture.nodes
    assert all(isinstance(node.get("node_hash"), str) and node["node_hash"] for node in capture.nodes)
