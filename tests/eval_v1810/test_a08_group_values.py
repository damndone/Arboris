"""Grouping values preserve numeric, boolean and missing categories."""
import numpy as np
import pandas as pd
import pytest
from workbench.combinators.by_group import ByGroupRefusal, plan_groups
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


@pytest.mark.parametrize("values, keys", [([1.0, 2.0, 1.0, 2.0], ["1", "2"]),
                                          ([True, False, True, False], ["False", "True"]),
                                          ([1.0, np.nan, 1.0, np.nan], ["1", "(missing)"])])
def test_group_values_and_masks(values, keys):
    groups = plan_groups(pd.DataFrame({"g": values}), "g")
    assert [g.key for g in groups] == keys
    assert sum(g.nobs for g in groups) == len(values)
    assert np.all(np.sum([g.mask for g in groups], axis=0) == 1)


def test_all_missing_group_is_refused():
    with pytest.raises(ByGroupRefusal, match="nothing to split"):
        plan_groups(pd.DataFrame({"g": [np.nan] * 100}), "g")


@pytest.mark.parametrize("values,keys", [([1.0, 2.0], ["1", "2"]),
                                        ([False, True], ["False", "True"]),
                                        ([1.0, np.nan], ["1", "(missing)"])])
def test_group_value_types_execute_without_losing_rows(tmp_path, values, keys):
    rng = np.random.default_rng(20261004)
    x = rng.normal(size=240)
    frame = pd.DataFrame({"g": np.repeat(values, 120), "x": x, "y": x + rng.normal(size=240)})
    path = tmp_path / "values.csv"
    frame.to_csv(path, index=False)
    project = create_project(tmp_path, "values")
    result = run_workflow(project.root, [path], mode="auto", model_type="ols", y="y", x=["x"],
                          by_group={"column": "g"})
    root = project.root / "runs" / result["run_id"]
    assert result["status"] == "completed", read_json(root / "errors.json")
    members = read_json(root / "model_results/collections/by_group.json")["members"]
    assert [m["key"] for m in members] == keys
    assert all(m["status"] == "estimated" and m["nobs"] == 120 for m in members)
