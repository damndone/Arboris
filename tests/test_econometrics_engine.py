import pandas as pd

from workbench.econometrics.runner import (
    run_fixed_effects,
    run_ols,
    run_time_series_diagnostics,
)


def test_run_ols_returns_source_bound_coefficients():
    frame = pd.DataFrame({"y": [1 + 2 * i for i in range(35)], "x": list(range(35))})
    result = run_ols(frame, y="y", x=["x"], robust=True, model_id="regression_1")
    assert result["model_id"] == "regression_1"
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
