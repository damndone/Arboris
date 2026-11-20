"""Verified native portfolio replay, rolling risk, and historical tail risk."""
from __future__ import annotations

import ctypes
from functools import lru_cache
from itertools import chain
import math
from numbers import Integral, Real
from pathlib import Path
import re
from threading import Lock
from typing import Any

import numpy as np
import pandas as pd
from pandas.api import types as dtypes

from .native_build import NativeBuildError, artifact_names, default_output, manifest_path, verify_build


_MODULE = Path(__file__).resolve().parents[2] / "native" / "quant_replay"
ABI_VERSION = 1
MAX_PERIODS = 10_000
MAX_ASSETS = 32
MAX_SERIES_POINTS = 256
MAX_RISK_WINDOW = 2048
_BASIS_POINTS = 10_000
_MAX_NAME_BYTES = 256
_ISO_TIMESTAMP_LENGTH = 64
_SUBNANOSECOND = re.compile(r"[.,][0-9]{10}")
_START, _POST, _END, _EXPOSURE, _FEES, _NOTIONAL, _HOLDING, _PNL, _RETURN = range(9)
_OUTPUT_COLUMNS = 9
_LEDGER_VALUES = ("starting_equity", "post_trade_equity", "ending_equity", "gross_exposure", "fees",
                  "traded_notional", "holding_pnl", "net_pnl", "net_return")
REPLAY_LEDGER_COLUMNS = ("row", "signal_time", "execution_time", "end_time", *_LEDGER_VALUES,
                         "net_exposure", "drawdown")
_ACCOUNTING_RTOL = 128.0 * np.finfo(np.float64).eps
_RISK_RTOL = 2e-12
_DOUBLE = ctypes.POINTER(ctypes.c_double)
_I64 = ctypes.POINTER(ctypes.c_int64)
_SIZE = ctypes.c_size_t
_CHECKPOINT = ctypes.CFUNCTYPE(ctypes.c_int32)
_NO_ROW = _SIZE(-1).value
_LOAD_LOCK = Lock()


class QuantReplayError(ValueError):
    """Invalid input, unavailable native build, or a failed replay."""

    def __init__(self, code: str, message: str, *, row: int | None = None):
        super().__init__(message)
        self.code = code
        self.row = row


def _output_directory() -> Path:
    return default_output(_MODULE)


def _invalid(message: str) -> QuantReplayError:
    return QuantReplayError("QUANT_REPLAY_INVALID_INPUT", message)


def _native_invalid(message: str, row: int | None = None) -> QuantReplayError:
    return QuantReplayError("QUANT_REPLAY_NATIVE_INVALID", message, row=row)


def _open(path: Path):
    library = ctypes.CDLL(str(path))
    library.arboris_quant_replay_abi.argtypes = []
    library.arboris_quant_replay_abi.restype = ctypes.c_int32
    if library.arboris_quant_replay_abi() != ABI_VERSION:
        raise _native_invalid("Quant replay ABI mismatch. Rebuild the library and restart Workbench.")
    library.arboris_quant_replay_output_len.argtypes = [_SIZE]
    library.arboris_quant_replay_output_len.restype = _SIZE
    library.arboris_quant_replay.argtypes = [
        _SIZE, _SIZE, _I64, _SIZE, _DOUBLE, _SIZE, _DOUBLE, _SIZE,
        ctypes.c_double, ctypes.c_double, _DOUBLE, _SIZE, ctypes.POINTER(_SIZE),
    ]
    library.arboris_quant_replay.restype = ctypes.c_int32
    library.arboris_quant_replay_fee_comparison.argtypes = [
        _SIZE, _SIZE, _I64, _SIZE, _DOUBLE, _SIZE, _DOUBLE, _SIZE,
        ctypes.c_double, ctypes.c_double, ctypes.c_double, _DOUBLE, _SIZE, ctypes.POINTER(_SIZE), _CHECKPOINT,
    ]
    library.arboris_quant_replay_fee_comparison.restype = ctypes.c_int32
    library.arboris_quant_risk_output_len.argtypes = [_SIZE, _SIZE, _SIZE]
    library.arboris_quant_risk_output_len.restype = _SIZE
    library.arboris_quant_risk.argtypes = [
        _SIZE, _SIZE, _SIZE, _I64, _SIZE, _DOUBLE, _SIZE, _DOUBLE, _SIZE, ctypes.POINTER(_SIZE),
    ]
    library.arboris_quant_risk.restype = ctypes.c_int32
    library.arboris_quant_tail_risk.argtypes = [
        _SIZE, _SIZE, _SIZE, _DOUBLE, _SIZE, _DOUBLE, _SIZE, ctypes.POINTER(_SIZE),
    ]
    library.arboris_quant_tail_risk.restype = ctypes.c_int32
    library.arboris_quant_min_variance.argtypes = [
        _SIZE, _SIZE, _SIZE, _I64, _SIZE, _DOUBLE, _SIZE, _DOUBLE, _SIZE, ctypes.POINTER(_SIZE), _CHECKPOINT,
    ]
    library.arboris_quant_min_variance.restype = ctypes.c_int32
    library.arboris_quant_walk_forward.argtypes = [
        _SIZE, _SIZE, _SIZE, _SIZE, _SIZE, _I64, _SIZE, _DOUBLE, _SIZE,
        ctypes.c_double, ctypes.c_double, _DOUBLE, _SIZE, ctypes.POINTER(_SIZE), _CHECKPOINT,
    ]
    library.arboris_quant_walk_forward.restype = ctypes.c_int32
    return library


