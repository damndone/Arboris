from __future__ import annotations

import ctypes
from typing import Any

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    _DOUBLE, _SIZE, _loaded, _native_checkpoint, _numeric_buffer, _option_periods, _series_columns, _time_grid,
)


_MIN_ROWS = 20
_MAX_ROWS = 20_000
_MAX_LAG = 20
_MIN_ADF_RESIDUAL_DF = 5


def validate_stationarity_size(rows: int, method: str, lag: int) -> None:
    if type(method) is not str or method not in ('adf', 'kpss'):
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'stationarity method must be adf or kpss')
    _option_periods(lag, 'lag', 0, _MAX_LAG)
    if rows > _MAX_ROWS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'fixed-lag stationarity supports at most {_MAX_ROWS} time rows')
    minimum = max(_MIN_ROWS, 2 * lag + 3 + _MIN_ADF_RESIDUAL_DF if method == 'adf' else lag + 1)
    if rows < minimum:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS',
                                  f'{method.upper()} with fixed lag {lag} requires at least {minimum} time rows')


def _check_status(status: int, index: int, outcome: str) -> None:
    if not status:
        return
    code, message = {
        2: ('TIME_SERIES_NUMERIC_FAILURE', 'fixed-lag stationarity statistic exceeded its numerical range'),
        3: ('TIME_SERIES_NON_FINITE_VALUE', f'outcome {outcome!r} is missing or non-finite at row {index}'),
        4: ('TIME_SERIES_STATIONARITY_RANK', f'ADF lag design is rank deficient at pivot {index}'),
        6: ('TIME_SERIES_CONSTANT_SERIES', 'fixed-lag stationarity requires a nonconstant outcome'),
        7: ('TIME_SERIES_STATIONARITY_VARIANCE', 'fixed-lag stationarity statistic has unresolved residual variance'),
    }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native fixed-lag stationarity rejected its inputs'))
    raise TimeSeriesPackError(code, message)


def run_stationarity_statistic(
    frame: pd.DataFrame, *, time_col: str, outcome: str, method: str, lag: int,
) -> dict[str, Any]:
    time, observations = _series_columns(frame, time_col, outcome,
                                         lambda rows: validate_stationarity_size(rows, method, lag))
    _, _, cadence = _time_grid(time, 0)
    values = _numeric_buffer(observations)
    library, engine = _loaded()
    adf = method == 'adf'
    output = np.empty(3 if adf else 1, dtype=np.float64)
    error_index = _SIZE()
    with _native_checkpoint() as poll:
        status = library.arboris_stationarity_constant_fixed(
            values.ctypes.data_as(_DOUBLE), len(values), 0 if adf else 1, lag,
            output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error_index), poll,
        )
    _check_status(status, error_index.value, outcome)
    result = {
        'schema_version': 1, 'model': 'stationarity_statistic', 'engine': engine,
        'method': method, 'statistic': float(output[0]), 'statistic_name': 'adf_tau2' if adf else 'kpss_lm',
        'null_hypothesis': 'unit_root' if adf else 'level_stationarity',
        'evidence_scope': 'statistic_only', 'scientific_validity': 'not_certified',
        'n_observations': len(values), 'n_effective': len(values) - lag - 1 if adf else len(values),
        'policy': {
            'time_col': time_col, 'outcome': outcome, 'cadence': cadence, 'deterministic': 'constant',
            'lag': lag, 'lag_policy': 'fixed', 'lag_definition': 'lagged_differences' if adf else 'bartlett_truncation',
            'missing': 'reject',
        },
    }
    if adf:
        result['adf_regression'] = {
            'lagged_level_coefficient': float(output[1]), 'lagged_level_std_error': float(output[2]),
            'residual_df': len(values) - 2 * lag - 3,
        }
    return result
