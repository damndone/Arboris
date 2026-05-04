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
    result = run_ols(frame, y="y", x=["x"], robust=True, model_id="regression_1")
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
    result = run_fixed_effects(
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

    result = run_logit(frame, y="y", x=["x1", "x2"], model_id="logit_1")

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

    result = run_poisson(frame, y="y", x=["x1"], model_id="poisson_1")

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
    result = run_ols(frame, y="y", x=["x"], robust=True, model_id="ols_1")
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

    result = run_logit(frame, y="y", x=["x1"], model_id="logit_test")

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

    result = run_poisson(frame, y="y", x=["x1"], model_id="poisson_zero")
    assert result["model_type"] == "poisson"
    assert result["pseudo_r2"] is not None
