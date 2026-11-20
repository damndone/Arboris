from __future__ import annotations

import ctypes
from numbers import Integral

import numpy as np
import pandas as pd

from .native_quant_replay import (
    MAX_ASSETS, MAX_PERIODS, MAX_RISK_WINDOW, QuantReplayError, _DOUBLE, _I64, _NO_ROW, _SIZE, _loaded,
    _numeric_matrix, _time_label, _time_matrix, _valid_name,
)
from .native_time_series import _native_checkpoint


_FIELDS = ('sample_variance', 'objective_variance', 'sample_rank', 'relative_rank_threshold',
           'scaled_sample_min_eigenvalue', 'scaled_objective_min_eigenvalue', 'diagonal_scale', 'iterations',
           'normalized_kkt_residual', 'weight_sum_error')


def _invalid(message: str) -> QuantReplayError:
    return QuantReplayError('QUANT_MIN_VARIANCE_INVALID_INPUT', message)


def validate_min_variance_window(rows: int, window: int, end_period: int) -> int:
    if not 2 <= rows <= MAX_PERIODS:
        raise _invalid(f'use 2 to {MAX_PERIODS} aligned observation rows')
    if isinstance(end_period, (bool, np.bool_)) or not isinstance(end_period, Integral) or not 0 <= end_period <= rows:
        raise _invalid('end_period must be zero for the final row or a completed period in the input')
    completed = int(end_period or rows)
    if isinstance(window, (bool, np.bool_)) or not isinstance(window, Integral) or not 2 <= window <= min(MAX_RISK_WINDOW, completed):
        raise _invalid('use a trailing window of 2 to 2048 observations ending at the completed period')
    return completed


def run_min_variance(
    frame: pd.DataFrame, *, time_col: str, return_columns: list[str], window: int,
    end_period: int = 0, shrinkage_bps: int = 0,
):
    if not isinstance(frame, pd.DataFrame):
        raise _invalid('select a DataFrame with an aligned return window')
    completed = validate_min_variance_window(len(frame), window, end_period)
    if not isinstance(return_columns, (list, tuple)) or not 2 <= len(return_columns) <= MAX_ASSETS:
        raise _invalid(f'choose 2 to {MAX_ASSETS} ordered return columns')
    columns = tuple(return_columns)
    names = (time_col, *columns)
    if (not all(_valid_name(name) for name in names) or len(set(names)) != len(names)
            or not frame.columns.is_unique or not all(name in frame.columns for name in names)):
        raise _invalid('choose distinct existing time and return columns')
    if isinstance(shrinkage_bps, (bool, np.bool_)) or not isinstance(shrinkage_bps, Integral) or not 0 <= shrinkage_bps <= 10_000:
        raise _invalid('shrinkage_bps must be an integer from 0 to 10000')
    frame_window = frame.iloc[completed - int(window):completed]
    times, clock = _time_matrix(frame_window, (time_col,), invalid=_invalid)
    returns = _numeric_matrix(frame_window, columns, invalid=_invalid)
    library, engine = _loaded()
    width = len(columns)
    output = np.empty(width + 2 * width**2 + len(_FIELDS), dtype=np.float64)
    error_row = _SIZE(_NO_ROW)
    with _native_checkpoint() as poll:
        status = library.arboris_quant_min_variance(
            int(window), width, int(shrinkage_bps), times.ctypes.data_as(_I64), times.size,
            returns.ctypes.data_as(_DOUBLE), returns.size, output.ctypes.data_as(_DOUBLE), output.size,
            ctypes.byref(error_row), poll,
        )
    if status or error_row.value != _NO_ROW:
        suffix, message = {
            2: ('TIME_ORDER', 'completed-window times must be strictly increasing'),
            4: ('NON_FINITE_RETURN', 'each asset needs a complete finite return in the selected window'),
            7: ('NUMERIC_FAILURE', 'covariance or weights exceeded the supported numeric range'),
            9: ('UNIDENTIFIED', 'covariance is degenerate at the requested shrinkage'),
            10: ('NONCONVERGENCE', 'the long-only optimum did not pass the numerical certificate'),
        }.get(status, ('NATIVE_INVALID', 'the verified portfolio engine did not produce a valid result'))
        row = completed - int(window) + error_row.value if error_row.value < window else None
        raise QuantReplayError(f'QUANT_MIN_VARIANCE_{suffix}', message, row=row)
    covariance_end = width + width**2
    sample_covariance = output[width:covariance_end].reshape(width, width)
    objective_covariance = output[covariance_end:covariance_end + width**2].reshape(width, width)
    metrics = dict(zip(_FIELDS, map(float, output[-len(_FIELDS):]), strict=True))
    for name in ('sample_rank', 'iterations'):
        metrics[name] = int(metrics[name])
    return {
        'contract_version': 'quant_min_variance_v1', 'engine': engine,
        'inputs': {'time_col': time_col, 'return_columns': list(columns), 'window': int(window),
                   'end_period': completed, 'asset_count': width, 'shrinkage_bps': int(shrinkage_bps)},
        'assumptions': {'scope': 'offline_historical_allocation', 'objective': 'long_only_minimum_variance',
                        'shrinkage_target': 'mean_sample_variance_identity', 'sample_covariance_divisor': 'window_minus_one',
                        'annualized': False, 'time_basis': 'supplied_availability_order', 'source_vintage_verified': False},
        'metrics': metrics,
        'allocation': dict(zip(columns, map(float, output[:width]), strict=True)),
        'sample_covariance': {'columns': list(columns), 'matrix': sample_covariance.tolist()},
        'objective_covariance': {'columns': list(columns), 'matrix': objective_covariance.tolist()},
        'cutoff': {'first_period': completed - int(window) + 1, 'last_period': completed,
                   'as_of_time': _time_label(int(times[-1, 0]), clock)},
    }
