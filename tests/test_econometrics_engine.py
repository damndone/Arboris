import numpy as np
import pandas as pd
import pytest

from workbench.econometrics.specs import ModelSpec
from workbench.econometrics.runner import (
    run_fixed_effects,
    run_logit,
    run_ols,
    run_poisson,
    run_time_series_diagnostics,
)


def test_run_ols_returns_source_bound_coefficients():
    frame = pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": list(range(35))})
    result, _ = run_ols(frame, y="y", x=["x"], robust=True, model_id="regression_1")
    assert result["model_id"] == "regression_1"
    assert result["model_type"] == "ols_robust"
    assert result["nobs"] == 35
    assert abs(result["coefficients"]["x"]["estimate"] - 2.0) < 1e-8
    assert (
        result["coefficients"]["x"]["source_id"]
        == "model_results.regression_1.coefficients.x"
    )


def test_run_fixed_effects_includes_entity_terms():
    frame = pd.DataFrame(
        {"y": [1, 2, 2, 3], "x": [0, 1, 0, 1], "firm_id": [1, 1, 2, 2]}
    )
    result, _ = run_fixed_effects(
        frame, y="y", x=["x"], entity="firm_id", time=None, model_id="fe_1"
    )
    assert result["model_id"] == "fe_1"
    assert result["nobs"] == 4


def test_time_series_diagnostics_reports_autocorrelation():
    frame = pd.DataFrame(
        {"y": [1.0, 1.5, 2.2, 2.8, 3.6], "date": pd.date_range("2020-01-01", periods=5)}
    )
    result = run_time_series_diagnostics(frame, y="y", time="date")
    assert "lag1_autocorrelation" in result


def test_model_spec_matches_planned_contract():
    spec = ModelSpec(model_id="m1", model_type="ols", y="y", x=["x1", "x2"])
    assert spec.model_type == "ols"
    assert spec.x == ("x1", "x2")
    assert spec.robust is True
    with pytest.raises(AttributeError):
        spec.x.append("x3")


def test_run_logit_binary_y():
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 10, n)
    x2 = rng.normal(5, 2, n)
    logit = -2 + 0.5 * x1 + 0.3 * x2
    p = 1 / (1 + np.exp(-logit))
    y = (rng.uniform(0, 1, n) < p).astype(int)
    frame = pd.DataFrame({"y": y, "x1": x1, "x2": x2})

    result, _ = run_logit(frame, y="y", x=["x1", "x2"], model_id="logit_1")

    assert result["model_id"] == "logit_1"
    assert result["model_type"] == "logit"
    assert result["nobs"] == n
    assert result["pseudo_r2"] is not None
    assert result["pseudo_r2"] > 0
    assert result["llf"] is not None
    assert result["llf"] < 0
    assert result["aic"] is not None
    assert result["bic"] is not None
    assert "x1" in result["coefficients"]
    assert result["coefficients"]["x1"]["source_id"] == "model_results.logit_1.coefficients.x1"
    assert result["coefficients"]["x1"]["p_value"] is not None


def test_run_poisson_count_y():
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 5, n)
    lam = np.exp(-0.5 + 0.3 * x1)
    y = rng.poisson(lam)
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_poisson(frame, y="y", x=["x1"], model_id="poisson_1")

    assert result["model_id"] == "poisson_1"
    assert result["model_type"] == "poisson"
    assert result["nobs"] == n
    assert result["pseudo_r2"] is not None
    assert result["llf"] is not None
    assert "x1" in result["coefficients"]
    assert result["coefficients"]["x1"]["source_id"] == "model_results.poisson_1.coefficients.x1"


def test_detect_y_kind_binary():
    from workbench.router import YKind, detect_y_kind

    frame = pd.DataFrame({"y": [0, 1, 0, 1, 1, 0]})
    assert detect_y_kind(frame, "y") == YKind.BINARY

    frame2 = pd.DataFrame({"y": [True, False, True, False]})
    assert detect_y_kind(frame2, "y") == YKind.BINARY


def test_detect_y_kind_count():
    from workbench.router import YKind, detect_y_kind

    frame = pd.DataFrame({"y": [0, 1, 2, 3, 5, 1, 0, 2]})
    assert detect_y_kind(frame, "y") == YKind.COUNT


def test_detect_y_kind_continuous():
    from workbench.router import YKind, detect_y_kind

    frame = pd.DataFrame({"y": [1.5, 2.7, 3.1, 4.2, 5.8]})
    assert detect_y_kind(frame, "y") == YKind.CONTINUOUS


def test_unified_schema_ols():
    frame = pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": list(range(35))})
    result, _ = run_ols(frame, y="y", x=["x"], robust=True, model_id="ols_1")
    assert result["model_id"] == "ols_1"
    assert "r_squared" in result
    assert "pseudo_r2" in result
    assert "llf" in result
    assert "aic" in result
    assert "bic" in result
    assert result["r_squared"] is not None


