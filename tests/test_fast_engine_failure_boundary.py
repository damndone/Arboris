"""A failed native self-check is an error, and inference checks cover more than beta/SE."""
import numpy as np
import pandas as pd
import pytest

from workbench.estimation_engine import iv


def test_failed_self_check_does_not_fall_back_or_fit(monkeypatch):
    monkeypatch.setattr(iv, "_coverage_gap", lambda *args: None)
    monkeypatch.setattr(iv, "_self_check", lambda: "covariance disagrees")
    monkeypatch.setattr(iv, "_fit", lambda *args: pytest.fail("unverified library executed"))
    with pytest.raises(RuntimeError, match="self-check.*covariance disagrees"):
        iv.fast_iv_2sls(pd.DataFrame(), y="y", exog=[], endog=["d"], instruments=["z"], covariance="robust")


def test_unsupported_covariance_keeps_explicit_reference_reason(monkeypatch):
    monkeypatch.setattr(iv, "_self_check", lambda: pytest.fail("unsupported fit triggered native self-check"))
    fitted, selection = iv.fast_iv_2sls(pd.DataFrame(), y="y", exog=[], endog=["d"], instruments=["z"], covariance="clustered")
    assert fitted is None
    assert selection.used == "reference"
    assert "not covered" in selection.reason


def test_agreement_checks_full_inference_and_extra_fields():
    from linearmodels.iv import IV2SLS

    data = iv._self_check_fixture()
    fitted = IV2SLS.from_formula("y ~ 1 + w + [d ~ z1 + z2]", data=data).fit(cov_type="unadjusted")
    expected = iv.comparable_numbers(fitted)
    fields = ("cov.Intercept.w", "pvalues.d", "tstats.d", "conf_int.d.lower",
              "nobs", "df_model", "df_resid", "first_stage.d.pval", "sargan.pval", "wu_hausman.df_denom")
    assert set(fields) <= expected.keys()
    for name in fields:
        changed = {**expected, name: expected[name] + 0.1}
        assert iv.disagreements(changed, expected, fitted.nobs), name
    assert iv.disagreements({**expected, "unexpected.statistic": 1.0}, expected, fitted.nobs)


def test_nan_covariance_is_not_a_successful_agreement():
    reference = {"cov.x.x": 1.0}
    assert iv.disagreements({"cov.x.x": np.nan}, reference, 10)


@pytest.mark.parametrize("name, expected, changed", [
    ("pvalues.x", 1e-200, 2e-200),
    ("std_errors.x", 1e-20, 2e-20),
    ("nobs", 1e10, 1e10 + 1),
    ("cov.x.x", 1e-40, 2e-40),
])
def test_field_specific_tolerances_do_not_hide_small_inference_errors(name, expected, changed):
    assert iv.disagreements({name: changed}, {name: expected}, 10)
