"""Verified Rust time-series diagnostics, local-level filtering and forecasts."""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import math
from numbers import Real
from pathlib import Path
from statistics import NormalDist
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd

from .checks.ar_cancellation import check_cancellation, current_check
from .engine.packs.time_series.errors import TimeSeriesPackError
from .native_build import NativeBuildError, artifact_names, default_output, manifest_path, verify_build
from .native_time_series_abi import CHECKPOINT as _CHECKPOINT, DOUBLE as _DOUBLE, SIZE as _SIZE, bind_time_series_symbols


ABI_VERSION = 1
MAX_OBSERVATIONS = 100_000
MAX_FORECAST_PERIODS = 200
MAX_HOLDOUT_PERIODS = 200
MAX_TRACE_ROWS = 512
MAX_CORRELOGRAM_LAG = 200
MAX_ARIMA_ROWS = 20_000
MAX_ARIMA_WHITENESS_LAG = 12
MAX_SARIMA_ROWS = 2_000
_MAX_LIKELIHOOD_WORK = 180_000_000
_STATIONARY_COVARIANCE_MAX_ITERATIONS = 32
_MAX_REGRESSION_DESIGN_COLUMNS = 5
_MAX_SAFE_INTEGER = 2**53 - 1
_MODULE = Path(__file__).resolve().parents[2] / 'native/time_series'
_BUILD_COMMAND = 'native/time_series/build.py'
_LOAD_LOCK = Lock()
_ARIMA_TRENDS = {'none': 0, 'mean': 1, 'drift': 2}
_TRACE_COLUMNS = (
    'predicted_mean', 'predicted_variance', 'filtered_mean', 'filtered_variance',
    'innovation', 'innovation_variance', 'log_likelihood',
)
_CALENDAR_OFFSETS = (
    pd.offsets.MonthBegin, pd.offsets.MonthEnd, pd.offsets.QuarterBegin, pd.offsets.QuarterEnd,
    pd.offsets.YearBegin, pd.offsets.YearEnd,
)
_ISO_DATE = r'[0-9]{4}-[0-9]{2}-[0-9]{2}'
_ISO_DATETIME = _ISO_DATE + r'[T ](?:[01][0-9]|2[0-3]):[0-5][0-9](?::[0-5][0-9](?:\.[0-9]{1,9})?)?'
_ISO_OFFSET = r'Z|[+-][0-9]{2}:[0-9]{2}'


def _file_identity(path: Path) -> tuple[int, ...]:
    stat = path.stat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=1)
def _load_once():
    out = default_output(_MODULE)
    path = out / artifact_names(_MODULE)[0]
    record_path = manifest_path(out)
    if not any(item.exists() or item.is_symlink() for item in (path, record_path)):
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_BUILD_MISSING', f'build offline with {_BUILD_COMMAND}')
    try:
        identity = _file_identity(path)
        manifest = verify_build(_MODULE, out)
        if _file_identity(path) != identity:
            raise NativeBuildError('the binary changed during verification')
    except (OSError, NativeBuildError) as error:
        raise TimeSeriesPackError(
            'TIME_SERIES_NATIVE_BUILD_INVALID', f'build identity could not be verified. Rebuild offline with {_BUILD_COMMAND}',
        ) from error
    try:
        library = ctypes.CDLL(str(path))
        library.arboris_time_series_abi.argtypes = []
        library.arboris_time_series_abi.restype = ctypes.c_int32
        if library.arboris_time_series_abi() != ABI_VERSION:
            raise NativeBuildError('time-series ABI mismatch')
        bind_time_series_symbols(library)
        if _file_identity(path) != identity:
            raise NativeBuildError('the binary changed while loading')
    except (OSError, AttributeError, NativeBuildError) as error:
        # dlopen can leave the previous image mapped. Retrying that path after
        # a rebuild could otherwise attest a different binary than the handle.
        return error
    engine = {'name': 'arboris_time_series', 'abi_version': ABI_VERSION}
    engine.update({key: manifest[key] for key in ('build_identity_sha256', 'binary_sha256', 'source_sha256')})
    return library, engine, path, identity


def _loaded():
    with _LOAD_LOCK:
        loaded = _load_once()
    try:
        if isinstance(loaded, Exception):
            raise loaded
        library, engine, path, identity = loaded
        if _file_identity(path) != identity:
            raise NativeBuildError('the loaded time-series binary has changed')
    except (OSError, AttributeError, NativeBuildError) as error:
        raise TimeSeriesPackError(
            'TIME_SERIES_NATIVE_BUILD_INVALID',
            f'loaded library failed ABI or file-identity validation. Rebuild offline with {_BUILD_COMMAND} and restart the application',
        ) from error
    return library, engine.copy()


def _real_numeric(dtype) -> bool:
    return (pd.api.types.is_numeric_dtype(dtype)
            and not pd.api.types.is_bool_dtype(dtype)
            and not pd.api.types.is_complex_dtype(dtype))