def _file_identity(path: Path) -> tuple[int, ...]:
    stat = path.lstat()
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


@lru_cache(maxsize=1)
def _load_once():
    output = _output_directory()
    path = output / artifact_names(_MODULE)[0]
    manifest_file = manifest_path(output)
    if not (path.exists() or path.is_symlink() or manifest_file.exists() or manifest_file.is_symlink()
            or any(output.glob("*arboris_quant_replay*"))):
        raise QuantReplayError(
            "QUANT_REPLAY_NATIVE_UNAVAILABLE",
            "Build the local replay library with native/quant_replay/build.py before running this operation.",
        )
    try:
        before = _file_identity(path)
        manifest = verify_build(_MODULE, output)
        if _file_identity(path) != before:
            raise _native_invalid("Quant replay binary changed during verification. Restart Workbench.")
    except (NativeBuildError, OSError) as error:
        raise _native_invalid("Quant replay requires a current verified local build. Rebuild it and restart Workbench.") from error
    try:
        library = _open(path)
        if _file_identity(path) != before:
            raise _native_invalid("Quant replay binary changed while loading. Restart Workbench.")
    except (AttributeError, OSError, QuantReplayError) as error:
        # The image may already be mapped. A different file at this path
        # cannot safely replace it within the same process.
        return error
    receipt = {key: manifest[key] for key in ("source_sha256", "binary_sha256", "build_identity_sha256")}
    return library, {"id": "arboris_quant_replay", "abi_version": ABI_VERSION, **receipt}, path, before


def _loaded():
    with _LOAD_LOCK:
        result = _load_once()
        if isinstance(result, Exception):
            raise _native_invalid("Could not load the verified quant replay ABI. Rebuild it and restart Workbench.") from result
        library, receipt, path, identity = result
        try:
            same_image = _file_identity(path) == identity
        except OSError:
            same_image = False
        if not same_image:
            raise _native_invalid("Quant replay binary changed after loading. Restart Workbench.")
    return library, receipt


def _valid_name(value: Any) -> bool:
    if type(value) is not str or not value:
        return False
    try:
        return len(value.encode("utf-8")) <= _MAX_NAME_BYTES
    except UnicodeEncodeError:
        return False


def _number(value: Any, option: str) -> float:
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real):
        raise _invalid(f"{option} must be a finite number.")
    try:
        number = float(value)
    except OverflowError as error:
        raise _invalid(f"{option} must be a finite number.") from error
    if not math.isfinite(number):
        raise _invalid(f"{option} must be a finite number.")
    return number


def _time_matrix(frame: pd.DataFrame, names: tuple[str, ...], *, invalid=_invalid) -> tuple[np.ndarray, str]:
    output = np.empty((len(frame), len(names)), dtype=np.int64)
    domains = set()
    for index, name in enumerate(names):
        values = frame[name]
        if values.isna().any():
            raise invalid("Timestamp columns must be complete.")
        if dtypes.is_integer_dtype(values.dtype):
            if dtypes.is_unsigned_integer_dtype(values.dtype) and int(values.max()) > np.iinfo(np.int64).max:
                raise invalid("Integer timestamps must fit in signed 64 bits.")
            output[:, index] = values.to_numpy(dtype=np.int64)
            domains.add("integer_tick")
            continue
        try:
            if dtypes.is_datetime64_any_dtype(values.dtype):
                parsed = pd.to_datetime(values, utc=True)
            else:
                for value in values:
                    if not isinstance(value, str):
                        raise invalid("Timestamps must be integer ticks, datetimes, or ISO 8601 strings.")
                    if len(value) > _ISO_TIMESTAMP_LENGTH or _SUBNANOSECOND.search(value):
                        raise invalid("ISO 8601 timestamps allow at most 64 characters and nine fractional second digits.")
                parsed = pd.to_datetime(values, format="ISO8601", utc=True)
            if parsed.isna().any():
                raise invalid("Timestamp columns must be complete.")
            output[:, index] = pd.DatetimeIndex(parsed).as_unit("ns").asi8
        except QuantReplayError:
            raise
        except (TypeError, ValueError, OverflowError) as error:
            raise invalid("ISO 8601 timestamps must be representable at nanosecond precision.") from error
        domains.add("iso8601_utc")
    if len(domains) != 1:
        raise invalid("The timestamps must use a single clock domain.")
    return output, domains.pop()


