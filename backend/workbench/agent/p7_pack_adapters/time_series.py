"""Time-series pack adapters (ACF/PACF, unit roots, ARIMA, VAR/IRF, cointegration, VECM, Granger)."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, TypeAlias, cast
import numpy as np
import pandas as pd
from workbench.contracts.model.categorical import CategoricalResultEnvelope
from workbench.contracts.model.glm_extensions import (
    GLMExtensionResultEnvelope,
)
from workbench.contracts.model.iv_gmm import validate_iv_gmm_result
from workbench.contracts.model.matching import validate_matching_result
from workbench.contracts.model.meta_analysis import MetaAnalysisResultEnvelope
from workbench.contracts.model.power_analysis import POWER_ANALYSIS_SOLVE_TARGETS
from workbench.contracts.model.missing_data import validate_missing_data_result
from workbench.contracts.model.model_diagnostics import ModelDiagnosticsResultEnvelope
from workbench.contracts.model.multiple_comparisons import validate_multiple_comparisons_result
from workbench.contracts.model.multivariate import MultivariateResultEnvelope
from workbench.contracts.model.nonparametric import NonparametricResultEnvelope
from workbench.contracts.model.power_analysis import PowerAnalysisResult
from workbench.contracts.model.repeated_measures_anova import (
    RepeatedMeasuresAnovaResultEnvelope,
)
from workbench.contracts.model.resampling import validate_resampling_result
from workbench.contracts.model.roc_diagnostics import RocDiagnosticsResultEnvelope
from workbench.contracts.model.spatial_statistics import validate_spatial_statistics_result
from workbench.contracts.model.survival_analysis import SurvivalAnalysisResultEnvelope
from workbench.contracts.model.synthetic_control import validate_synthetic_control_result
from workbench.contracts.model.time_series_pack import (
    TIME_SERIES_PACK_CONTRACT,
    TIME_SERIES_PACK_CONTRACT_VERSION,
    TimeSeriesResultEnvelope,
)
from .base import P7PackAdapterError, Request, Result, _binding, _binding_columns, _frame, _option, _request_parts, _require_columns, _validate_declared_bindings


def validate_time_series_request(request: Request) -> Request:
    _operation_id, _bindings, options = _request_parts(request)
    _validate_declared_bindings(request)
    _option(options, "time_order")
    return request


def execute_time_series(frame: pd.DataFrame | None, request: Request) -> Result:
    source = _frame(frame)
    operation_id, bindings, options = _request_parts(request)
    _require_columns(source, bindings)
    try:
        return _TIME_SERIES_EXECUTORS[operation_id](source, bindings, options)
    except KeyError as exc:
        raise P7PackAdapterError(
            f"time-series adapter received unsupported operation: {operation_id}"
        ) from exc


def _time_columns(
    bindings: Mapping[str, object], options: Mapping[str, object]
) -> tuple[str, str]:
    return _binding(bindings, "time"), str(_option(options, "time_order"))


def _execute_time_series_acf(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_acf

    time_column, time_order = _time_columns(bindings, options)
    return run_acf(
        frame=source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        nlags=int(_option(options, "nlags")),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        adjusted=bool(_option(options, "adjusted", False)),
    )


def _execute_time_series_pacf(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_pacf

    time_column, time_order = _time_columns(bindings, options)
    return run_pacf(
        frame=source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        nlags=int(_option(options, "nlags")),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        method=str(_option(options, "method", "ywm")),
    )


def _execute_time_series_adf(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_adf

    time_column, time_order = _time_columns(bindings, options)
    return run_adf(
        source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        regression=str(_option(options, "regression", "c")),
        autolag=str(_option(options, "autolag", "aic")),
        max_lag=int(_option(options, "max_lag", 12)),
    )


def _execute_time_series_kpss(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_kpss

    time_column, time_order = _time_columns(bindings, options)
    return run_kpss(
        source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        regression=str(_option(options, "regression", "c")),
        nlags=cast(str | int, _option(options, "nlags", "auto")),
    )


def _execute_time_series_arima(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import fit_arima

    time_column, time_order = _time_columns(bindings, options)
    return fit_arima(
        source,
        time_column=time_column,
        value_column=_binding(bindings, "value"),
        time_order=time_order,
        order=cast(Sequence[int], _option(options, "order")),
        seasonal_order=cast(Sequence[int], _option(options, "seasonal_order", (0, 0, 0, 0))),
        trend=str(_option(options, "trend", "c")),
        forecast_horizon=int(_option(options, "forecast_horizon", 1)),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
    )


def _execute_time_series_var(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import fit_var

    time_column, time_order = _time_columns(bindings, options)
    return fit_var(
        source,
        time_column=time_column,
        value_columns=_binding_columns(bindings, "values"),
        time_order=time_order,
        lags=int(_option(options, "lags")),
        trend=str(_option(options, "trend", "c")),
        forecast_horizon=int(_option(options, "forecast_horizon", 1)),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        stability_policy=str(_option(options, "stability_policy", "reject_unstable")),
    )


def _execute_time_series_irf(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_irf

    time_column, time_order = _time_columns(bindings, options)
    return run_irf(
        source,
        time_column=time_column,
        value_columns=_binding_columns(bindings, "values"),
        time_order=time_order,
        lags=int(_option(options, "lags")),
        trend=str(_option(options, "trend", "c")),
        horizon=int(_option(options, "horizon", 10)),
        orthogonalized=bool(_option(options, "orthogonalized", True)),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        ci_method=str(_option(options, "ci_method", "asymptotic_normal")),
        stability_policy=str(_option(options, "stability_policy", "reject_unstable")),
    )


def _execute_time_series_cointegration(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_cointegration

    time_column, time_order = _time_columns(bindings, options)
    return run_cointegration(
        source,
        time_column=time_column,
        value_columns=_binding_columns(bindings, "values"),
        time_order=time_order,
        method=str(_option(options, "method")),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
        max_lag=int(_option(options, "max_lag", 1)),
        trend=str(_option(options, "trend", "c")),
        det_order=int(_option(options, "det_order", 0)),
        k_ar_diff=int(_option(options, "k_ar_diff", 1)),
    )


def _execute_time_series_vecm(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import fit_vecm

    time_column, time_order = _time_columns(bindings, options)
    return fit_vecm(
        source,
        time_column=time_column,
        value_columns=_binding_columns(bindings, "values"),
        time_order=time_order,
        det_order=int(_option(options, "det_order", 0)),
        k_ar_diff=int(_option(options, "k_ar_diff", 1)),
        deterministic=str(_option(options, "deterministic")),
        forecast_horizon=int(_option(options, "forecast_horizon", 1)),
        confidence_level=float(_option(options, "confidence_level", 0.95)),
    )


def _execute_time_series_granger(
    source: pd.DataFrame, bindings: Mapping[str, object], options: Mapping[str, object]
) -> Result:
    from workbench.engine.packs.time_series import run_granger

    time_column, time_order = _time_columns(bindings, options)
    return run_granger(
        source,
        time_column=time_column,
        cause=_binding(bindings, "cause"),
        effect=_binding(bindings, "effect"),
        time_order=time_order,
        max_lag=int(_option(options, "max_lag")),
        test=str(_option(options, "test", "ssr_ftest")),
    )


_TIME_SERIES_EXECUTORS: Mapping[
    str, Callable[[pd.DataFrame, Mapping[str, object], Mapping[str, object]], Result]
] = MappingProxyType(
    {
        "time_series.acf": _execute_time_series_acf,
        "time_series.pacf": _execute_time_series_pacf,
        "time_series.adf": _execute_time_series_adf,
        "time_series.kpss": _execute_time_series_kpss,
        "time_series.arima": _execute_time_series_arima,
        "time_series.var": _execute_time_series_var,
        "time_series.irf": _execute_time_series_irf,
        "time_series.cointegration": _execute_time_series_cointegration,
        "time_series.vecm": _execute_time_series_vecm,
        "time_series.granger": _execute_time_series_granger,
    }
)