def _option_number(value: Real, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', f'{name} must be a finite number')
    try:
        result = float(value)
    except OverflowError:
        result = math.inf
    if not math.isfinite(result):
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', f'{name} must be a finite number')
    return result


def _option_periods(value: int, name: str, minimum: int, maximum: int) -> None:
    if type(value) is not int or not minimum <= value <= maximum:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', f'{name} must be an integer in [{minimum}, {maximum}]')


def _numeric_time_grid(time: pd.Series, horizon: int):
    raw = time.to_numpy(na_value=np.nan)
    if not np.isfinite(raw).all():
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_TIME', 'numeric time values must be finite')
    if np.any(raw[1:] <= raw[:-1]):
        raise TimeSeriesPackError('TIME_SERIES_ORDER_INVALID', 'time must already be strictly increasing and unique')
    if pd.api.types.is_integer_dtype(time.dtype):
        if int(raw[0]) < -_MAX_SAFE_INTEGER or int(raw[-1]) > _MAX_SAFE_INTEGER:
            raise TimeSeriesPackError('TIME_SERIES_INVALID_TIME', 'integer time is outside the exact JSON integer range')
        values = raw.astype(np.int64, copy=False)
        differences = np.diff(values)
        step = int(differences[0])
        if not np.all(differences == step):
            raise TimeSeriesPackError('TIME_SERIES_IRREGULAR_TIME', 'integer time steps must be equal')
        future = [int(values[-1]) + step * index for index in range(1, horizon + 1)]
        if future and future[-1] > _MAX_SAFE_INTEGER:
            raise TimeSeriesPackError('TIME_SERIES_INVALID_TIME', 'future time is outside the exact JSON integer range')
        return values, future, {'kind': 'numeric', 'step': step}

    with np.errstate(over='ignore', invalid='ignore'):
        values = raw.astype(np.float64, copy=False)
        differences = np.diff(values)
        span = float(values[-1]) - float(values[0])
        step = span / (len(values) - 1)
    if not math.isfinite(step) or step <= 0 or not np.isfinite(differences).all() or np.any(differences <= 0):
        raise TimeSeriesPackError('TIME_SERIES_INVALID_TIME', 'numeric time steps must be representable in float64')
    # Roundoff tolerance uses the source precision, capped at 1% of one step.
    magnitude = max(abs(float(values[0])), abs(float(values[-1])))
    roundoff = (4 * float(np.finfo(raw.dtype).eps)) * magnitude
    tolerance = min(step * 0.01, max(step * 1e-10, roundoff))
    expected = float(values[0]) + step * np.arange(len(values), dtype=np.float64)
    if not np.all(np.abs(values - expected) <= tolerance):
        raise TimeSeriesPackError('TIME_SERIES_IRREGULAR_TIME', 'numeric time steps must be equal within roundoff')
    future = [float(values[-1]) + step * index for index in range(1, horizon + 1)]
    if future and (not all(map(math.isfinite, future)) or any(
        right <= left for left, right in zip([float(values[-1]), *future[:-1]], future, strict=True)
    )):
        raise TimeSeriesPackError('TIME_SERIES_INVALID_TIME', 'future time cannot be represented as increasing float64 values')
    return values, future, {'kind': 'numeric', 'step': step}


def _datetime_time_grid(time: pd.Series, horizon: int):
    try:
        values = pd.DatetimeIndex(time)
        if not values.is_monotonic_increasing or not values.is_unique:
            raise TimeSeriesPackError('TIME_SERIES_ORDER_INVALID', 'time must already be strictly increasing and unique')
        frequency = pd.infer_freq(values) if len(values) >= 3 else None
        offset = pd.tseries.frequencies.to_offset(frequency) if frequency else None
        if isinstance(offset, _CALENDAR_OFFSETS):
            expected = pd.date_range(start=values[0], periods=len(values), freq=offset)
            if np.all(values == expected):
                future = pd.date_range(start=values[-1], periods=horizon + 1, freq=offset)[1:]
                return values, [item.isoformat() for item in future], {'kind': 'calendar', 'offset': offset.freqstr}
        differences = values[1:] - values[:-1]
        step = differences[0]
        if not np.all(differences == step):
            raise TimeSeriesPackError(
                'TIME_SERIES_IRREGULAR_TIME', 'datetime time must follow a fixed interval or a supported calendar cadence',
            )
        future = [values[-1] + step * index for index in range(1, horizon + 1)]
        return values, [item.isoformat() for item in future], {'kind': 'datetime', 'step': step.isoformat()}
    except TimeSeriesPackError:
        raise
    except (ValueError, OverflowError) as error:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_TIME', 'datetime cadence or future time is out of range') from error


def _iso_time_grid(time: pd.Series, horizon: int):
    if not (time.str.fullmatch(_ISO_DATE).all() or time.str.fullmatch(_ISO_DATETIME).all()):
        if not time.str.fullmatch(f'{_ISO_DATETIME}(?:{_ISO_OFFSET})').all():
            raise TimeSeriesPackError('TIME_SERIES_INVALID_TIME', 'use uniformly ISO dates or ISO timestamps')
        # Preserve the recorded wall clock for calendar periods. An offset
        # change in text cannot identify a time zone for future periods.
        offsets = time.str.extract(f'({_ISO_OFFSET})$', expand=False).replace('Z', '+00:00')
        if offsets.nunique() != 1:
            raise TimeSeriesPackError('TIME_SERIES_INVALID_TIME', 'ISO timestamps must share one offset or use a typed time zone')
    try:
        dates = pd.to_datetime(time, format='ISO8601')
    except (TypeError, ValueError, OverflowError) as error:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_TIME', 'ISO time contains an invalid date or timestamp') from error
    values, future, cadence = _datetime_time_grid(dates, horizon)
    return values, future, cadence | {'input': 'iso8601'}


def _time_grid(time: pd.Series, horizon: int):
    if time.isna().any():
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_TIME', 'time cannot be missing')
    if _real_numeric(time.dtype):
        return _numeric_time_grid(time, horizon)
    if pd.api.types.is_datetime64_any_dtype(time.dtype):
        return _datetime_time_grid(time, horizon)
    if pd.api.types.infer_dtype(time, skipna=False) == 'string':
        return _iso_time_grid(time, horizon)
    raise TimeSeriesPackError('TIME_SERIES_INVALID_TIME', 'time must be real numeric, datetime-typed or uniformly ISO text')


def _time_label(value):
    return value.isoformat() if isinstance(value, pd.Timestamp) else value.item()


def _filter(values: np.ndarray, q: float, r: float, mean: float, variance: float):
    library, engine = _loaded()
    check_cancellation()
    rows = np.empty((len(values), len(_TRACE_COLUMNS)), dtype=np.float64)
    total = ctypes.c_double()
    error_index = _SIZE()
    status = library.arboris_local_level(
        values.ctypes.data_as(_DOUBLE), len(values), q, r, mean, variance,
        rows.ctypes.data_as(_DOUBLE), rows.size, ctypes.byref(total), ctypes.byref(error_index),
    )
    check_cancellation()
    if status == 2:
        raise TimeSeriesPackError('TIME_SERIES_NUMERIC_FAILURE', f'non-finite filtering result at row {error_index.value}')
    if status:
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native local-level filter rejected its inputs')
    return rows, total.value, engine


def _fit_scale(values: np.ndarray, ratio: float, mean: float, prior_ratio: float):
    library, _ = _loaded()
    check_cancellation()
    estimate = np.empty(4, dtype=np.float64)
    error_index = _SIZE()
    status = library.arboris_local_level_fit_scale(
        values.ctypes.data_as(_DOUBLE), len(values), ratio, mean, prior_ratio,
        estimate.ctypes.data_as(_DOUBLE), estimate.size, ctypes.byref(error_index),
    )
    check_cancellation()
    if status:
        errors = {
            2: ('TIME_SERIES_NUMERIC_FAILURE', f'non-finite scale calculation at row {error_index.value}'),
            3: ('TIME_SERIES_INSUFFICIENT_TRAINING_OBSERVATIONS', 'scale fitting requires at least two observed training points'),
            4: ('TIME_SERIES_SCALE_UNIDENTIFIED', 'all training innovations are zero; there is no positive likelihood maximum'),
            5: ('TIME_SERIES_NUMERIC_FAILURE', 'fitted scale is outside the positive normal float64 range'),
            6: ('TIME_SERIES_NUMERIC_FAILURE', 'a fitted process or prior variance overflowed or rounded to zero'),
        }
        reason, message = errors.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native scale fitter rejected its inputs'))
        raise TimeSeriesPackError(reason, message)
    return tuple(map(float, estimate))


def _forecast(state, future, q: float, r: float, critical: float):
    mean, variance = map(float, state[2:4])
    output = {key: [] for key in ('steps', 'time', 'mean', 'state_variance', 'observation_variance', 'lower', 'upper')}
    for index, time in enumerate(future, start=1):
        state_variance = variance + index * q
        observation_variance = state_variance + r
        margin = critical * math.sqrt(observation_variance)
        lower, upper = mean - margin, mean + margin
        if not all(map(math.isfinite, (observation_variance, lower, upper))):
            raise TimeSeriesPackError('TIME_SERIES_NUMERIC_FAILURE', f'non-finite forecast at horizon {index}')
        for column, value in zip(output.values(), (index, time, mean, state_variance, observation_variance, lower, upper), strict=True):
            column.append(value)
    return output


def _error_scores(actual: np.ndarray, prediction) -> tuple[float, float]:
    with np.errstate(over='ignore'):
        errors = np.abs(actual - prediction)
    scale = float(np.max(errors))
    if not math.isfinite(scale):
        raise TimeSeriesPackError('TIME_SERIES_NUMERIC_FAILURE', 'non-finite holdout forecast error')
    if scale == 0:
        return 0.0, 0.0
    scaled = errors / scale
    return float(scaled.mean()) * scale, math.sqrt(float(np.square(scaled).mean())) * scale


def _holdout_metrics(values, observed, train_size: int, forecast, *, seasonal_period: int | None = None):
    retained = observed[train_size:]
    count = int(np.count_nonzero(retained))
    metrics = None
    if count:
        actual = values[train_size:][retained]
        lower, upper = np.asarray(forecast['lower'])[retained], np.asarray(forecast['upper'])[retained]
        if seasonal_period is None:
            naive_mean = float(values[:train_size][observed[:train_size]][-1])
        else:
            training_rows = np.flatnonzero(observed[:train_size])
            last_by_phase = np.full(seasonal_period, -1, dtype=np.intp)
            np.maximum.at(last_by_phase, training_rows % seasonal_period, training_rows)
            baseline_rows = last_by_phase[(train_size + np.flatnonzero(retained)) % seasonal_period]
            naive_mean = values[baseline_rows] if (baseline_rows >= 0).all() else None
        mae, rmse = _error_scores(actual, np.asarray(forecast['mean'])[retained])
        naive_mae, naive_rmse = (None, None) if naive_mean is None else _error_scores(actual, naive_mean)
        metrics = {'mae': mae, 'rmse': rmse, 'interval_coverage': float(np.mean((lower <= actual) & (actual <= upper))),
                   'naive_mae': naive_mae, 'naive_rmse': naive_rmse}
    return count, metrics


def _holdout(values, observed, rows, time, train_size: int, q: float, r: float, critical: float):
    forecast = _forecast(rows[train_size - 1], [_time_label(value) for value in time[train_size:]], q, r, critical)
    count, metrics = _holdout_metrics(values, observed, train_size, forecast)
    return {
        'status': 'completed' if count else 'no_observed_holdout', 'training_steps': train_size,
        'origin_time': _time_label(time[train_size - 1]), 'n_observed': count, 'n_missing': len(values) - train_size - count,
        'forecast': forecast, 'metrics': metrics,
    }


def validate_local_level_rows(rows: int) -> None:
    if rows < 2:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', 'at least two time rows are required')
    if rows > MAX_OBSERVATIONS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'local-level filtering supports at most {MAX_OBSERVATIONS} time rows')


