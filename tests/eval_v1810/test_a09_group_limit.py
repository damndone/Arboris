"""Exactly fifty groups execute; fifty-one are refused."""
import numpy as np
import pandas as pd
import pytest
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


@pytest.mark.parametrize("count", [50, 51])
def test_group_limit_in_pipeline(tmp_path, count):
    rng = np.random.default_rng(20261004)
    n = count * 30
    x = rng.normal(size=n)
    frame = pd.DataFrame({"g": np.repeat(np.arange(count), 30), "x": x, "y": 1 + x + rng.normal(size=n)})
    path = tmp_path / "groups.csv"
    frame.to_csv(path, index=False)
    project = create_project(tmp_path, f"groups-{count}")
    result = run_workflow(project.root, [path], mode="auto", model_type="ols", y="y", x=["x"],
                          by_group={"column": "g"})
    root = project.root / "runs" / result["run_id"]
    if count == 50:
        assert result["status"] == "completed", read_json(root / "errors.json")
        members = read_json(root / "model_results/collections/by_group.json")["members"]
        assert len(members) == 50 and all(m["status"] == "estimated" for m in members)
    else:
        assert result["status"] in {"failed", "blocked"}
        assert any("51" in i["message"] and "50" in i["message"]
                   for i in read_json(root / "errors.json")["issues"])
