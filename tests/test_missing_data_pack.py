from __future__ import annotations

from math import sqrt

import pytest
from scipy import stats


def test_rubin_pool_exposes_variance_components_for_fixed_model_results():
    model_results = [
        {"coefficients": {"Intercept": {"estimate": 1.0, "std_error": 0.2}}},
        {"coefficients": {"Intercept": {"estimate": 1.8, "std_error": 0.2}}},
    ]

    try:
        from workbench.engine.packs.missing_data.rubin import rubin_pool
    except ModuleNotFoundError:
        pytest.fail(
            "Wished-for API is not implemented: "
            "workbench.engine.packs.missing_data.rubin.rubin_pool"
        )
    except ImportError:
        pytest.fail(
            "Wished-for API is not importable: "
            "workbench.engine.packs.missing_data.rubin.rubin_pool"
        )

    pooled = rubin_pool(model_results)
    intercept = pooled["coefficients"]["Intercept"]

    # Wished-for Rubin output: Qbar/Ubar/B/T plus a two-sided 95% Rubin-t CI.
    # With r=((1+1/m)*B/U), Rubin's df is (m-1)*(1+1/r)^2 = 169/144 here.
    expected_df = (2 - 1) * (1 + 0.04 / ((1 + 1 / 2) * 0.32)) ** 2
    expected_standard_error = sqrt(0.52)
    critical_value = stats.t.ppf(0.975, expected_df)
    expected_interval = [
        1.4 - critical_value * expected_standard_error,
        1.4 + critical_value * expected_standard_error,
    ]

    assert intercept["estimate"] == pytest.approx(1.4)
    assert intercept["within_variance"] == pytest.approx(0.04)
    assert intercept["between_variance"] == pytest.approx(0.32)
    assert intercept["total_variance"] == pytest.approx(0.52)
    assert intercept["standard_error"] == pytest.approx(expected_standard_error)
    assert intercept["degrees_of_freedom"] == pytest.approx(169 / 144)
    assert intercept["confidence_level"] == pytest.approx(0.95)
    assert intercept["confidence_interval_method"] == "rubin_t"
    assert intercept["confidence_interval"] == pytest.approx(expected_interval)