def validate_local_level_holdout(rows: int, holdout_periods: int, *, fit_scale: bool = False) -> None:
    _option_periods(holdout_periods, 'holdout_periods', 0, min(MAX_HOLDOUT_PERIODS, rows - 1))
    if fit_scale and rows - holdout_periods < 2:
        raise TimeSeriesPackError(
            'TIME_SERIES_INSUFFICIENT_TRAINING_OBSERVATIONS',
            'holdout_periods must leave at least two training rows to fit the common scale',
        )


def _series_columns(frame: pd.DataFrame, time_col: str, outcome: str, validate_rows):
    check_cancellation()
    if not isinstance(frame, pd.DataFrame) or any(type(name) is not str or not name for name in (time_col, outcome)):
        raise TimeSeriesPackError('TIME_SERIES_BAD_INPUT', 'provide a DataFrame and distinct time/outcome column names')
    if time_col == outcome:
        raise TimeSeriesPackError('TIME_SERIES_BAD_INPUT', 'time and outcome columns must be distinct')
    if time_col not in frame.columns or outcome not in frame.columns:
        raise TimeSeriesPackError('TIME_SERIES_MISSING_COLUMN', 'time or outcome column is missing')
    validate_rows(len(frame))
    time_series, outcome_series = frame[time_col], frame[outcome]
    if not isinstance(time_series, pd.Series) or not isinstance(outcome_series, pd.Series):
        raise TimeSeriesPackError('TIME_SERIES_BAD_INPUT', 'time and outcome names must select unique columns')
    if not _real_numeric(outcome_series.dtype):
        raise TimeSeriesPackError('TIME_SERIES_NON_NUMERIC_VALUE', 'outcome must be real numeric')
    return time_series, outcome_series


