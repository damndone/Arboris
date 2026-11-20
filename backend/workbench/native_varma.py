from __future__ import annotations

import ctypes
from typing import Any

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    MAX_FORECAST_PERIODS, MAX_HOLDOUT_PERIODS, _DOUBLE, _SIZE, _holdout_metrics, _interval_forecast, _loaded,
    _native_checkpoint, _numeric_design, _option_number, _option_periods, _prediction_level, _series_columns,
    _time_grid, _time_label,
)


_SERIES_COUNT = 2
_MAX_ROWS = 20_000
_MIN_TRAINING_ROWS = 8
_MAX_ABS_MA = .95
_IRF_RESPONSE_LIMIT = 1e6
_HEADER_LENGTH = 15


def validate_varma11_size(rows: int, columns: int, intercept: bool, holdout_periods: int) -> None:
    _option_periods(columns, 'series count', _SERIES_COUNT, _SERIES_COUNT)
    _option_periods(holdout_periods, 'holdout_periods', 0, MAX_HOLDOUT_PERIODS)
    if type(intercept) is not bool:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'intercept must be true or false')
    if rows > _MAX_ROWS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'fixed-MA VARMA supports at most {_MAX_ROWS} time rows')
    if rows - holdout_periods < _MIN_TRAINING_ROWS:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS',
                                  f'fixed-MA VARMA requires at least {_MIN_TRAINING_ROWS} training rows')


def _check_status(status: int, index: int, names: list[str]) -> None:
    if status == 0:
        return
    if status == 3:
        row, series = divmod(index, _SERIES_COUNT)
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE',
                                  f'VARMA requires complete finite values; {names[series]!r} is invalid at row {row}')
    code, message = {
        2: ('TIME_SERIES_NUMERIC_FAILURE', 'fixed-MA VARMA exceeded its fit numerical range'),
        4: ('TIME_SERIES_VARMA_RANK', f'VARMA filtered lag design is rank deficient at pivot {index}'),
        6: ('TIME_SERIES_NUMERIC_FAILURE', f'VARMA forecast or innovation response failed at horizon {index}'),
        7: ('TIME_SERIES_NUMERIC_FAILURE', f'VARMA innovation response exceeded the limit at horizon {index}'),
        8: ('TIME_SERIES_VARMA_INNOVATION_COVARIANCE', 'VARMA innovation covariance is numerically singular'),
    }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native fixed-MA VARMA did not produce a verified result'))
    raise TimeSeriesPackError(code, message)


def _fit(library, values, names, training, intercept, theta, times, critical, irf_periods=0):
    horizon = len(times)
    forecast_end = _HEADER_LENGTH + 6 * horizon
    irf_length = 8 * (irf_periods + 1) if irf_periods else 0
    output = np.empty(forecast_end + irf_length, dtype=np.float64)
    error = _SIZE()
    with _native_checkpoint() as poll:
        status = library.arboris_varma11_fixed_ma(
            values.ctypes.data_as(_DOUBLE), values.size, len(values), training, int(intercept), theta, horizon,
            irf_periods, _IRF_RESPONSE_LIMIT, output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error), poll,
        )
    _check_status(status, error.value, names)
    forecast = output[_HEADER_LENGTH:forecast_end].reshape(horizon, 6)
    covariance = forecast[:, 2:].reshape(horizon, _SERIES_COUNT, _SERIES_COUNT)
    variance = covariance.diagonal(axis1=1, axis2=2)
    curves = {name: _interval_forecast(np.column_stack((forecast[:, i], variance[:, i])), times, critical, 'VARMA')
              for i, name in enumerate(names)}
    return output[:_HEADER_LENGTH], curves, covariance, output[forecast_end:]


