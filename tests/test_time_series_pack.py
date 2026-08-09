from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest


def _series_frame() -> pd.DataFrame:
    time = np.arange(1.0, 61.0)
    signal = np.sin(time / 4.0) + 0.04 * time
    return pd.DataFrame({"time": time, "value": signal, "other": signal * 0.5})


def test_time_series_contract_declares_the_complete_standalone_surface():
    from workbench.contracts.model.time_series_pack import (
        TIME_SERIES_PACK_CONTRACT,
        TIME_SERIES_PACK_OPERATION_IDS,
        make_time_series_result,
    )

    assert TIME_SERIES_PACK_CONTRACT == "time_series.pack.result"
    assert TIME_SERIES_PACK_OPERATION_IDS == {
        "time_series.acf",
        "time_series.pacf",
        "time_series.adf",
        "time_series.kpss",
        "time_series.arima",
        "time_series.var",
        "time_series.granger",
        "time_series.irf",
        "time_series.cointegration",
        "time_series.vecm",
    }
    envelope = make_time_series_result(
        operation_id="time_series.acf",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=3,
        variables=["value"],
        result={"values": [0.0]},
    )
    assert set(envelope) == {
        "contract",
        "contract_version",
        "operation_id",
        "status",
        "reason_code",
        "n_observations",
        "variables",
        "result",
    }


def test_time_series_boundary_requires_declared_order_and_never_infers_frequency():
    from workbench.engine.packs.time_series.input import prepare_time_series
    from workbench.engine.packs.time_series.errors import TimeSeriesPackError

    frame = _series_frame().iloc[[0, 2, 1, *range(3, 60)]].reset_index(drop=True)
    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_ORDER_INVALID"):
        prepare_time_series(
            frame,
            time_column="time",
            value_columns=["value"],
            time_order="declared_monotonic",
        )
    prepared = prepare_time_series(
        frame,
        time_column="time",
        value_columns=["value"],
        time_order="sort_by_time",
    )
    assert prepared.n_observations == 60
    assert prepared.time_order == "sort_by_time"
    assert prepared.inferred_frequency is None


def test_acf_and_pacf_are_bounded_json_safe_and_explicit():
    from workbench.engine.packs.time_series import run_acf, run_pacf
    from workbench.engine.packs.time_series.errors import TimeSeriesPackError

    kwargs = {
        "time_column": "time",
        "value_column": "value",
        "time_order": "declared_monotonic",
        "nlags": 8,
        "confidence_level": 0.95,
    }
    acf = run_acf(_series_frame(), adjusted=False, **kwargs)
    pacf = run_pacf(_series_frame(), method="ywm", **kwargs)
    assert acf["operation_id"] == "time_series.acf"
    assert pacf["operation_id"] == "time_series.pacf"
    assert acf["result"]["lags"] == list(range(9))
    assert len(acf["result"]["values"]) == 9
    assert len(pacf["result"]["values"]) == 9
    json.dumps(acf, allow_nan=False)
    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_INVALID_OPTION"):
        run_pacf(_series_frame(), method="ols", **kwargs)


def test_adf_and_kpss_return_evidence_and_do_not_difference_automatically():
    from workbench.engine.packs.time_series import run_adf, run_kpss

    frame = _series_frame()
    adf = run_adf(
        frame,
        time_column="time",
        value_column="value",
        time_order="declared_monotonic",
        regression="c",
        autolag="aic",
        max_lag=4,
    )
    kpss = run_kpss(
        frame,
        time_column="time",
        value_column="value",
        time_order="declared_monotonic",
        regression="c",
        nlags="auto",
    )
    assert adf["operation_id"] == "time_series.adf"
    assert kpss["operation_id"] == "time_series.kpss"
    assert adf["result"]["policy"]["autolag"] == "aic"
    assert kpss["result"]["policy"]["nlags"] == "auto"
    assert "differenced_values" not in adf["result"]
    assert adf["result"]["p_value_status"] == "approximate"
    assert kpss["result"]["p_value_status"] in {"approximate", "lower_bound", "upper_bound"}


def test_time_series_diagnostics_reject_nonfinite_values_and_excessive_lags():
    from workbench.engine.packs.time_series import run_acf
    from workbench.engine.packs.time_series.errors import TimeSeriesPackError

    frame = _series_frame()
    frame.loc[4, "value"] = np.inf
    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_NON_FINITE_VALUE"):
        run_acf(
            frame,
            time_column="time",
            value_column="value",
            time_order="declared_monotonic",
            nlags=4,
            adjusted=False,
            confidence_level=0.95,
        )
    with pytest.raises(TimeSeriesPackError, match="TIME_SERIES_INVALID_OPTION"):
        run_acf(
            _series_frame(),
            time_column="time",
            value_column="value",
            time_order="declared_monotonic",
            nlags=300,
            adjusted=False,
            confidence_level=0.95,
        )
