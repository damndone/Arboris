"""Categorical predictors must be retained or explicitly refused."""
import json
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


@pytest.mark.parametrize("missing_category", [False, True])
def test_categorical_predictor_is_retained_or_refused(tmp_path, missing_category):
    source = Path(__file__).parents[1] / "fixtures/multiple_imputation/data.csv"
    frame = pd.read_csv(source)
    frame["category"] = ["east" if i % 2 else "west" for i in range(len(frame))]
    if missing_category:
        frame.loc[frame.index[:15], "category"] = None
    path = tmp_path / "categorical.csv"
    frame.to_csv(path, index=False)
    project = create_project(tmp_path, "categorical")
    result = run_workflow(project.root, [path], mode="auto", model_type="ols", y="y",
                          x=["x1", "category"], imputation={"method": "mice", "m": 2})
    root = project.root / "runs" / result["run_id"]
    if result["status"] in {"failed", "blocked"}:
        issues = read_json(root / "errors.json")["issues"]
        assert any(issue.get("code") and issue.get("message") for issue in issues), issues
        if missing_category:
            assert any("category" in issue["message"].lower() for issue in issues), issues
        assert not list((root / "processed").glob("imputed_dataset*"))
        return
    assert result["status"] == "completed"
    packet = read_json(root / "model_results/ols_1.json")
    assert packet["multiple_imputation"]["m"] == 2
    assert "category" in json.dumps(list(packet["coefficients"])), packet
    for index in (1, 2):
        completed = pd.read_parquet(root / f"processed/imputed_dataset_{index:04d}.parquet")
        assert len(completed) == len(frame)
        assert "category" in completed and not completed["category"].isna().any()
