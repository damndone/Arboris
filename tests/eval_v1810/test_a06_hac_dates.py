"""Quarterly dates, missing months and mixed date formats."""
from pathlib import Path

import pandas as pd
import pytest
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


@pytest.mark.parametrize("case", ["quarterly", "missing_month", "mixed"])
def test_hac_date_boundaries(tmp_path, case):
    frame = pd.read_csv(Path(__file__).parents[1] / "fixtures/hac/data.csv").sort_values("year")
    frequency = "QS" if case == "quarterly" else "MS"
    dates = pd.date_range("2001-01-01", periods=len(frame), freq=frequency)
    frame["date"] = dates.strftime("%Y-%m-%d")
    if case == "missing_month":
        frame = frame.drop(frame.index[8])
    if case == "mixed":
        frame.loc[frame.index[1::2], "date"] = dates[1::2].strftime("%Y/%m/%d")
    path = tmp_path / f"{case}.csv"
    frame.sample(frac=1, random_state=5).to_csv(path, index=False)
    project = create_project(tmp_path, case)
    result = run_workflow(project.root, [path], mode="auto", model_type="ols", y="y", x=["x1", "x2"],
                          model_options={"covariance": "hac", "time_order": "date", "hac_lags": 4})
    root = project.root / "runs" / result["run_id"]
    issues = read_json(root / "errors.json")
    print(case, result["status"], issues)
    if case == "quarterly":
        assert result["status"] == "completed", issues
    elif case == "missing_month":
        assert result["status"] in {"failed", "blocked"}
        assert any("gap" in i["message"].lower() or "frequency" in i["message"].lower()
                   for i in issues["issues"]), issues
    elif result["status"] == "completed":
        packet = read_json(root / "model_results/ols_1.json")
        assert packet["nobs"] == len(frame)
        oracle = read_json(Path(__file__).parents[1] / "fixtures/hac/oracle.json")
        for term, se in oracle["cases"]["lag_4"]["std_error"].items():
            assert packet["coefficients"][term]["std_error"] == pytest.approx(se, rel=1e-9)
    else:
        assert result["status"] in {"failed", "blocked"}
        assert any(i.get("message") for i in issues["issues"])