def _validate_frame(frame: pd.DataFrame, time_col: str, outcome: str, forecast_periods: int, holdout_periods: int):
    time_series, outcome_series = _series_columns(frame, time_col, outcome, validate_local_level_rows)
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    validate_local_level_holdout(len(frame), holdout_periods)
    return time_series, outcome_series


def validate_correlogram_size(rows: int, max_lag: int) -> None:
    if rows < 2:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', 'at least two time rows are required')
    if rows > MAX_OBSERVATIONS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'correlograms support at most {MAX_OBSERVATIONS} time rows')
    _option_periods(max_lag, 'max_lag', 1, min(MAX_CORRELOGRAM_LAG, rows - 1))


@contextmanager
def _native_checkpoint():
    check_cancellation()
    cancellation = None
    check = current_check()
    poll = _CHECKPOINT()
    if check is not None:
        @_CHECKPOINT
        def poll():
            nonlocal cancellation
            try:
                check()
            except BaseException as error:
                cancellation = error
                return 1
            return 0
    yield poll
    if cancellation is not None:
        raise cancellation
    check_cancellation()


def _numeric_buffer(observations: pd.Series, *, private: bool = True) -> np.ndarray:
    if pd.api.types.is_integer_dtype(observations.dtype):
        minimum, maximum = observations.min(), observations.max()
        if not pd.isna(minimum) and (int(minimum) < -_MAX_SAFE_INTEGER or int(maximum) > _MAX_SAFE_INTEGER):
            raise TimeSeriesPackError('TIME_SERIES_OUTCOME_PRECISION', 'integer outcomes must be within the exact binary64 integer range')
    with np.errstate(over='ignore', invalid='ignore'):
        values = observations.to_numpy(dtype=np.float64, copy=private, na_value=np.nan)
    return np.require(values, requirements=['C', 'A']) if private else values


def _numeric_design(frame: pd.DataFrame, names, *, excluded: tuple[str, ...]) -> np.ndarray:
    if any(type(name) is not str or not name or name in excluded for name in names) or len(set(names)) != len(names):
        raise TimeSeriesPackError('TIME_SERIES_BAD_INPUT', 'select distinct series columns separate from time and outcome roles')
    design = np.empty((len(frame), len(names)), dtype=np.float64)
    for index, name in enumerate(names):
        if name not in frame.columns:
            raise TimeSeriesPackError('TIME_SERIES_MISSING_COLUMN', f'missing series column {name!r}')
        column = frame[name]
        if not isinstance(column, pd.Series) or not _real_numeric(column.dtype):
            raise TimeSeriesPackError('TIME_SERIES_NON_NUMERIC_VALUE', f'series column {name!r} must be unique and real numeric')
        design[:, index] = _numeric_buffer(column, private=False)
    return design


def run_correlogram(
    frame: pd.DataFrame, *, time_col: str, outcome: str, max_lag: int = 1,
) -> dict[str, Any]:
    time, observations = _series_columns(frame, time_col, outcome, lambda rows: validate_correlogram_size(rows, max_lag))
    _, _, cadence = _time_grid(time, 0)
    values = _numeric_buffer(observations)
    library, engine = _loaded()
    output = np.empty(2 * max_lag + 1, dtype=np.float64)
    error_index = _SIZE()
    with _native_checkpoint() as poll:
        status = library.arboris_correlogram(
            values.ctypes.data_as(_DOUBLE), len(values), max_lag,
            output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error_index), poll,
        )
    if status == 2:
        message = (f'Yule-Walker system is numerically singular at lag {error_index.value}'
                   if error_index.value else 'ACF normalization failed')
        raise TimeSeriesPackError('TIME_SERIES_NUMERIC_FAILURE', message)
    if status == 3:
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE', f'outcome is missing or non-finite at row {error_index.value}')
    if status == 4:
        raise TimeSeriesPackError('TIME_SERIES_CONSTANT_SERIES', 'correlograms require a nonconstant outcome')
    if status:
        raise TimeSeriesPackError('TIME_SERIES_NATIVE_EXECUTION_ERROR', 'native correlogram rejected its inputs')

    return {
        'schema_version': 1, 'model': 'correlogram', 'engine': engine,
        'policy': {'time_col': time_col, 'outcome': outcome, 'cadence': cadence, 'max_lag': max_lag,
                   'acf_method': 'demeaned_common_n', 'pacf_method': 'yule_walker_durbin_levinson',
                   'missing': 'reject', 'assumption': 'weak_stationarity'},
        'n_observations': len(values), 'lags': list(range(max_lag + 1)),
        'acf': output[:max_lag + 1].tolist(), 'pacf': [None, *output[max_lag + 1:].tolist()],
    }