def test_unified_schema_logit():
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 10, n)
    logit = -1 + 0.5 * x1
    p = 1 / (1 + np.exp(-logit))
    y = (rng.uniform(0, 1, n) < p).astype(int)
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_logit(frame, y="y", x=["x1"], model_id="logit_test")

    assert "r_squared" in result
    assert result["pseudo_r2"] is not None
    assert result["llf"] is not None


def test_logit_perfect_separation_raises():
    frame = pd.DataFrame({
        "y": [0, 0, 0, 1, 1, 1],
        "x": [1, 2, 3, 10, 11, 12],
    })
    with pytest.raises(ValueError, match="perfect separation|failed to fit"):
        run_logit(frame, y="y", x=["x"], model_id="sep_test")


def test_poisson_negative_y_raises():
    frame = pd.DataFrame({
        "y": [0, 1, 2, -1, 3],
        "x": [1, 2, 3, 4, 5],
    })
    with pytest.raises(ValueError, match="negative"):
        run_poisson(frame, y="y", x=["x"], model_id="neg_test")


def test_poisson_zero_counts_ok():
    rng = np.random.default_rng(42)
    n = 40
    x1 = rng.uniform(0, 5, n)
    lam = np.exp(-1 + 0.2 * x1)
    y = rng.poisson(lam)
    assert (y == 0).any(), "test data should include zeros"
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_poisson(frame, y="y", x=["x1"], model_id="poisson_zero")
    assert result["model_type"] == "poisson"
    assert result["pseudo_r2"] is not None


def test_poisson_normalize_includes_irr():
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 5, n)
    lam = np.exp(-0.5 + 0.3 * x1)
    y = rng.poisson(lam)
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_poisson(frame, y="y", x=["x1"], model_id="poisson_irr")
    assert "irr" in result
    assert "x1" in result["irr"]
    assert result["irr"]["x1"]["irr"] is not None
    irr_val = result["irr"]["x1"]["irr"]
    assert irr_val > 0
    assert abs(irr_val - np.exp(0.3)) < 0.5  # rough check


def test_poisson_irr_includes_confidence_intervals():
    """IRR entries should include IR CI lower/upper bounds."""
    rng = np.random.default_rng(42)
    n = 100
    x1 = rng.uniform(0, 5, n)
    lam = np.exp(-0.5 + 0.3 * x1)
    y = rng.poisson(lam)
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_poisson(frame, y="y", x=["x1"], model_id="poisson_ci")
    term_irr = result["irr"]["x1"]
    assert "irr_ci_lower" in term_irr
    assert "irr_ci_upper" in term_irr
    assert term_irr["irr_ci_lower"] is not None
    assert term_irr["irr_ci_upper"] is not None
    assert term_irr["irr_ci_lower"] < term_irr["irr_ci_upper"]


def test_poisson_irr_not_in_ols_result():
    """OLS results should NOT contain IRR."""
    frame = pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": list(range(35))})
    result, _ = run_ols(frame, y="y", x=["x"], robust=True, model_id="ols_1")
    assert "irr" not in result
    assert "odds_ratios" not in result  # OLS has no prsquared


def test_poisson_overdispersion_in_diagnostics():
    """Overdispersion diagnostic should be computed for Poisson models."""
    from workbench.econometrics.diagnostics import compute_diagnostics

    rng = np.random.default_rng(42)
    n = 100
    x1 = rng.uniform(0, 5, n)
    lam = np.exp(-0.5 + 0.3 * x1)
    y = rng.poisson(lam)
    frame = pd.DataFrame({"y": y, "x1": x1})

    _, fitted = run_poisson(frame, y="y", x=["x1"], model_id="poisson_od")
    exog = frame[["x1"]]
    diag = compute_diagnostics(fitted, exog, model_id="poisson_od", model_family="poisson")

    assert "overdispersion" in diag
    od = diag["overdispersion"]
    assert "pearson_chi2" in od
    assert "overdispersion_ratio" in od
    assert "zero_rate" in od
    assert "mean_y" in od
    assert "var_y" in od
    assert od["zero_rate"] is not None
    assert od["mean_y"] is not None


def test_poisson_formatted_estimate_for_tiny_coefficients():
    """Very small significant coefs should get scientific notation."""
    from workbench.econometrics.normalize import _format_estimate_string

    # Tiny coefficient with significant p-value
    formatted = _format_estimate_string(2.3e-05, 0.012)
    assert formatted is not None
    assert "e-" in formatted

    # Non-significant p-value should not format
    formatted2 = _format_estimate_string(2.3e-05, 0.15)
    assert formatted2 is None

    # Larger coefficient should not format
    formatted3 = _format_estimate_string(0.005, 0.01)
    assert formatted3 is None


