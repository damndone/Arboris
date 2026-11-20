from __future__ import annotations

import ctypes
from typing import Any

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    MAX_FORECAST_PERIODS, MAX_HOLDOUT_PERIODS, _DOUBLE, _SIZE, _loaded, _native_checkpoint, _option_periods,
    _prepare_series, _series_columns, _time_label,
)


_FAMILIES = {'arch_1': 0, 'garch_1_1': 1, 'gjr_garch_1_1_1': 2}
_SUMMARY_FIELDS = (
    'omega', 'alpha', 'gamma', 'beta', 'persistence', 'long_run_variance', 'initial_backcast', 'training_rms',
    'log_likelihood', 'standardized_residual_mean', 'standardized_residual_rms', 'optimizer_iterations',
    'optimizer_evaluations', 'projected_gradient_norm', 'minimum_free_curvature_pivot', 'boundary_mask',
    'converged_starts', 'mean_gaussian_loss', 'variance_mae',
)
_BOUNDARIES = ('omega_lower', 'omega_upper', 'positive_shock_zero', 'negative_shock_zero', 'beta_zero', 'persistence_cap')


def validate_volatility_size(rows: int, holdout_periods: int) -> None:
    _option_periods(holdout_periods, 'holdout_periods', 0, MAX_HOLDOUT_PERIODS)
    if rows > 20_000:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', 'volatility models support at most 20000 time rows')
    if rows - holdout_periods < 50:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', 'volatility models require at least 50 training rows')


def run_volatility(
    frame: pd.DataFrame, *, time_col: str, outcome: str, family: str = 'garch_1_1', forecast_periods: int = 1,
    holdout_periods: int = 0,
) -> dict[str, Any]:
    if type(family) is not str or family not in _FAMILIES:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'choose ARCH(1), GARCH(1,1) or GJR-GARCH(1,1,1)')
    time, observations = _series_columns(frame, time_col, outcome, lambda rows: validate_volatility_size(rows, holdout_periods))
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    data = _prepare_series(time, observations, forecast_periods, holdout_periods)
    if not data.observed.all():
        missing = int(np.argmin(data.observed))
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE', f'volatility models require complete innovations; invalid row {missing}')
    library, engine = _loaded()
    summary = np.empty(len(_SUMMARY_FIELDS), dtype=np.float64)
    variances = np.empty(holdout_periods + forecast_periods, dtype=np.float64)
    error_index = _SIZE()
    with _native_checkpoint() as poll:
        status = library.arboris_volatility_fit(
            data.values.ctypes.data_as(_DOUBLE), data.values.size, data.train_size, _FAMILIES[family], forecast_periods,
            summary.ctypes.data_as(_DOUBLE), summary.size, variances.ctypes.data_as(_DOUBLE), variances.size,
            ctypes.byref(error_index), poll,
        )
    if status:
        code, message = {
            1: ('TIME_SERIES_BAD_INPUT', f'volatility fit rejected the inputs at position {error_index.value}'),
            2: ('TIME_SERIES_NUMERIC_FAILURE', 'volatility fit exceeded its numerical range'),
            3: ('TIME_SERIES_TOO_FEW_OBSERVATIONS', 'volatility models require at least 50 training rows'),
            4: ('TIME_SERIES_VOLATILITY_UNIDENTIFIED', 'volatility fit requires nondegenerate innovations'),
            5: ('TIME_SERIES_VOLATILITY_NONCONVERGENCE', 'volatility fit did not certify convergence'),
            6: ('TIME_SERIES_SIZE_LIMIT', 'volatility specification exceeds the native size limit'),
        }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native volatility fit did not produce a verified result'))
        raise TimeSeriesPackError(code, message)
    facts = dict(zip(_SUMMARY_FIELDS, map(float, summary), strict=True))
    parameters = {name: facts.pop(name) for name in ('omega', 'alpha', 'gamma', 'beta')}
    boundary_mask = int(facts.pop('boundary_mask'))
    metrics = {name: facts.pop(name) for name in ('mean_gaussian_loss', 'variance_mae')}
    for name in ('optimizer_iterations', 'optimizer_evaluations', 'converged_starts'):
        facts[name] = int(facts[name])
    fit = {**facts, 'n_observed': data.train_size, 'n_missing': 0,
           'active_bounds': [name for index, name in enumerate(_BOUNDARIES) if boundary_mask & (1 << index)]}
    holdout = None
    if holdout_periods:
        holdout = {
            'status': 'completed', 'training_steps': data.train_size, 'n_observed': holdout_periods,
            'origin_time': _time_label(data.time[data.train_size - 1]), 'metrics': metrics,
            'forecast': {'time': [_time_label(value) for value in data.time[data.train_size:]],
                         'variance': variances[:holdout_periods].tolist()},
        }
    return {
        'schema_version': 1, 'model': 'conditional_volatility', 'engine': engine, 'parameters': parameters, 'fit': fit,
        'policy': {'family': family, 'time_col': time_col, 'outcome': outcome, 'cadence': data.cadence, 'mean': 'fixed_zero',
                   'estimation': 'conditional_gaussian_ml_training_only', 'persistence_limit': 0.999,
                   'holdout_method': 'rolling_one_step_fixed_training_parameters', 'missing': 'reject'},
        'forecast': {'time': data.future, 'variance': variances[holdout_periods:].tolist()},
        'holdout': holdout,
    }
