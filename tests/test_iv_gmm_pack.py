from __future__ import annotations

import json

import numpy as np
import pytest

from workbench.engine.packs.iv_gmm import (
    IVGMMPackError,
    diagnose_weak_instruments,
    fit_gmm,
)


def _iv_data(n: int = 240) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(20260808)
    x = rng.normal(size=n)
    w1 = rng.normal(size=n)
    w2 = rng.normal(size=n)
    v = rng.normal(scale=0.65, size=n)
    endogenous = 0.85 * w1 + 0.35 * w2 + 0.45 * x + v
    error = 0.50 * v + rng.normal(scale=0.75, size=n)
    y = 1.25 + 0.70 * x + 1.80 * endogenous + error
    exog = np.column_stack((np.ones(n), x))
    excluded_instruments = np.column_stack((w1, w2))
    return y, exog, endogenous[:, None], excluded_instruments


def test_two_step_gmm_returns_coefficients_j_test_and_explicit_weak_evidence() -> None:
    y, exog, endog, instruments = _iv_data()
    result = fit_gmm(
        y,
        exog,
        endog,
        instruments,
        estimator="two_step",
        exog_names=["Intercept", "x"],
        endog_names=["educ"],
        instrument_names=["dist", "nearby"],
    )

    assert result["operation_id"] == "iv.gmm"
    assert result["status"] == "completed"
    payload = result["result"]
    assert payload["estimator"] == "two_step"
    assert list(payload["coefficients"]) == ["Intercept", "x", "educ"]
    assert payload["overidentification"]["degrees_of_freedom"] == 1
    assert 0.0 <= payload["overidentification"]["p_value"] <= 1.0
    weak = payload["weak_instruments"]
    assert weak["diagnostic_policy"] == "descriptive_no_automatic_threshold_decision"
    assert weak["by_endogenous"]["educ"]["partial_f"] > 10.0
    assert weak["by_endogenous"]["educ"]["robust_excluded_wald_f"] > 0.0
    assert len(payload["covariance"]) == 3
    json.dumps(result, allow_nan=False)


def test_weak_instrument_pack_is_composable_and_preserves_names() -> None:
    y, exog, endog, instruments = _iv_data()
    result = diagnose_weak_instruments(
        exog,
        endog,
        instruments,
        exog_names=["Intercept", "x"],
        endog_names=["educ"],
        instrument_names=["dist", "nearby"],
    )

    assert result["operation_id"] == "iv.weak_instruments"
    weak = result["result"]
    assert weak["endogenous_names"] == ["educ"]
    assert weak["excluded_instrument_names"] == ["dist", "nearby"]
    assert weak["minimum_partial_f"] == weak["by_endogenous"]["educ"]["partial_f"]


def test_one_step_and_two_step_are_explicitly_distinct() -> None:
    y, exog, endog, instruments = _iv_data()
    one_step = fit_gmm(y, exog, endog, instruments, estimator="one_step")
    two_step = fit_gmm(y, exog, endog, instruments, estimator="two_step")
    assert one_step["result"]["estimator"] == "one_step"
    assert two_step["result"]["estimator"] == "two_step"
    assert one_step["result"]["weighting"]["method"] == "z'z_inverse"
    assert two_step["result"]["weighting"]["method"] == "heteroskedastic_hc0_two_step"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"estimator": "cue"},
        {"endog_names": ["educ", "educ"]},
        {"instrument_names": ["dist"]},
    ],
)
def test_gmm_rejects_undeclared_options_or_name_mismatches(kwargs: dict[str, object]) -> None:
    y, exog, endog, instruments = _iv_data()
    options: dict[str, object] = {
        "exog_names": ["Intercept", "x"],
        "endog_names": ["educ"],
        "instrument_names": ["dist", "nearby"],
    }
    options.update(kwargs)
    with pytest.raises(IVGMMPackError):
        fit_gmm(
            y,
            exog,
            endog,
            instruments,
            **options,
        )


def test_gmm_fails_closed_for_underidentification_singularity_and_nonfinite_input() -> None:
    y, exog, endog, instruments = _iv_data(80)
    underidentified_endog = np.column_stack((endog[:, 0], endog[:, 0] + np.arange(80.0) / 100.0))
    with pytest.raises(IVGMMPackError, match="IV_GMM_UNDERIDENTIFIED"):
        fit_gmm(y, exog, underidentified_endog, instruments[:, :1])
    with pytest.raises(IVGMMPackError, match="IV_GMM_SINGULAR_DESIGN"):
        fit_gmm(y, exog, endog, np.column_stack((instruments[:, 0], instruments[:, 0])))
    bad_y = y.copy()
    bad_y[0] = np.nan
    with pytest.raises(IVGMMPackError, match="IV_GMM_NONFINITE_INPUT"):
        fit_gmm(bad_y, exog, endog, instruments)
