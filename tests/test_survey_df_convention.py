"""v1.8.10: the df convention for coefficient tests under a sampling design.

Default "design": t(degf) and the Korn-Graubard adjusted F, as in Stata svy
(compared live in tests/test_by_group_survey.py). Option "design_minus_p":
t(degf - p + 1) and W / q on (q, degf - p + 1), as in R survey (compared with
the committed R oracle in tests/fixtures/survey/). The choice is recorded in
the result, the inference kernel, the Agent's projection and the report.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.lineage.run_inputs import read_run_inputs
from workbench.orchestrator import run_workflow
from workbench.postestimation import wald_test
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "survey"
ORACLE = json.loads((FIXTURES / "oracle.json").read_text())
JOINT = [{"terms": {"x1": 1.0}, "value": 0.0}, {"terms": {"x2": 1.0}, "value": 0.0}]
DESIGN = {"sampling_weight": "weight", "survey_strata_col": "stratum", "survey_psu_col": "psu",
          "survey_fpc_col": "fpc"}


def _run(tmp_path: Path, **extra) -> Path:
    tmp_path.mkdir(parents=True)
    source = tmp_path / "design.csv"
    source.write_text((FIXTURES / "design.csv").read_text())
    project = create_project(tmp_path, "svy")
    outcome = run_workflow(project.root, [source], mode="auto", model_type="ols", y="y",
                           x=["x1", "x2"], **DESIGN, **extra)
    run_root = project.root / "runs" / outcome["run_id"]
    assert outcome["status"] == "completed", read_json(run_root / "errors.json")
    return run_root


def _kernel(run_root: Path) -> dict:
    return read_json(run_root / kernel_relative_path("ols_1"))


def test_the_default_is_the_design_df_and_the_korn_graubard_f(tmp_path: Path) -> None:
    run_root = _run(tmp_path / "a")
    # Absent from the stored inputs when not chosen, so earlier runs' inputs are unchanged.
    assert "survey_df" not in read_run_inputs(run_root)["form"]
    design = read_json(run_root / "model_results" / "ols_1.json")["survey_design"]
    assert (design["df_convention"], design["degf"], design["inference_degf"], design["residual_degf"]) == (
        "design", 8, 8, 6,
    )
    kernel = _kernel(run_root)
    assert kernel["df_method"] == "design" and kernel["df_resid"] == 8
    wald = wald_test(kernel, JOINT)
    assert wald["adjustment"] == "korn_graubard_adjusted_f"
    assert wald["df_den"] == 7
    w = ORACLE["adjusted_wald"]["statistic"] * 2  # same W as R's, F = W / q there
    assert wald["statistic"] == pytest.approx(w * 7 / (8 * 2), rel=1e-7)


def test_the_r_convention_reproduces_r_survey(tmp_path: Path) -> None:
    run_root = _run(tmp_path / "b", survey_df="design_minus_p")
    # A rerun replays the stored inputs, so it keeps the chosen convention.
    assert read_run_inputs(run_root)["form"]["survey_df"] == "design_minus_p"
    packet = read_json(run_root / "model_results" / "ols_1.json")
    assert packet["survey_design"]["df_convention"] == "design_minus_p"
    assert packet["survey_design"]["inference_degf"] == 6
    oracle = ORACLE["linearization"]
    assert packet["coefficients"]["x1"]["ci_lower"] == pytest.approx(oracle["ci_lower"]["x1"], rel=1e-8)
    kernel = _kernel(run_root)
    assert kernel["df_method"] == "design_minus_p" and kernel["df_resid"] == 6
    wald = wald_test(kernel, JOINT)
    expected = ORACLE["adjusted_wald"]
    assert wald.get("adjustment") is None
    assert (wald["df_num"], wald["df_den"]) == (expected["df"], expected["ddf"])
    assert wald["statistic"] == pytest.approx(expected["statistic"], rel=1e-7)
    assert wald["p_value"] == pytest.approx(expected["p_value"], rel=1e-6)


def test_the_agent_reads_the_design_inference_not_the_pre_design_fit(tmp_path: Path) -> None:
    """The fitted object's covariance evidence still says HC1, t(N - K)."""
    from workbench.agent.context_tools import _bounded_inference

    packet = read_json(_run(tmp_path / "c") / "model_results" / "ols_1.json")
    assert packet["covariance_evidence"]["effective_df"] == 77  # unchanged, fingerprinted
    assert _bounded_inference(packet) == {
        "covariance": "survey_design", "covariance_estimator": "survey_design_linearization",
        "inference_distribution": "t", "effective_df": 8, "df_method": "design", "legacy_asymptotic": False,
    }


def test_the_convention_is_published_and_reaches_the_agent_and_the_report(tmp_path: Path) -> None:
    from workbench.agent.workflow_contracts import genesis_run_params
    from workbench.report_view_model import _design_df_fact
    from workbench.survey.fields import DESIGN_FIELDS

    assert "survey_df" in DESIGN_FIELDS
    assert genesis_run_params({"survey_df": "design_minus_p"})["survey_df"] == "design_minus_p"
    assert "t(8)" in _design_df_fact({"df_convention": "design", "degf": 8, "inference_degf": 8})
    # Results from before v1.8.10 carry no convention and used R's.
    legacy = _design_df_fact({"degf": 8, "residual_degf": 6})
    assert "t(6)" in legacy and "R survey" in legacy
