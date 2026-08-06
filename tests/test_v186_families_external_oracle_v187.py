"""v1.8.7 A3 — the four v1.8.6 families, checked against R rather than themselves.

v1.8.6 shipped `ordinal_logit`, `multinomial_logit`, `quantile_regression` and
`survival_cox` with `validation.level = "internal_consistency_only"`. statsmodels
is the execution engine, so a statsmodels-versus-statsmodels check is not an
oracle; nothing in the suite could tell a correct fit from a consistently wrong
one.

Reference values come from `tests/fixtures/v186_families/generate_oracle.R`,
which is committed and re-runnable. **The tolerances below are not decorative
and were not tuned until they passed.** Each is the observed disagreement
between two independent solvers, stated with its cause:

  survival_cox         ~1e-13  agreement to machine precision
  quantile_regression  ~1e-6   quantreg uses the Barrodale-Roberts simplex,
                               statsmodels an iteratively reweighted fit
  ordinal_logit        ~3e-5   MASS::polr and statsmodels OrderedModel optimise
                               the same likelihood with different optimisers
  multinomial_logit    ~3e-5   nnet::multinom (BFGS on a neural-net objective)
                               against statsmodels' Newton method

Claiming "matches R exactly" for the last three would be false.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "v186_families"


def _oracle() -> dict:
    return json.loads((FIXTURES / "oracle.json").read_text())


def _frame() -> pd.DataFrame:
    return pd.read_csv(FIXTURES / "families.csv")


def _run(tmp_path: Path, name: str, **kwargs) -> dict:
    source = tmp_path / "families.csv"
    if not source.exists():
        _frame().to_csv(source, index=False)
    project = create_project(tmp_path, name)
    outcome = run_workflow(project.root, [source], mode="auto", **kwargs)
    assert outcome["status"] == "completed", outcome
    results = project.root / "runs" / outcome["run_id"] / "model_results"
    model_type = kwargs["model_type"]
    return read_json(results / f"{model_type}_1.json")


X = ["x1", "x2", "grp"]


# ---------------------------------------------------------------------------
# survival_cox -- the one that agrees to machine precision
# ---------------------------------------------------------------------------

def test_cox_matches_r_coxph_to_machine_precision(tmp_path):
    oracle = _oracle()["survival_cox"]
    result = _run(
        tmp_path, "cox", model_type="survival_cox", y="duration", x=X,
        model_options={"event_column": "event"},
    )

    for term, expected in oracle["coefficients"].items():
        entry = result["coefficients"][term]
        assert entry["estimate"] == pytest.approx(expected, rel=1e-10)
        assert entry["std_error"] == pytest.approx(
            oracle["std_errors"][term], rel=1e-10
        )
        assert entry["hazard_ratio"] == pytest.approx(
            oracle["hazard_ratios"][term], rel=1e-10
        )


# ---------------------------------------------------------------------------
# quantile_regression
# ---------------------------------------------------------------------------

def test_quantile_regression_matches_r_rq_within_solver_tolerance(tmp_path):
    """Every tau, not just the median: a fit that ignored tau would match at 0.5."""
    oracle = _oracle()["quantile_regression"]
    result = _run(
        tmp_path, "qr", model_type="quantile_regression", y="y", x=X,
        model_options={"quantiles": [0.25, 0.5, 0.75]},
    )

    fits = {round(float(fit["quantile"]), 4): fit for fit in result["fits"].values()}
    assert set(fits) == {0.25, 0.5, 0.75}

    for key, expected in oracle.items():
        tau = round(float(expected["tau"]), 4)
        coefficients = fits[tau]["coefficients"]
        for r_term, value in expected["coefficients"].items():
            term = "const" if r_term == "(Intercept)" else r_term
            assert coefficients[term]["estimate"] == pytest.approx(value, abs=1e-5), (
                f"tau={tau} term={term}"
            )


def test_the_quantile_slopes_genuinely_differ_across_tau(tmp_path):
    """Guards the fixture, not the engine.

    On homoskedastic data every tau estimates the same slope, and the assertions
    above would pass for an implementation that fitted the mean three times.
    """
    oracle = _oracle()["quantile_regression"]
    slopes = [entry["coefficients"]["x1"] for entry in oracle.values()]
    assert max(slopes) - min(slopes) > 0.05


# ---------------------------------------------------------------------------
# ordinal_logit
# ---------------------------------------------------------------------------

def test_ordinal_logit_matches_r_polr_within_solver_tolerance(tmp_path):
    """Requires the level order to be declared -- see the default-order test below."""
    oracle = _oracle()["ordinal_logit"]
    result = _run(
        tmp_path, "ord", model_type="ordinal_logit", y="rating", x=X,
        model_options={"outcome_order": ["low", "mid", "high"]},
    )

    assert result["outcome_levels"] == ["low", "mid", "high"]
    for term, expected in oracle["coefficients"].items():
        assert result["coefficients"][term]["estimate"] == pytest.approx(
            expected, abs=1e-4
        ), term


def test_ordinal_thresholds_match_r_after_undoing_the_increment_parameterisation(tmp_path):
    """The two engines report cutpoints differently, and the difference is not a sign.

    `polr` reports both cutpoints on the response scale. statsmodels reports the
    first that way and every later one as the **log of the increment** from its
    predecessor. Comparing them term by term would show the first agreeing and
    the second wildly off (0.163 against 0.999) and invite the conclusion that
    the model is wrong. The cumulative values are what the two agree on.
    """
    oracle = _oracle()["ordinal_logit"]["thresholds"]
    result = _run(
        tmp_path, "ordthr", model_type="ordinal_logit", y="rating", x=X,
        model_options={"outcome_order": ["low", "mid", "high"]},
    )

    coefficients = result["coefficients"]
    first = coefficients["low/mid"]["estimate"]
    increment = coefficients["mid/high"]["estimate"]
    cumulative = first + math.exp(increment)

    assert first == pytest.approx(oracle["low|mid"], abs=1e-4)
    assert cumulative == pytest.approx(oracle["mid|high"], abs=1e-4)


def test_ordinal_logit_orders_levels_alphabetically_when_none_is_declared(tmp_path):
    """A silent wrong answer, recorded here because a user cannot see it.

    With no `outcome_order` the levels are sorted as strings, so `high < low <
    mid` -- an order with no relation to the ratings' meaning. The run completes,
    the report renders, every coefficient carries a standard error and a p-value,
    and nothing anywhere says the scale was invented. The estimate for `x1` comes
    back -0.355 where the correctly ordered fit gives +0.712: not merely
    imprecise, but the opposite sign.

    Asserted rather than fixed: with labels like `a`, `b`, `c` alphabetical order
    is often right, and the engine cannot know the intended one. What it must not
    do is stay silent -- covered by the v1.8.7 measurement-level advisory.
    """
    oracle = _oracle()["ordinal_logit"]["coefficients"]
    result = _run(tmp_path, "ordflip", model_type="ordinal_logit", y="rating", x=X)

    assert result["outcome_levels"] == ["high", "low", "mid"]
    estimate = result["coefficients"]["x1"]["estimate"]
    assert estimate < 0 < oracle["x1"], (
        "the alphabetical default no longer flips the sign; re-check the advisory"
    )


# ---------------------------------------------------------------------------
# multinomial_logit
# ---------------------------------------------------------------------------

def test_multinomial_logit_matches_r_multinom_within_solver_tolerance(tmp_path):
    oracle = _oracle()["multinomial_logit"]
    result = _run(
        tmp_path, "mn", model_type="multinomial_logit", y="choice", x=X,
        model_options={"base_category": oracle["baseline"]},
    )

    assert result["base_category"] == oracle["baseline"]
    for level, terms in oracle["coefficients"].items():
        for r_term, value in terms.items():
            term = "const" if r_term == "(Intercept)" else r_term
            entry = result["coefficients"][f"{level}:{term}"]
            assert entry["estimate"] == pytest.approx(value, abs=1e-4), f"{level}:{term}"


def test_multinomial_baseline_is_not_the_first_level_unless_declared(tmp_path):
    """Undeclared, the contrasts are against a different category than R's.

    Every number changes with the baseline, so a comparison that did not pin it
    would report a mismatch that looks like a wrong model. Recorded so the
    default is a stated fact rather than something each caller rediscovers.
    """
    oracle = _oracle()["multinomial_logit"]["coefficients"]
    result = _run(tmp_path, "mnbase", model_type="multinomial_logit", y="choice", x=X)

    declared = result.get("base_category")
    if declared == "a":
        pytest.skip("the default baseline is now R's; this guard has served its purpose")

    # With another baseline the a-versus-baseline slope mirrors R's c-versus-a.
    assert result["coefficients"]["a:x1"]["estimate"] == pytest.approx(
        -oracle["c"]["x1"], abs=1e-4
    )


# ---------------------------------------------------------------------------
# what the result tells the user about its own validation
# ---------------------------------------------------------------------------

def test_each_family_reports_the_verification_level_it_actually_has(tmp_path):
    """`validation` is a claim made to the user, so it has to track reality.

    v1.8.6 hard-coded every family to `internal_consistency_only` /
    `not_verified` and the contract *rejected* any other value -- correct at the
    time, and stale the moment this file started comparing against R. A result
    that still says "not verified" after an oracle test exists understates what
    is known; one that said "verified" without the tolerance would overstate it.

    The four levels are not the same, so a single flag cannot carry them:
    Cox agrees to machine precision, the other three only within a stated
    solver tolerance.
    """
    from workbench.contracts.model.v186_model_families import EXTERNAL_ORACLES

    for family in (
        "survival_cox", "quantile_regression", "ordinal_logit", "multinomial_logit",
    ):
        record = EXTERNAL_ORACLES[family]
        assert record.reference, f"{family} declares no reference implementation"
        assert record.tolerance, f"{family} declares no tolerance"

    # The claim must be specific: agreeing to 1e-4 is not agreeing exactly.
    assert EXTERNAL_ORACLES["survival_cox"].level == "external_oracle_exact"
    assert EXTERNAL_ORACLES["ordinal_logit"].level == "external_oracle_within_tolerance"

    result = _run(
        tmp_path, "vlevel", model_type="ordinal_logit", y="rating", x=X,
        model_options={"outcome_order": ["low", "mid", "high"]},
    )
    validation = result["validation"]
    assert validation["level"] == "external_oracle_within_tolerance"
    assert "polr" in validation["external_oracle"]
