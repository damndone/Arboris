"""v1.8.10 step 7: by-group execution equals filtering then running.

One generic test for every capability open to by-group execution: the result
for group g must equal the result of filtering group == g and running the
capability alone. A capability is added to `BY_GROUP_OPEN` only when this test
covers it; the test fails for an open capability it does not know how to run.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.combinators.by_group import (
    BY_GROUP_OPEN,
    MAX_GROUPS,
    MISSING_GROUP,
    ByGroupRefusal,
    adjust_p_values,
    plan_groups,
)
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

# model family -> (outcome column, model_type)
MODEL_CASES = {
    "ols": ("y", "ols"),
    "logit": ("yb", "logit"),
    "probit": ("yb", "probit"),
    "poisson": ("yc", "poisson"),
}
MODEL_FAMILIES = sorted(name for name in BY_GROUP_OPEN if not name.startswith(("test.", "statistical.")))


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(20261003)
    n = 1200
    region = rng.choice(["east", "north", "south", "west"], n)
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    shift = pd.Series(region).map({"east": 0.2, "north": 0.6, "south": -0.4, "west": 0.0}).to_numpy()
    y = 1 + (0.5 + shift) * x1 - 0.3 * x2 + rng.normal(size=n)
    yb = (rng.random(n) < 1 / (1 + np.exp(-(-0.2 + (0.8 + shift) * x1 - 0.4 * x2)))).astype(int)
    yc = rng.poisson(np.exp(0.3 + (0.3 + shift / 2) * x1 - 0.2 * x2))
    frame = pd.DataFrame({"region": region, "y": y, "yb": yb, "yc": yc, "x1": x1, "x2": x2})
    frame.loc[frame.index[:150], "region"] = np.nan  # a missing group large enough to estimate
    return frame


@pytest.fixture(scope="module")
def data(tmp_path_factory) -> Path:
    path = tmp_path_factory.mktemp("by-group-data") / "groups.csv"
    _frame().to_csv(path, index=False)
    return path


def _run(root: Path, name: str, source: Path, model_type: str, outcome: str, **extra):
    project = create_project(root, name)
    result = run_workflow(project.root, [source], mode="auto", model_type=model_type, y=outcome,
                          x=["x1", "x2"], **extra)
    return result, project.root / "runs" / result["run_id"]


def test_every_open_model_family_is_covered_here() -> None:
    assert set(MODEL_FAMILIES) <= set(MODEL_CASES), sorted(set(MODEL_FAMILIES) - set(MODEL_CASES))


@pytest.mark.parametrize("family", MODEL_FAMILIES)
def test_each_group_equals_filtering_then_running(family: str, data: Path, tmp_path) -> None:
    outcome, model_type = MODEL_CASES[family]
    result, run_root = _run(tmp_path, f"{family}-by", data, model_type, outcome, by_group={"column": "region"})
    assert result["status"] == "completed", read_json(run_root / "errors.json")
    collection = read_json(run_root / "model_results" / "collections" / "by_group.json")
    keys = [member["key"] for member in collection["members"]]
    assert keys == ["east", "north", "south", "west", MISSING_GROUP]
    frame = pd.read_csv(data)
    for member in collection["members"]:
        assert member["status"] == "estimated", member
        packet = read_json(run_root / member["result_ref"])
        subset = frame[frame["region"].isna()] if member["key"] == MISSING_GROUP else frame[frame["region"] == member["key"]]
        assert member["nobs"] == len(subset) == packet["nobs"]
        alone_path = tmp_path / f"{family}-{packet['by_group']['index']}.csv"
        subset.to_csv(alone_path, index=False)
        _, alone_root = _run(tmp_path, f"{family}-alone-{packet['by_group']['index']}", alone_path, model_type, outcome)
        alone = read_json(next((alone_root / "model_results").glob(f"{family}_1.json")))
        for term, entry in alone["coefficients"].items():
            for field in ("estimate", "std_error", "p_value", "ci_lower", "ci_upper"):
                assert packet["coefficients"][term][field] == pytest.approx(entry[field], rel=1e-9, abs=1e-12), (
                    member["key"], term, field)
        kernel = read_json(run_root / kernel_relative_path(packet["model_id"]))
        alone_kernel = read_json(alone_root / kernel_relative_path(alone["model_id"]))
        assert np.allclose(kernel["vcov"], alone_kernel["vcov"], rtol=1e-9, atol=1e-14)
        assert kernel["model_id"] == packet["model_id"] != alone["model_id"]


def test_a_group_below_the_check_librarys_minimum_is_listed_not_dropped(data: Path, tmp_path) -> None:
    frame = pd.read_csv(data)
    frame.loc[frame.index[:150], "region"] = "tiny"
    frame = frame[(frame["region"] != "tiny") | (frame.index < 20)]
    source = tmp_path / "tiny.csv"
    frame.to_csv(source, index=False)
    result, run_root = _run(tmp_path, "tiny", source, "ols", "y", by_group={"column": "region"})
    assert result["status"] == "completed"
    members = {m["key"]: m for m in read_json(run_root / "model_results" / "collections" / "by_group.json")["members"]}
    assert members["tiny"]["status"] == "not_estimable" and members["tiny"]["nobs"] == 20
    assert "per parameter" in members["tiny"]["reason"] and "Harrell" in members["tiny"]["reason"]
    written = [read_json(path).get("by_group", {}).get("key") for path in (run_root / "model_results").glob("ols_1_g*.json")]
    assert "tiny" not in written and len(written) == 4


def test_a_family_not_open_to_by_group_is_refused_and_told_what_is(data: Path, tmp_path) -> None:
    result, run_root = _run(tmp_path, "nb", data, "negative_binomial", "yc", by_group={"column": "region"})
    assert result["status"] == "failed"
    issue = read_json(run_root / "errors.json")["issues"][-1]
    assert issue["code"] == "BY_GROUP_NOT_OFFERED" and "ols" in issue["message"]


def test_the_grouping_column_cannot_be_in_the_model(data: Path, tmp_path) -> None:
    frame = pd.read_csv(data).assign(code=lambda d: d["region"].map({"east": 1, "north": 2, "south": 3, "west": 4}))
    source = tmp_path / "coded.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "inmodel")
    result = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=["x1", "code"],
                          by_group={"column": "code"})
    issue = read_json(project.root / "runs" / result["run_id"] / "errors.json")["issues"][-1]
    assert issue["code"] == "BY_GROUP_COLUMN_IN_MODEL"


def test_more_than_fifty_groups_are_refused() -> None:
    frame = pd.DataFrame({"g": range(MAX_GROUPS + 1)})
    with pytest.raises(ByGroupRefusal, match="multilevel"):
        plan_groups(frame, "g")


def test_holm_and_benjamini_hochberg_match_r_p_adjust() -> None:
    # R: p.adjust(c(0.01, 0.04, 0.03, 0.2), "holm") and "BH"
    p = [0.01, 0.04, 0.03, 0.2]
    assert adjust_p_values(p, "holm") == pytest.approx([0.04, 0.09, 0.09, 0.2])
    assert adjust_p_values(p, "bh") == pytest.approx([0.04, 0.0533333333, 0.0533333333, 0.2])
    assert adjust_p_values([0.01, None, 0.02], "holm") == pytest.approx([0.02, None, 0.02])


ORACLE_DIR = Path(__file__).parent / "fixtures" / "by_group"


@pytest.mark.parametrize("family", MODEL_FAMILIES)
def test_group_difference_tests_match_car_linear_hypothesis(family: str, tmp_path) -> None:
    import json

    oracle = json.loads((ORACLE_DIR / "oracle.json").read_text())
    outcome, model_type = MODEL_CASES[family]
    result, run_root = _run(tmp_path, f"{family}-diff", ORACLE_DIR / "data.csv", model_type, outcome,
                            by_group={"column": "region"})
    assert result["status"] == "completed", read_json(run_root / "errors.json")
    collection = read_json(run_root / "model_results" / "collections" / "by_group.json")
    assert collection["pooled"]["method"] == "group_differences"
    differences = read_json(run_root / collection["pooled"]["result_ref"])
    assert differences["status"] == "estimated" and differences["reference_group"] == "east"
    tests = {test["name"]: test for test in differences["tests"]}
    for name, reference in oracle["cases"][family].items():
        ours = tests[name]
        assert ours["statistic"] == pytest.approx(reference["statistic"], rel=1e-6), (family, name)
        assert ours["df_num"] == reference["df_num"]
        if "df_den" in reference:
            assert ours["df_den"] == reference["df_den"]
        assert ours["p_value"] == pytest.approx(reference["p_value"], rel=1e-5, abs=1e-14), (family, name)
    # Every group's result carries the same tests, so no reader of one group misses them.
    first = read_json(run_root / collection["members"][0]["result_ref"])
    assert first["by_group"]["difference_tests"] == differences


def test_the_report_agent_and_disclosure_see_every_group(data: Path, tmp_path) -> None:
    from workbench.agent.context_tools import _bounded_persisted_model_facts, _public_requested_model_coefficients
    from workbench.analysis_disclosure import _estimated_groups
    from workbench.artifacts import read_json as _read

    result, run_root = _run(tmp_path, "views", data, "ols", "y", by_group={"column": "region"})
    report = (run_root / "reports" / "report.html").read_text()
    assert "Estimated separately for each group of region" in report
    assert "not a test of a difference" in report
    collection = _read(run_root / "model_results" / "collections" / "by_group.json")
    packets = [_read(run_root / member["result_ref"]) for member in collection["members"]]
    summary = _bounded_persisted_model_facts(packets, run_root=run_root)
    assert [item["by_group"]["group"] for item in summary] == ["east", "north", "south", "west", MISSING_GROUP]
    project = _public_requested_model_coefficients(run_id="r", result=packets[0], requested_terms=("x1",))
    tests = project["by_group"]["difference_tests"]["tests"]
    assert {test["label"] for test in tests} >= {"all coefficients equal across groups", "effect of x1 equal across groups"}
    assert _estimated_groups(run_root.parent.parent, run_root.name) == 5


def test_the_agent_requests_by_group_on_model_genesis() -> None:
    import json

    from workbench.agent.workflow_contracts import genesis_run_params, validate_model_genesis_spec
    from workbench.contracts.common.errors import OperationValidationError

    branches = [{"branch_id": "b", "outcome": "y", "predictors": ["x1"]}]
    spec = {"model_family": "ols", "branches": branches, "by_group": "region"}
    validate_model_genesis_spec(spec)
    assert json.loads(genesis_run_params(spec)["by_group"]) == {"column": "region"}
    for bad, message in (
        ({**spec, "model_family": "negative_binomial"}, "not offered for negative_binomial"),
        ({**spec, "by_group": "x1"}, "cannot also be the outcome or a predictor"),
        ({**spec, "multiple_imputations": 5}, "cannot be combined with multiple_imputations"),
    ):
        with pytest.raises(OperationValidationError, match=message):
            validate_model_genesis_spec(bad)