def run_varma11_fixed_ma(
    frame: pd.DataFrame, *, time_col: str, series_columns: list[str], ma_coefficient: float, intercept: bool = True,
    forecast_periods: int = 1, holdout_periods: int = 0, confidence_level: float = .95, irf_periods: int = 0,
) -> dict[str, Any]:
    theta = _option_number(ma_coefficient, 'ma_coefficient')
    if not -_MAX_ABS_MA <= theta <= _MAX_ABS_MA:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', f'ma_coefficient must be in [{-_MAX_ABS_MA}, {_MAX_ABS_MA}]')
    if not isinstance(series_columns, (list, tuple)) or len(series_columns) != _SERIES_COUNT:
        raise TimeSeriesPackError('TIME_SERIES_BAD_INPUT', 'choose exactly two distinct VARMA series')
    names = list(series_columns)
    time_series, _ = _series_columns(frame, time_col, names[0], lambda rows: validate_varma11_size(
        rows, len(names), intercept, holdout_periods))
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    _option_periods(irf_periods, 'irf_periods', 0, MAX_FORECAST_PERIODS)
    level, critical = _prediction_level(confidence_level)
    time, future, cadence = _time_grid(time_series, forecast_periods)
    values = _numeric_design(frame, names, excluded=(time_col,))
    rows = len(values)
    library, engine = _loaded()
    holdout = None
    if holdout_periods:
        training = rows - holdout_periods
        holdout_times = [_time_label(item) for item in time[training:]]
        training_fit, predicted, covariance, _ = _fit(library, values, names, training, intercept, theta,
                                                      holdout_times, critical)
        observed = np.ones(rows, dtype=np.bool_)
        holdout = {
            'training_steps': training, 'training_effective_rows': training - 1,
            'training_conditional_log_likelihood': float(training_fit[2]), 'origin_time': _time_label(time[training - 1]),
            'metrics': {name: _holdout_metrics(values[:, i], observed, training, predicted[name])[1]
                        for i, name in enumerate(names)},
            'forecast': predicted, 'forecast_covariance': covariance.tolist(), 'status': 'completed',
        }

    fitted, forecast, covariance, irf = _fit(library, values, names, rows, intercept, theta, future, critical, irf_periods)
    bound, pivot, log_likelihood = map(float, fitted[:3])
    ar_rows = fitted[5:9].reshape(_SERIES_COUNT, _SERIES_COUNT).T.tolist()
    terms = (['intercept'] if intercept else []) + [f'L1.{name}' for name in names]
    coefficients = ([fitted[3:5].tolist()] if intercept else []) + ar_rows
    detail = {
        'coefficient_table': {'terms': terms, 'equations': names, 'matrix': coefficients},
        'moving_average_matrix': {'columns': names, 'matrix': [[theta, 0.], [0., theta]]},
        'innovation_covariance': {'columns': names, 'matrix': fitted[9:13].reshape(2, 2).tolist()},
        'terminal_innovation': dict(zip(names, fitted[13:15].tolist(), strict=True)),
        'forecast_covariance': covariance.tolist(),
    }
    diagnostics = {}
    if irf_periods:
        response = irf.reshape(-1, 2, _SERIES_COUNT, _SERIES_COUNT)
        detail['impulse_responses'] = {
            'columns': names, 'horizons': list(range(irf_periods + 1)), 'response': response[:, 0].tolist(),
            'forecast_covariance': response[:, 1].tolist(),
        }
        diagnostics['impulse_response'] = {'periods': irf_periods, 'basis': 'reduced_form_unit_innovation',
                                           'response_limit': _IRF_RESPONSE_LIMIT}
    contraction = bound < 1 - 8 * len(terms) * np.finfo(np.float64).eps
    return {
        'schema_version': 1, 'model': 'varma11_fixed_ma', 'engine': engine,
        'fit': {'n_observed': rows, 'n_effective': rows - 1, 'conditional_log_likelihood': log_likelihood,
                'scaled_ar_contraction_bound': bound, 'minimum_qr_pivot_ratio': pivot,
                'stability': 'sufficient_ar_contraction' if contraction else 'undetermined'},
        'policy': {
            'time_col': time_col, 'series_columns': names, 'ar_order': 1, 'ma_order': 1, 'ma_coefficient': theta,
            'ma_matrix_policy': 'fixed_shared_scalar_identity', 'intercept': intercept, 'cadence': cadence,
            'initial_level': 'condition_on_first_observation', 'initial_innovation': 'zero',
            'confidence_level': level, 'covariance': 'maximum_likelihood_n_effective',
            'forecast_interval': 'marginal_gaussian_plugin', 'forecast_fit': 'full_observed_sample',
            'holdout_method': 'training_prefix_fit_fixed_origin', 'holdout_baseline': 'last_training_level', 'missing': 'reject',
        },
        'diagnostics': diagnostics, 'forecast': forecast, 'holdout': holdout, 'local': detail,
    }
