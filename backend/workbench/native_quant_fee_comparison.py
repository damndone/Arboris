"""Offline cost sensitivity for identical portfolio targets and holding periods."""
from __future__ import annotations

import ctypes
from typing import Any

import numpy as np
import pandas as pd

from . import native_quant_replay as replay
from .checks.ar_cancellation import check_cancellation
from .native_time_series import _native_checkpoint


_SCENARIOS = ('base', 'higher')


def validate_replay_fee_comparison_options(
    base_transaction_cost_bps: float, higher_transaction_cost_bps: float, initial_equity: float,
) -> tuple[float, float, float]:
    base = replay._number(base_transaction_cost_bps, 'base_transaction_cost_bps')
    higher = replay._number(higher_transaction_cost_bps, 'higher_transaction_cost_bps')
    equity = replay._number(initial_equity, 'initial_equity')
    base_rate, higher_rate = base / replay._BASIS_POINTS, higher / replay._BASIS_POINTS
    if not (0 <= base < higher < replay._BASIS_POINTS and 0 <= base_rate < higher_rate < 1 and equity > 0):
        raise replay._invalid('Use distinct fee rates with 0 ≤ base < higher < 10000 bps and positive initial equity.')
    return base, higher, equity


def _native_pair(library, times, returns, weights, fee_rates, equity):
    rows, width = returns.shape
    if library.arboris_quant_replay_output_len(rows) != rows * replay._OUTPUT_COLUMNS:
        raise replay._native_invalid('The quant replay ABI returned an invalid ledger length.')
    output = np.full((len(_SCENARIOS), rows, replay._OUTPUT_COLUMNS), np.nan)
    error_index = replay._SIZE(replay._NO_ROW)
    with _native_checkpoint() as poll:
        status = library.arboris_quant_replay_fee_comparison(
            rows, width, times.ctypes.data_as(replay._I64), times.size,
            returns.ctypes.data_as(replay._DOUBLE), returns.size, weights.ctypes.data_as(replay._DOUBLE), weights.size,
            *fee_rates, equity, output.ctypes.data_as(replay._DOUBLE), output.size, ctypes.byref(error_index), poll,
        )
    if status in replay._REPLAY_ERRORS and error_index.value < len(_SCENARIOS) * rows:
        scenario, row = divmod(error_index.value, rows)
        code, message = replay._REPLAY_ERRORS[status]
        raise replay.QuantReplayError(code, f'{_SCENARIOS[scenario].capitalize()}-fee scenario. {message}', row=row)
    if status or error_index.value != replay._NO_ROW:
        raise replay._native_invalid('The verified quant replay library returned an invalid fee comparison status.')
    return output


def run_replay_fee_comparison(
    frame: pd.DataFrame, *, signal_time_col: str, execution_time_col: str, end_time_col: str,
    return_columns: list[str] | tuple[str, ...], weight_columns: list[str] | tuple[str, ...],
    base_transaction_cost_bps: float, higher_transaction_cost_bps: float, initial_equity: float,
) -> dict[str, Any]:
    check_cancellation()
    bindings = replay._replay_bindings(
        frame, signal_time_col=signal_time_col, execution_time_col=execution_time_col, end_time_col=end_time_col,
        return_columns=return_columns, weight_columns=weight_columns,
    )
    base, higher, equity = validate_replay_fee_comparison_options(
        base_transaction_cost_bps, higher_transaction_cost_bps, initial_equity,
    )
    times, returns, weights, inputs = replay._prepare_replay_input(frame, bindings, {
        'base_transaction_cost_bps': base, 'higher_transaction_cost_bps': higher, 'initial_equity': equity,
    })
    fee_rates = (base / replay._BASIS_POINTS, higher / replay._BASIS_POINTS)
    library, receipt = replay._loaded()
    ledgers = _native_pair(library, times, returns, weights, fee_rates, equity)

    metrics, series = {}, {}
    for name, ledger, rate in zip(_SCENARIOS, ledgers, fee_rates, strict=True):
        replay._verify_accounting(ledger, returns, weights, rate, equity)
        metrics[name], series[name] = replay._summarize(ledger, times, inputs['time_format'])
        check_cancellation()
    difference = {
        field: metrics['higher'][field] - metrics['base'][field]
        for field in ('final_equity', 'total_fees', 'total_traded_notional', 'max_drawdown')
    }
    difference['cumulative_net_return'] = difference['final_equity'] / equity
    return {
        'contract_version': 'quant_replay_fee_comparison_v1', 'engine': dict(receipt), 'inputs': inputs,
        'assumptions': {**replay._REPLAY_ASSUMPTIONS,
                        'scenario_basis': 'common_targets_returns_timing_initial_equity',
                        'comparison_direction': 'higher_minus_base'},
        'metrics': {**metrics, 'higher_minus_base': difference}, 'series': series,
    }
