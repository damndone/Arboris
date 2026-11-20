"""Point-in-time offline minimum-variance and equal-weight replay."""
from __future__ import annotations

import ctypes
from itertools import chain
import math
from numbers import Integral

import numpy as np
import pandas as pd

from .native_quant_replay import (
    MAX_PERIODS, QuantReplayError, _ACCOUNTING_RTOL, _BASIS_POINTS, _DOUBLE, _I64, _NO_ROW,
    _OUTPUT_COLUMNS, _REPLAY_ASSUMPTIONS, _REPLAY_ERRORS, _RETURN, _SIZE, _loaded, _number, _numeric_matrix,
    _summarize, _time_label, _time_matrix, _valid_name,
)
from .native_time_series import _native_checkpoint


_MAX_ASSETS = 16
_MAX_WINDOW = 512
_MAX_EVALUATIONS = 256
_EVIDENCE_FIELDS = ('sample_rank', 'objective_variance', 'normalized_kkt_residual', 'residual_cash_weight',
                    'funding_adjustment')
_EPSILON = np.finfo(np.float64).eps


def _invalid(message: str) -> QuantReplayError:
    return QuantReplayError('QUANT_WALK_FORWARD_INVALID_INPUT', message)


def _native_invalid(message: str, row: int | None = None) -> QuantReplayError:
    return QuantReplayError('QUANT_WALK_FORWARD_NATIVE_INVALID', message, row=row)


def _integer(value, low: int, high: int) -> bool:
    return isinstance(value, Integral) and not isinstance(value, (bool, np.bool_)) and low <= value <= high


def validate_walk_forward_size(rows: int, window: int, first_period: int, end_period: int) -> tuple[int, int]:
    if not 5 <= rows <= MAX_PERIODS or not _integer(window, 2, _MAX_WINDOW):
        raise _invalid(f'Use 5 to {MAX_PERIODS} rows and a lookback of 2 to {_MAX_WINDOW} periods.')
    if not _integer(first_period, 0, rows) or not _integer(end_period, 0, rows):
        raise _invalid('Choose integer evaluation bounds within the input. Zero uses the earliest or latest eligible period.')
    first, completed = int(first_period or window + 2), int(end_period or rows)
    if first < window + 2 or not 2 <= completed - first + 1 <= _MAX_EVALUATIONS:
        raise _invalid('Evaluation must start at least two periods after the lookback and include 2 to 256 periods.')
    return first, completed


def _verify_cash(weights: np.ndarray, observed: float) -> bool:
    cash = math.fsum(chain((1.0,), (-weight for weight in weights)))
    return (0 <= cash <= _EPSILON and 0 <= observed <= _EPSILON
            and abs(cash - observed) <= _ACCOUNTING_RTOL * _EPSILON)


def _verify_ledger(ledger, returns, weights, cash, fee, equity, first):
    prior = np.zeros(returns.shape[1], dtype=np.float64)
    for offset, (values, realized, target, residual) in enumerate(zip(ledger, returns, weights, cash, strict=True)):
        opening, funded, ending, exposure, fees, notional, holding, pnl, net = map(float, values)
        try:
            with np.errstate(over='raise', invalid='raise', under='ignore'):
                dollars = funded * target
                trade = math.fsum(np.abs(dollars - prior))
                next_holdings = dollars * (1 + realized)
                close = math.fsum(chain(next_holdings, (funded * residual,)))
                fee_due = fee * trade
                gain = math.fsum(dollars * realized)
                profit = gain - fee_due
                net_return = -1.0 if ending == 0.0 else profit / equity
            monetary = ((opening, equity), (funded, equity - fee_due), (ending, close), (fees, fee_due),
                        (notional, trade), (holding, gain), (pnl, profit))
            money_scale = max(opening, ending)
            valid = (
                opening > 0 and funded > 0 and ending >= 0 and 0 <= exposure <= 1 and fees >= 0 and notional >= 0
                and net >= -1 and abs(exposure - (1.0 - residual)) <= _ACCOUNTING_RTOL
                and abs(net - net_return) / max(1.0, abs(net_return)) <= _ACCOUNTING_RTOL
                and all(math.isfinite(expected) and abs(actual - expected) / money_scale <= _ACCOUNTING_RTOL
                        for actual, expected in monetary)
            )
        except (ArithmeticError, ValueError):
            valid = False
        if not valid:
            raise _native_invalid('Walk-forward ledger failed independent accounting checks.', first - 1 + offset)
        equity, prior = close, next_holdings


