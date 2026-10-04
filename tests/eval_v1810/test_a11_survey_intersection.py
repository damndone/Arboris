"""Survey group domains intersect the declared subpopulation, against Stata."""
import numpy as np
import pandas as pd
import pytest
from tests.stata_oracle import emit, run
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def test_survey_subpopulation_and_group_intersect_like_stata(tmp_path):
    rng = np.random.default_rng(20261004)
    n = 900
    strata = rng.integers(1, 5, n)
    psu = strata * 100 + rng.integers(1, 11, n)
    region = rng.choice(["east", "north", "south"], n)
    x = rng.normal(size=n)
    eligible = rng.binomial(1, .65, n)
    y = 1 + .4 * x + eligible * (.8 * x + 1) + .3 * (psu % 7) + rng.normal(size=n)
    frame = pd.DataFrame({"y": y, "x": x, "region": region, "stratum": strata, "psu": psu,
                          "w": rng.uniform(.5, 3, n), "eligible": eligible})
    path = tmp_path / "survey.csv"
    frame.to_csv(path, index=False)
    project = create_project(tmp_path, "survey-intersection")
    result = run_workflow(project.root, [path], mode="auto", model_type="ols", y="y", x=["x"],
                          by_group={"column": "region"}, sampling_weight="w", survey_strata_col="stratum",
                          survey_psu_col="psu", survey_subpop="eligible == 1")
    root = project.root / "runs" / result["run_id"]
    assert result["status"] == "completed", read_json(root / "errors.json")
    collection = read_json(root / "model_results/collections/by_group.json")
    lines = [f'import delimited using "{path}", clear asdouble', 'svyset psu [pweight=w], strata(stratum)']
    for index, region in enumerate(("east", "north", "south")):
        lines += [f'svy, subpop(if eligible==1 & region=="{region}"): regress y x',
                  emit(f"b{index}", "_b[x]"), emit(f"se{index}", "_se[x]"),
                  emit(f"c{index}", "_b[_cons]"), emit(f"sec{index}", "_se[_cons]")]
    stata = run(tmp_path / "stata", "\n".join(lines), name="intersection")
    members = {m["key"]: m for m in collection["members"]}
    for index, region in enumerate(("east", "north", "south")):
        member = members[region]
        assert member["status"] == "estimated", member
        packet = read_json(root / member["result_ref"])
        expected_n = int(((frame["region"] == region) & (frame["eligible"] == 1)).sum())
        assert packet["nobs_subpopulation"] == member["nobs"] == expected_n
        for term, b, se in (("x", f"b{index}", f"se{index}"), ("Intercept", f"c{index}", f"sec{index}")):
            assert packet["coefficients"][term]["estimate"] == pytest.approx(stata[b], rel=1e-9)
            assert packet["coefficients"][term]["std_error"] == pytest.approx(stata[se], rel=1e-8)
