"""Verified finite-lag FIGARCH variance filtering with fixed coefficients."""
from __future__ import annotations

import ctypes
import math
from typing import Any

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    MAX_FORECAST_PERIODS, MAX_HOLDOUT_PERIODS, _DOUBLE, _SIZE, _loaded, _native_checkpoint,
    _option_number, _option_periods, _prepare_series, _series_columns, _time_label,
)


_MAX_ROWS = 20_000
_MAX_WORK = 40_000_000
_SUMMARY_FIELDS = (
    'retained_weight_mass', 'omitted_weight_mass', 'initial_backcast', 'variance_intercept', 'log_likelihood',
    'mean_gaussian_loss', 'variance_mae', 'standardized_residual_mean', 'standardized_residual_rms',
)
_NO_ROW = _SIZE(-1).value


def validate_figarch_size(rows: int, holdout_periods: int, forecast_periods: int, truncation: int) -> None:
    _option_periods(holdout_periods, 'holdout_periods', 0, MAX_HOLDOUT_PERIODS)
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    _option_periods(truncation, 'truncation', 32, 2048)
    if rows > _MAX_ROWS or (rows + forecast_periods) * truncation > _MAX_WORK:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', 'FIGARCH exceeds the native row or lag work bound')
    if rows - holdout_periods < 2:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', 'FIGARCH requires at least two training rows')


def _decode(summary: np.ndarray, weights: np.ndarray, variances: np.ndarray, intercept: float, holdout: int):
    error = 'native FIGARCH returned inconsistent variance or weight evidence'
    if not (np.isfinite(summary).all() and np.isfinite(variances).all() and
            ((0 <= weights) & (weights < 1)).all()):
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
    facts = dict(zip(_SUMMARY_FIELDS, map(float, summary), strict=True))
    retained, omitted = facts['retained_weight_mass'], facts['omitted_weight_mass']
    if not (
        0 < retained < 1 and 0 < omitted < 1 and omitted == 1.0 - retained
        and math.isclose(retained, math.fsum(weights), rel_tol=2e-15)
        and facts['variance_intercept'] == intercept and intercept > 0 and (variances >= intercept).all()
        and facts['initial_backcast'] >= 0 and facts['standardized_residual_rms'] >= 0 and facts['variance_mae'] >= 0
        and (holdout > 0 or facts['mean_gaussian_loss'] == facts['variance_mae'] == 0)
    ):
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
    metrics = {name: facts.pop(name) for name in ('mean_gaussian_loss', 'variance_mae')}
    return facts, metrics


def run_figarch(
    frame: pd.DataFrame, *, time_col: str, outcome: str, omega: float, phi: float, d: float, beta: float,
    truncation: int = 1000, forecast_periods: int = 1, holdout_periods: int = 0,
) -> dict[str, Any]:
    omega, phi, d, beta = (
        _option_number(value, name) for name, value in (('omega', omega), ('phi', phi), ('d', d), ('beta', beta))
    )
    if not (omega > 0 and .05 <= d <= .95 and 0 <= phi <= .5 * (1-d) and 0 <= beta <= d + phi):
        raise TimeSeriesPackError(
            'TIME_SERIES_INVALID_OPTION',
            'FIGARCH requires omega > 0, 0.05 <= d <= 0.95, 0 <= phi <= (1-d)/2 and 0 <= beta <= d+phi',
        )
    time, observations = _series_columns(
        frame, time_col, outcome, lambda rows: validate_figarch_size(rows, holdout_periods, forecast_periods, truncation),
    )
    data = _prepare_series(time, observations, forecast_periods, holdout_periods)
    if not data.observed.all():
        row = int(np.argmin(data.observed))
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE', f'FIGARCH requires complete innovations; invalid row {row}')
    library, engine = _loaded()
    summary = np.full(len(_SUMMARY_FIELDS), np.nan, dtype=np.float64)
    weights = np.full(truncation, np.nan, dtype=np.float64)
    variances = np.full(holdout_periods + forecast_periods, np.nan, dtype=np.float64)
    error_row = _SIZE(_NO_ROW)
    with _native_checkpoint() as poll:
        status = library.arboris_figarch_filter(
            data.values.ctypes.data_as(_DOUBLE), data.values.size, data.train_size, forecast_periods, truncation,
            omega, phi, d, beta, summary.ctypes.data_as(_DOUBLE), summary.size, weights.ctypes.data_as(_DOUBLE),
            weights.size, variances.ctypes.data_as(_DOUBLE), variances.size, ctypes.byref(error_row), poll,
        )
    if status or error_row.value != _NO_ROW:
        invalid = ('FIGARCH rejected the native input shape' if error_row.value == _NO_ROW
                   else f'FIGARCH rejected the innovation at row {error_row.value}')
        code, message = {
            1: ('TIME_SERIES_BAD_INPUT', invalid),
            2: ('TIME_SERIES_NUMERIC_FAILURE', 'FIGARCH exceeded its binary64 range'),
            3: ('TIME_SERIES_TOO_FEW_OBSERVATIONS', 'FIGARCH requires at least two training rows'),
            6: ('TIME_SERIES_SIZE_LIMIT', 'FIGARCH exceeds the native row or lag work bound'),
        }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native FIGARCH did not return a verified filter result'))
        raise TimeSeriesPackError(code, message)
    facts, metrics = _decode(summary, weights, variances, omega / (1.0-beta), holdout_periods)
    facts.update(n_observed=data.train_size, n_missing=0, long_run_variance=None,
                 long_run_variance_status='infinite_lag_unit_weight_mass')
    holdout = None
    if holdout_periods:
        holdout = {
            'status': 'completed', 'training_steps': data.train_size, 'n_observed': holdout_periods,
            'origin_time': _time_label(data.time[data.train_size - 1]), 'metrics': metrics,
            'forecast': {'time': [_time_label(value) for value in data.time[data.train_size:]],
                         'variance': variances[:holdout_periods].tolist()},
        }
    return {
        'schema_version': 1, 'model': 'conditional_volatility', 'engine': engine,
        'parameters': {'omega': omega, 'phi': phi, 'd': d, 'beta': beta}, 'fit': facts,
        'policy': {
            'family': 'figarch_1_d_1', 'time_col': time_col, 'outcome': outcome, 'cadence': data.cadence,
            'mean': 'fixed_zero', 'innovation_distribution': 'gaussian', 'estimation': 'fixed_parameters',
            'truncation': truncation, 'backcast': 'training_first_75_ewma_decay_0_94', 'missing': 'reject',
            'variance_units': 'squared_input_units', 'forecast_method': 'truncated_arch_conditional_expected_variance',
            'holdout_method': 'rolling_one_step_fixed_parameters',
        },
        'forecast': {'time': data.future, 'variance': variances[holdout_periods:].tolist()}, 'holdout': holdout,
        'lag_weights': {'privacy': 'local_only', 'first_lag': 1, 'values': weights.tolist()},
    }
