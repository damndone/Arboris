from __future__ import annotations

import ctypes
import sys

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    MAX_FORECAST_PERIODS, MAX_HOLDOUT_PERIODS, _DOUBLE, _SIZE, _holdout_metrics, _interval_forecast, _loaded,
    _native_checkpoint, _numeric_design, _option_periods, _prediction_level, _series_columns, _time_grid, _time_label,
)


def validate_var_size(rows, columns, lag_order, intercept, holdout_periods):
    _option_periods(columns, 'series count', 2, 8)
    _option_periods(lag_order, 'lag_order', 1, 8)
    _option_periods(holdout_periods, 'holdout_periods', 0, MAX_HOLDOUT_PERIODS)
    if type(intercept) is not bool:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'intercept must be true or false')
    if rows > 20_000:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', 'VAR supports at most 20000 time rows')
    minimum = lag_order + lag_order * columns + int(intercept) + 1
    if rows - holdout_periods < minimum:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', f'VAR requires at least {minimum} training rows')


def validate_granger_roles(names, effect, excluded) -> bool:
    selected = effect is not None or excluded is not None
    if selected and (
        effect not in names or not isinstance(excluded, (list, tuple)) or not excluded
        or any(type(name) is not str or name not in names or name == effect for name in excluded)
        or len(set(excluded)) != len(excluded)
    ):
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'Granger tests need a response and distinct excluded series in the VAR')
    return selected


def _check_status(status, error_index, columns):
    if not status:
        return
    index = error_index.value
    code, message = {
        2: ('TIME_SERIES_NUMERIC_FAILURE', 'VAR exceeded its numerical range'),
        3: ('TIME_SERIES_NON_FINITE_VALUE', f'VAR requires complete series; invalid cell at flattened index {index} in {columns} columns'),
        4: ('TIME_SERIES_VAR_RANK', f'VAR lag design is rank deficient at pivot {index}'),
        6: ('TIME_SERIES_NUMERIC_FAILURE', f'VAR forecast failed at horizon {index}'),
        7: ('TIME_SERIES_NUMERIC_FAILURE', f'VAR innovation response exceeded the limit at horizon {index}'),
    }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native VAR did not produce a verified result'))
    raise TimeSeriesPackError(code, message)


def _fit(library, values, names, training, lag, intercept, times, critical, *, retain_evidence=False):
    rows, series = values.shape
    predictors = series * lag + int(intercept)
    horizon = len(times)
    length = 2 + predictors * series + series**2 + horizon * (series + series**2)
    receipt_length = series + predictors + predictors * series + series**2 + predictors**2 if retain_evidence else 0
    output = np.empty(length + receipt_length, dtype=np.float64)
    error = _SIZE()
    kernel = library.arboris_var_fit_with_evidence if retain_evidence else library.arboris_var_fit
    with _native_checkpoint() as poll:
        status = kernel(values.ctypes.data_as(_DOUBLE), values.size, rows, series, training, lag, int(intercept), horizon,
                        output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error), poll)
    _check_status(status, error, series)
    coefficient_end = 2 + predictors * series
    covariance_end = coefficient_end + series**2
    forecast = output[covariance_end:length].reshape(horizon, series + series**2)
    covariance = forecast[:, series:].reshape(horizon, series, series)
    variance = covariance.diagonal(axis1=1, axis2=2)
    curves = {name: _interval_forecast(np.column_stack((forecast[:, i], variance[:, i])), times, critical, 'VAR')
              for i, name in enumerate(names)}
    coefficients = output[2:coefficient_end].reshape(predictors, series)
    innovations = output[coefficient_end:covariance_end].reshape(series, series)
    return output[:2], coefficients, innovations, curves, covariance, output[length:]


