"""Newey-West at lag zero equals HC1 on the same observations."""
from pathlib import Path

import pytest
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_hac_lag_zero_equals_robust(tmp_path):
    source = Path(__file__).parents[1] / "fixtures/hac/data.csv"
    packets = []
    for name, options in (("hac", {"covariance": "hac", "time_order": "year", "hac_lags": 0}),
                          ("robust", {"covariance": "robust"})):
        project = create_project(tmp_path, name)
        result = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=["x1", "x2"],
                              model_options=options)
        root = project.root / "runs" / result["run_id"]
        assert result["status"] == "completed", read_json(root / "errors.json")
        packets.append(read_json(root / "model_results/ols_1.json"))
    for term, value in packets[0]["coefficients"].items():
        assert value["std_error"] == pytest.approx(packets[1]["coefficients"][term]["std_error"], rel=1e-10)
