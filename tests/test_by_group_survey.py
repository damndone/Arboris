"""v1.8.10 step 7: by-group under a sampling design is domain estimation.

Filtering a group's rows before a design-based fit destroys the variance
estimate, so each group is a subpopulation of the full design (Stata
`svy, subpop()`). Compared live with Stata 18: each group's coefficients,
standard errors and design degrees of freedom, and the group-difference test
(`test` after `svy: regress y i.region##c.x`, Korn-Graubard adjusted F).

Also pins the single-run subpopulation fix found here: the point estimate is
the subpopulation's, not every row's.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.stata_oracle import emit, requires_stata, run
from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

DESIGN = {"sampling_weight": "w", "survey_strata_col": "stratum", "survey_psu_col": "psu"}
REGIONS = ("east", "north", "south")


@pytest.fixture(scope="module")
def survey_csv(tmp_path_factory) -> Path:
    rng = np.random.default_rng(7)
    n = 900
    stratum = rng.integers(1, 5, n)
    psu = stratum * 100 + rng.integers(1, 11, n)
    region = rng.choice(list(REGIONS), n)
    x = rng.normal(size=n)
    slope = pd.Series(region).map({"east": 0.4, "north": 0.9, "south": 0.2}).to_numpy()
    y = 1 + slope * x + rng.normal(size=n) + 0.3 * (psu % 7)
    frame = pd.DataFrame({"y": y, "x": x, "region": region, "stratum": stratum, "psu": psu,
                          "w": rng.uniform(0.5, 3, n)})
    path = tmp_path_factory.mktemp("svy") / "svy.csv"
    frame.to_csv(path, index=False)
    return path


@pytest.fixture(scope="module")
def grouped(survey_csv, tmp_path_factory):
    project = create_project(tmp_path_factory.mktemp("svy-run"), "svy")
    result = run_workflow(project.root, [survey_csv], mode="auto", model_type="ols", y="y", x=["x"],
                          by_group={"column": "region"}, **DESIGN)
    run_root = project.root / "runs" / result["run_id"]
    assert result["status"] == "completed", read_json(run_root / "errors.json")
    return run_root


def test_groups_are_domains_of_the_full_design(grouped) -> None:
    collection = read_json(grouped / "model_results" / "collections" / "by_group.json")
    assert collection["parameters"]["semantics"] == "domain"
    for member in collection["members"]:
        packet = read_json(grouped / member["result_ref"])
        assert packet["by_group"]["semantics"] == "domain"
        assert packet["nobs_subpopulation"] == member["nobs"] and packet["nobs"] == 900
        assert "r_squared" not in packet


@requires_stata
def test_each_group_and_the_difference_test_match_stata_svy_subpop(grouped, survey_csv, tmp_path) -> None:
    lines = [f'import delimited using "{survey_csv}", clear asdouble',
             "svyset psu [pweight=w], strata(stratum)",
             "encode region, gen(reg)"]
    for index, name in enumerate(REGIONS, start=1):
        lines += [f'svy, subpop(if region=="{name}"): regress y x',
                  emit(f"b{index}", "_b[x]"), emit(f"se{index}", "_se[x]"),
                  emit(f"c{index}", "_b[_cons]"), emit(f"sec{index}", "_se[_cons]"), emit(f"df{index}", "e(df_r)")]
    lines += ["svy: regress y i.reg##c.x",
              "test 2.reg 3.reg 2.reg#c.x 3.reg#c.x", emit("all_F", "r(F)"), emit("all_df", "r(df)"),
              emit("all_dfr", "r(df_r)"), emit("all_p", "r(p)"),
              "test 2.reg#c.x 3.reg#c.x", emit("x_F", "r(F)"), emit("x_dfr", "r(df_r)"), emit("x_p", "r(p)")]
    stata = run(tmp_path, "\n".join(lines), name="svy_by")
    collection = read_json(grouped / "model_results" / "collections" / "by_group.json")
    for index, member in enumerate(collection["members"], start=1):
        packet = read_json(grouped / member["result_ref"])
        coefficients = packet["coefficients"]
        assert coefficients["x"]["estimate"] == pytest.approx(stata[f"b{index}"], rel=1e-9)
        assert coefficients["x"]["std_error"] == pytest.approx(stata[f"se{index}"], rel=1e-8)
        assert coefficients["Intercept"]["estimate"] == pytest.approx(stata[f"c{index}"], rel=1e-9)
        assert coefficients["Intercept"]["std_error"] == pytest.approx(stata[f"sec{index}"], rel=1e-8)
        # Stata's e(df_r) is the design df (PSUs - strata). Coefficient t tests
        # here follow R survey, which subtracts the parameters: degf - p + 1.
        # The two conventions differ by p - 1; the design df itself agrees.
        assert packet["survey_design"]["degf"] == stata[f"df{index}"]
        assert packet["survey_design"]["residual_degf"] == stata[f"df{index}"] - (len(coefficients) - 1)
    differences = read_json(grouped / collection["pooled"]["result_ref"])
    tests = {test["name"]: test for test in differences["tests"]}
    # Compare the Wald statistic W both report through their adjusted F:
    # F = (d - q + 1) / (d q) W, with Stata's d the design df and ours the
    # residual df of the convention above.
    for name, (stata_f, stata_dfr, q) in {"all": (stata["all_F"], stata["all_dfr"], 4),
                                           "x": (stata["x_F"], stata["x_dfr"], 2)}.items():
        stata_d = stata_dfr + q - 1
        stata_w = stata_f * stata_d * q / (stata_d - q + 1)
        ours = tests[name]
        our_d = ours["df_den"] + q - 1
        our_w = ours["statistic"] * our_d * q / (our_d - q + 1)
        assert our_w == pytest.approx(stata_w, rel=1e-7), name
        assert ours["df_num"] == q and ours["adjustment"] == "korn_graubard_adjusted_f"


def test_a_family_without_design_variance_is_refused_by_group_under_a_design(survey_csv, tmp_path) -> None:
    frame = pd.read_csv(survey_csv).assign(yb=lambda d: (d["y"] > d["y"].median()).astype(int))
    source = tmp_path / "svy_binary.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "svy-logit")
    result = run_workflow(project.root, [source], mode="auto", model_type="logit", y="yb", x=["x"],
                          by_group={"column": "region"}, **DESIGN)
    assert result["status"] in {"failed", "blocked"}
    issues = read_json(project.root / "runs" / result["run_id"] / "errors.json")["issues"]
    assert any(issue["code"].startswith(("BY_GROUP_", "SURVEY_")) for issue in issues), issues
