"""Approved single-stage FPC semantics, independent R/Stata reference values."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from workbench.contracts.model.inference_kernel import build_inference_kernel
from workbench.postestimation.registry import run_operation
from workbench.survey import SurveyDesign, SurveyEngineError, estimate_with_design
from workbench.survey.adapters import glm_estimator_spec

FIXTURES = Path(__file__).parent / "fixtures/survey_fpc_v1811"
REFERENCE = json.loads((FIXTURES / "oracle_reference.json").read_text())["cases"]
STATA = json.loads((FIXTURES / "stata_reference.json").read_text())


def _data(source="design"):
    return pd.read_csv(FIXTURES / f"{source}.csv")


def _design(frame=None, **kwargs):
    return SurveyDesign(frame=_data() if frame is None else frame,
                        weight="weight", strata="stratum", psu="psu", **kwargs)


def _fit(case):
    frame = _data(case["source"])
    if not case["psu"]:
        frame["observation_fpc"] = 20
    if not case["strata"]:
        frame["unstratified_fpc"] = 32
    design = SurveyDesign(frame=frame, weight="weight",
                          strata="stratum" if case["strata"] else None,
                          psu="psu" if case["psu"] else None,
                          fpc=case["fpc"], lonely_psu=case["lonely_psu"],
                          subpop="subpop == 1" if case["domain"] else None)
    result = estimate_with_design(design, glm_estimator_spec(
        family="ols", glm_family="gaussian", y="y", x=["x1", "x2"]),
        method="linearization")
    return design, result


@pytest.mark.parametrize("name", sorted(REFERENCE))
def test_single_stage_covariance_and_inference_match_independent_r(name):
    reference = REFERENCE[name]
    design, result = _fit(reference)
    assert result.terms == reference["terms"]
    assert result.degf == reference["design_df"] == design.degf
    np.testing.assert_allclose(result.covariance, reference["covariance"], rtol=1e-9, atol=1e-11)
    for term in result.terms:
        assert result.estimates[term] == pytest.approx(reference["coefficients"][term], abs=1e-10)
        assert result.standard_errors[term] == pytest.approx(reference["standard_errors"][term], rel=1e-9)
        t = result.estimates[term] / result.standard_errors[term]
        assert t == pytest.approx(reference["t"][term], rel=1e-9)
        assert 2 * stats.t.sf(abs(t), result.inference_degf) == pytest.approx(reference["p"][term], rel=1e-8)
        assert result.ci_lower[term] == pytest.approx(reference["ci_lower"][term], abs=1e-9)
        assert result.ci_upper[term] == pytest.approx(reference["ci_upper"][term], abs=1e-9)
    test = result.joint_test(["x1", "x2"])
    assert test.statistic == pytest.approx(reference["wald"]["statistic"], rel=1e-9)
    assert (test.df, test.ddf) == (reference["wald"]["df"], reference["wald"]["ddf"])
    assert test.p_value == pytest.approx(reference["wald"]["p"], rel=1e-8)
    kernel = build_inference_kernel(
        model_id="ols_1", model_type="ols", param_names=result.terms,
        params=[result.estimates[t] for t in result.terms], vcov=result.covariance,
        reference_distribution="t", df_resid=result.inference_degf, loglik=None,
        nobs=reference["nobs"], covariance_estimator="survey_linearization",
        weights="sampling", df_method="design")
    linear = run_operation("lincom", [kernel], {"terms": {"x1": 1, "x2": -1}})
    for key, reference_key in [("estimate", "estimate"), ("std_error", "se"), ("p_value", "p")]:
        assert linear[key] == pytest.approx(reference["lincom"][reference_key], rel=1e-8, abs=1e-10)
    np.testing.assert_allclose(linear["ci"], [reference["lincom"]["low"], reference["lincom"]["high"]],
                               rtol=1e-8, atol=1e-10)


def test_count_and_fraction_are_equivalent_with_heterogeneous_strata():
    frame = _data()
    contributions = frame[["x1", "x2"]].to_numpy()
    a = _design(frame, fpc="population_fpc")._design_variance(contributions)
    b = _design(frame, fpc="fraction_fpc")._design_variance(contributions)
    np.testing.assert_array_equal(a, b)


def test_zero_fraction_is_bitwise_identical_to_without_fpc():
    frame = _data()
    contributions = frame[["x1", "x2"]].to_numpy()
    expected = _design(frame)._design_variance(contributions)
    actual = _design(frame, fpc="zero_fpc")._design_variance(contributions)
    np.testing.assert_array_equal(actual, expected)


def test_census_has_zero_variance_even_for_a_single_psu_stratum():
    frame = _data("lonely")
    actual = _design(frame, fpc="all_certainty_fpc")._design_variance(frame[["x1", "x2"]].to_numpy())
    np.testing.assert_array_equal(actual, np.zeros((2, 2)))


def test_noncertainty_single_psu_still_fails():
    frame = _data("lonely")
    with pytest.raises(SurveyEngineError, match="SURVEY_LONELY_PSU"):
        _design(frame, fpc="fraction_fpc")._design_variance(frame[["x1"]].to_numpy())


@pytest.mark.parametrize("value", [-.1, np.nan, np.inf, -np.inf, pd.NA, "10", True, 10.5, 10+1j])
def test_invalid_fpc_values_are_rejected_without_coercion(value):
    frame = _data()
    frame["invalid"] = value
    with pytest.raises(SurveyEngineError, match="FPC"):
        _design(frame, fpc="invalid")


def test_mixed_count_fraction_units_are_rejected_even_across_strata():
    frame = _data()
    frame["invalid"] = np.where(frame.stratum == "h01", .5, 10)
    with pytest.raises(SurveyEngineError, match="FPC"):
        _design(frame, fpc="invalid")


def test_boolean_inside_numeric_object_column_is_not_cast():
    frame = _data()
    values = [10] * len(frame)
    values[0] = True
    frame["invalid"] = pd.Series(values, dtype=object)
    with pytest.raises(SurveyEngineError, match="FPC"):
        _design(frame, fpc="invalid")


def test_fpc_must_be_constant_within_each_stratum():
    frame = _data()
    frame.loc[0, "population_fpc"] = 30
    with pytest.raises(SurveyEngineError, match="FPC"):
        _design(frame, fpc="population_fpc")


def test_population_cannot_be_smaller_than_full_design_psu_count():
    frame = _data("subpop")
    frame["invalid"] = 2
    with pytest.raises(SurveyEngineError, match="FPC"):
        _design(frame, fpc="invalid", subpop="subpop == 1")


@pytest.mark.parametrize("column", [True, False, 0, 1, [], ["population_fpc"], ""])
def test_fpc_column_parameter_is_a_single_nonempty_name(column):
    with pytest.raises(SurveyEngineError, match="FPC"):
        _design(fpc=column)


@pytest.mark.parametrize("kind", ["brr", "jackknife", "bootstrap", "provided"])
def test_fpc_with_declared_replicate_design_is_rejected(kind):
    with pytest.raises(SurveyEngineError, match="FPC"):
        _design(fpc="population_fpc", replicate_type=kind,
                replicate_weight_columns=["repw01"] if kind == "provided" else [])


def test_fpc_with_replicate_columns_is_rejected_even_without_a_type():
    with pytest.raises(SurveyEngineError, match="FPC"):
        _design(fpc="population_fpc", replicate_weight_columns=["repw01"])


def test_fpc_is_revalidated_after_dataframe_mutation():
    frame = _data()
    design = _design(frame, fpc="population_fpc")
    frame.loc[0, "population_fpc"] = np.nan
    with pytest.raises(SurveyEngineError, match="FPC"):
        design._design_variance(frame[["x1"]].to_numpy())


@pytest.mark.parametrize("name", STATA["cases"])
def test_complete_report_quantities_match_stata_svy(name):
    _, result = _fit(REFERENCE[name])
    values = STATA["values"]
    assert result.inference_degf == values[f"{name}_df"]
    for i, term in enumerate(result.terms):
        label = "Intercept" if term == "(Intercept)" else term
        assert result.estimates[term] == pytest.approx(values[f"{name}_b_{label}"], abs=1e-10)
        assert result.standard_errors[term] == pytest.approx(values[f"{name}_se_{label}"], rel=1e-9)
        p = 2 * stats.t.sf(abs(result.estimates[term] / result.standard_errors[term]), result.inference_degf)
        assert p == pytest.approx(values[f"{name}_p_{label}"], rel=1e-8)
        for j, other in enumerate(result.terms):
            other_label = "Intercept" if other == "(Intercept)" else other
            assert result.covariance[i, j] == pytest.approx(values[f"{name}_cov_{label}_{other_label}"], rel=1e-9, abs=1e-11)
    test = result.joint_test(["x1", "x2"])
    assert test.statistic == pytest.approx(values[f"{name}_wald"], rel=1e-9)
    assert test.df == values[f"{name}_wald_df"]
    assert test.ddf == values[f"{name}_wald_ddf"]
    assert test.p_value == pytest.approx(values[f"{name}_wald_p"], rel=1e-8)
    kernel = build_inference_kernel(
        model_id="ols_1", model_type="ols", param_names=result.terms,
        params=[result.estimates[t] for t in result.terms], vcov=result.covariance,
        reference_distribution="t", df_resid=result.inference_degf, loglik=None,
        nobs=REFERENCE[name]["nobs"], covariance_estimator="survey_linearization",
        weights="sampling", df_method="design")
    linear = run_operation("lincom", [kernel], {"terms": {"x1": 1, "x2": -1}})
    for key, suffix in [("estimate", "lincom"), ("std_error", "lincom_se"), ("p_value", "lincom_p")]:
        assert linear[key] == pytest.approx(values[f"{name}_{suffix}"], rel=1e-8, abs=1e-10)
    np.testing.assert_allclose(linear["ci"], [values[f"{name}_lincom_lo"], values[f"{name}_lincom_hi"]],
                               rtol=1e-8, atol=1e-10)


@pytest.mark.parametrize("name", ["population", "subpopulation", "lonely_census"])
def test_real_workflow_kernel_and_postestimation_read_corrected_covariance(tmp_path, name):
    from workbench.artifacts import read_json
    from workbench.contracts.model.inference_kernel import kernel_relative_path
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    reference = REFERENCE[name]
    project = create_project(tmp_path, "fpc_workflow")
    outcome = run_workflow(
        project.root, [FIXTURES / f"{reference['source']}.csv"], mode="auto",
        model_type="ols", y="y", x=["x1", "x2"], sampling_weight="weight",
        survey_strata_col="stratum", survey_psu_col="psu", survey_fpc_col=reference["fpc"],
        survey_subpop="subpop == 1" if reference["domain"] else "")
    root = project.root / "runs" / outcome["run_id"]
    assert outcome["status"] == "completed", read_json(root / "errors.json")
    primary = read_json(root / "model_results/ols_1.json")
    kernel = read_json(root / kernel_relative_path("ols_1"))
    mapping = {"Intercept": "(Intercept)", "x1": "x1", "x2": "x2"}
    positions = [reference["terms"].index(mapping[name]) for name in kernel["param_names"]]
    expected = np.asarray(reference["covariance"])[np.ix_(positions, positions)]
    np.testing.assert_allclose(kernel["vcov"], expected, rtol=1e-9, atol=1e-11)
    assert kernel["df_method"] == "design"
    assert kernel["df_resid"] == reference["design_df"]
    for term, entry in primary["coefficients"].items():
        rterm = mapping[term]
        assert entry["std_error"] == pytest.approx(reference["standard_errors"][rterm], rel=1e-9)
        assert entry["p_value"] == pytest.approx(reference["p"][rterm], rel=1e-8)
        assert entry["variance_source"] == "survey_design"
    linear = run_operation("lincom", [kernel], {"terms": {"x1": 1, "x2": -1}})
    assert linear["std_error"] == pytest.approx(reference["lincom"]["se"], rel=1e-9)
    assert linear["p_value"] == pytest.approx(reference["lincom"]["p"], rel=1e-8)