def _path_metrics(ledger, times, clock):
    metrics, series = _summarize(ledger, times, clock)
    realized = ledger[:, _RETURN]
    magnitude = float(np.max(np.abs(realized)))
    spread = 0.0
    if magnitude:
        scaled = realized / magnitude
        spread = float(np.std(scaled - scaled[0], ddof=1) * magnitude)
    if not math.isfinite(spread) or (spread == 0 and np.any(realized != realized[0])):
        raise QuantReplayError('QUANT_WALK_FORWARD_NUMERICAL', 'Realized sample volatility exceeded its binary64 range.')
    return {**metrics, 'realized_net_return_volatility': spread}, series


def run_walk_forward(
    frame: pd.DataFrame, *, time_col: str, return_columns: list[str], window: int, first_period: int = 0,
    end_period: int = 0, shrinkage_bps: int = 0, transaction_cost_bps: float = 0.0, initial_equity: float = 1.0,
):
    if not isinstance(frame, pd.DataFrame) or isinstance(frame.columns, pd.MultiIndex):
        raise _invalid('Select a DataFrame with flat completion-time and simple-return columns.')
    first, completed = validate_walk_forward_size(len(frame), window, first_period, end_period)
    if not isinstance(return_columns, (list, tuple)) or not 2 <= len(return_columns) <= _MAX_ASSETS:
        raise _invalid(f'Choose 2 to {_MAX_ASSETS} ordered return columns.')
    columns = tuple(return_columns)
    names = (time_col, *columns)
    if (not all(_valid_name(name) for name in names) or len(set(names)) != len(names)
            or not frame.columns.is_unique or not all(name in frame.columns for name in names)):
        raise _invalid('Choose distinct existing time and return columns.')
    if not _integer(shrinkage_bps, 0, _BASIS_POINTS):
        raise _invalid('shrinkage_bps must be an integer from 0 to 10000.')
    try:
        bps = _number(transaction_cost_bps, 'transaction_cost_bps')
        equity = _number(initial_equity, 'initial_equity')
    except QuantReplayError as error:
        raise _invalid(str(error)) from error
    fee = bps / _BASIS_POINTS
    if not 0 <= bps < _BASIS_POINTS or fee >= 1 or equity <= 0:
        raise _invalid('Transaction costs must be in [0, 10000) bps and initial equity must be positive.')

    prefix = frame if completed == len(frame) else frame.iloc[:completed]
    times, clock = _time_matrix(prefix, (time_col,), invalid=_invalid)
    returns = _numeric_matrix(prefix, columns, invalid=_invalid)
    library, engine = _loaded()
    width = len(columns)
    stride = 2 * _OUTPUT_COLUMNS + width + len(_EVIDENCE_FIELDS)
    size = width + 2 + (completed - first + 1) * stride
    packed = np.full(size, np.nan, dtype=np.float64)
    error_row = _SIZE(_NO_ROW)
    with _native_checkpoint() as poll:
        status = library.arboris_quant_walk_forward(
            completed, width, int(window), first, int(shrinkage_bps), times.ctypes.data_as(_I64), times.size,
            returns.ctypes.data_as(_DOUBLE), returns.size, fee, equity, packed.ctypes.data_as(_DOUBLE), packed.size,
            ctypes.byref(error_row), poll,
        )
    if status or error_row.value != _NO_ROW:
        row = error_row.value if error_row.value < completed else None
        if status in _REPLAY_ERRORS:
            code, message = _REPLAY_ERRORS[status]
            raise QuantReplayError(code.replace('QUANT_REPLAY_', 'QUANT_WALK_FORWARD_'), message, row=row)
        if status == 9:
            raise QuantReplayError('QUANT_WALK_FORWARD_UNIDENTIFIED', 'A historical covariance window is degenerate.', row=row)
        if status == 10:
            raise QuantReplayError('QUANT_WALK_FORWARD_NONCONVERGENCE', 'An allocation failed its funding or KKT certificate.', row=row)
        raise _native_invalid('The native library did not return a complete walk-forward result.', row)

    baseline = packed[:width]
    baseline_cash, baseline_adjustment = map(float, packed[width:width + 2])
    rows = packed[width + 2:].reshape(-1, stride)
    policy_ledger, benchmark_ledger = rows[:, :_OUTPUT_COLUMNS], rows[:, _OUTPUT_COLUMNS:2 * _OUTPUT_COLUMNS]
    weights, evidence = rows[:, 2 * _OUTPUT_COLUMNS:2 * _OUTPUT_COLUMNS + width], rows[:, -len(_EVIDENCE_FIELDS):]
    rank, objective, kkt, cash, adjustment = evidence.T
    if not (
        np.isfinite(packed).all() and ((0 <= weights) & (weights <= 1)).all()
        and np.all(np.abs(baseline - 1.0 / width) <= 1e-12) and 0 <= baseline_adjustment <= 1e-12
        and ((1 <= rank) & (rank <= min(width, window - 1)) & (rank == np.floor(rank))).all()
        and (objective > 0).all() and ((0 <= kkt) & (kkt <= 1e-9)).all()
        and ((0 <= adjustment) & (adjustment <= 1e-12)).all()
        and _verify_cash(baseline, baseline_cash)
        and all(_verify_cash(row, residual) for row, residual in zip(weights, cash, strict=True))
    ):
        raise _native_invalid('Walk-forward allocation evidence failed its receipt checks.')
    held = returns[first - 1:]
    _verify_ledger(policy_ledger, held, weights, cash, fee, equity, first)
    _verify_ledger(benchmark_ledger, held, np.broadcast_to(baseline, weights.shape),
                   np.broadcast_to(baseline_cash, cash.shape), fee, equity, first)
    timing = np.column_stack((times[first - 3:-2, 0], times[first - 2:-1, 0], times[first - 1:, 0]))
    policy_metrics, strategy_series = _path_metrics(policy_ledger, timing, clock)
    benchmark_metrics, benchmark_series = _path_metrics(benchmark_ledger, timing, clock)

    decisions = []
    for offset, (date, target, facts) in enumerate(zip(timing, weights, evidence, strict=True)):
        period = first + offset
        decisions.append({
            'period': period, 'first_training_period': period - int(window) - 1, 'last_training_period': period - 2,
            'as_of_time': _time_label(int(date[0]), clock), 'execution_time': _time_label(int(date[1]), clock),
            'end_time': _time_label(int(date[2]), clock), 'target': dict(zip(columns, map(float, target), strict=True)),
            **{name: int(value) if name == 'sample_rank' else float(value)
               for name, value in zip(_EVIDENCE_FIELDS, facts, strict=True)},
        })
    return {
        'contract_version': 'quant_walk_forward_v1', 'engine': dict(engine),
        'inputs': {'time_col': time_col, 'return_columns': list(columns), 'asset_count': width, 'window': int(window),
                   'first_period': first, 'end_period': completed, 'evaluated_periods': len(rows), 'time_format': clock,
                   'shrinkage_bps': int(shrinkage_bps), 'transaction_cost_bps': bps, 'initial_equity': equity},
        'assumptions': {**_REPLAY_ASSUMPTIONS, 'scope': 'offline_walk_forward_simulation',
                        'strategy_policy': 'long_only_minimum_variance', 'embargo_periods': 1,
                        'interval_policy': 'adjacent_supplied_completion_times',
                        'shrinkage_target': 'mean_sample_variance_identity', 'sample_divisor': 'periods_minus_one',
                        'benchmark_policy': 'equal_weight_rebalanced_each_evaluation_period',
                        'execution_policy': 'both_paths_rebalanced_each_evaluation_period',
                        'funding_rounding': 'largest_target_weight_certified_after_adjustment', 'annualized': False},
        'metrics': {'strategy': policy_metrics, 'benchmark': benchmark_metrics,
                    'cumulative_net_return_difference': policy_metrics['cumulative_net_return'] - benchmark_metrics['cumulative_net_return'],
                    'max_normalized_kkt_residual': float(kkt.max()), 'max_strategy_funding_adjustment': float(adjustment.max())},
        'strategy_series': strategy_series, 'benchmark_series': benchmark_series,
        'decisions': {'privacy': 'local_only', 'benchmark_target': dict(zip(columns, map(float, baseline), strict=True)),
                      'benchmark_residual_cash_weight': baseline_cash, 'benchmark_funding_adjustment': baseline_adjustment,
                      'rows': decisions},
    }
