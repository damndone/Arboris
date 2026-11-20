"""Verified Gaussian EGARCH with one-step conditional variance forecasts."""
from __future__ import annotations

import ctypes
import math
from typing import Any

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    _DOUBLE, _SIZE, _loaded, _native_checkpoint, _option_periods, _prepare_series, _series_columns, _time_label,
)
from .native_volatility import validate_volatility_size as validate_egarch_size


_SUMMARY_FIELDS = (
    'omega', 'alpha', 'gamma', 'beta', 'normalized_omega', 'initial_log_backcast', 'training_rms', 'log_likelihood',
    'standardized_residual_mean', 'standardized_residual_rms', 'optimizer_iterations', 'optimizer_evaluations',
    'projected_gradient_norm', 'minimum_free_curvature_pivot', 'boundary_mask', 'converged_starts',
    'mean_gaussian_loss', 'variance_mae', 'initial_log_variance',
)
_BOUNDARIES = ('omega_lower', 'omega_upper', 'alpha_lower', 'alpha_upper', 'gamma_lower', 'gamma_upper', 'beta_lower', 'beta_upper')
_NO_ROW = _SIZE(-1).value


def _decode(summary: np.ndarray, forecasts: np.ndarray, holdout: int):
    error = 'native EGARCH returned inconsistent fit or forecast evidence'
    if not np.isfinite(summary).all() or not np.isfinite(forecasts).all() or not (forecasts[:, 1] > 0).all():
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
    facts = dict(zip(_SUMMARY_FIELDS, map(float, summary), strict=True))
    for name, low, high in [('boundary_mask', 0, 255), ('optimizer_iterations', 0, 100),
                            ('optimizer_evaluations', 1, 1025), ('converged_starts', 1, 4)]:
        value = facts[name]
        if not value.is_integer() or not low <= value <= high:
            raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
        facts[name] = int(value)
    if not (
        0 < facts['training_rms'] and 0 <= facts['beta'] <= .995
        and -1 <= facts['alpha'] <= 1 and -1 <= facts['gamma'] <= 1 and -2 <= facts['normalized_omega'] <= 2
        and 0 <= facts['projected_gradient_norm'] <= 1e-7 and facts['minimum_free_curvature_pivot'] > 0
        and facts['optimizer_iterations'] <= facts['optimizer_evaluations'] and facts['variance_mae'] >= 0
        and (holdout > 0 or facts['variance_mae'] == facts['mean_gaussian_loss'] == 0)
    ):
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
    log_scale = 2 * math.log(facts['training_rms'])
    raw_omega = facts['normalized_omega'] + (1 - facts['beta']) * log_scale
    raw_initial = facts['omega'] + facts['beta'] * facts['initial_log_backcast']
    with np.errstate(over='ignore', under='ignore'):
        variance = np.exp(forecasts[:, 0])
    if not (math.isclose(facts['omega'], raw_omega, rel_tol=1e-12, abs_tol=1e-12)
            and math.isclose(facts['initial_log_variance'], raw_initial, rel_tol=1e-12, abs_tol=1e-12)
            and (np.abs(forecasts[:, 0] - log_scale) <= 40 + 1e-12).all()
            and np.allclose(variance, forecasts[:, 1], rtol=2e-12, atol=0.0)):
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', error)
    parameters = {name: facts.pop(name) for name in ('omega', 'alpha', 'gamma', 'beta')}
    metrics = {name: facts.pop(name) for name in ('mean_gaussian_loss', 'variance_mae')}
    boundary_mask = facts.pop('boundary_mask')
    facts['active_bounds'] = [name for i, name in enumerate(_BOUNDARIES) if boundary_mask & (1 << i)]
    return parameters, facts, metrics


def _forecast(times, values: np.ndarray) -> dict:
    return {'time': times, 'variance': values[:, 1].tolist(), 'log_variance': values[:, 0].tolist()}