@dataclass(frozen=True)
class _PreparedSeries:
    time: np.ndarray | pd.DatetimeIndex
    future: list[int | float | str]
    cadence: dict[str, Any]
    values: np.ndarray
    observed: np.ndarray
    n_observed: int
    train_size: int


def _prepare_series(time_series: pd.Series, outcome_series: pd.Series, forecast_periods: int, holdout_periods: int):
    time, future, cadence = _time_grid(time_series, forecast_periods)
    values = _numeric_buffer(outcome_series)
    if np.isinf(values).any():
        raise TimeSeriesPackError('TIME_SERIES_NON_FINITE_VALUE', 'outcome contains infinity')
    observed = ~np.isnan(values)
    count = int(np.count_nonzero(observed))
    if not count:
        raise TimeSeriesPackError('TIME_SERIES_NO_OBSERVATIONS', 'at least one observed outcome is required')
    train_size = len(values) - holdout_periods
    if not observed[:train_size].any():
        raise TimeSeriesPackError('TIME_SERIES_NO_TRAINING_OBSERVATIONS', 'holdout requires an observed outcome in training')
    return _PreparedSeries(time, future, cadence, values, observed, count, train_size)


def validate_arima_size(rows: int, ar_order: int, differences: int, ma_order: int, deterministic: str,
                        holdout_periods: int) -> None:
    _option_periods(ar_order, 'ar_order', 0, 5)
    _option_periods(differences, 'differences', 0, 2)
    _option_periods(ma_order, 'ma_order', 0, 5)
    if ar_order + ma_order > 6:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'the combined AR and MA order cannot exceed six')
    if deterministic not in ('none', ('mean', 'drift', 'none')[differences]):
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', f'{deterministic} is unsupported with d={differences}')
    _option_periods(holdout_periods, 'holdout_periods', 0, MAX_HOLDOUT_PERIODS)
    if rows > MAX_ARIMA_ROWS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'ARIMA supports at most {MAX_ARIMA_ROWS} time rows')
    minimum = differences + 2 * (ar_order + ma_order) + int(deterministic != 'none') + 2
    if rows - holdout_periods < minimum:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', f'ARIMA requires at least {minimum} observed training rows')


def validate_sarima_size(
    rows: int, ar_order: int, differences: int, ma_order: int, seasonal_ar_order: int,
    seasonal_differences: int, seasonal_ma_order: int, seasonal_period: int, deterministic: str, holdout_periods: int,
    *, predictors: int = 0,
) -> None:
    _option_periods(ar_order, 'ar_order', 0, 3)
    _option_periods(ma_order, 'ma_order', 0, 3)
    _option_periods(differences, 'differences', 0, 2)
    _option_periods(seasonal_ar_order, 'seasonal_ar_order', 0, 1)
    _option_periods(seasonal_differences, 'seasonal_differences', 0, 1)
    _option_periods(seasonal_ma_order, 'seasonal_ma_order', 0, 1)
    if type(seasonal_period) is not int or not (2 <= seasonal_period <= 12 or seasonal_period == 24):
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'seasonal_period must be an integer from 2 through 12, or 24')
    _option_periods(holdout_periods, 'holdout_periods', 0, MAX_HOLDOUT_PERIODS)
    if seasonal_ar_order + seasonal_differences + seasonal_ma_order == 0:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'SARIMA requires at least one seasonal term')
    dynamics = ar_order + ma_order + seasonal_ar_order + seasonal_ma_order
    if dynamics > 4:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'the combined ordinary and seasonal AR/MA order cannot exceed four')
    integration = differences + seasonal_differences * seasonal_period
    stationary_width = max(ar_order + seasonal_ar_order * seasonal_period,
                           ma_order + seasonal_ma_order * seasonal_period + 1)
    width = integration + stationary_width
    if width > 28:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', 'SARIMA state dimension cannot exceed 28')
    total_differences = differences + seasonal_differences
    if deterministic != 'none' and not (
        (total_differences == 0 and deterministic == 'mean') or (total_differences == 1 and deterministic == 'drift')
    ):
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', f'{deterministic} is unsupported with d+D={total_differences}')
    if rows > MAX_SARIMA_ROWS:
        raise TimeSeriesPackError('TIME_SERIES_SIZE_LIMIT', f'SARIMA supports at most {MAX_SARIMA_ROWS} time rows')
    trend_columns = int(deterministic != 'none')
    minimum = integration + 2 * dynamics + trend_columns + 2
    training_rows = rows - holdout_periods
    if training_rows < minimum:
        raise TimeSeriesPackError('TIME_SERIES_TOO_FEW_OBSERVATIONS', f'SARIMA requires at least {minimum} observed training rows')
    if predictors and training_rows < minimum + predictors:
        raise TimeSeriesPackError(
            'TIME_SERIES_TOO_FEW_OBSERVATIONS', f'need at least {minimum + predictors} historical training rows for the regression',
        )
    if seasonal_period == 24 and dynamics:
        setup_work = 3 * _STATIONARY_COVARIANCE_MAX_ITERATIONS * stationary_width ** 3
        row_work = width ** 2
        model = 'SARIMA'
        if predictors:
            model = 'SARIMAX'
            row_work += width * _MAX_REGRESSION_DESIGN_COLUMNS + (predictors + trend_columns) ** 2
        required = (2 * dynamics + 1) * 18 + 2 * dynamics ** 2
        phases = [('full historical fit', rows)]
        if holdout_periods:
            phases.insert(0, ('holdout training fit', training_rows))
        for phase, phase_rows in phases:
            allowed = _MAX_LIKELIHOOD_WORK // (setup_work + phase_rows * row_work)
            if allowed < required:
                raise TimeSeriesPackError(
                    'TIME_SERIES_SIZE_LIMIT',
                    f'period-24 {model} {phase} ({phase_rows} rows) requires at least {required} likelihood evaluations '
                    f'but its native work budget allows {allowed}',
                )