def run_var(
    frame: pd.DataFrame, *, time_col: str, series_columns: list[str], lag_order: int = 1, intercept: bool = True,
    forecast_periods: int = 1, holdout_periods: int = 0, confidence_level: float = 0.95, irf_periods: int = 0,
    granger_effect: str | None = None, granger_excluded: list[str] | None = None,
):
    if not isinstance(series_columns, (list, tuple)) or not 2 <= len(series_columns) <= 8:
        raise TimeSeriesPackError('TIME_SERIES_BAD_INPUT', 'choose two to eight distinct VAR series')
    names = list(series_columns)
    time_series, _ = _series_columns(frame, time_col, names[0], lambda rows: validate_var_size(
        rows, len(names), lag_order, intercept, holdout_periods))
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    _option_periods(irf_periods, 'irf_periods', 0, MAX_FORECAST_PERIODS)
    granger = validate_granger_roles(names, granger_effect, granger_excluded)
    level, critical = _prediction_level(confidence_level)
    time, future, cadence = _time_grid(time_series, forecast_periods)
    values = _numeric_design(frame, names, excluded=(time_col,))
    rows, width = values.shape
    training = rows - holdout_periods
    library, engine = _loaded()
    holdout = None
    if holdout_periods:
        holdout_times = [_time_label(item) for item in time[training:]]
        _, _, _, predicted, covariance, _ = _fit(library, values, names, training, lag_order, intercept, holdout_times, critical)
        observed = np.ones(rows, dtype=np.bool_)
        metrics = {name: _holdout_metrics(values[:, i], observed, training, predicted[name])[1]
                   for i, name in enumerate(names)}
        holdout = {'training_steps': training, 'origin_time': _time_label(time[training - 1]), 'metrics': metrics,
                   'forecast': predicted, 'forecast_covariance': covariance.tolist(), 'status': 'completed'}
    fit_header, coefficients, innovations, forecast, covariance, evidence = _fit(
        library, values, names, rows, lag_order, intercept, future, critical, retain_evidence=granger or bool(irf_periods))
    k = coefficients.shape[0]
    fitted_rows = rows - lag_order
    bound, pivot = map(float, fit_header)
    verified_stability = bound < 1 - 8 * k * np.finfo(np.float64).eps
    diagnostics = {}
    detail = {}
    error = _SIZE()
    if granger:
        from scipy.special import fdtrc

        mask = sum(1 << names.index(name) for name in granger_excluded)
        tested = np.empty(6, dtype=np.float64)
        with _native_checkpoint() as poll:
            status = library.arboris_var_granger_block(
                evidence.ctypes.data_as(_DOUBLE), evidence.size, width, lag_order, int(intercept), fitted_rows,
                names.index(granger_effect), mask, tested.ctypes.data_as(_DOUBLE), tested.size, ctypes.byref(error), poll,
            )
        _check_status(status, error, width)
        statistic, df_num, df_den, sse, restricted, explained = map(float, tested)
        diagnostics['granger'] = {'response': granger_effect, 'excluded': list(granger_excluded), 'f_statistic': statistic,
                                  'df_num': int(df_num), 'df_den': int(df_den), 'p_value': float(fdtrc(df_num, df_den, statistic)),
                                  'unrestricted_sse': sse, 'restricted_sse': restricted, 'explained_sse': explained}
    if irf_periods:
        response = np.empty((irf_periods + 1, 2, width, width), dtype=np.float64)
        with _native_checkpoint() as poll:
            status = library.arboris_var_irf(
                evidence.ctypes.data_as(_DOUBLE), evidence.size, width, lag_order, int(intercept), irf_periods,
                sys.float_info.max, response.ctypes.data_as(_DOUBLE), response.size, ctypes.byref(error), poll,
            )
        _check_status(status, error, width)
        detail['impulse_responses'] = {'columns': names, 'horizons': list(range(irf_periods + 1)),
                                       'response': response[:, 0].tolist(), 'forecast_covariance': response[:, 1].tolist()}
        diagnostics['impulse_response'] = {'periods': irf_periods, 'basis': 'reduced_form_unit_innovation'}
    terms = (['intercept'] if intercept else []) + [f'L{lag}.{name}' for lag in range(1, lag_order + 1) for name in names]
    return {
        'schema_version': 1, 'model': 'var', 'engine': engine,
        'fit': {'n_observed': rows, 'n_effective': fitted_rows, 'residual_df': fitted_rows - k,
                'scaled_contraction_bound': bound, 'minimum_qr_pivot_ratio': pivot,
                'stability': 'sufficient_contraction' if verified_stability else 'undetermined'},
        'policy': {'time_col': time_col, 'series_columns': names, 'lag_order': lag_order, 'intercept': intercept,
                   'cadence': cadence, 'confidence_level': level, 'covariance': 'residual_df',
                   'forecast_interval': 'marginal_gaussian_plugin', 'missing': 'reject'},
        'diagnostics': diagnostics, 'forecast': forecast, 'holdout': holdout,
        'local': {**detail, 'coefficient_table': {'terms': terms, 'equations': names, 'matrix': coefficients.tolist()},
                  'innovation_covariance': {'columns': names, 'matrix': innovations.tolist()},
                  'forecast_covariance': covariance.tolist()},
    }