def _numeric_matrix(frame: pd.DataFrame, columns: tuple[str, ...], *, invalid=_invalid) -> np.ndarray:
    # Own the aligned C-order snapshot for the complete GIL-releasing call.
    output = np.empty((len(frame), len(columns)), dtype=np.float64)
    for index, name in enumerate(columns):
        values = frame[name]
        if (not dtypes.is_numeric_dtype(values.dtype) or dtypes.is_bool_dtype(values.dtype)
                or dtypes.is_complex_dtype(values.dtype)):
            raise invalid("Selected numeric columns must contain real values.")
        try:
            output[:, index] = values.to_numpy(dtype=np.float64, na_value=np.nan)
        except (TypeError, ValueError, OverflowError) as error:
            raise invalid("Selected numeric columns must be representable as binary64.") from error
    return output


_REPLAY_ERRORS = {
    2: ("QUANT_REPLAY_TIME_ORDER", "Holding intervals must be ordered and contiguous, with execution before end."),
    3: ("QUANT_REPLAY_LOOKAHEAD", "Signal availability must be strictly earlier than simulated execution."),
    4: ("QUANT_REPLAY_RETURN", "Each simple asset return must be finite and at least -1."),
    5: ("QUANT_REPLAY_WEIGHT", "Weights must be finite and long-only, and their sum cannot exceed one."),
    6: ("QUANT_REPLAY_NONPOSITIVE_EQUITY", "Replay cannot continue after portfolio equity has reached zero."),
    7: ("QUANT_REPLAY_NUMERICAL", "The portfolio ledger cannot be represented and reconciled in binary64."),
}


def _native_call(library, times, returns, weights, fee_rate, initial_equity) -> np.ndarray:
    rows, width = returns.shape
    output = np.full((rows, _OUTPUT_COLUMNS), np.nan)
    if library.arboris_quant_replay_output_len(rows) != output.size:
        raise _native_invalid("The quant replay ABI returned an invalid output length.")
    error_row = _SIZE(_NO_ROW)
    status = library.arboris_quant_replay(
        rows, width, times.ctypes.data_as(_I64), times.size,
        returns.ctypes.data_as(_DOUBLE), returns.size, weights.ctypes.data_as(_DOUBLE), weights.size,
        fee_rate, initial_equity, output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error_row),
    )
    if status in _REPLAY_ERRORS and 0 <= error_row.value < rows:
        code, message = _REPLAY_ERRORS[status]
        raise QuantReplayError(code, message, row=error_row.value)
    if status != 0 or error_row.value != _NO_ROW:
        raise _native_invalid("The verified quant replay library returned an invalid result status.")
    return output


def _verify_accounting(output, returns, weights, fee_rate, initial_equity) -> None:
    if output.shape != (len(weights), _OUTPUT_COLUMNS) or not np.isfinite(output).all():
        raise _native_invalid("The quant replay output is incomplete or non-finite.")
    start, post, end, exposure, fees, notional, hold, pnl, net = output.T
    invalid = ((start <= 0) | (post <= 0) | (end < 0) | (exposure < 0) | (exposure > 1)
               | (fees < 0) | (notional < 0) | (net < -1))
    # Verify the candidate funded value and every ledger field with NumPy
    # portfolio identities. This check does not reuse the Rust root solver.
    with np.errstate(over="ignore", invalid="ignore", under="ignore", divide="ignore"):
        targets = post[:, None] * weights
        marked = targets * (1.0 + returns)
        prior = np.empty_like(targets)
        prior[0] = 0.0
        prior[1:] = marked[:-1]
        expected_notional = np.sum(np.abs(targets - prior), axis=1)
        expected_fee = fee_rate * expected_notional
        expected_hold = np.sum(targets * returns, axis=1)
        cash_weight = np.fromiter(
            (math.fsum(chain((1.0,), (-weight for weight in row))) for row in weights),
            dtype=np.float64, count=len(weights),
        )
        invalid |= cash_weight < 0
        expected_exposure = 1.0 - cash_weight
        expected_end = np.sum(marked, axis=1) + post * cash_weight
        expected_start = np.concatenate(([initial_equity], expected_end[:-1]))
        expected_pnl = expected_hold - expected_fee
        expected_net = np.where(end == 0, -1.0, expected_pnl / expected_start)
        money_scale = np.maximum(start, end)
        for actual, expected in (
            (start, expected_start), (post, expected_start - expected_fee), (end, expected_end),
            (fees, expected_fee), (notional, expected_notional), (hold, expected_hold), (pnl, expected_pnl),
        ):
            invalid |= ~np.isfinite(expected) | (np.abs(actual - expected) / money_scale > _ACCOUNTING_RTOL)
        for actual, expected in ((exposure, expected_exposure), (net, expected_net)):
            relative_error = np.abs(actual - expected) / np.maximum(1.0, np.abs(expected))
            invalid |= ~np.isfinite(expected) | (relative_error > _ACCOUNTING_RTOL)
    if invalid.any():
        raise _native_invalid("The quant replay output failed independent accounting checks.", int(np.flatnonzero(invalid)[0]))


