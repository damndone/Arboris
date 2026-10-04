"""v1.8.10 step 3: the check library.

Checks apply by traits, report one of six statuses with their evidence, and
agree with reference implementations where one exists.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest
import statsmodels.formula.api as smf

from workbench.checks import CHECKS, applicable_checks, build_context, run_checks
from workbench.checks.contracts import BLINDING_LEVELS, STATUSES
from workbench.contracts.model.result_envelope_registry import (
    FAMILY_TRAITS,
    TRAIT_VOCABULARY,
    declaration_for,
    declared_families,
)

FIXTURES = Path(__file__).parent / "fixtures" / "checks"
ORACLE = json.loads((FIXTURES / "oracle.json").read_text())
CROSS = Path(__file__).resolve().parents[1] / "examples" / "datasets" / "cross_section.csv"


def _context(formula: str, frame: pd.DataFrame, model_type: str = "ols"):
    fitted = smf.ols(formula, frame).fit()
    return build_context(model_id="ols_1", model_type=model_type, fitted=fitted, kernel=None, nobs=int(fitted.nobs))


def _result(results, check_id):
    return next(item for item in results if item["check_id"] == check_id)


def test_every_family_declares_traits_from_the_vocabulary() -> None:
    assert set(FAMILY_TRAITS) == set(declared_families())
    for family in declared_families():
        traits = declaration_for(family).traits
        assert traits and traits <= TRAIT_VOCABULARY, family


def test_every_check_declares_its_blinding_and_sourced_thresholds() -> None:
    for spec in CHECKS:
        assert spec.blinding in BLINDING_LEVELS
        assert spec.requires <= TRAIT_VOCABULARY | {"vce.cluster", "weights.sampling"}, spec.check_id
        for threshold in spec.thresholds:
            assert threshold.source.strip(), (spec.check_id, threshold.name)


def test_applicability_is_traits_only() -> None:
    linear = declaration_for("logit").traits
    aggregation = declaration_for("cs_did").traits
    assert {spec.check_id for spec in applicable_checks(linear)} >= {"collinearity.gvif"}
    assert "collinearity.gvif" not in {spec.check_id for spec in applicable_checks(aggregation)}


@pytest.mark.parametrize(
    ("case", "formula", "path"),
    [
        ("cross_section_two", "wage ~ Q('education') + Q('experience')", CROSS),
        ("cross_section_region", "wage ~ Q('education') + Q('experience') + C(region)", CROSS),
        ("factor_frame", "y ~ Q('x1') + Q('x2') + Q('x3') + Q('x4') + C(grp)", FIXTURES / "gvif.csv"),
    ],
)
def test_gvif_agrees_with_car_vif(case, formula, path) -> None:
    results = run_checks(_context(formula, pd.read_csv(path)))
    terms = _result(results, "collinearity.gvif")["evidence"]["terms"]
    for term, expected in ORACLE[case].items():
        assert terms[term]["df"] == expected["df"]
        assert terms[term]["gvif"] == pytest.approx(expected["gvif"], abs=0.006)
        assert terms[term]["gvif_adjusted"] == pytest.approx(expected["gvif_adjusted"], abs=6e-4)


def test_a_vif_of_75_is_a_caution_that_names_the_term() -> None:
    result = _result(run_checks(_context("wage ~ Q('education') + Q('experience')", pd.read_csv(CROSS))), "collinearity.gvif")
    assert result["status"] == "caution"
    assert "VIF 75.7" in result["summary"]
    assert result["source"] == "computed" and result["blinding"] == "design"


def test_perfect_collinearity_fails_and_names_the_terms() -> None:
    frame = pd.read_csv(FIXTURES / "gvif.csv")
    frame["x5"] = frame["x1"] + 2 * frame["x3"]
    result = _result(run_checks(_context("y ~ Q('x1') + Q('x3') + Q('x5')", frame)), "collinearity.gvif")
    assert result["status"] == "fails"
    assert set(result["evidence"]["perfectly_collinear_terms"]) == {"x1", "x3", "x5"}


def test_rows_per_parameter_cautions_a_thin_design() -> None:
    frame = pd.read_csv(FIXTURES / "gvif.csv").head(30)
    result = _result(run_checks(_context("y ~ Q('x1') + Q('x2') + Q('x3') + Q('x4') + C(grp)", frame)), "design.rows_per_parameter")
    assert result["status"] == "caution"
    assert result["evidence"] == {"rows": 30, "parameters": 8, "rows_per_parameter": 3.75}


def test_a_check_that_cannot_run_says_so() -> None:
    context = _context("wage ~ Q('education') + Q('experience')", pd.read_csv(CROSS))
    context.design = None
    statuses = {item["check_id"]: item["status"] for item in run_checks(context)}
    assert statuses["collinearity.gvif"] == "not_checked"
    assert set(statuses.values()) <= set(STATUSES)


def _unfitted_context(model, model_type: str):
    """A context from the model object alone: separation needs no fit, and a
    separated logit may not fit at all."""
    from types import SimpleNamespace

    from workbench.checks.context import CheckContext, design_from_fitted

    holder = SimpleNamespace(model=model)
    return CheckContext(
        model_id="m_1", model_type=model_type, traits=declaration_for(model_type).traits,
        nobs=len(model.endog), design=design_from_fitted(holder), outcome=model.endog.astype(float),
    )


@pytest.mark.parametrize("case", list(ORACLE["separation"]))
def test_separation_agrees_with_detectseparation(case) -> None:
    outcome, link = case.rsplit("_", 1)
    frame = pd.read_csv(FIXTURES / "separation.csv")
    constructor = smf.logit if link == "logit" else smf.probit
    context = _unfitted_context(constructor(f"{outcome} ~ Q('x1') + Q('x2')", frame), link)
    result = _result(run_checks(context), "fit.separation")
    expected = ORACLE["separation"][case]
    assert (result["status"] == "fails") is expected["separated"]
    infinite = {item.split(" ")[0] for item in result["evidence"]["infinite_estimates"]}
    expected_infinite = {
        {"(Intercept)": "Intercept"}.get(name, name)
        for name, value in expected["coefficients"].items() if value in ("Inf", "-Inf")
    }
    assert infinite == expected_infinite


@pytest.mark.parametrize("outcome", ["over", "equi"])
def test_overdispersion_agrees_with_the_cameron_trivedi_regression(outcome) -> None:
    frame = pd.read_csv(FIXTURES / "counts.csv")
    fitted = smf.poisson(f"{outcome} ~ Q('x')", frame).fit(disp=False)
    context = build_context(model_id="poisson_1", model_type="poisson", fitted=fitted, kernel=None, nobs=len(frame))
    result = _result(run_checks(context), "fit.overdispersion")
    expected = ORACLE["overdispersion"][outcome]
    assert result["evidence"]["alpha"] == pytest.approx(expected["alpha"], rel=1e-6)
    assert result["evidence"]["p_value"] == pytest.approx(expected["p_value"], rel=1e-5)
    assert (result["status"] == "caution") is (expected["p_value"] < 0.05)


def test_overdispersion_does_not_apply_where_the_dispersion_is_estimated() -> None:
    ids = {spec.check_id for spec in applicable_checks(declaration_for("negative_binomial").traits)}
    assert "fit.overdispersion" not in ids
    assert "fit.overdispersion" in {spec.check_id for spec in applicable_checks(declaration_for("poisson").traits)}


def test_a_perfect_fit_fails() -> None:
    result = _result(run_checks(_context("wage ~ Q('education') + Q('experience')", pd.read_csv(CROSS))), "fit.perfect")
    assert result["status"] == "fails" and result["blinding"] == "post_fit"


def test_few_clusters_are_a_caution() -> None:
    context = _context("wage ~ Q('education') + Q('experience')", pd.read_csv(CROSS))
    context.kernel = {"covariance_estimator": "cluster", "n_clusters": 12}
    context.traits = context.traits | {"vce.cluster"}
    result = _result(run_checks(context), "vce.cluster_count")
    assert result["status"] == "caution" and result["evidence"] == {"clusters": 12}
