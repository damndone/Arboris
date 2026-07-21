from __future__ import annotations

import math
import warnings

import numpy as np
import pytest


def test_aicc_uses_actual_parameter_and_effective_sample_counts() -> None:
    from workbench.engine.packs.arma_garch.statistics import calculate_aicc

    result = calculate_aicc(aic=100.0, parameter_count=3, effective_sample=50)

    assert result == pytest.approx(100.0 + (2 * 3 * 4) / (50 - 3 - 1))


@pytest.mark.parametrize("effective_sample", [3, 4])
def test_aicc_is_null_when_denominator_is_not_positive(
    effective_sample: int,
) -> None:
    from workbench.engine.packs.arma_garch.statistics import calculate_aicc

    result = calculate_aicc(
        aic=100.0,
        parameter_count=3,
        effective_sample=effective_sample,
    )

    assert result is None


@pytest.mark.parametrize("aic", [math.inf, -math.inf, math.nan])
def test_aicc_is_null_for_nonfinite_aic(aic: float) -> None:
    from workbench.engine.packs.arma_garch.statistics import calculate_aicc

    assert calculate_aicc(aic=aic, parameter_count=2, effective_sample=30) is None


def test_ljung_box_is_scale_invariant_and_runtime_warning_safe() -> None:
    from workbench.engine.packs.arma_garch.statistics import ljung_box_results

    values = np.sin(np.arange(80, dtype=float))
    expected = ljung_box_results(values)

    with warnings.catch_warnings():
        warnings.simplefilter("error", RuntimeWarning)
        scaled = ljung_box_results(values * 1e308)

    assert tuple(item["lag"] for item in scaled) == tuple(
        item["lag"] for item in expected
    )
    for actual, baseline in zip(scaled, expected, strict=True):
        assert actual["statistic"] == pytest.approx(baseline["statistic"])
        assert actual["p_value"] == pytest.approx(baseline["p_value"])


def test_ljung_box_constant_series_returns_empty_result() -> None:
    from workbench.engine.packs.arma_garch.statistics import ljung_box_results

    assert ljung_box_results(np.full(40, 1e308)) == ()
