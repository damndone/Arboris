from __future__ import annotations

import pytest


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

    assert {
        "within_variance",
        "between_variance",
        "total_variance",
    }.issubset(intercept)
    assert intercept["within_variance"] == pytest.approx(0.2**2)
    assert intercept["between_variance"] == pytest.approx(0.32)
    assert intercept["total_variance"] > intercept["within_variance"]
