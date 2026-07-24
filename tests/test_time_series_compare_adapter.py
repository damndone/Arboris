"""Integration-owned cross-family time-series comparison seam."""

from __future__ import annotations

from workbench.analysis_loop.time_series_compare import build_compare_packet


def test_cross_family_compare_returns_restricted_without_an_ic_verdict() -> None:
    packet = build_compare_packet(
        left={"model_type": "time_series.ets", "aic": 12043.7},
        right={"model_type": "time_series.arma_garch", "aic": 11900.0},
    )

    assert packet["comparability"] == "restricted"
    assert packet["reason_code"] == "ETS_ARMA_LIKELIHOOD_NOT_COMPARABLE"
    assert packet["criteria"] is None
    assert packet["left"]["model_type"] == "time_series.ets"
    assert packet["right"]["model_type"] == "time_series.arma_garch"