def _time_label(value: int, clock: str) -> str:
    if clock == "integer_tick":
        return str(value)  # Preserve all 64 bits through a JavaScript JSON reader.
    return pd.Timestamp(value, unit="ns", tz="UTC").isoformat()


def _preview_indices(count: int):
    if count <= MAX_SERIES_POINTS:
        return range(count)
    return (index * (count - 1) // (MAX_SERIES_POINTS - 1) for index in range(MAX_SERIES_POINTS))


def _summarize(output, times, clock) -> tuple[dict, dict]:
    end = output[:, _END]
    initial_equity = float(output[0, _START])
    peak = np.maximum.accumulate(np.concatenate(([initial_equity], end)))[1:]
    drawdown = (peak - end) / peak
    n = len(end)
    try:
        metrics = {
            "initial_equity": initial_equity, "final_equity": float(end[-1]),
            "cumulative_net_return": float(end[-1]) / initial_equity - 1.0,
            "total_fees": math.fsum(output[:, _FEES]),
            "total_traded_notional": math.fsum(output[:, _NOTIONAL]),
            "max_drawdown": float(drawdown.max()),
            "max_gross_exposure": float(output[:, _EXPOSURE].max()),
            "max_net_exposure": float(output[:, _EXPOSURE].max()),
        }
    except OverflowError as error:
        raise QuantReplayError("QUANT_REPLAY_NUMERICAL", "Replay aggregate exceeds the supported numeric range.") from error
    if not all(math.isfinite(value) for value in metrics.values()):
        raise QuantReplayError("QUANT_REPLAY_NUMERICAL", "Replay aggregate exceeds the supported numeric range.")
    series = {
        "privacy": "local_only", "total_rows": n, "truncated": n > MAX_SERIES_POINTS,
        "rows": [
            {"row": index, "execution_time": _time_label(int(times[index, 1]), clock),
             "end_time": _time_label(int(times[index, 2]), clock),
             "starting_equity": float(output[index, _START]), "post_trade_equity": float(output[index, _POST]),
             "ending_equity": float(end[index]), "gross_exposure": float(output[index, _EXPOSURE]),
             "net_exposure": float(output[index, _EXPOSURE]), "fees": float(output[index, _FEES]),
             "traded_notional": float(output[index, _NOTIONAL]), "holding_pnl": float(output[index, _HOLDING]),
             "net_pnl": float(output[index, _PNL]), "net_return": float(output[index, _RETURN]),
             "drawdown": float(drawdown[index])}
            for index in _preview_indices(n)
        ],
    }
    return metrics, series


def validate_replay_rows(rows: int) -> None:
    if not 1 <= rows <= MAX_PERIODS:
        raise _invalid(f"Replay requires a table with 1 to {MAX_PERIODS} periods.")


_REPLAY_ASSUMPTIONS = {
    "scope": "offline_simulation", "interval_policy": "contiguous",
    "timestamp_evidence": "supplied_values_order_only", "source_vintage_verified": False,
    "naive_datetime_timezone": "UTC", "fill_model": "full_simulated_fill_at_execution",
    "initial_positions": "all_cash", "cash_return": 0.0, "return_type": "simple_total_return",
    "fee_model": "one_way_bps_on_absolute_traded_notional",
    "exposure_basis": "post_fee_risky_value_fraction", "drawdown_basis": "initial_and_period_end_equity",
}


def _replay_bindings(
    frame: pd.DataFrame, *, signal_time_col: str, execution_time_col: str, end_time_col: str,
    return_columns: list[str] | tuple[str, ...], weight_columns: list[str] | tuple[str, ...],
):
    validate_replay_rows(len(frame) if isinstance(frame, pd.DataFrame) else 0)
    if (not isinstance(return_columns, (list, tuple)) or not isinstance(weight_columns, (list, tuple))
            or len(return_columns) != len(weight_columns) or not 1 <= len(return_columns) <= MAX_ASSETS):
        raise _invalid(f"Select 1 to {MAX_ASSETS} ordered pairs of return and weight columns.")
    returns_names, weight_names = tuple(return_columns), tuple(weight_columns)
    time_names = (signal_time_col, execution_time_col, end_time_col)
    names = (*time_names, *returns_names, *weight_names)
    if (not all(_valid_name(name) for name in names) or len(set(names)) != len(names)
            or not frame.columns.is_unique or not all(name in frame.columns for name in names)):
        raise _invalid("Each replay column must have a distinct, nonempty name present in the table.")
    return time_names, returns_names, weight_names


def _prepare_replay_input(frame: pd.DataFrame, bindings, options: dict):
    time_names, returns_names, weight_names = bindings
    signal_time_col, execution_time_col, end_time_col = time_names
    times, clock = _time_matrix(frame, time_names)
    returns, weights = _numeric_matrix(frame, returns_names), _numeric_matrix(frame, weight_names)
    inputs = {
        "signal_time_col": signal_time_col, "execution_time_col": execution_time_col, "end_time_col": end_time_col,
        "return_columns": list(returns_names), "weight_columns": list(weight_names),
        **options, "period_count": len(frame), "asset_count": len(returns_names), "time_format": clock,
    }
    return times, returns, weights, inputs


def _verified_replay(
    frame: pd.DataFrame, *, signal_time_col: str, execution_time_col: str, end_time_col: str,
    return_columns: list[str] | tuple[str, ...], weight_columns: list[str] | tuple[str, ...],
    transaction_cost_bps: float, initial_equity: float,
):
    bindings = _replay_bindings(
        frame, signal_time_col=signal_time_col, execution_time_col=execution_time_col, end_time_col=end_time_col,
        return_columns=return_columns, weight_columns=weight_columns,
    )
    bps = _number(transaction_cost_bps, "transaction_cost_bps")
    equity = _number(initial_equity, "initial_equity")
    fee_rate = bps / 10_000.0
    if not 0.0 <= bps < 10_000.0 or fee_rate >= 1.0 or equity <= 0:
        raise _invalid("Transaction cost must be in [0, 10000) bps and initial equity must be positive.")
    times, returns, weights, inputs = _prepare_replay_input(
        frame, bindings, {"transaction_cost_bps": bps, "initial_equity": equity},
    )
    library, receipt = _loaded()
    output = _native_call(library, times, returns, weights, fee_rate, equity)
    _verify_accounting(output, returns, weights, fee_rate, equity)
    return library, receipt, output, times, inputs


def run_replay(
    frame: pd.DataFrame, *, signal_time_col: str, execution_time_col: str, end_time_col: str,
    return_columns: list[str] | tuple[str, ...], weight_columns: list[str] | tuple[str, ...],
    transaction_cost_bps: float, initial_equity: float,
) -> dict[str, Any]:
    """Replay supplied holdings targets with explicit fees and timing, offline."""
    _, receipt, output, times, inputs = _verified_replay(
        frame, signal_time_col=signal_time_col, execution_time_col=execution_time_col, end_time_col=end_time_col,
        return_columns=return_columns, weight_columns=weight_columns, transaction_cost_bps=transaction_cost_bps,
        initial_equity=initial_equity,
    )
    return _replay_result(receipt, output, times, inputs)


def _replay_result(receipt, output, times, inputs) -> dict[str, Any]:
    """The existing bounded JSON result, shared with the workflow's CSV delivery."""
    metrics, series = _summarize(output, times, inputs["time_format"])
    return {
        "contract_version": "quant_replay_v1", "engine": dict(receipt),
        "inputs": inputs, "assumptions": dict(_REPLAY_ASSUMPTIONS), "metrics": metrics, "series": series,
    }


def _replay_ledger(output: np.ndarray, times: np.ndarray, clock: str) -> pd.DataFrame:
    """Retain every verified native ledger row without another simulation or row JSON."""
    from .checks.ar_cancellation import check_cancellation

    data = {"row": np.arange(len(output), dtype=np.int64)}
    for column, name in enumerate(("signal_time", "execution_time", "end_time")):
        labels = []
        for start in range(0, len(output), 256):
            check_cancellation()
            labels.extend(_time_label(int(value), clock) for value in times[start:start + 256, column])
        data[name] = labels
    data.update({name: output[:, column] for column, name in enumerate(_LEDGER_VALUES)})
    data["net_exposure"] = output[:, _EXPOSURE]
    end = output[:, _END]
    peak = np.maximum.accumulate(np.concatenate(([output[0, _START]], end)))[1:]
    data["drawdown"] = (peak - end) / peak
    check_cancellation()
    return pd.DataFrame(data, copy=False)


def _tail_invalid(message: str) -> QuantReplayError:
    return QuantReplayError("QUANT_REPLAY_TAIL_RISK_INVALID_INPUT", message)


def _tail_native_invalid(message: str, row: int | None = None) -> QuantReplayError:
    return QuantReplayError("QUANT_REPLAY_TAIL_RISK_NATIVE_INVALID", message, row=row)


def validate_tail_risk_window(rows: int, window: int, end_period: int = 0) -> int:
    if (isinstance(end_period, (bool, np.bool_)) or not isinstance(end_period, Integral)
            or not 0 <= end_period <= min(rows, MAX_PERIODS)):
        raise _tail_invalid(f"end_period must be zero for the last row or a period from 1 to {min(rows, MAX_PERIODS)}.")
    periods = int(end_period) or rows
    if not 2 <= periods <= MAX_PERIODS:
        raise _tail_invalid(f"Historical tail risk requires a replay prefix of 2 to {MAX_PERIODS} completed periods.")
    maximum_window = min(periods, MAX_RISK_WINDOW)
    if isinstance(window, (bool, np.bool_)) or not isinstance(window, Integral) or not 2 <= window <= maximum_window:
        raise _tail_invalid(f"The tail window must be an integer from 2 to {maximum_window} observations.")
    return periods


def _tail_native_call(library, ledger: np.ndarray, window: int, confidence_bps: int) -> tuple[float, float]:
    if ledger.ndim != 2 or ledger.shape[1] != _OUTPUT_COLUMNS or ledger.dtype != np.float64 or not ledger.flags.c_contiguous:
        raise _tail_native_invalid("Historical tail risk requires a contiguous verified replay ledger.")
    output = np.full(2, np.nan)
    error_row = _SIZE(_NO_ROW)
    status = library.arboris_quant_tail_risk(
        len(ledger), window, confidence_bps, ledger.ctypes.data_as(_DOUBLE), ledger.size,
        output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error_row),
    )
    if status in (4, 7) and 0 <= error_row.value < len(ledger):
        raise _tail_native_invalid("Historical tail risk rejected a verified ledger value.", error_row.value)
    if status != 0 or error_row.value != _NO_ROW:
        raise _tail_native_invalid("The verified historical tail risk library returned an invalid status.")
    return float(output[0]), float(output[1])