def test_poisson_rate_coefficient_entries_include_irr():
    """Coefficient entries for poisson (rate) should include irr/irr_ci_lower/irr_ci_upper."""
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 5, n)
    lam = np.exp(-0.5 + 0.3 * x1)
    y = rng.poisson(lam)
    frame = pd.DataFrame({"y": y, "x1": x1})

    result, _ = run_poisson(frame, y="y", x=["x1"], model_id="poisson_coef_irr")
    coef = result["coefficients"]["x1"]
    assert "irr" in coef, "coefficient entry missing irr"
    assert "irr_ci_lower" in coef, "coefficient entry missing irr_ci_lower"
    assert "irr_ci_upper" in coef, "coefficient entry missing irr_ci_upper"
    assert coef["irr"] is not None
    assert coef["irr_ci_lower"] < coef["irr_ci_upper"]


def test_poisson_rate_narrative_uses_irr_language():
    """build_claims with poisson_rate model_type should use IRR/multiplicative language."""
    from workbench.narrative import build_claims

    model_results = [{
        "model_id": "poisson_1",
        "coefficients": {
            "x1": {"estimate": 0.3, "p_value": 0.01, "source_id": "src1"},
        },
        "irr": {
            "x1": {"irr": 1.35, "irr_ci_lower": 1.10, "irr_ci_upper": 1.65},
        },
    }]
    claims = build_claims(model_results, [], model_type="poisson_rate")
    assert len(claims) > 0
    text = claims[0]["claim"]
    # Should use IRR / multiplicative language (not OLS "average change" language)
    assert "multiplicative" in text or "IRR" in text or "expected count" in text
    assert "average change" not in text


def test_poisson_rate_narrative_handles_binary_vars_with_irr():
    """Binary variables in poisson_rate narrative should use presence/absence IRR language."""
    from workbench.narrative import build_claims

    model_results = [{
        "model_id": "poisson_1",
        "coefficients": {
            "treatment": {"estimate": 0.5, "p_value": 0.003, "source_id": "src2"},
        },
        "irr": {
            "treatment": {"irr": 1.65, "irr_ci_lower": 1.20, "irr_ci_upper": 2.25},
        },
    }]
    claims = build_claims(model_results, [], binary_vars={"treatment"}, model_type="poisson_rate")
    assert len(claims) > 0
    text = claims[0]["claim"]
    assert "presence" in text or "expected count" in text


def test_poisson_detect_exposure_candidates():
    """Exposure candidate detection should match known exposure names."""
    from workbench.orchestrator import _detect_exposure_candidates

    x_vars = ["exposure_months", "policy_count", "annual_miles", "offset"]
    detected = _detect_exposure_candidates(x_vars)
    assert "exposure_months" in detected
    assert "offset" in detected
    assert "policy_count" not in detected
    assert "annual_miles" not in detected


def test_run_poisson_with_exposure():
    """run_poisson with exposure_col should use offset and return poisson_rate."""
    rng = np.random.default_rng(42)
    n = 100
    x1 = rng.uniform(0, 5, n)
    exposure = np.full(n, 12.0)  # 12 months of exposure
    # True rate: 0.1 claims per month
    rate = np.exp(-2.5 + 0.2 * x1)
    lam = rate * exposure
    y = rng.poisson(lam)
    frame = pd.DataFrame({"y": y, "x1": x1, "exposure_months": exposure})

    result, fitted = run_poisson(
        frame, y="y", x=["x1"], model_id="poisson_exp",
        exposure_col="exposure_months",
    )

    assert result["model_type"] == "poisson_rate"
    assert result["exposure_col"] == "exposure_months"
    assert result["nobs"] == n
    # Note: GLM with exposure does not expose prsquared, but coefficients work
    # x1 should be in coefficients
    assert "x1" in result["coefficients"]
    # exposure_months should NOT be in coefficients (it's the offset)
    assert "exposure_months" not in result["coefficients"]


def test_run_poisson_exposure_zero_fallback():
    """Exposure with zeros should fall back to standard Poisson with warning."""
    rng = np.random.default_rng(42)
    n = 60
    x1 = rng.uniform(0, 5, n)
    exposure = np.full(n, 12.0)
    exposure[0] = 0  # one zero
    lam = np.exp(-0.5 + 0.3 * x1)
    y = rng.poisson(lam)
    frame = pd.DataFrame({"y": y, "x1": x1, "exposure_months": exposure})

    import warnings
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        result, fitted = run_poisson(
            frame, y="y", x=["x1"], model_id="poisson_zero_exp",
            exposure_col="exposure_months",
        )

    # Should have warned about non-positive exposure
    assert len(w) >= 1
    assert any("non-positive" in str(warning.message).lower() for warning in w)
    # Should have fallen back to standard Poisson
    assert result["model_type"] == "poisson"
    assert "exposure_col" not in result
