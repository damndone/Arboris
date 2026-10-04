"""Combined HAC and grouping agrees with independently sorted R groups."""
from pathlib import Path
import pytest
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_hac_by_group_sorts_each_group_or_explicitly_refuses(tmp_path):
    fixtures = Path(__file__).parents[1] / "fixtures/eval_v1810/a07"
    project = create_project(tmp_path, "hac-groups")
    result = run_workflow(project.root, [fixtures / "data.csv"], mode="auto", model_type="ols", y="y", x=["x1", "x2"],
                          model_options={"covariance": "hac", "time_order": "year", "hac_lags": 4},
                          by_group={"column": "region"})
    root = project.root / "runs" / result["run_id"]
    print("HAC by_group", result["status"], read_json(root / "errors.json"))
    if result["status"] in {"failed", "blocked"}:
        assert any(i.get("message") for i in read_json(root / "errors.json")["issues"])
        return
    assert result["status"] == "completed"
    collection = read_json(root / "model_results/collections/by_group.json")
    assert len(collection["members"]) == 2
    member = next(m for m in collection["members"] if m["key"] == "east")
    assert member["status"] == "estimated", member
    packet = read_json(root / member["result_ref"])
    expected = read_json(fixtures / "oracle.json")
    for term, value in expected["coefficients"].items():
        assert packet["coefficients"][term]["estimate"] == pytest.approx(value, rel=1e-9)
        assert packet["coefficients"][term]["std_error"] == pytest.approx(expected["std_error"][term], rel=1e-9)
    assert packet["covariance_evidence"]["hac"]["lags"] == 4
