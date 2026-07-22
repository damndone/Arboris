from __future__ import annotations

import math

import numpy as np
import pytest


def test_mean_diagnostics_emit_all_required_structured_series_and_tests() -> None:
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics

    rng = np.random.default_rng(404)
    innovations = rng.normal(size=200)
    values = np.empty(200)
    values[0] = innovations[0]
    for index in range(1, len(values)):
        values[index] = 0.45 * values[index - 1] + innovations[index]
    residuals = innovations[1:]

    diagnostics = build_mean_diagnostics(values, residuals, model_df=1)
    payload = diagnostics.to_dict()

    assert diagnostics.max_plot_lag == 40
    assert diagnostics.adf["status"] == "ok"
    assert diagnostics.adf["statistic"] is not None
    assert diagnostics.adf["p_value"] is not None
    assert diagnostics.series_acf[0] == {"lag": 0, "value": 1.0}
    assert diagnostics.series_pacf[0] == {"lag": 0, "value": 1.0}
    assert len(diagnostics.residual_series) == len(residuals)
    assert diagnostics.residual_acf[0]["lag"] == 0
    assert diagnostics.residual_pacf[0]["lag"] == 0
    assert diagnostics.ljung_box
    assert diagnostics.squared_residual_acf[0]["lag"] == 0
    assert diagnostics.arch_lm["status"] == "ok"
    assert diagnostics.normality["status"] == "ok"
    assert len(diagnostics.qq_data) == len(residuals)
    assert set(diagnostics.qq_data[0]) == {"theoretical_quantile", "observed"}
    assert payload["max_plot_lag"] == 40
    assert isinstance(payload["qq_data"], list)


def test_short_series_returns_partial_structured_diagnostics_without_crashing() -> None:
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics

    diagnostics = build_mean_diagnostics(
        np.array([1.0, 2.0, 3.0, 4.0, 5.0]),
        np.array([0.2, -0.1, 0.3, -0.2, 0.1]),
    )

    assert diagnostics.max_plot_lag == 1
    assert diagnostics.adf["status"] == "unavailable"
    assert len(diagnostics.series_acf) <= 2
    assert len(diagnostics.series_pacf) <= 2
    assert all(item["lag"] < 5 for item in diagnostics.ljung_box)
    assert diagnostics.arch_lm["status"] == "unavailable"
    assert diagnostics.normality["status"] == "ok"
    assert len(diagnostics.qq_data) == 5
    assert diagnostics.warnings


def test_constant_or_nonfinite_diagnostic_inputs_use_nulls_not_nan_or_inf() -> None:
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics

    diagnostics = build_mean_diagnostics(
        np.ones(12),
        np.array([0.0, 1.0, np.nan, -1.0, np.inf, 0.5]),
    )
    payload = diagnostics.to_dict()

    assert diagnostics.adf["status"] == "unavailable"
    assert diagnostics.adf["statistic"] is None
    assert diagnostics.adf["p_value"] is None
    assert len(diagnostics.residual_series) == 4
    assert len(diagnostics.qq_data) == 4
    assert _contains_no_nonfinite_float(payload)


def test_dynamic_lags_never_exceed_statsmodels_pacf_or_sample_limits() -> None:
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics

    values = np.linspace(-1.0, 1.0, 13) + np.sin(np.arange(13))
    diagnostics = build_mean_diagnostics(values, values - values.mean(), model_df=2)

    assert diagnostics.max_plot_lag == 3
    assert max(item["lag"] for item in diagnostics.series_acf) <= 3
    assert max(item["lag"] for item in diagnostics.series_pacf) < len(values) / 2
    assert max(item["lag"] for item in diagnostics.residual_pacf) < len(values) / 2
    assert all(2 < item["lag"] < len(values) for item in diagnostics.ljung_box)


def test_qq_data_is_ordered_and_contains_no_plot_object() -> None:
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics

    residuals = np.random.default_rng(88).standard_t(df=6, size=60)
    diagnostics = build_mean_diagnostics(residuals, residuals)

    observed = [item["observed"] for item in diagnostics.qq_data]
    theoretical = [item["theoretical_quantile"] for item in diagnostics.qq_data]
    assert observed == sorted(observed)
    assert theoretical == sorted(theoretical)
    assert not hasattr(diagnostics, "figure")


def test_large_finite_values_degrade_to_structured_diagnostics() -> None:
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics

    values = np.array([1e155, -1e155] * 20)

    diagnostics = build_mean_diagnostics(values, values)

    assert diagnostics.adf["status"] in {"ok", "unavailable"}
    assert diagnostics.arch_lm["status"] in {"ok", "unavailable"}
    assert _contains_no_nonfinite_float(diagnostics.to_dict())


def test_diagnostic_nested_results_are_immutable() -> None:
    from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics

    values = np.random.default_rng(901).normal(size=80)
    diagnostics = build_mean_diagnostics(values, values)

    with pytest.raises(TypeError):
        diagnostics.adf["status"] = "tampered"
    with pytest.raises(TypeError):
        diagnostics.series_acf[0]["value"] = 0.0


def _contains_no_nonfinite_float(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_contains_no_nonfinite_float(item) for item in value.values())
    if isinstance(value, (list, tuple)):
        return all(_contains_no_nonfinite_float(item) for item in value)
    return True
