from __future__ import annotations

import ctypes
from typing import Any

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    MAX_FORECAST_PERIODS, MAX_HOLDOUT_PERIODS, MAX_OBSERVATIONS, MAX_TRACE_ROWS, _DOUBLE, _SIZE,
    _holdout_metrics, _interval_forecast, _loaded, _native_checkpoint, _option_number, _option_periods,
    _prediction_level, _prepare_series, _series_columns, _time_label,
)


_TRACE_COLUMNS = ('one_step_mean', 'innovation', 'level', 'trend', 'seasonal')
_ALPHA_GRID_COUNT = 20
_JOINT_SUMMARY_WIDTH = 8
MAX_JOINT_HOLT_WINTERS_ROWS = 2_000


def validate_holt_winters_size(rows: int, season_period: int, holdout_periods: int) -> None:
    _option_periods(season_period, 'season_period', 2, 366)
    _option_periods(holdout_periods, 'holdout_periods', 0, MAX_HOLDOUT_PERIODS)
    if rows > MAX_OBSERVATIONS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'Holt-Winters supports at most {MAX_OBSERVATIONS} time rows')
    if rows - holdout_periods < 3 * season_period:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', 'training requires at least three full seasonal cycles')


def _native_fit(library, data, period, future, beta, gamma, critical, *, alpha=None):
    estimate_alpha = alpha is None
    horizon = len(future)
    rows = data.train_size if estimate_alpha else len(data.values)
    trace_count = min(MAX_TRACE_ROWS, rows - 2 * period)
    prefix = 1 + _ALPHA_GRID_COUNT if estimate_alpha else 0
    output = np.empty(prefix + 6 + 2 * period + trace_count * len(_TRACE_COLUMNS) + 2 * horizon, dtype=np.float64)
    error_index = _SIZE()
    estimate = library.arboris_holt_winters_fit_alpha if estimate_alpha else library.arboris_holt_winters_additive
    smoothing = (beta, gamma) if estimate_alpha else (alpha, beta, gamma)
    with _native_checkpoint() as poll:
        status = estimate(data.values.ctypes.data_as(_DOUBLE), data.values.size, period, horizon, *smoothing,
                          output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error_index), poll)
    if status:
        code, message = {
            2: ('TIME_SERIES_NUMERIC_FAILURE', 'Holt-Winters state update exceeded its numerical range'),
            3: ('TIME_SERIES_NON_FINITE_VALUE', f'Holt-Winters requires complete outcomes; invalid row {error_index.value}'),
            4: ('TIME_SERIES_NUMERIC_FAILURE', f'Holt-Winters forecast failed at horizon {error_index.value}'),
            6: ('TIME_SERIES_HOLT_WINTERS_UNIDENTIFIED', 'all training alpha candidates have the same error'),
        }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native Holt-Winters did not produce a verified result'))
        raise TimeSeriesPackError(code, message)
    return _decode_fit(output, prefix, data.time, rows, period, future, critical)


def _decode_fit(output, prefix, time, rows, period, future, critical):
    horizon = len(future)
    trace_count = min(MAX_TRACE_ROWS, rows - 2 * period)
    initial_level, initial_trend, final_level, final_trend, sse, variance = map(float, output[prefix:prefix + 6])
    season_start = prefix + 6
    trace_start = season_start + 2 * period
    tail_start = len(output) - 2 * horizon
    trace = dict(zip(_TRACE_COLUMNS, output[trace_start:tail_start].reshape(trace_count, -1).T.tolist(), strict=True))
    trace['time'] = [_time_label(value) for value in time[rows - trace_count:rows]]
    trace['total_rows'] = rows - 2 * period
    trace['initial_seasonal'] = output[season_start:season_start + period].tolist()
    trace['final_seasonal'] = output[season_start + period:trace_start].tolist()
    fit = {'n_observed': rows, 'n_missing': 0, 'training_warmup': 2 * period, 'sse': sse,
           'innovation_variance': variance, 'initial_level': initial_level, 'initial_trend': initial_trend,
           'final_level': final_level, 'final_trend': final_trend, 'trace': trace}
    return output[:prefix], fit, _interval_forecast(output[tail_start:].reshape(horizon, 2), future, critical, 'Holt-Winters')