def _verify_tail_risk(net_returns, confidence_bps: int, value_at_risk: float, expected_shortfall: float) -> None:
    error = "Historical tail risk failed independent empirical rank or weighted tail checks."
    if not math.isfinite(value_at_risk) or not value_at_risk <= expected_shortfall <= 1.0:
        raise _tail_native_invalid(error)
    units = len(net_returns) * (_BASIS_POINTS - confidence_bps)
    more = tied = 0
    highest = value_at_risk
    smallest_above = math.inf
    for value in net_returns:
        loss = -float(value)
        if loss > value_at_risk:
            more += 1
            highest = max(highest, loss)
            smallest_above = min(smallest_above, loss)
        elif loss == value_at_risk:
            tied += 1
    if not more <= units // _BASIS_POINTS < more + tied or expected_shortfall > highest:
        raise _tail_native_invalid(error)
    remaining_units = units - more * _BASIS_POINTS
    smallest_included = value_at_risk if remaining_units else smallest_above
    if expected_shortfall < smallest_included:
        raise _tail_native_invalid(error)
    scale = max(abs(highest), abs(smallest_included))
    if scale == 0:
        if expected_shortfall != 0:
            raise _tail_native_invalid(error)
        return
    weight = _BASIS_POINTS / units
    losses = (-float(value) for value in net_returns)
    boundary = ((value_at_risk / scale) * (remaining_units / units),) if remaining_units else ()
    mean = math.fsum(chain(((loss / scale) * weight for loss in losses if loss > value_at_risk), boundary))
    # Compare after both estimates have rounded to the output loss units.
    rounded_mean = min(highest, max(smallest_included, mean * scale))
    if abs(expected_shortfall - rounded_mean) / scale > _ACCOUNTING_RTOL:
        raise _tail_native_invalid(error)


