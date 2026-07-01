# tests/lineage/test_recording_roles.py
import numpy as np
import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _run(tmp_path, frame, *, y, x, model_type="auto", **extra):
    source = tmp_path / "data.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "demo")
    result = run_workflow(project.root, [source], mode="auto", y=y, x=x,
                          model_type=model_type, **extra)
    return project.root / "runs" / result["run_id"], result


def _role_edges(run_root):
    graph = read_json(run_root / "graph.json")
    return {
        (e["source_id"], e["target_id"], e["op"])
        for e in graph["edges"].values()
    }


def test_ols_emits_role_edges_unspecified(tmp_path):
    rng = np.random.default_rng(0)
    n = 40
    frame = pd.DataFrame({
        "y": rng.normal(size=n),
        "x1": rng.normal(size=n),
        "x2": rng.normal(size=n),
    })
    run_root, result = _run(tmp_path, frame, y="y", x=["x1", "x2"])
    assert result["status"] == "completed", result
    edges = _role_edges(run_root)
    # outcome flows into the model
    assert ("var:y:cleaned", "model:ols_1", "enters_as_outcome") in edges
    # no focal declared -> explanatory_unspecified for the RHS regressors
    assert ("var:x1:cleaned", "model:ols_1", "enters_as_explanatory_unspecified") in edges
    assert ("var:x2:cleaned", "model:ols_1", "enters_as_explanatory_unspecified") in edges


def test_role_edges_carry_role_param(tmp_path):
    rng = np.random.default_rng(1)
    n = 40
    frame = pd.DataFrame({"y": rng.normal(size=n), "x1": rng.normal(size=n)})
    run_root, result = _run(tmp_path, frame, y="y", x=["x1"])
    assert result["status"] == "completed", result
    graph = read_json(run_root / "graph.json")
    outcome = [e for e in graph["edges"].values() if e["op"] == "enters_as_outcome"]
    assert outcome and outcome[0]["params"]["role"] == "outcome"
    assert outcome[0]["params"]["dropped"] is False
