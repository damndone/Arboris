"""A separated group is excluded without preventing other fits."""
import numpy as np
import pandas as pd
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_separated_group_is_not_estimable_and_excluded_from_differences(tmp_path):
    rng = np.random.default_rng(20261004)
    n = 900
    x = rng.normal(size=n)
    y = rng.binomial(1, 1 / (1 + np.exp(-0.5 * x)))
    groups = np.repeat(["east", "north", "separated"], 300)
    x[-300:] = np.tile([-1., 1.], 150)
    y[-300:] = (x[-300:] > 0).astype(int)
    path = tmp_path / "separation.csv"
    pd.DataFrame({"region": groups, "x": x, "yb": y}).to_csv(path, index=False)
    project = create_project(tmp_path, "separation")
    result = run_workflow(project.root, [path], mode="auto", model_type="logit", y="yb", x=["x"],
                          by_group={"column": "region"})
    root = project.root / "runs" / result["run_id"]
    assert result["status"] == "completed", read_json(root / "errors.json")
    collection = read_json(root / "model_results/collections/by_group.json")
    members = {m["key"]: m for m in collection["members"]}
    assert members["separated"]["status"] == "not_estimable", members["separated"]
    assert members["separated"].get("reason")
    assert all(members[key]["status"] == "estimated" for key in ("east", "north"))
    differences = read_json(root / collection["pooled"]["result_ref"])
    assert differences["status"] == "estimated", differences
    assert differences["nobs"] == 600
    assert not any("separated" in term for test in differences["tests"] for term in test["terms"])