def run_egarch(frame: pd.DataFrame, *, time_col: str, outcome: str, forecast_periods: int = 1,
               holdout_periods: int = 0) -> dict[str, Any]:
    """Fit on the training prefix and evaluate true conditional one-step variances."""
    _option_periods(forecast_periods, 'forecast_periods', 1, 1)
    time, observations = _series_columns(frame, time_col, outcome, lambda rows: validate_egarch_size(rows, holdout_periods))
    data = _prepare_series(time, observations, forecast_periods, holdout_periods)
    if not data.observed.all():
        missing = int(np.argmin(data.observed))
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE', f'EGARCH requires complete innovations; invalid row {missing}')
    library, engine = _loaded()
    summary = np.full(len(_SUMMARY_FIELDS), np.nan, dtype=np.float64)
    forecasts = np.full((holdout_periods + 1, 2), np.nan, dtype=np.float64)
    error_row = _SIZE(_NO_ROW)
    with _native_checkpoint() as poll:
        status = library.arboris_egarch_fit(
            data.values.ctypes.data_as(_DOUBLE), data.values.size, data.train_size, forecast_periods,
            summary.ctypes.data_as(_DOUBLE), summary.size, forecasts.ctypes.data_as(_DOUBLE), forecasts.size,
            ctypes.byref(error_row), poll,
        )
    if status or error_row.value != _NO_ROW:
        invalid = ('EGARCH rejected the native input shape' if error_row.value == _NO_ROW
                   else f'EGARCH rejected the innovation at row {error_row.value}')
        code, message = {
            1: ('TIME_SERIES_BAD_INPUT', invalid),
            2: ('TIME_SERIES_NUMERIC_FAILURE', 'EGARCH exceeded its binary64 or normalized log-variance range'),
            3: ('TIME_SERIES_TOO_FEW_OBSERVATIONS', 'EGARCH requires at least 50 training rows'),
            4: ('TIME_SERIES_VOLATILITY_UNIDENTIFIED', 'EGARCH could not certify an identified conditional fit'),
            5: ('TIME_SERIES_VOLATILITY_NONCONVERGENCE', 'EGARCH could not certify a bounded likelihood optimum'),
            6: ('TIME_SERIES_SIZE_LIMIT', 'EGARCH exceeds the native observation or holdout bound'),
        }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native EGARCH did not return a verified fit'))
        raise TimeSeriesPackError(code, message)
    parameters, fit_receipt, metrics = _decode(summary, forecasts, holdout_periods)
    fit_receipt.update(n_observed=data.train_size, n_missing=0)
    holdout = None
    if holdout_periods:
        holdout = {
            'status': 'completed', 'training_steps': data.train_size, 'n_observed': holdout_periods,
            'origin_time': _time_label(data.time[data.train_size - 1]), 'metrics': metrics,
            'forecast': _forecast([_time_label(value) for value in data.time[data.train_size:]], forecasts[:holdout_periods]),
        }
    return {
        'schema_version': 1, 'model': 'conditional_volatility', 'engine': engine, 'parameters': parameters,
        'fit': fit_receipt, 'holdout': holdout, 'forecast': _forecast(data.future, forecasts[holdout_periods:]),
        'policy': {
            'family': 'egarch_1_1', 'time_col': time_col, 'outcome': outcome, 'cadence': data.cadence,
            'mean': 'fixed_zero', 'innovation_distribution': 'gaussian', 'estimation': 'conditional_gaussian_ml_training_only',
            'backcast': 'training_first_75_ewma_decay_0_94_then_log', 'scaling': 'training_rms',
            'recursion': 'log_variance', 'gaussian_absolute_innovation_mean': math.sqrt(2 / math.pi),
            'bounds': {'normalized_omega': [-2.0, 2.0], 'alpha': [-1.0, 1.0], 'gamma': [-1.0, 1.0], 'beta': [0.0, .995],
                       'normalized_log_variance': [-40.0, 40.0]},
            'variance_units': 'squared_input_units', 'log_variance_units': 'natural_log_of_squared_input_units',
            'forecast_method': 'one_step_given_last_observed_innovation', 'forecast_periods': 1,
            'holdout_method': 'rolling_one_step_fixed_training_parameters', 'missing': 'reject',
        },
    }