def run_holt_winters(
    frame: pd.DataFrame, *, time_col: str, outcome: str, season_period: int, alpha: float, beta: float, gamma: float,
    forecast_periods: int = 1, confidence_level: float = 0.95,
) -> dict[str, Any]:
    alpha = _option_number(alpha, 'alpha')
    if not 0 < alpha <= 1:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'require 0 < alpha <= 1')
    return _run(frame, time_col, outcome, season_period, alpha, beta, gamma, forecast_periods, 0, confidence_level)


def run_holt_winters_fit_alpha(
    frame: pd.DataFrame, *, time_col: str, outcome: str, season_period: int, beta: float, gamma: float,
    holdout_periods: int, forecast_periods: int = 1, confidence_level: float = 0.95,
) -> dict[str, Any]:
    _option_periods(holdout_periods, 'holdout_periods', 1, MAX_HOLDOUT_PERIODS)
    return _run(frame, time_col, outcome, season_period, None, beta, gamma, forecast_periods, holdout_periods, confidence_level)


def _run(frame, time_col, outcome, period, alpha, beta, gamma, horizon, holdout_periods, confidence_level):
    time, observations = _series_columns(frame, time_col, outcome, lambda rows: validate_holt_winters_size(
        rows, period, holdout_periods))
    _option_periods(horizon, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    beta, gamma = _option_number(beta, 'beta'), _option_number(gamma, 'gamma')
    if not 0 <= beta <= 1 or not 0 <= gamma <= 1:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'require 0 <= beta and gamma <= 1')
    level, critical = _prediction_level(confidence_level)
    data = _prepare_series(time, observations, horizon, holdout_periods)
    _require_complete(data)
    library, engine = _loaded()
    holdout = None
    estimation = {'method': 'fixed_smoothing_parameters'}
    if alpha is None:
        training = data.train_size
        grid, training_fit, predicted = _native_fit(library, data, period,
                                                    [_time_label(t) for t in data.time[training:]], beta, gamma, critical)
        alpha = float(grid[0])
        count, metrics = _holdout_metrics(data.values, data.observed, training, predicted, seasonal_period=period)
        holdout = {'status': 'completed', 'training_steps': training, 'training_observed': training_fit['n_observed'],
                   'n_observed': count, 'n_missing': 0, 'origin_time': _time_label(data.time[training - 1]),
                   'forecast': predicted, 'metrics': metrics}
        estimation = {'method': 'training_prefix_alpha_grid', 'training_steps': training,
                      'training_sse': training_fit['sse'], 'alpha_candidates': _ALPHA_GRID_COUNT,
                      'alpha_grid_sse': grid[1:].tolist()}
    _, fit, forecast = _native_fit(library, data, period, data.future, beta, gamma, critical, alpha=alpha)
    return {
        'schema_version': 1, 'model': 'holt_winters_additive', 'engine': engine,
        'parameters': {'alpha': alpha, 'beta': beta, 'gamma': gamma}, 'fit': fit, 'forecast': forecast,
        'holdout': holdout, 'estimation': estimation,
        'policy': {'time_col': time_col, 'outcome': outcome, 'cadence': data.cadence, 'season_period': period,
                   'confidence_level': level, 'forecast_interval': 'gaussian_plugin',
                   'missing': 'reject', 'holdout_method': 'training_prefix_fit_fixed_origin',
                   'holdout_baseline': 'last_observed_training_seasonal_phase'},
    }


def _require_complete(data):
    if not data.observed.all():
        missing = int(np.argmin(data.observed))
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE', f'Holt-Winters requires complete outcomes; invalid row {missing}')


def validate_holt_winters_joint_size(rows: int, season_period: int, holdout_periods: int) -> None:
    _option_periods(season_period, 'season_period', 2, 24)
    _option_periods(holdout_periods, 'holdout_periods', 0, MAX_HOLDOUT_PERIODS)
    if rows > MAX_JOINT_HOLT_WINTERS_ROWS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'joint Holt-Winters supports at most {MAX_JOINT_HOLT_WINTERS_ROWS} time rows')
    minimum = 2 * season_period + max(24, 2 * season_period)
    if rows - holdout_periods < minimum:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', f'joint Holt-Winters requires at least {minimum} training rows')


