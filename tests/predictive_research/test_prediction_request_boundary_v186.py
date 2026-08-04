from __future__ import annotations

from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json, write_json
from workbench.econometrics.optional_deps import OptionalDependencyNotInstalled
from workbench.orchestrator import run_workflow
from workbench import prediction
from workbench.prediction import run_prediction_model_v186
from workbench.projects import create_project


class MeanEstimator:
    def fit(self, features: pd.DataFrame, target: pd.Series) -> "MeanEstimator":
        self.mean_ = float(target.mean())
        return self

    def predict(self, features: pd.DataFrame) -> list[float]:
        return [self.mean_] * len(features)


def test_new_prediction_without_structure_is_blocked_before_legacy_split(
    monkeypatch, tmp_path: Path,
) -> None:
    import workbench.orchestrator as orchestrator

    def fake_legacy_prediction(frame, run_root, **kwargs):
        prediction_dir = Path(run_root) / "prediction_results"
        prediction_dir.mkdir()
        write_json(prediction_dir / "legacy.json", {"protocol": "legacy"})
        return {"protocol": "legacy"}

    monkeypatch.setattr(orchestrator, "run_prediction_model", fake_legacy_prediction)

    source = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [float(i) for i in range(40)], "x": [float(i) for i in range(40)]}
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "prediction_unknown_structure")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x"],
        model_type="ols",
        prediction_model_type="prediction_ridge",
        prediction_cv_folds=3,
    )

    run_root = project.root / "runs" / result["run_id"]
    issues = read_json(run_root / "errors.json")["issues"]
    assert result["status"] == "completed"
    assert not (run_root / "prediction_results").exists()
    assert any(issue["code"] == "PREDICTION_DATA_STRUCTURE_UNKNOWN" for issue in issues)


def test_prediction_run_with_mice_uses_fold_local_preprocessing(
    tmp_path: Path,
) -> None:
    y = [float(1 + 2 * i) for i in range(40)]
    x1 = [float(i) for i in range(40)]
    x2 = [float(i % 5) for i in range(40)]
    for index in (7, 13, 19, 29):
        x1[index] = float("nan")
    source = tmp_path / "data.csv"
    pd.DataFrame({"y": y, "x1": x1, "x2": x2}).to_csv(source, index=False)
    project = create_project(tmp_path, "prediction_mice_boundary")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x1", "x2"],
        model_type="ols",
        imputation={"method": "mice"},
        prediction_model_type="prediction_ridge",
        prediction_cv_folds=3,
        prediction_data_structure="iid",
    )

    run_root = project.root / "runs" / result["run_id"]
    packet = read_json(run_root / "prediction_results" / "prediction_ridge_1.json")
    assert packet["preprocessing"]["method"] == "mice"
    assert packet["preprocessing"]["fit_scope"] == "fold_local"
    assert packet["preprocessing"]["final_holdout"]["fit_partition"] == "development_only"


def test_prediction_mice_missing_dependency_is_structured_and_has_no_packet(
    monkeypatch, tmp_path: Path,
) -> None:
    import workbench.predictive_research.prediction_protocol as protocol

    real_require = protocol.require_optional_dependency

    def missing_mice_dependency(module_name: str, **kwargs: object):
        if kwargs.get("model_type") == "prediction_mice":
            raise OptionalDependencyNotInstalled(
                extra="ml",
                package="sklearn.impute",
                model_type="prediction_mice",
                step="prediction",
                engine="scikit-learn",
            )
        return real_require(module_name, **kwargs)

    monkeypatch.setattr(protocol, "require_optional_dependency", missing_mice_dependency)
    source = tmp_path / "data.csv"
    pd.DataFrame(
        {"y": [float(i * 2 + 1) for i in range(40)], "x1": [float(i) for i in range(40)], "x2": [float(i % 5) for i in range(40)]}
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "prediction_mice_optional_dependency")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x1", "x2"],
        model_type="ols",
        imputation={"method": "mice"},
        prediction_model_type="prediction_ridge",
        prediction_cv_folds=3,
        prediction_data_structure="iid",
    )

    run_root = project.root / "runs" / result["run_id"]
    issues = read_json(run_root / "errors.json")["issues"]
    issue = next(issue for issue in issues if issue["code"] == "OPTIONAL_DEPENDENCY_MISSING")
    assert issue["evidence"]["step"] == "prediction"
    assert "pip install" in issue["evidence"]["install"]
    assert not (run_root / "prediction_results").exists()


def test_workflow_persists_prediction_graph_chain_without_packet_internals_as_nodes(
    monkeypatch, tmp_path: Path,
) -> None:
    def typed_prediction_with_test_estimator(frame, run_root, **kwargs):
        return run_prediction_model_v186(
            frame,
            run_root,
            estimator_factory=MeanEstimator,
            **kwargs,
        )

    monkeypatch.setattr(prediction, "run_prediction_model_v186", typed_prediction_with_test_estimator)
    source = tmp_path / "data.csv"
    pd.DataFrame(
        {
            "y": [float(i * 2 + 1) for i in range(40)],
            "x1": [float(i) for i in range(40)],
            "x2": [float(i % 5) for i in range(40)],
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "prediction_graph_chain")

    result = run_workflow(
        project.root,
        [source],
        mode="auto",
        y="y",
        x=["x1", "x2"],
        model_type="ols",
        prediction_model_type="prediction_ridge",
        prediction_cv_folds=3,
        prediction_data_structure="iid",
    )

    graph = read_json(project.root / "runs" / result["run_id"] / "graph.json")
    nodes = graph["nodes"]
    edges = graph["edges"]
    expected = {
        "prediction:dataset_snapshot",
        "prediction:task",
        "prediction:split_plan",
        "prediction:baseline",
        "prediction:candidate",
        "prediction:evaluation",
        "prediction:negative_controls",
        "prediction:result",
    }
    assert expected.issubset(nodes)
    assert not any("fold" in node_id or "permutation" in node_id for node_id in nodes)
    prediction_edges = [edge for edge in edges.values() if edge["op"] == "predictive_research"]
    assert len(prediction_edges) == 8
