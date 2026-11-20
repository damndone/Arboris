from __future__ import annotations

import ctypes
from typing import Any

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    MAX_FORECAST_PERIODS, MAX_HOLDOUT_PERIODS, _DOUBLE, _SIZE, _holdout_metrics, _interval_forecast, _loaded,
    _native_checkpoint, _numeric_design, _option_periods, _prediction_level, _series_columns, _time_grid, _time_label,
)


_SERIES_COUNT = 2
_MAX_ROWS = 20_000
_MAX_DIFFERENCE_LAGS = 4
_RANK_BLOCKS = ('lagged differences', 'residualized levels and constant', 'residualized differences', 'error-correction regression')


def validate_vecm_size(rows: int, columns: int, difference_lags: int, holdout_periods: int) -> None:
    _option_periods(columns, 'series count', _SERIES_COUNT, _SERIES_COUNT)
    _option_periods(difference_lags, 'difference_lags', 1, _MAX_DIFFERENCE_LAGS)
    _option_periods(holdout_periods, 'holdout_periods', 0, MAX_HOLDOUT_PERIODS)
    if rows > _MAX_ROWS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'fixed-rank VECM supports at most {_MAX_ROWS} time rows')
    minimum = 3 * difference_lags + 7
    if rows - holdout_periods < minimum:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', f'VECM requires at least {minimum} training rows')


def _check_status(status: int, index: int, names: list[str]) -> None:
    if status == 0:
        return
    if status == 3:
        row, series = divmod(index, _SERIES_COUNT)
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE', f'VECM requires complete finite values; {names[series]!r} is invalid at row {row}')
    if status == 4:
        stage, pivot = divmod(index, 16)
        if stage < len(_RANK_BLOCKS):
            raise TimeSeriesPackError('TIME_SERIES_VECM_RANK', f'VECM {_RANK_BLOCKS[stage]} is rank deficient at pivot {pivot}')
    if status == 7:
        message = ('leading canonical correlations are too close to identify one direction' if index == 1
                   else 'leading canonical correlation is on the unresolved boundary')
        raise TimeSeriesPackError('TIME_SERIES_VECM_CANONICAL_UNRESOLVED', f'VECM {message}')
    code, message = {
        2: ('TIME_SERIES_NUMERIC_FAILURE', 'VECM exceeded its fit numerical range'),
        6: ('TIME_SERIES_NUMERIC_FAILURE', f'VECM level forecast failed at horizon {index}'),
        8: ('TIME_SERIES_VECM_NORMALIZATION_UNAVAILABLE', f'VECM cannot normalize its cointegrating vector on {names[0]!r}'),
    }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native VECM did not produce a verified result'))
    raise TimeSeriesPackError(code, message)


def _fit(library, values, names, training, lag, times, critical):
    horizon = len(times)
    header_length = 11 + 4 * lag
    output = np.empty(header_length + 6 * horizon, dtype=np.float64)
    error = _SIZE()
    with _native_checkpoint() as poll:
        status = library.arboris_vecm_rank1(
            values.ctypes.data_as(_DOUBLE), values.size, len(values), training, lag, horizon,
            output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error), poll,
        )
    _check_status(status, error.value, names)
    forecast = output[header_length:].reshape(horizon, 6)
    covariance = forecast[:, 2:].reshape(horizon, _SERIES_COUNT, _SERIES_COUNT)
    variance = covariance.diagonal(axis1=1, axis2=2)
    curves = {
        name: _interval_forecast(np.column_stack((forecast[:, i], variance[:, i])), times, critical, 'VECM')
        for i, name in enumerate(names)
    }
    return output[:header_length], curves, covariance


def run_vecm_rank1(
    frame: pd.DataFrame, *, time_col: str, series_columns: list[str], difference_lags: int = 1,
    forecast_periods: int = 1, holdout_periods: int = 0, confidence_level: float = 0.95,
) -> dict[str, Any]:
    if not isinstance(series_columns, (list, tuple)) or len(series_columns) != _SERIES_COUNT:
        raise TimeSeriesPackError('TIME_SERIES_BAD_INPUT', 'choose exactly two distinct VECM series')
    names = list(series_columns)
    time_series, _ = _series_columns(frame, time_col, names[0], lambda rows: validate_vecm_size(
        rows, len(names), difference_lags, holdout_periods))
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    level, critical = _prediction_level(confidence_level)
    time, future, cadence = _time_grid(time_series, forecast_periods)
    values = _numeric_design(frame, names, excluded=(time_col,))
    rows = len(values)
    library, engine = _loaded()
    holdout = None
    if holdout_periods:
        training = rows - holdout_periods
        holdout_times = [_time_label(item) for item in time[training:]]
        training_fit, predicted, covariance = _fit(library, values, names, training, difference_lags, holdout_times, critical)
        observed = np.ones(rows, dtype=np.bool_)
        metrics = {name: _holdout_metrics(values[:, i], observed, training, predicted[name])[1]
                   for i, name in enumerate(names)}
        holdout = {
            'training_steps': training, 'training_effective_rows': training - difference_lags - 1,
            'training_canonical_eigenvalues': training_fit[:2].tolist(),
            'origin_time': _time_label(time[training - 1]), 'metrics': metrics, 'status': 'completed',
            'forecast': predicted, 'forecast_covariance': covariance.tolist(),
        }

    fitted, forecast, covariance = _fit(library, values, names, rows, difference_lags, future, critical)
    return {
        'schema_version': 1, 'model': 'vecm_rank1', 'engine': engine,
        'fit': {'n_observed': rows, 'n_effective': rows - difference_lags - 1, 'rank': 1,
                'canonical_eigenvalues': fitted[:2].tolist(), 'normalized_series': names[0]},
        'policy': {
            'time_col': time_col, 'series_columns': names, 'difference_lags': difference_lags,
            'levels_order': difference_lags + 1, 'rank_policy': 'fixed_rank_one',
            'deterministic': 'restricted_constant', 'cadence': cadence, 'confidence_level': level,
            'covariance': 'maximum_likelihood_n_effective', 'forecast_interval': 'marginal_gaussian_plugin',
            'forecast_fit': 'full_observed_sample', 'holdout_method': 'training_prefix_fit_fixed_origin',
            'holdout_baseline': 'last_training_level', 'missing': 'reject',
        },
        'forecast': forecast, 'holdout': holdout,
        'local': {
            'cointegrating_relation': {'levels': dict(zip(names, fitted[2:4].tolist(), strict=True)),
                                       'restricted_constant': float(fitted[4]), 'normalized_series': names[0]},
            'loading_coefficients': {'equations': names, 'values': fitted[5:7].tolist()},
            'short_run_coefficients': {'columns': names, 'lags': list(range(1, difference_lags + 1)),
                                       'matrices': fitted[7:-4].reshape(difference_lags, 2, 2).tolist()},
            'innovation_covariance': {'columns': names, 'matrix': fitted[-4:].reshape(2, 2).tolist()},
            'forecast_covariance': covariance.tolist(),
        },
    }