def _joint_fit(library, values, time, period, future, critical):
    rows, horizon = len(values), len(future)
    trace_count = min(MAX_TRACE_ROWS, rows - 2 * period)
    output = np.empty(_JOINT_SUMMARY_WIDTH + 6 + 2 * period + trace_count * len(_TRACE_COLUMNS) + 2 * horizon, dtype=np.float64)
    error_index = _SIZE()
    with _native_checkpoint() as poll:
        status = library.arboris_holt_winters_fit_joint(
            values.ctypes.data_as(_DOUBLE), rows, period, horizon,
            output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error_index), poll,
        )
    if status:
        code, message = {
            2: ('TIME_SERIES_NUMERIC_FAILURE', 'joint Holt-Winters state update exceeded its numerical range'),
            3: ('TIME_SERIES_NON_FINITE_VALUE', f'Holt-Winters requires complete outcomes at row {error_index.value}'),
            4: ('TIME_SERIES_NUMERIC_FAILURE', f'Holt-Winters forecast failed at horizon {error_index.value}'),
            6: ('TIME_SERIES_HOLT_WINTERS_UNIDENTIFIED', 'the search did not verify a stable interior joint fit'),
            7: ('TIME_SERIES_HOLT_WINTERS_BOUNDARY', 'the best joint fit could not be separated from a smoothing boundary'),
            8: ('TIME_SERIES_SIZE_LIMIT', 'joint Holt-Winters exceeded its native work or row limit'),
        }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native joint Holt-Winters did not produce a verified result'))
        raise TimeSeriesPackError(code, message)
    receipt, fit, forecast = _decode_fit(output, _JOINT_SUMMARY_WIDTH, time, rows, period, future, critical)
    alpha, beta, gamma, evaluations, gradient, curvature, boundary_gap, agreeing = map(float, receipt)
    fit['n_effective'] = rows - 2 * period
    estimation = {
        'method': 'joint_conditional_training_sse', 'training_steps': rows, 'scored_steps': fit['n_effective'],
        'objective_evaluations': int(evaluations), 'gradient_max_abs': gradient,
        'minimum_profile_curvature': curvature, 'boundary_log_sse_gap': boundary_gap,
        'agreeing_search_starts': int(agreeing),
    }
    return {'alpha': alpha, 'beta': beta, 'gamma': gamma}, fit, forecast, estimation


def run_holt_winters_fit_joint(
    frame: pd.DataFrame, *, time_col: str, outcome: str, season_period: int,
    forecast_periods: int = 1, holdout_periods: int = 0, confidence_level: float = 0.95,
) -> dict[str, Any]:
    time, observations = _series_columns(frame, time_col, outcome, lambda rows: validate_holt_winters_joint_size(
        rows, season_period, holdout_periods))
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    level, critical = _prediction_level(confidence_level)
    data = _prepare_series(time, observations, forecast_periods, holdout_periods)
    _require_complete(data)
    library, engine = _loaded()
    holdout = None
    if holdout_periods:
        start = data.train_size
        targets = [_time_label(t) for t in data.time[start:]]
        training_parameters, training_fit, predicted, training_estimation = _joint_fit(
            library, data.values[:start], data.time, season_period, targets, critical,
        )
        count, metrics = _holdout_metrics(data.values, data.observed, start, predicted, seasonal_period=season_period)
        training_fit.pop('trace')
        holdout = {
            'status': 'completed', 'training_steps': start, 'training_observed': training_fit['n_observed'],
            'n_observed': count, 'n_missing': 0, 'origin_time': _time_label(data.time[start - 1]),
            'training_parameters': training_parameters, 'training_fit': training_fit,
            'training_estimation': training_estimation, 'forecast': predicted, 'metrics': metrics,
        }
    parameters, fit, forecast, estimation = _joint_fit(library, data.values, data.time, season_period, data.future, critical)
    return {
        'schema_version': 1, 'model': 'holt_winters_additive', 'engine': engine,
        'parameters': parameters, 'fit': fit, 'forecast': forecast, 'holdout': holdout, 'estimation': estimation,
        'policy': {
            'time_col': time_col, 'outcome': outcome, 'cadence': data.cadence, 'season_period': season_period,
            'confidence_level': level, 'initialization': 'two_complete_cycles',
            'smoothing_parameterization': 'traditional_holt_winters_weights',
            'variance_estimation': 'centered_training_innovation_sample_variance',
            'forecast_interval': 'gaussian_conditional_on_fitted_parameters', 'missing': 'reject',
            'holdout_method': 'training_prefix_fit_fixed_origin', 'holdout_baseline': 'last_observed_training_seasonal_phase',
        },
    }
