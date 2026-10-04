"""Direct workflow requests must not silently choose between combinators."""
import json
from pathlib import Path

import pandas as pd

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_direct_request_discloses_or_refuses_combination(tmp_path):
    frame = pd.read_csv(Path(__file__).parents[1] / "fixtures/multiple_imputation/data.csv")
    frame["region"] = ["east" if i % 2 else "west" for i in range(len(frame))]
    path = tmp_path / "combined.csv"
    frame.to_csv(path, index=False)
    project = create_project(tmp_path, "combined")
    result = run_workflow(project.root, [path], mode="auto", model_type="ols", y="y", x=["x1", "x3"],
                          imputation={"method": "mice", "m": 2}, by_group={"column": "region"})
    root = project.root / "runs" / result["run_id"]
    if result["status"] in {"failed", "blocked"}:
        issues = read_json(root / "errors.json")["issues"]
        assert any("imput" in i["message"].lower() and "group" in i["message"].lower() for i in issues), issues
    else:
        assert result["status"] == "completed"
        evidence = json.dumps(read_json(root / "errors.json"), ensure_ascii=False)
        assert "imput" in evidence.lower() and "group" in evidence.lower(), (
            "Both requested; completed without disclosing which combinator was omitted", result, evidence)