def run_replay_tail_risk(
    frame: pd.DataFrame, *, signal_time_col: str, execution_time_col: str, end_time_col: str,
    return_columns: list[str] | tuple[str, ...], weight_columns: list[str] | tuple[str, ...],
    transaction_cost_bps: float, initial_equity: float, window: int, confidence_bps: int = 9500, end_period: int = 0,
) -> dict[str, Any]:
    """Measure trailing historical VaR and ES on simulated, fee-inclusive returns."""
    if not isinstance(frame, pd.DataFrame) or isinstance(frame.columns, pd.MultiIndex):
        raise _tail_invalid("Historical tail risk requires a table with flat columns.")
    periods = validate_tail_risk_window(len(frame), window, end_period)
    if (isinstance(confidence_bps, (bool, np.bool_)) or not isinstance(confidence_bps, Integral)
            or not 1 <= confidence_bps < _BASIS_POINTS):
        raise _tail_invalid("confidence_bps must be an integer from 1 to 9999.")
    window, confidence_bps = int(window), int(confidence_bps)
    prefix = frame if periods == len(frame) else frame.iloc[:periods]
    library, receipt, ledger, times, inputs = _verified_replay(
        prefix, signal_time_col=signal_time_col, execution_time_col=execution_time_col, end_time_col=end_time_col,
        return_columns=return_columns, weight_columns=weight_columns, transaction_cost_bps=transaction_cost_bps,
        initial_equity=initial_equity,
    )
    var, es = _tail_native_call(library, ledger, window, confidence_bps)
    first = periods - window
    _verify_tail_risk(ledger[first:, _RETURN], confidence_bps, var, es)
    clock = inputs["time_format"]
    return {
        "contract_version": "quant_replay_tail_risk_v1", "engine": dict(receipt),
        "inputs": {**inputs, "end_period": periods, "window": window, "confidence_bps": confidence_bps},
        "assumptions": {
            **_REPLAY_ASSUMPTIONS, "scope": "offline_simulation_descriptive_tail_risk",
            "as_of_basis": "completed_period_end_inclusive", "window_basis": "trailing_periods_through_end_period",
            "loss_basis": "negative_simulated_net_simple_return", "units": "fraction_of_starting_period_equity",
            "value_at_risk_method": "inverse_empirical_loss_cdf",
            "expected_shortfall_method": "mean_worst_empirical_loss_with_fractional_boundary", "annualized": False,
        },
        "metrics": {
            "value_at_risk": var, "expected_shortfall": es, "window": window, "confidence_bps": confidence_bps,
            "tail_observation_equivalent": window * (_BASIS_POINTS - confidence_bps) / _BASIS_POINTS,
        },
        "tail_window": {
            "privacy": "local_only", "first_period": first + 1, "as_of_period": periods,
            "first_end_time": _time_label(int(times[first, 2]), clock), "as_of_end_time": _time_label(int(times[-1, 2]), clock),
        },
    }


