"""v1.8.7 block 2 — design variance engine, checked against R `survey`.

Every reference value here comes from `tests/fixtures/survey/generate_oracle.R`,
which is committed and re-runnable.  Nothing in this file is compared against
another Python implementation: statsmodels is the execution engine, so checking
it against itself is internal consistency, not an oracle.

The fixture is built so these assertions cannot pass by accident:
  * degf is 8, making t (2.306) far from normal (1.96);
  * the five lonely-PSU strategies give five distinguishable SEs;
  * the subpopulation fixture empties whole PSUs, so the correct and incorrect
    approaches genuinely disagree.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

FIXTURES = Path(__file__).parent / "fixtures" / "survey"


def _oracle() -> dict:
    return json.loads((FIXTURES / "oracle.json").read_text())


def _design_frame() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "design.csv")


def weighted_ols(frame: pd.DataFrame, weights: np.ndarray) -> dict[str, float]:
    """A plain weighted least squares fit: the minimum an estimator must provide.

    Deliberately written here rather than imported: the engine must be able to
    drive *any* deterministic re-fit, and an estimator defined entirely inside a
    test proves the engine has no privileged knowledge of the real families.
    """
    x = np.column_stack([np.ones(len(frame)), frame["x1"].to_numpy(), frame["x2"].to_numpy()])
    y = frame["y"].to_numpy()
    w = np.asarray(weights, dtype=float)
    xtw = x.T * w
    beta = np.linalg.solve(xtw @ x, xtw @ y)
    return {"(Intercept)": beta[0], "x1": beta[1], "x2": beta[2]}


@pytest.fixture()
def design():
    from workbench.survey import SurveyDesign

    return SurveyDesign(
        frame=_design_frame(),
        strata="stratum",
        psu="psu",
        weight="weight",
    )


def weighted_ols_influence(frame: pd.DataFrame, weights: np.ndarray) -> dict[str, np.ndarray]:
    """Per-observation influence contributions for the WLS fit above.

    infl_j = (X'WX)^-1 x_j w_j e_j -- the bread times each observation's score.
    Supplying this is what unlocks the linearization channel; an estimator that
    cannot produce it is still perfectly usable through replicate weights.
    """
    x = np.column_stack([np.ones(len(frame)), frame["x1"].to_numpy(), frame["x2"].to_numpy()])
    y = frame["y"].to_numpy()
    w = np.asarray(weights, dtype=float)
    bread = np.linalg.inv((x.T * w) @ x)
    resid = y - x @ (bread @ ((x.T * w) @ y))
    contrib = (x * (w * resid)[:, None]) @ bread.T
    return {"(Intercept)": contrib[:, 0], "x1": contrib[:, 1], "x2": contrib[:, 2]}


@pytest.fixture()
def estimator():
    """Refit only: the minimum contract, so only the replicate channel is open."""
    from workbench.survey import EstimatorSpec

    return EstimatorSpec(name="synthetic_wls", refit=weighted_ols)


@pytest.fixture()
def linearizable_estimator():
    """Refit plus influence: additionally unlocks Taylor linearization."""
    from workbench.survey import EstimatorSpec

    return EstimatorSpec(
        name="synthetic_wls_linearizable",
        refit=weighted_ols,
        influence=weighted_ols_influence,
    )


# --------------------------------------------------------------------------
# design structure and degrees of freedom
# --------------------------------------------------------------------------

def test_design_reports_structure_and_degrees_of_freedom(design):
    oracle = _oracle()["design"]
    assert design.n_obs == oracle["n_obs"]
    assert design.n_strata == oracle["n_strata"]
    assert design.n_psu == oracle["n_psu"]
    assert design.degf == oracle["degf"] == design.n_psu - design.n_strata


@pytest.mark.parametrize(
    ("bad_weights", "reason"),
    [
        (lambda n: np.full(n, -1.0), "nonpositive"),
        (lambda n: np.array([np.nan] + [1.0] * (n - 1)), "nonfinite"),
        (lambda n: np.array([np.inf] + [1.0] * (n - 1)), "nonfinite"),
        (lambda n: np.zeros(n), "all_zero"),
    ],
)
def test_survey_design_rejects_invalid_sampling_weights_at_real_entry(
    bad_weights, reason
):
    """Sampling weights cannot reach variance math as an unchecked array."""
    from workbench.survey import SurveyDesign, SurveyEngineError

    frame = _design_frame()
    frame["weight"] = bad_weights(len(frame))

    with pytest.raises(SurveyEngineError) as excinfo:
        SurveyDesign(frame=frame, strata="stratum", psu="psu", weight="weight")

    assert excinfo.value.code == "SURVEY_INVALID_SAMPLING_WEIGHTS"
    assert excinfo.value.context["reason"] == reason


def test_survey_engine_revalidates_mutated_sampling_weights_before_estimation(
    design, linearizable_estimator
):
    """The engine entry remains fail-closed even if its mutable frame changes."""
    from workbench.survey import SurveyEngineError, estimate_with_design

    design.frame.loc[:, "weight"] = 0.0

    with pytest.raises(SurveyEngineError) as excinfo:
        estimate_with_design(design, linearizable_estimator, method="linearization")

    assert excinfo.value.code == "SURVEY_INVALID_SAMPLING_WEIGHTS"
    assert excinfo.value.context["reason"] == "all_zero"


def test_survey_design_rejects_object_integer_weight_before_float_conversion():
    """An unrepresentable object integer is a typed design failure, not OverflowError."""
    from workbench.survey import SurveyDesign, SurveyEngineError

    frame = _design_frame()
    frame["weight"] = pd.Series(
        [10**400] + [1] * (len(frame) - 1),
        index=frame.index,
        dtype=object,
    )

    with pytest.raises(SurveyEngineError) as excinfo:
        SurveyDesign(frame=frame, strata="stratum", psu="psu", weight="weight")

    assert excinfo.value.code == "SURVEY_INVALID_SAMPLING_WEIGHTS"
    assert excinfo.value.context["reason"] == "not_float_representable"


def test_survey_engine_rejects_mutated_object_integer_weight_before_float_conversion(
    design, linearizable_estimator
):
    """The mutable engine entry must apply the same safe weight boundary."""
    from workbench.survey import SurveyEngineError, estimate_with_design

    design.frame["weight"] = pd.Series(
        [10**400] + [1] * (len(design.frame) - 1),
        index=design.frame.index,
        dtype=object,
    )

    with pytest.raises(SurveyEngineError) as excinfo:
        estimate_with_design(design, linearizable_estimator, method="linearization")

    assert excinfo.value.code == "SURVEY_INVALID_SAMPLING_WEIGHTS"
    assert excinfo.value.context["reason"] == "not_float_representable"


@pytest.mark.parametrize(
    "expression",
    [
        "missing_column == 1",
        "x1 +",
        "__import__('os').system('echo injected')",
    ],
)
def test_invalid_subpopulation_expressions_are_bounded_typed_failures(expression):
    """Subpopulation expressions must not leak pandas parser errors or execute code."""
    from workbench.survey import SurveyDesign, SurveyEngineError

    with pytest.raises(SurveyEngineError) as excinfo:
        SurveyDesign(
            frame=_design_frame(),
            strata="stratum",
            psu="psu",
            weight="weight",
            subpop=expression,
        ).subpop_mask()

    assert excinfo.value.code == "SURVEY_SUBPOP_INVALID"
    assert len(str(excinfo.value)) <= 512
    assert "UndefinedVariableError" not in str(excinfo.value)
    assert "SyntaxError" not in str(excinfo.value)


@pytest.mark.parametrize("kind", ["numeric", "object", "nullable_boolean", "undefined"])
def test_subpopulation_requires_boolean_values_without_missingness(kind):
    """A subpopulation is a boolean design mask, never truthy coercion."""
    from workbench.survey import SurveyDesign, SurveyEngineError

    frame = _design_frame()
    if kind == "numeric":
        expression = "x1"
    elif kind == "object":
        frame["object_flag"] = pd.Series([True] * len(frame), dtype=object)
        expression = "object_flag"
    elif kind == "nullable_boolean":
        frame["nullable_flag"] = pd.Series(
            [True] + [pd.NA] * (len(frame) - 1), dtype="boolean"
        )
        expression = "nullable_flag"
    else:
        expression = "undefined_flag == 1"

    with pytest.raises(SurveyEngineError) as excinfo:
        SurveyDesign(
            frame=frame, strata="stratum", psu="psu", weight="weight", subpop=expression
        ).subpop_mask()

    assert excinfo.value.code == "SURVEY_SUBPOP_INVALID"


def test_non_boolean_subpopulation_expression_is_not_silently_coerced():
    from workbench.survey import SurveyDesign, SurveyEngineError

    frame = _design_frame()
    frame["flag"] = pd.Series([True, False] * (len(frame) // 2), dtype=bool)
    mask = SurveyDesign(
        frame=frame, strata="stratum", psu="psu", weight="weight", subpop="flag"
    ).subpop_mask()
    assert mask.dtype == bool
    assert mask.tolist() == frame["flag"].tolist()


@pytest.mark.parametrize("replicate_type", ["brr", "jackknife", "bootstrap"])
def test_generated_replicate_types_reject_carried_columns_instead_of_ignoring_them(
    replicate_type, estimator
):
    """Generated methods cannot silently discard publisher-supplied columns."""
    from workbench.survey import SurveyDesign, SurveyEngineError
    from workbench.survey.replicates import build_replicates

    kwargs = {"replicate_type": replicate_type, "replicate_weight_columns": ["missing_repw"]}
    if replicate_type == "brr":
        kwargs["hadamard_matrix"] = _oracle()["replicate"]["brr"]["hadamard"]["matrix"]
    design = SurveyDesign(
        frame=_design_frame(), strata="stratum", psu="psu", weight="weight", **kwargs
    )

    with pytest.raises(SurveyEngineError) as excinfo:
        build_replicates(design, replicate_type)

    assert excinfo.value.code == "SURVEY_REPLICATE_COLUMNS_UNSUPPORTED"


def test_provided_replicate_column_names_are_persisted_in_the_estimate(estimator):
    from workbench.survey import SurveyDesign, estimate_with_design

    frame = pd.read_csv(FIXTURES / "design_with_replicate_weights.csv")
    columns = sorted(c for c in frame.columns if c.startswith("repw"))
    design = SurveyDesign(
        frame=frame,
        strata="stratum",
        psu="psu",
        weight="weight",
        replicate_type="provided",
        replicate_weight_columns=columns,
    )
    result = estimate_with_design(design, estimator, method="replicate")
    assert result.replicate_weight_columns == columns


def test_replicate_columns_cannot_be_ignored_by_linearization_or_missing_method(linearizable_estimator):
    from workbench.survey import SurveyDesign, SurveyEngineError, estimate_with_design

    frame = pd.read_csv(FIXTURES / "design_with_replicate_weights.csv")
    columns = sorted(c for c in frame.columns if c.startswith("repw"))
    design = SurveyDesign(
        frame=frame,
        strata="stratum",
        psu="psu",
        weight="weight",
        replicate_weight_columns=columns,
    )

    with pytest.raises(SurveyEngineError) as missing_method:
        estimate_with_design(design, linearizable_estimator, method="linearization")
    assert missing_method.value.code == "SURVEY_REPLICATE_TYPE_REQUIRED"


@pytest.mark.parametrize("declared_type", ["brr", "jackknife", "bootstrap"])
def test_replicate_method_argument_cannot_override_declared_design(declared_type, linearizable_estimator):
    from workbench.survey import SurveyDesign, SurveyEngineError, estimate_with_design

    frame = _design_frame()
    kwargs = {"replicate_type": declared_type}
    if declared_type == "brr":
        kwargs["hadamard_matrix"] = _oracle()["replicate"]["brr"]["hadamard"]["matrix"]
    design = SurveyDesign(frame=frame, strata="stratum", psu="psu", weight="weight", **kwargs)

    with pytest.raises(SurveyEngineError) as excinfo:
        estimate_with_design(
            design,
            linearizable_estimator,
            method="replicate",
            replicate_type="provided",
        )
    assert excinfo.value.code == "SURVEY_REPLICATE_DECLARATION_MISMATCH"


@pytest.mark.parametrize("subpopulation", [False, 0, [], ""])
def test_falsey_declared_subpopulation_is_invalid_not_undeclared(subpopulation):
    from workbench.survey import SurveyDesign, SurveyEngineError

    design = SurveyDesign(
        frame=_design_frame(),
        strata="stratum",
        psu="psu",
        weight="weight",
        subpop=subpopulation,
    )
    with pytest.raises(SurveyEngineError) as excinfo:
        design.subpop_mask()
    assert excinfo.value.code == "SURVEY_SUBPOP_INVALID"


@pytest.mark.parametrize("raw_weight", [10**100, 10**300])
def test_sampling_weight_absolute_bound_is_typed(raw_weight):
    from workbench.survey import SurveyDesign, SurveyEngineError

    frame = _design_frame()
    frame["weight"] = [raw_weight] * len(frame)
    with pytest.raises(SurveyEngineError) as excinfo:
        SurveyDesign(frame=frame, strata="stratum", psu="psu", weight="weight")
    assert excinfo.value.code == "SURVEY_INVALID_SAMPLING_WEIGHTS"
    assert excinfo.value.context["reason"] == "absolute_bound"


def test_design_effects_rejects_nonfinite_or_undefined_reference_variance():
    from workbench.survey import SurveyDesign, SurveyEngineError

    frame = _design_frame()
    frame["weight"] = 1.0
    design = SurveyDesign(
        frame=frame,
        strata="stratum",
        psu="psu",
        weight="weight",
        lonely_psu="remove",
    )
    with pytest.raises(SurveyEngineError) as excinfo:
        design.design_effects("x1")
    assert excinfo.value.code == "SURVEY_INFERENCE_UNAVAILABLE"
    assert excinfo.value.context["reason"] == "nonfinite_design_effect"


def test_nonpositive_residual_degf_is_a_typed_unavailable_inference(linearizable_estimator):
    from workbench.survey import SurveyDesign, SurveyEngineError, estimate_with_design

    frame = _design_frame()
    frame["stratum"] = "only-stratum"
    frame["psu"] = np.where(np.arange(len(frame)) % 2 == 0, "psu-a", "psu-b")
    design = SurveyDesign(
        frame=frame,
        strata="stratum",
        psu="psu",
        weight="weight",
        lonely_psu="adjust",
    )

    with pytest.raises(SurveyEngineError) as excinfo:
        estimate_with_design(design, linearizable_estimator, method="linearization")

    assert excinfo.value.code == "SURVEY_INFERENCE_UNAVAILABLE"
    assert excinfo.value.context["reason"] == "nonpositive_residual_degf"


def test_nonfinite_standard_error_is_a_typed_unavailable_inference(design):
    from workbench.survey import EstimatorSpec, SurveyEngineError, estimate_with_design

    def refit(frame, weights):
        return {"x": 1.0}

    def influence(frame, weights):
        return {"x": np.full(len(frame), np.nan)}

    with pytest.raises(SurveyEngineError) as excinfo:
        estimate_with_design(
            design,
            EstimatorSpec(name="nonfinite", refit=refit, influence=influence),
            method="linearization",
        )

    assert excinfo.value.code == "SURVEY_INFERENCE_UNAVAILABLE"
    assert excinfo.value.context["reason"] == "nonfinite_covariance"


def test_unknown_survey_weight_frame_is_rejected_before_design_construction():
    from workbench.survey import SurveyEngineError
    from workbench.survey.adapters import build_design_from_artifacts

    with pytest.raises(SurveyEngineError) as excinfo:
        build_design_from_artifacts(
            _design_frame(),
            {
                "_sampling_weight": "weight",
                "_survey_strata_col": "stratum",
                "_survey_psu_col": "psu",
                "_survey_weight_frame": "banana",
            },
        )

    assert excinfo.value.code == "SURVEY_WEIGHT_FRAME_INVALID"


def test_confidence_intervals_use_the_design_t_not_the_normal(design, linearizable_estimator):
    """The multiplier must come from the design, not from the normal.

    An earlier version of this test asserted qt(.975, degf) = 2.306. That was
    wrong: intervals use the *residual* design df, `degf - p + 1` = 6, giving
    2.447 -- which is what R reports as `df.residual` for svyglm. Both are far
    from 1.96, so the test still catches a normal approximation, but asserting
    the wrong one of the two would have hard-coded a real error.
    """
    from workbench.survey import estimate_with_design

    result = estimate_with_design(design, linearizable_estimator, method="linearization")
    oracle = _oracle()["linearization"]
    for term in ("(Intercept)", "x1", "x2"):
        assert result.ci_lower[term] == pytest.approx(oracle["ci_lower"][term], rel=1e-8)
        assert result.ci_upper[term] == pytest.approx(oracle["ci_upper"][term], rel=1e-8)

    half_width = result.ci_upper["x1"] - result.estimates["x1"]
    assert result.residual_degf == 6
    assert half_width / result.standard_errors["x1"] == pytest.approx(2.447, abs=0.01)


# --------------------------------------------------------------------------
# linearization
# --------------------------------------------------------------------------

def test_linearization_matches_r_svyglm(design, linearizable_estimator):
    from workbench.survey import estimate_with_design

    result = estimate_with_design(design, linearizable_estimator, method="linearization")
    oracle = _oracle()["linearization"]
    for term in ("(Intercept)", "x1", "x2"):
        assert result.estimates[term] == pytest.approx(oracle["estimate"][term], rel=1e-10)
        assert result.standard_errors[term] == pytest.approx(oracle["se"][term], rel=1e-8)
    assert result.degf == _oracle()["design"]["degf"]


# --------------------------------------------------------------------------
# replicate weights — the general channel
# --------------------------------------------------------------------------

@pytest.mark.parametrize("replicate_type", ["brr", "jackknife"])
def test_replicate_weights_match_r_withreplicates(estimator, replicate_type):
    """BRR additionally requires fixing the balanced set -- see the note below."""
    from workbench.survey import SurveyDesign, estimate_with_design

    kwargs = {}
    if replicate_type == "brr":
        kwargs["hadamard_matrix"] = _oracle()["replicate"]["brr"]["hadamard"]["matrix"]
    design = SurveyDesign(
        frame=_design_frame(), strata="stratum", psu="psu", weight="weight", **kwargs
    )
    result = estimate_with_design(
        design, estimator, method="replicate", replicate_type=replicate_type
    )
    key = {"brr": "brr", "jackknife": "jackknife"}[replicate_type]
    oracle = _oracle()["replicate"][key]
    for term in ("(Intercept)", "x1", "x2"):
        assert result.standard_errors[term] == pytest.approx(oracle["se"][term], rel=1e-8)


def test_brr_depends_on_the_balanced_set(estimator):
    """Not a defect -- a property, and one a reported SE must not hide.

    The same data and the same design give different BRR standard errors under
    different balanced sets: R returns 1.62518598 from its 12-replicate matrix
    and 1.70845732 from a 20-replicate one. A BRR standard error quoted without
    naming its set is therefore under-specified, which is why the oracle pins
    the matrix rather than asserting a bare number.
    """
    from workbench.survey import SurveyDesign, estimate_with_design

    r_matrix = _oracle()["replicate"]["brr"]["hadamard"]["matrix"]
    with_r_set = estimate_with_design(
        SurveyDesign(frame=_design_frame(), strata="stratum", psu="psu", weight="weight",
                     hadamard_matrix=r_matrix),
        estimator, method="replicate", replicate_type="brr",
    ).standard_errors["(Intercept)"]
    with_default_set = estimate_with_design(
        SurveyDesign(frame=_design_frame(), strata="stratum", psu="psu", weight="weight"),
        estimator, method="replicate", replicate_type="brr",
    ).standard_errors["(Intercept)"]

    assert with_r_set != pytest.approx(with_default_set, rel=1e-6)
    assert 0.5 < with_default_set / with_r_set < 2.0, "both sets must stay plausible"


def test_provided_replicate_weights_reproduce_the_brr_design(estimator):
    """The NHANES/CPS shape: the publisher ships replicate weight columns."""
    from workbench.survey import SurveyDesign, estimate_with_design

    frame = pd.read_csv(FIXTURES / "design_with_replicate_weights.csv")
    rep_cols = sorted(c for c in frame.columns if c.startswith("repw"))
    assert rep_cols, "fixture is missing its replicate weight columns"

    design = SurveyDesign(
        frame=frame, strata="stratum", psu="psu", weight="weight",
        replicate_weight_columns=rep_cols, replicate_type="provided",
    )
    result = estimate_with_design(design, estimator, method="replicate")
    oracle = _oracle()["replicate"]["provided"]
    for term in ("(Intercept)", "x1", "x2"):
        assert result.standard_errors[term] == pytest.approx(oracle["se"][term], rel=1e-8)


def test_replicate_failures_are_reported_not_silently_dropped(design, estimator):
    """A replicate that cannot be fitted must be counted and explained.

    R warns and discards; silently discarding shrinks the SE with nothing to
    show for it, which is the shape of error this release exists to remove.
    """
    from workbench.survey import estimate_with_design

    def sometimes_fails(frame, weights):
        if float(np.asarray(weights).sum()) % 7 < 1:
            raise np.linalg.LinAlgError("singular replicate")
        return weighted_ols(frame, weights)

    from workbench.survey import EstimatorSpec

    result = estimate_with_design(
        design,
        EstimatorSpec(name="flaky", refit=sometimes_fails),
        method="replicate",
        replicate_type="jackknife",
    )
    summary = result.replicate_summary
    assert summary.attempted == summary.succeeded + summary.failed
    if summary.failed:
        assert summary.failure_reasons, "failed replicates must carry a reason breakdown"


def test_too_many_failed_replicates_refuses_to_produce_a_result(design):
    from workbench.survey import EstimatorSpec, SurveyEngineError, estimate_with_design

    # Must succeed on the full sample and fail only on replicates: an estimator
    # that cannot fit the data at all is a different failure, and conflating the
    # two would let this test pass without the replicate guard existing.
    full_sample_weights = _design_frame()["weight"].to_numpy()

    def always_fails(frame, weights):
        if np.allclose(np.asarray(weights), full_sample_weights):
            return weighted_ols(frame, weights)
        raise np.linalg.LinAlgError("singular replicate")

    with pytest.raises(SurveyEngineError) as excinfo:
        estimate_with_design(
            design,
            EstimatorSpec(name="broken", refit=always_fails),
            method="replicate",
            replicate_type="jackknife",
        )
    assert excinfo.value.code == "SURVEY_REPLICATE_FAILURE_RATE_EXCEEDED"


# --------------------------------------------------------------------------
# lonely PSU
# --------------------------------------------------------------------------

def test_lonely_psu_fails_closed_by_default(linearizable_estimator):
    from workbench.survey import SurveyDesign, SurveyEngineError, estimate_with_design

    frame = pd.read_csv(FIXTURES / "lonely.csv")
    design = SurveyDesign(frame=frame, strata="stratum", psu="psu", weight="weight")
    with pytest.raises(SurveyEngineError) as excinfo:
        estimate_with_design(design, linearizable_estimator, method="linearization")
    assert excinfo.value.code == "SURVEY_LONELY_PSU"
    assert "h01" in str(excinfo.value.detail), "the offending stratum must be named"


@pytest.mark.parametrize("policy", ["remove", "adjust", "average", "certainty"])
def test_lonely_psu_strategies_match_r(linearizable_estimator, policy):
    from workbench.survey import SurveyDesign, estimate_with_design

    frame = pd.read_csv(FIXTURES / "lonely.csv")
    design = SurveyDesign(
        frame=frame, strata="stratum", psu="psu", weight="weight", lonely_psu=policy
    )
    result = estimate_with_design(design, linearizable_estimator, method="linearization")
    oracle = _oracle()["lonely_psu"][policy]
    assert oracle["status"] == "ok"
    for term in ("(Intercept)", "x1", "x2"):
        assert result.standard_errors[term] == pytest.approx(oracle["se"][term], rel=1e-8)


# --------------------------------------------------------------------------
# subpopulation
# --------------------------------------------------------------------------

def test_subpopulation_subsets_the_design_not_the_data(linearizable_estimator):
    """Filtering the rows first understates the standard error.

    The fixture empties whole PSUs precisely so the two approaches disagree; an
    earlier fixture left every PSU non-empty and the two were byte-identical,
    which would have made this assertion vacuous.
    """
    from workbench.survey import SurveyDesign, estimate_with_design

    frame = pd.read_csv(FIXTURES / "subpop.csv")
    design = SurveyDesign(
        frame=frame, strata="stratum", psu="psu", weight="weight", subpop="subpop == 1"
    )
    result = estimate_with_design(design, linearizable_estimator, method="linearization")

    oracle = _oracle()["subpopulation"]
    for term in ("(Intercept)", "x1", "x2"):
        assert result.standard_errors[term] == pytest.approx(
            oracle["design_internal"]["se"][term], rel=1e-8
        )
        assert result.standard_errors[term] != pytest.approx(
            oracle["pre_filtered_incorrect"]["se"][term], rel=1e-6
        )


# --------------------------------------------------------------------------
# design effect, effective sample size, adjusted Wald
# --------------------------------------------------------------------------

def test_design_effect_and_effective_sample_size_match_r(design):
    oracle = _oracle()["design_effect"]
    effects = design.design_effects("y")
    assert effects.deff == pytest.approx(oracle["deff_y"], rel=1e-8)
    assert effects.kish_n_eff == pytest.approx(oracle["kish_n_eff"], rel=1e-10)
    assert effects.n_obs == oracle["n_obs"]


def test_adjusted_wald_uses_design_degrees_of_freedom(design, linearizable_estimator):
    from workbench.survey import estimate_with_design

    result = estimate_with_design(design, linearizable_estimator, method="linearization")
    wald = result.joint_test(["x1", "x2"])
    oracle = _oracle()["adjusted_wald"]
    assert wald.statistic == pytest.approx(oracle["statistic"], rel=1e-8)
    assert wald.df == oracle["df"]
    assert wald.ddf == oracle["ddf"]
    assert wald.p_value == pytest.approx(oracle["p_value"], rel=1e-6)


# --------------------------------------------------------------------------
# end to end: what a real run actually writes
# --------------------------------------------------------------------------

def test_every_coefficient_in_a_real_run_carries_the_design_standard_error(tmp_path):
    """A full workflow, checked term by term against R -- intercept included.

    The engine tests above drive `estimate_with_design` directly and pass while
    the wiring layer delivers the design SE to only *some* coefficients.  That is
    not hypothetical: the payload names the intercept `Intercept` and the engine
    names it `(Intercept)`, and the merge skipped what it could not match, so a
    browser run showed x1/x2 matching R to twelve decimals and the intercept
    still carrying its naive 0.7804 against R's 1.5955 -- half the true width,
    with nothing in the result marking it as different from its neighbours.

    Asserting on the slopes alone is what let that through.  This walks the whole
    coefficient table.
    """
    from workbench.orchestrator import run_workflow
    from workbench.artifacts import read_json
    from workbench.projects import create_project

    project = create_project(tmp_path, "svy_e2e")
    source = project.root / "design.csv"
    source.write_text((FIXTURES / "design.csv").read_text())

    outcome = run_workflow(
        project.root, [source], mode="auto", model_type="ols",
        y="y", x=["x1", "x2"],
        sampling_weight="weight",
        survey_strata_col="stratum",
        survey_psu_col="psu",
    )
    assert outcome["status"] == "completed"

    result = read_json(
        project.root / "runs" / outcome["run_id"] / "model_results" / "ols_1.json"
    )
    oracle = _oracle()["linearization"]
    coefficients = result["coefficients"]

    # Every term R reports must be present and carry R's standard error. Naming
    # is the failure mode, so the mapping is asserted rather than assumed.
    assert set(coefficients) == {"Intercept", "x1", "x2"}
    for payload_term, oracle_term in [
        ("Intercept", "(Intercept)"), ("x1", "x1"), ("x2", "x2"),
    ]:
        entry = coefficients[payload_term]
        assert entry["estimate"] == pytest.approx(oracle["estimate"][oracle_term], rel=1e-10)
        assert entry["std_error"] == pytest.approx(oracle["se"][oracle_term], rel=1e-8), (
            f"{payload_term} kept a standard error the design engine did not produce"
        )
        assert entry["ci_lower"] == pytest.approx(oracle["ci_lower"][oracle_term], rel=1e-8)
        assert entry["ci_upper"] == pytest.approx(oracle["ci_upper"][oracle_term], rel=1e-8)
        assert entry["variance_source"] == "survey_design"
