import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

pytest.importorskip("sklearn")


def _frame() -> pd.DataFrame:
    n = 60
    xs = [float(i) for i in range(n)]
    ys = [2.0 + 1.5 * v + (i % 7) for i, v in enumerate(xs)]
    return pd.DataFrame({"y": ys, "x": xs})


def _run(tmp_path, **kwargs):
    source = tmp_path / "data.csv"
    _frame().to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], **kwargs)
    return project.root / "runs" / result["run_id"], result


def test_prediction_via_request_writes_artifact(tmp_path):
    run_root, result = _run(
        tmp_path, mode="auto", y="y", x=["x"], model_type="auto",
        prediction_model_type="prediction_ridge", prediction_cv_folds=3,
        prediction_data_structure="iid",
    )
    assert result["status"] == "completed"
    pred = read_json(run_root / "prediction_results" / "prediction_ridge_1.json")
    assert pred["model_type"] == "prediction_ridge"
    evaluation = read_json(run_root / "evaluation_results" / "prediction_ridge_1.json")
    assert len(evaluation["cv"]) == 3
    assert "oos" in evaluation


def test_no_prediction_request_writes_nothing(tmp_path):
    run_root, result = _run(tmp_path, mode="auto", y="y", x=["x"])
    assert not (run_root / "prediction_results").exists()