def _risk_invalid(message: str) -> QuantReplayError:
    return QuantReplayError("QUANT_ROLLING_RISK_INVALID_INPUT", message)


def _risk_native_invalid(message: str, row: int | None = None) -> QuantReplayError:
    return QuantReplayError("QUANT_ROLLING_RISK_NATIVE_INVALID", message, row=row)


_RISK_ERRORS = {
    2: ("QUANT_ROLLING_RISK_TIME_ORDER", "Observation availability timestamps must be strictly increasing."),
    4: ("QUANT_ROLLING_RISK_RETURN", "Each observation must have a finite return for every selected column."),
    7: ("QUANT_ROLLING_RISK_NUMERICAL", "The rolling risk result exceeds the supported binary64 range."),
}


def _risk_native_call(library, times, returns, window) -> tuple[np.ndarray, np.ndarray]:
    rows, width = returns.shape
    complete = rows - window + 1
    covariance_offset = complete * width
    expected = covariance_offset + width * width
    if library.arboris_quant_risk_output_len(rows, width, window) != expected:
        raise _risk_native_invalid("The rolling risk ABI returned an invalid output length.")
    output = np.full(expected, np.nan)
    error_row = _SIZE(_NO_ROW)
    status = library.arboris_quant_risk(
        rows, width, window, times.ctypes.data_as(_I64), times.size,
        returns.ctypes.data_as(_DOUBLE), returns.size,
        output.ctypes.data_as(_DOUBLE), output.size, ctypes.byref(error_row),
    )
    if status in _RISK_ERRORS and 0 <= error_row.value < rows:
        code, message = _RISK_ERRORS[status]
        raise QuantReplayError(code, message, row=error_row.value)
    if status != 0 or error_row.value != _NO_ROW:
        raise _risk_native_invalid("The verified rolling risk library returned an invalid status.")
    return output[:covariance_offset].reshape(complete, width), output[covariance_offset:].reshape(width, width)


def _risk_agrees(observed, expected, scale) -> bool:
    error = np.abs(observed - expected)
    relative = np.divide(error, scale, out=np.zeros_like(error), where=scale > 0)
    return bool(np.isfinite(expected).all() and np.all(np.where(scale > 0, relative <= _RISK_RTOL, error == 0)))