def _prediction_level(confidence_level: float) -> tuple[float, float]:
    level = _option_number(confidence_level, 'confidence_level')
    if not 0 < level < 1:
        raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'require 0 < confidence_level < 1')
    return level, -NormalDist().inv_cdf((1.0 - level) / 2.0)


def _interval_forecast(forecasts, future, critical, model):
    with np.errstate(over='ignore', invalid='ignore'):
        means, variances = forecasts.T
        margin = critical * np.sqrt(variances)
        lower, upper = means - margin, means + margin
    if not np.isfinite(lower).all() or not np.isfinite(upper).all():
        raise TimeSeriesPackError('TIME_SERIES_NUMERIC_FAILURE', f'{model} prediction intervals exceeded their numerical range')
    return {'steps': list(range(1, len(future) + 1)), 'time': future, 'mean': means.tolist(),
            'observation_variance': variances.tolist(), 'lower': lower.tolist(), 'upper': upper.tolist()}


def _arima_whiteness(output):
    status, n, lag, fit_df, df, statistic = map(float, output)
    reason = {
        0: None,
        1: 'TIME_SERIES_ARIMA_WHITENESS_GAPS',
        2: 'TIME_SERIES_ARIMA_WHITENESS_NONPOSITIVE_DF',
        3: 'TIME_SERIES_ARIMA_WHITENESS_INSUFFICIENT_INNOVATIONS',
        4: 'TIME_SERIES_ARIMA_WHITENESS_CONSTANT_INNOVATIONS',
    }.get(status, 'TIME_SERIES_ARIMA_WHITENESS_NUMERIC_FAILURE')
    probability = None
    if reason is None:
        from scipy.stats import chi2
        probability = float(chi2.sf(statistic, df))
        if not math.isfinite(probability):
            reason = 'TIME_SERIES_ARIMA_WHITENESS_NUMERIC_FAILURE'
    return {
        'method': 'ljung_box_demeaned_common_n', 'scope': 'full_fit_standardized_one_step_innovations',
        'reference_distribution': 'asymptotic_chi_square', 'n_effective': int(n),
        'lag': int(lag), 'fit_df': int(fit_df), 'df': int(df) if df > 0 else None,
        'status': 'computed' if reason is None else 'unavailable', 'reason_code': reason,
        'statistic': statistic if reason is None else None, 'p_value': probability if reason is None else None,
    }


def _arima_fit(library, values, order, trend, future, critical, seasonal_order=None, regressors=None,
               whiteness_lag=None):
    p, d, q = order
    seasonal_ar, _, seasonal_ma, _ = seasonal_order or (0, 0, 0, 0)
    model = 'SARIMA' if seasonal_order is not None else 'ARIMA'
    names, design_args = (), ()
    if regressors is not None:
        names, training_x, future_x = regressors
        model += 'X'
        design_args = (training_x.ctypes.data_as(_DOUBLE), training_x.size, future_x.ctypes.data_as(_DOUBLE), future_x.size, len(names))
    coefficient_end = 6 + p + q + seasonal_ar + seasonal_ma
    fit = np.empty(coefficient_end + len(names), dtype=np.float64)
    forecasts = np.empty((len(future), 2), dtype=np.float64)
    residuals = np.empty(26, dtype=np.float64)
    whiteness = None
    lag_args, diagnostic_args = (), ()
    symbol = f'arboris_{model.lower()}_fit'
    if whiteness_lag is not None:
        if model != 'ARIMA':
            raise TimeSeriesPackError('TIME_SERIES_INVALID_OPTION', 'whiteness_lag requires ordinary ARIMA')
        symbol = 'arboris_arima_fit_with_whiteness'
        whiteness = np.empty(6, dtype=np.float64)
        lag_args = (whiteness_lag,)
        diagnostic_args = (whiteness.ctypes.data_as(_DOUBLE), whiteness.size)
    error_index = _SIZE()
    with _native_checkpoint() as poll:
        estimate = getattr(library, symbol)
        status = estimate(
            values.ctypes.data_as(_DOUBLE), values.size, *design_args, p, d, q, *(seasonal_order or ()),
            _ARIMA_TRENDS[trend], len(future), *lag_args,
            fit.ctypes.data_as(_DOUBLE), fit.size, forecasts.ctypes.data_as(_DOUBLE), forecasts.size,
            residuals.ctypes.data_as(_DOUBLE), residuals.size, *diagnostic_args, ctypes.byref(error_index), poll,
        )
    if status:
        if status in (9, 10):
            row, column = divmod(error_index.value, len(names))
            segment = 'historical' if status == 9 else 'future'
            raise TimeSeriesPackError('TIME_SERIES_INVALID_REGRESSOR',
                                      f'{segment} predictor {names[column]!r} requires a finite value at row {row}')
        code, message = {
            1: ('TIME_SERIES_BAD_INPUT', f'{model} rejected the inputs at position {error_index.value}'),
            2: ('TIME_SERIES_NUMERIC_FAILURE', f'{model} exceeded its numerical range'),
            3: ('TIME_SERIES_TOO_FEW_OBSERVATIONS', f'{model} has too few observed outcomes for this specification'),
            4: ('TIME_SERIES_ARIMA_UNIDENTIFIED', f'{model} likelihood is degenerate or locally singular'),
            5: ('TIME_SERIES_ARIMA_NONCONVERGENCE', f'{model} did not converge to an interior likelihood optimum'),
            6: ('TIME_SERIES_SIZE_LIMIT', f'{model} specification exceeds the native work limit'),
            8: ('TIME_SERIES_MISSING_SEASONAL_ANCHOR',
                f'SARIMA with seasonal differencing requires a complete starting block; missing outcome at row {error_index.value}'),
        }.get(status, ('TIME_SERIES_NATIVE_EXECUTION_ERROR', f'native {model} did not produce a verified result'))
        raise TimeSeriesPackError(code, message)
    variance, likelihood, deterministic, observed, effective, iterations = map(float, fit[:6])
    parameters = {f'ar{lag}': float(value) for lag, value in enumerate(fit[6:6 + p], 1)}
    parameters.update({f'ma{lag}': float(value) for lag, value in enumerate(fit[6 + p:6 + p + q], 1)})
    if seasonal_ar:
        parameters['sar1'] = float(fit[6 + p + q])
    if seasonal_ma:
        parameters['sma1'] = float(fit[coefficient_end - 1])
    if trend != 'none':
        parameters['intercept' if names and trend == 'mean' else trend] = deterministic
    k = 1 + len(parameters) + len(names)
    if names:
        parameters['exogenous'] = dict(zip(names, map(float, fit[coefficient_end:]), strict=True))
    diagnostics = {
        'standardized_innovation_mean': float(residuals[0]), 'standardized_innovation_rms': float(residuals[1]),
        'paired_lag_correlations': [{'lag': lag, 'pairs': int(pairs),
                                     'correlation': float(correlation) if np.isfinite(correlation) else None}
                                    for lag, (correlation, pairs) in enumerate(residuals[2:].reshape(-1, 2), 1)],
    }
    if whiteness is not None:
        diagnostics['whiteness'] = _arima_whiteness(whiteness)
    return parameters, {
        'n_observed': int(observed), 'n_effective': int(effective), 'n_missing': values.size - int(observed),
        'optimizer_iterations': int(iterations), 'innovation_variance': variance, 'log_likelihood': likelihood,
        'aic': 2 * (k - likelihood), 'bic': k * math.log(effective) - 2 * likelihood, 'diagnostics': diagnostics,
    }, _interval_forecast(forecasts, future, critical, model)


