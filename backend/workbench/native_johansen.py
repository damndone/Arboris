from __future__ import annotations

import ctypes
from typing import Any

import numpy as np
import pandas as pd

from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_time_series import (
    _DOUBLE, _SIZE, _loaded, _native_checkpoint, _numeric_design, _option_periods, _series_columns, _time_grid,
    _time_label,
)


_MIN_SERIES = 3
_MAX_SERIES = 4
_MAX_DIFFERENCE_LAGS = 4
_MAX_ROWS = 20_000
_RANK_BLOCKS = ('lagged differences', 'residualized levels and constant', 'residualized differences')


def validate_johansen_size(rows: int, columns: int, difference_lags: int) -> None:
    _option_periods(columns, 'series count', _MIN_SERIES, _MAX_SERIES)
    _option_periods(difference_lags, 'difference_lags', 1, _MAX_DIFFERENCE_LAGS)
    if rows > _MAX_ROWS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'Johansen rank diagnostics support at most {_MAX_ROWS} time rows')
    levels_order = difference_lags + 1
    design_width = columns * difference_lags + 2 * columns + 1
    minimum = levels_order + design_width + 1
    if rows < minimum:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', f'Johansen rank diagnostics require at least {minimum} time rows')


def _check_status(status: int, index: int, names: list[str]) -> None:
    if status == 0:
        return
    if status == 3:
        row, series = divmod(index, len(names))
        raise TimeSeriesPackError(
            'TIME_SERIES_NON_FINITE_VALUE', f'Johansen requires complete finite values; {names[series]!r} is invalid at row {row}',
        )
    if status == 4:
        stage, pivot = divmod(index, 16)
        if stage < len(_RANK_BLOCKS):
            raise TimeSeriesPackError(
                'TIME_SERIES_JOHANSEN_RANK_DEFICIENT', f'Johansen {_RANK_BLOCKS[stage]} are rank deficient at pivot {pivot}',
            )
    code, message = {
        2: ('TIME_SERIES_NUMERIC_FAILURE', 'Johansen canonical roots or statistics exceeded their numerical range'),
        7: ('TIME_SERIES_JOHANSEN_CANONICAL_UNRESOLVED', 'the largest Johansen canonical root is numerically unresolved at one'),
    }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native Johansen rank diagnostics rejected their inputs'))
    raise TimeSeriesPackError(code, message)


def run_johansen_rank(
    frame: pd.DataFrame, *, time_col: str, series_columns: list[str], difference_lags: int = 1,
) -> dict[str, Any]:
    if not isinstance(series_columns, (list, tuple)) or not _MIN_SERIES <= len(series_columns) <= _MAX_SERIES:
        raise TimeSeriesPackError('TIME_SERIES_BAD_INPUT', 'choose three or four distinct Johansen series')
    names = list(series_columns)
    time_series, _ = _series_columns(frame, time_col, names[0], lambda rows: validate_johansen_size(
        rows, len(names), difference_lags))
    levels_order = difference_lags + 1
    time, _, cadence = _time_grid(time_series, 0)
    if cadence.get('input') == 'iso8601':
        start_time, end_time = time_series.iloc[levels_order], time_series.iloc[-1]
    else:
        start_time, end_time = str(_time_label(time[levels_order])), str(_time_label(time[-1]))
    values = _numeric_design(frame, names, excluded=(time_col,))
    library, engine = _loaded()
    output = np.empty(3 * len(names), dtype=np.float64)
    error_index = _SIZE()
    with _native_checkpoint() as poll:
        status = library.arboris_johansen_rank(
            values.ctypes.data_as(_DOUBLE), values.size, len(values), len(names), difference_lags,
            output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error_index), poll,
        )
    _check_status(status, error_index.value, names)
    eigenvalues, trace, maximum = np.split(output, 3)
    return {
        'schema_version': 1, 'model': 'johansen_rank', 'engine': engine,
        'n_observations': len(values), 'n_effective': len(values) - levels_order,
        'sample': {'start_time': start_time, 'end_time': end_time},
        'ranks': list(range(len(names))), 'canonical_eigenvalues': eigenvalues.tolist(),
        'trace_statistics': trace.tolist(), 'max_eigenvalue_statistics': maximum.tolist(),
        'evidence_scope': 'statistics_only', 'rank_criterion': 'uncalibrated', 'scientific_validity': 'not_certified',
        'policy': {
            'time_col': time_col, 'series_columns': names, 'difference_lags': difference_lags,
            'levels_order': levels_order, 'deterministic': 'restricted_constant', 'cadence': cadence, 'missing': 'reject',
        },
    }
