"""Verified conditional Gaussian IGARCH with exact unit persistence."""
from __future__ import annotations

import ctypes
import math
from typing import Any

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    MAX_FORECAST_PERIODS, _DOUBLE, _SIZE, _loaded, _native_checkpoint, _option_periods,
    _prepare_series, _series_columns, _time_label,
)
from .native_volatility import validate_volatility_size as validate_igarch_size


_SUMMARY_FIELDS = (
    'omega', 'alpha', 'beta', 'persistence', 'normalized_omega', 'initial_backcast', 'training_rms', 'log_likelihood',
    'standardized_residual_mean', 'standardized_residual_rms', 'optimizer_iterations', 'optimizer_evaluations',
    'projected_gradient_norm', 'minimum_free_curvature_pivot', 'boundary_mask', 'converged_starts',
    'mean_gaussian_loss', 'variance_mae', 'initial_variance',
)
_BOUNDARIES = ('omega_lower', 'omega_upper', 'alpha_zero', 'alpha_one')
_NO_ROW = _SIZE(-1).value


def _decode(summary: np.ndarray, forecasts: np.ndarray, holdout: int):
    error = 'native IGARCH returned inconsistent fit or forecast evidence'
    if not np.isfinite(summary).all() or not np.isfinite(forecasts).all() or not (forecasts > 0).all():
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
    facts = dict(zip(_SUMMARY_FIELDS, map(float, summary), strict=True))
    for name, low, high in [('boundary_mask', 0, 15), ('optimizer_iterations', 0, 100),
                            ('optimizer_evaluations', 1, 769), ('converged_starts', 1, 3)]:
        value = facts[name]
        if not value.is_integer() or not low <= value <= high:
            raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
        facts[name] = int(value)
    if not (
        0 < facts['training_rms'] and facts['omega'] > 0 and 0 <= facts['alpha'] <= 1
        and facts['beta'] == 1.0 - facts['alpha'] and facts['alpha'] + facts['beta'] == facts['persistence'] == 1.0
        and 1e-8 * (1 - 4e-15) <= facts['normalized_omega'] <= 10 * (1 + 4e-15)
        and facts['initial_backcast'] >= 0 and facts['initial_variance'] > 0
        and 0 <= facts['projected_gradient_norm'] <= 1e-7 and facts['minimum_free_curvature_pivot'] > 0
        and facts['optimizer_iterations'] <= facts['optimizer_evaluations'] and facts['variance_mae'] >= 0
        and (holdout > 0 or facts['variance_mae'] == facts['mean_gaussian_loss'] == 0)
    ):
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
    raw_omega = facts['normalized_omega'] * (facts['training_rms'] * facts['training_rms'])
    raw_initial = facts['omega'] + facts['initial_backcast']
    future = forecasts[holdout:]
    with np.errstate(over='ignore', under='ignore'):
        expected = future[0] + facts['omega'] * np.arange(future.size)
    if not (math.isclose(facts['omega'], raw_omega, rel_tol=2e-12)
            and math.isclose(facts['initial_variance'], raw_initial, rel_tol=2e-12)
            and np.allclose(future, expected, rtol=2e-12, atol=0.0)):
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
    parameters = {name: facts.pop(name) for name in ('omega', 'alpha', 'beta')}
    metrics = {name: facts.pop(name) for name in ('mean_gaussian_loss', 'variance_mae')}
    boundary_mask = facts.pop('boundary_mask')
    facts['active_bounds'] = [name for i, name in enumerate(_BOUNDARIES) if boundary_mask & (1 << i)]
    return parameters, facts, metrics


def run_igarch(frame: pd.DataFrame, *, time_col: str, outcome: str, forecast_periods: int = 1,
               holdout_periods: int = 0) -> dict[str, Any]:
    """Fit on the training prefix and forecast integrated conditional variance."""
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    time, observations = _series_columns(frame, time_col, outcome, lambda rows: validate_igarch_size(rows, holdout_periods))
    data = _prepare_series(time, observations, forecast_periods, holdout_periods)
    if not data.observed.all():
        missing = int(np.argmin(data.observed))
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE', f'IGARCH requires complete innovations; invalid row {missing}')
    library, engine = _loaded()
    fit = library.arboris_igarch_fit
    summary = np.full(len(_SUMMARY_FIELDS), np.nan, dtype=np.float64)
    forecasts = np.full(holdout_periods + forecast_periods, np.nan, dtype=np.float64)
    error_row = _SIZE(_NO_ROW)
    with _native_checkpoint() as poll:
        status = fit(data.values.ctypes.data_as(_DOUBLE), data.values.size, data.train_size, forecast_periods,
                     summary.ctypes.data_as(_DOUBLE), summary.size, forecasts.ctypes.data_as(_DOUBLE), forecasts.size,
                     ctypes.byref(error_row), poll)
    if status or error_row.value != _NO_ROW:
        invalid = ('IGARCH rejected the native input shape' if error_row.value == _NO_ROW
                   else f'IGARCH rejected the innovation at row {error_row.value}')
        code, message = {
            1: ('TIME_SERIES_BAD_INPUT', invalid),
            2: ('TIME_SERIES_NUMERIC_FAILURE', 'IGARCH exceeded its binary64 range'),
            3: ('TIME_SERIES_TOO_FEW_OBSERVATIONS', 'IGARCH requires at least 50 training rows'),
            4: ('TIME_SERIES_VOLATILITY_UNIDENTIFIED', 'IGARCH could not certify an identified conditional fit'),
            5: ('TIME_SERIES_VOLATILITY_NONCONVERGENCE', 'IGARCH could not certify a bounded likelihood optimum'),
            6: ('TIME_SERIES_SIZE_LIMIT', 'IGARCH exceeds the native observation or holdout bound'),
        }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native IGARCH did not return a verified fit'))
        raise TimeSeriesPackError(code, message)
    parameters, fit_receipt, metrics = _decode(summary, forecasts, holdout_periods)
    fit_receipt.update(n_observed=data.train_size, n_missing=0, long_run_variance=None,
                       long_run_variance_reason='integrated_persistence_one')
    holdout = None
    if holdout_periods:
        holdout = {
            'status': 'completed', 'training_steps': data.train_size, 'n_observed': holdout_periods,
            'origin_time': _time_label(data.time[data.train_size - 1]), 'metrics': metrics,
            'forecast': {'time': [_time_label(value) for value in data.time[data.train_size:]],
                         'variance': forecasts[:holdout_periods].tolist()},
        }
    return {
        'schema_version': 1, 'model': 'conditional_volatility', 'engine': engine, 'parameters': parameters,
        'fit': fit_receipt, 'holdout': holdout,
        'forecast': {'time': data.future, 'variance': forecasts[holdout_periods:].tolist()},
        'policy': {
            'family': 'igarch_1_1', 'time_col': time_col, 'outcome': outcome, 'cadence': data.cadence,
            'mean': 'fixed_zero', 'innovation_distribution': 'gaussian', 'estimation': 'conditional_gaussian_ml_training_only',
            'backcast': 'training_first_75_ewma_decay_0_94', 'scaling': 'training_rms', 'persistence': 1.0,
            'bounds': {'normalized_omega': [1e-8, 10.0], 'alpha': [0.0, 1.0], 'beta': 'one_minus_alpha'},
            'variance_units': 'squared_input_units', 'forecast_method': 'integrated_conditional_variance_linear_in_horizon',
            'holdout_method': 'rolling_one_step_fixed_training_parameters', 'missing': 'reject',
        },
    }