def _verify_risk(volatility, covariance, returns, window) -> None:
    rows, width = returns.shape
    complete = rows - window + 1
    if (volatility.shape != (complete, width) or covariance.shape != (width, width)
            or not np.isfinite(volatility).all() or not np.isfinite(covariance).all()
            or np.any(volatility < 0) or np.any(np.diag(covariance) < 0)
            or not np.array_equal(covariance, covariance.T)):
        raise _risk_native_invalid("The rolling risk output is incomplete, non-finite, or nonsymmetric.")
    # Independent two-pass checks on bounded first, middle and last windows.
    with np.errstate(over="ignore", invalid="ignore", under="ignore", divide="ignore"):
        for index in dict.fromkeys((0, complete // 2, complete - 1)):
            sample = returns[index:index + window]
            offsets = sample - sample[0]
            centered = offsets - offsets.mean(axis=0)
            std = np.sqrt(np.einsum("ij,ij->j", centered, centered) / (window - 1))
            row = index + window - 1
            if not _risk_agrees(volatility[index], std, std):
                raise _risk_native_invalid("Rolling volatility failed an independent trailing-window check.", row)
            if index == complete - 1:
                expected = centered.T @ centered / (window - 1)
                if not _risk_agrees(covariance, expected, np.outer(std, std)):
                    raise _risk_native_invalid("Latest covariance failed an independent trailing-window check.", row)


def validate_risk_rows(rows: int) -> None:
    if not 2 <= rows <= MAX_PERIODS:
        raise _risk_invalid(f"Rolling risk requires a table with 2 to {MAX_PERIODS} observations.")


def validate_risk_window(rows: int, window: int) -> None:
    maximum_window = min(rows, MAX_RISK_WINDOW)
    if isinstance(window, (bool, np.bool_)) or not isinstance(window, Integral) or not 2 <= window <= maximum_window:
        raise _risk_invalid(f"The rolling window must be an integer from 2 to {maximum_window} observations.")


def run_rolling_risk(
    frame: pd.DataFrame, *, time_col: str, return_columns: list[str] | tuple[str, ...], window: int,
) -> dict[str, Any]:
    """Return trailing sample volatility and the latest complete covariance."""
    validate_risk_rows(len(frame) if isinstance(frame, pd.DataFrame) else 0)
    if not isinstance(return_columns, (list, tuple)) or not 1 <= len(return_columns) <= MAX_ASSETS:
        raise _risk_invalid(f"Select 1 to {MAX_ASSETS} ordered return columns.")
    columns = tuple(return_columns)
    names = (time_col, *columns)
    if (not all(_valid_name(name) for name in names) or len(set(names)) != len(names)
            or not frame.columns.is_unique or not all(name in frame.columns for name in names)):
        raise _risk_invalid("Each rolling risk column must have a distinct, nonempty name present in the table.")
    validate_risk_window(len(frame), window)
    window = int(window)
    times, clock = _time_matrix(frame, (time_col,), invalid=_risk_invalid)
    returns = _numeric_matrix(frame, columns, invalid=_risk_invalid)
    try:
        library, receipt = _loaded()
    except QuantReplayError as error:
        suffix = error.code.removeprefix("QUANT_REPLAY_")
        raise QuantReplayError(f"QUANT_ROLLING_RISK_{suffix}", str(error), row=error.row) from error
    volatility, covariance = _risk_native_call(library, times, returns, window)
    _verify_risk(volatility, covariance, returns, window)
    n = len(frame)
    complete = n - window + 1
    return {
        "contract_version": "quant_rolling_risk_v1", "engine": dict(receipt),
        "inputs": {"time_col": time_col, "return_columns": list(columns), "window": window,
                   "observation_count": n, "asset_count": len(columns), "time_format": clock},
        "assumptions": {
            "scope": "offline_descriptive_statistics", "timestamp_evidence": "supplied_values_order_only",
            "source_vintage_verified": False, "naive_datetime_timezone": "UTC", "annualized": False,
            "units": {"volatility": "input_return_units", "covariance": "squared_input_return_units",
                      "frequency": "per_observation"},
            "window_basis": "complete_trailing_observation_count", "covariance_divisor": "window_minus_one",
            "missing_policy": "reject",
        },
        "metrics": {"observation_count": n, "asset_count": len(columns), "window": window,
                    "complete_windows": complete, "warmup_rows": window - 1,
                    "latest_max_volatility": float(volatility[-1].max()),
                    "maximum_volatility": float(volatility.max())},
        "series": {
            "privacy": "local_only", "total_rows": complete, "truncated": complete > MAX_SERIES_POINTS,
            "rows": [
                {"row": index + window - 1, "time": _time_label(int(times[index + window - 1, 0]), clock),
                 "volatility": volatility[index].tolist()}
                for index in _preview_indices(complete)
            ],
        },
        "latest_covariance": {
            "privacy": "local_only", "row": n - 1, "time": _time_label(int(times[-1, 0]), clock),
            "columns": list(columns), "matrix": covariance.tolist(), "volatility": volatility[-1].tolist(),
        },
    }