def run_arima(frame: pd.DataFrame, *, time_col: str, outcome: str, ar_order: int = 1, differences: int = 0, ma_order: int = 0,
              deterministic: str = 'none', forecast_periods: int = 1, holdout_periods: int = 0,
              confidence_level: float = 0.95) -> dict[str, Any]:
    return _run_arima(frame, time_col, outcome, (ar_order, differences, ma_order),
                      deterministic, forecast_periods, holdout_periods, confidence_level, None)


def run_arima_with_whiteness(
    frame: pd.DataFrame, *, time_col: str, outcome: str, whiteness_lag: int,
    ar_order: int = 1, differences: int = 0, ma_order: int = 0, deterministic: str = 'none',
    forecast_periods: int = 1, holdout_periods: int = 0, confidence_level: float = 0.95,
) -> dict[str, Any]:
    _option_periods(whiteness_lag, 'whiteness_lag', 1, MAX_ARIMA_WHITENESS_LAG)
    return _run_arima(frame, time_col, outcome, (ar_order, differences, ma_order),
                      deterministic, forecast_periods, holdout_periods, confidence_level, None, whiteness_lag)


def run_sarima(
    frame: pd.DataFrame, *, time_col: str, outcome: str, seasonal_period: int, ar_order: int = 1,
    differences: int = 0, ma_order: int = 0, seasonal_ar_order: int = 0, seasonal_differences: int = 1,
    seasonal_ma_order: int = 0, deterministic: str = 'none', forecast_periods: int = 1, holdout_periods: int = 0,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    return _run_arima(frame, time_col, outcome, (ar_order, differences, ma_order), deterministic, forecast_periods,
                      holdout_periods, confidence_level, (seasonal_ar_order, seasonal_differences, seasonal_ma_order, seasonal_period))


def _run_arima(frame, time_col, outcome, order, deterministic, forecast_periods, holdout_periods, confidence_level,
               seasonal_order, whiteness_lag=None):
    validate = validate_sarima_size if seasonal_order is not None else validate_arima_size
    time, observations = _series_columns(frame, time_col, outcome, lambda rows: validate(
        rows, *order, *(seasonal_order or ()), deterministic, holdout_periods))
    _option_periods(forecast_periods, 'forecast_periods', 1, MAX_FORECAST_PERIODS)
    level, critical = _prediction_level(confidence_level)
    data = _prepare_series(time, observations, forecast_periods, holdout_periods)
    library, engine = _loaded()
    holdout = None
    if holdout_periods:
        start = data.train_size
        _, training_fit, predicted = _arima_fit(library, data.values[:start], order, deterministic,
                                               [_time_label(t) for t in data.time[start:]], critical, seasonal_order)
        count, metrics = _holdout_metrics(data.values, data.observed, start, predicted,
                                         seasonal_period=seasonal_order[-1] if seasonal_order is not None else None)
        holdout = {'status': 'completed' if count else 'no_observed_holdout', 'training_steps': start,
                   'training_observed': training_fit['n_observed'], 'origin_time': _time_label(data.time[start - 1]),
                   'n_observed': count, 'n_missing': holdout_periods - count, 'forecast': predicted, 'metrics': metrics}
    parameters, fit, forecast = _arima_fit(library, data.values, order, deterministic, data.future, critical,
                                            seasonal_order, whiteness_lag=whiteness_lag)
    policy = {'time_col': time_col, 'outcome': outcome, 'cadence': data.cadence, 'order': list(order),
              'deterministic': deterministic, 'confidence_level': level, 'estimation': 'gaussian_innovations_ml',
              'missing': 'skip_measurement_keep_time', 'forecast_interval': 'gaussian_plugin',
              'holdout_method': 'training_prefix_fit_fixed_origin'}
    if whiteness_lag is not None:
        policy['whiteness_lag'] = whiteness_lag
    if seasonal_order is not None:
        policy.update(seasonal_order=list(seasonal_order), holdout_baseline='last_observed_training_seasonal_phase')
    return {
        'schema_version': 1, 'model': 'sarima' if seasonal_order is not None else 'arima',
        'engine': engine, 'parameters': parameters, 'fit': fit, 'policy': policy,
        'forecast': forecast, 'holdout': holdout,
    }


def _result(data: _PreparedSeries, *, time_col: str, outcome: str, parameters, confidence_level: float):
    q, r, mean, variance = parameters
    check_cancellation()
    rows, total, engine = _filter(data.values, q, r, mean, variance)
    critical = -NormalDist().inv_cdf((1.0 - confidence_level) / 2.0)
    forecast = _forecast(rows[-1], data.future, q, r, critical)
    holdout_periods = len(data.values) - data.train_size
    holdout = (_holdout(data.values, data.observed, rows, data.time, data.train_size, q, r, critical)
               if holdout_periods else None)
    first = max(0, len(rows) - MAX_TRACE_ROWS)
    trace = []
    for index in range(first, len(rows)):
        record = dict(zip(_TRACE_COLUMNS, map(float, rows[index]), strict=True))
        if not data.observed[index]:
            record['innovation'] = None
        trace.append({'index': index, 'time': _time_label(data.time[index]), **record})
    check_cancellation()
    return {
        'schema_version': 1, 'model': 'local_level', 'engine': engine,
        'parameters': {'process_variance': q, 'observation_variance': r, 'initial_mean': mean, 'initial_variance': variance},
        'policy': {'time_col': time_col, 'outcome': outcome, 'cadence': data.cadence, 'forecast_periods': len(data.future),
                   'holdout_periods': holdout_periods, 'confidence_level': confidence_level, 'missing': 'skip_measurement_keep_time',
                   'forecast_interval': 'gaussian_observation', 'holdout_method': 'fixed_origin'},
        'fit': {'n_steps': len(data.values), 'n_observed': data.n_observed, 'n_missing': len(data.values) - data.n_observed,
                'log_likelihood': total,
                'final_state': {'mean': float(rows[-1, 2]), 'variance': float(rows[-1, 3])},
                'trace': {'first_index': first, 'total_steps': len(rows), 'rows': trace}},
        'forecast': forecast, 'holdout': holdout,
    }


def run_local_level(
    frame: pd.DataFrame,
    *,
    time_col: str,
    outcome: str,
    process_variance: float,
    observation_variance: float,
    initial_mean: float,
    initial_variance: float,
    forecast_periods: int = 1,
    holdout_periods: int = 0,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Filter a regular series using a known prior and fixed variances.

    Outcome gaps retain their time positions. The returned trace is limited to
    the final 512 steps, and holdout forecasts use only the training prefix.
    Datetimes and uniform ISO dates/timestamps support fixed durations and
    calendar cadence for month, quarter and year starts and ends.
    """
    time, values = _validate_frame(frame, time_col, outcome, forecast_periods, holdout_periods)
    q = _option_number(process_variance, 'process_variance')
    r = _option_number(observation_variance, 'observation_variance')
    mean = _option_number(initial_mean, 'initial_mean')
    variance = _option_number(initial_variance, 'initial_variance')
    level = _option_number(confidence_level, 'confidence_level')
    if q < 0 or r <= 0 or variance < 0 or not 0 < level < 1:
        raise TimeSeriesPackError(
            'TIME_SERIES_INVALID_OPTION',
            'require process_variance >= 0, observation_variance > 0, initial_variance >= 0 and 0 < confidence_level < 1',
        )
    data = _prepare_series(time, values, forecast_periods, holdout_periods)
    return _result(data, time_col=time_col, outcome=outcome, parameters=(q, r, mean, variance), confidence_level=level)


def run_local_level_fit(
    frame: pd.DataFrame,
    *,
    time_col: str,
    outcome: str,
    variance_ratio: float,
    initial_mean: float,
    relative_initial_variance: float,
    forecast_periods: int = 1,
    holdout_periods: int = 0,
    confidence_level: float = 0.95,
) -> dict[str, Any]:
    """Estimate R on the training prefix with fixed Q/R and P0/R ratios.

    The future state uses all measurements with that same fitted scale.
    Both forecast intervals condition on the estimated variances.
    """
    time, values = _validate_frame(frame, time_col, outcome, forecast_periods, holdout_periods)
    ratio = _option_number(variance_ratio, 'variance_ratio')
    mean = _option_number(initial_mean, 'initial_mean')
    prior_ratio = _option_number(relative_initial_variance, 'relative_initial_variance')
    level = _option_number(confidence_level, 'confidence_level')
    if ratio < 0 or prior_ratio < 0 or not 0 < level < 1:
        raise TimeSeriesPackError(
            'TIME_SERIES_INVALID_OPTION',
            'require variance_ratio >= 0, relative_initial_variance >= 0 and 0 < confidence_level < 1',
        )
    data = _prepare_series(time, values, forecast_periods, holdout_periods)
    q, r, variance, training_log_likelihood = _fit_scale(data.values[:data.train_size], ratio, mean, prior_ratio)
    result = _result(data, time_col=time_col, outcome=outcome, parameters=(q, r, mean, variance), confidence_level=level)
    count = int(np.count_nonzero(data.observed[:data.train_size]))
    result['estimation'] = {
        'method': 'gaussian_concentrated_ml_fixed_ratio', 'variance_ratio': ratio,
        'relative_initial_variance': prior_ratio, 'training_steps': data.train_size,
        'n_observed': count, 'n_missing': data.train_size - count, 'training_log_likelihood': training_log_likelihood,
    }
    result['policy'].update(parameter_mode='estimated_common_scale', forecast_interval='gaussian_observation_plugin')
    return result
