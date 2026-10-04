"""A one-category t-test group must not be labelled estimated."""
import numpy as np
import pandas as pd
from workbench.agent.workflow_runtime import _named_test_by_group
from workbench.statistical_tests import run_named_statistical_test


def test_one_category_group_is_not_estimable_and_others_continue():
    rng = np.random.default_rng(20261004)
    frame = pd.DataFrame({"region": np.repeat(["east", "north", "single"], 120),
                          "treated": np.tile(["no", "yes"], 180), "y": rng.normal(size=360)})
    frame.loc[frame["region"] == "single", "treated"] = "yes"
    result = _named_test_by_group(frame, "region", "test.t_tests", lambda rows:
        run_named_statistical_test(rows, family="t_tests", analysis_columns=["y", "treated"],
                                   dataset_sha256="0" * 64, lineage_parent="cleaned_dataset"))
    groups = {g["key"]: g for g in result["by_group"]["groups"]}
    assert groups["single"]["status"] == "not_estimable", (groups["single"], result)
    assert groups["single"].get("reason")
    assert all(groups[key]["status"] == "estimated" for key in ("east", "north"))
    assert {row["group"] for row in result["results"]} == {"east", "north"}
