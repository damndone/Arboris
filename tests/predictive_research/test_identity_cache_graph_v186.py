from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from workbench.artifacts import write_json
from workbench.graph_recorder import GraphRecorder
from workbench.graph_store import GraphStore
from workbench.lineage.family import scan_family
from workbench.lineage.headset import build_headset
from workbench.lineage.node_store import read_node_result
from workbench.prediction import run_prediction_model, run_prediction_model_v186
from workbench.predictive_research.cache import PredictionIdentityCache
from workbench.predictive_research.contracts import (
    AvailabilitySpecV1,
    SampleSpecV1,
    SamplingSpecV1,
    SplitPlanV1,
    StructureSpecV1,
)
from workbench.predictive_research.identity import build_prediction_identity


def _sample(
    *,
    split_plan_ref: str = "split-a",
    split_parameters: dict[str, object] | None = None,
) -> SampleSpecV1:
    return SampleSpecV1(
        dataset_sha256="a" * 64,
        sampling=SamplingSpecV1(),
        split_plan=SplitPlanV1(
            strategy="iid",
            profile_id="iid_holdout_kfold",
            profile_version=1,
            effective_parameters=split_parameters or {
                "random_seed": 7,
                "cv_folds": 3,
                "final_holdout_fraction": 0.25,
                "shuffle": True,
            },
        ),
        structure=StructureSpecV1(kind="iid"),
        availability=AvailabilitySpecV1(kind="declared", validation_status="declared"),
        split_plan_ref=split_plan_ref,
    )


class _MeanEstimator:
    def fit(self, features: pd.DataFrame, target: pd.Series) -> "_MeanEstimator":
        self.mean_ = float(target.mean())
        return self

    def predict(self, features: pd.DataFrame) -> list[float]:
        return [self.mean_] * len(features)


def _run_root(tmp_path: Path, run_id: str) -> Path:
    run_root = tmp_path / "runs" / run_id
    run_root.mkdir(parents=True)
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    write_json(run_root / "node_index.json", {})
    write_json(run_root / "run_inputs.json", {"form": {}, "rerun_of": None})
    write_json(run_root / "run_manifest.json", {"run_id": run_id, "status": "completed"})
    return run_root


def test_evaluation_identity_ignores_opaque_split_ref_but_tracks_embargo() -> None:
    first = _sample(split_plan_ref="split-a")
    same_plan_different_ref = _sample(split_plan_ref="unrelated-reference")
    embargoed = _sample(
        split_parameters={
            "random_seed": 7,
            "cv_folds": 3,
            "final_holdout_fraction": 0.25,
            "shuffle": True,
            "embargo": 2,
        }
    )

    assert first.transformation_hash == same_plan_different_ref.transformation_hash
    assert first.evaluation_hash == same_plan_different_ref.evaluation_hash
    assert first.transformation_hash == embargoed.transformation_hash
    assert first.evaluation_hash != embargoed.evaluation_hash


def test_prediction_identity_and_existing_cache_seam_separate_transform_and_split(tmp_path: Path) -> None:
    first = build_prediction_identity(_sample(), model_type="prediction_ridge", model_id="ridge-1")
    changed_split = build_prediction_identity(
        _sample(
            split_parameters={
                "random_seed": 7,
                "cv_folds": 3,
                "final_holdout_fraction": 0.25,
                "shuffle": True,
                "embargo": 2,
            }
        ),
        model_type="prediction_ridge",
        model_id="ridge-1",
    )
    unrelated_ref = build_prediction_identity(
        _sample(split_plan_ref="reference-only-change"),
        model_type="prediction_ridge",
        model_id="ridge-1",
    )
    cache = PredictionIdentityCache(tmp_path)

    assert first.transformation_identity_hash == unrelated_ref.transformation_identity_hash
    assert first.prediction_identity_hash == unrelated_ref.prediction_identity_hash
    assert first.sample_spec_hash == _sample().content_hash
    assert first.to_dict()["sample_spec_hash"] == first.sample_spec_hash
    assert first.run_identity_hash != changed_split.run_identity_hash
    assert cache.status(first).prediction_hit is False
    cache.record(first)
    marker = read_node_result(tmp_path, PredictionIdentityCache._key("prediction", first.prediction_identity_hash))
    assert marker["meta"]["sample_spec_hash"] == first.sample_spec_hash
    assert cache.status(unrelated_ref).prediction_hit is True
    assert cache.status(changed_split).transformation_hit is True
    assert cache.status(changed_split).prediction_hit is False


def test_v186_result_exposes_prediction_and_run_identity_with_cache_status(tmp_path: Path) -> None:
    frame = pd.DataFrame({"y": [float(i) for i in range(12)], "x": [float(i) for i in range(12)]})
    first = run_prediction_model_v186(
        frame,
        _run_root(tmp_path, "run-a"),
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
    second = run_prediction_model_v186(
        frame,
        _run_root(tmp_path, "run-b"),
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

    first_packet = first["prediction_packet"]
    second_packet = second["prediction_packet"]
    assert first["sample_spec_hash"] == first["sample_spec"]["sample_spec_hash"]
    assert first_packet["sample_spec_hash"] == first["sample_spec"]["sample_spec_hash"]
    assert isinstance(first_packet["prediction_identity_hash"], str)
    assert first["run_identity_hash"] == second["run_identity_hash"]
    assert first["cache"]["prediction_hit"] is False
    assert second["cache"]["prediction_hit"] is True


def test_prediction_graph_projection_keeps_prediction_nodes_clickable(tmp_path: Path) -> None:
    run_root = _run_root(tmp_path, "run-graph")
    recorder = GraphRecorder("run-graph", GraphStore(run_root.parent))
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
        graph_recorder=recorder,
    )
    recorder.flush()

    body = build_headset(run_root.parent, scan_family(run_root.parent, "run-graph"))
    prediction_nodes = [
        node for node in body["nodes"].values()
        if str(node.get("id", "")).startswith("prediction:")
    ]
    assert prediction_nodes
    assert all(node.get("node_hash") for node in prediction_nodes)
    assert not any(node.get("node_hash") is None for node in prediction_nodes)
    node_index = json.loads((run_root / "node_index.json").read_text(encoding="utf-8"))
    assert node_index["prediction:result"]["sample_spec_hash"].startswith("sha256:")


def test_legacy_prediction_is_explicit_historical_replay_with_shuffle_semantics(tmp_path: Path) -> None:
    run_root = tmp_path / "legacy-run"
    run_root.mkdir()
    write_json(run_root / "artifacts_index.json", {"schema_version": 1, "artifacts": []})
    result = run_prediction_model(
        pd.DataFrame({"y": [float(i) for i in range(8)], "x": [float(i) for i in range(8)]}),
        run_root,
        y="y",
        x=["x"],
        model_type="prediction_ridge",
        model_id="legacy-ridge-1",
        cv_folds=2,
        random_seed=3,
        shuffle=False,
    )

    assert result["protocol"] == "legacy_random_split_v0"
    assert result["historical_replay"] is True
    assert result["new_run_fallback"] is False
    assert result["replay_semantics"]["shuffle"] is False
    assert result["replay_semantics"]["cv_shuffle"] is False
