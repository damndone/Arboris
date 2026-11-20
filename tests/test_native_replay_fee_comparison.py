"""Shared-input offline fee scenarios and independent accounting receipts."""
from __future__ import annotations

import ctypes
from fractions import Fraction
import json
import math
import shutil

import numpy as np
import pytest

from tests.test_native_quant_replay import OPTIONS, _exact_replay, _frame
from workbench import native_build, native_quant_replay as replay
from workbench.checks.ar_cancellation import cancellation_scope


SETUP = {key: value for key, value in OPTIONS.items() if key != 'transaction_cost_bps'}
FEES = {'base_transaction_cost_bps': 0.0, 'higher_transaction_cost_bps': 156.25}
TOLERANCE = {'rel': 2e-13, 'abs': 2e-13}


@pytest.fixture(scope='module')
def build(tmp_path_factory):
    if shutil.which('cargo') is None or shutil.which('rustc') is None:
        pytest.skip('Rust compiler unavailable for the explicit offline native build')
    output = tmp_path_factory.mktemp('quant-fee-comparison-native')
    return output, native_build.build(replay._MODULE, output)


@pytest.fixture
def verified_native(build, monkeypatch):
    output, manifest = build
    replay._load_once.cache_clear()
    monkeypatch.setattr(replay, '_output_directory', lambda: output)
    yield manifest
    replay._load_once.cache_clear()


def run(frame, **overrides):
    from workbench.native_quant_fee_comparison import run_replay_fee_comparison

    return run_replay_fee_comparison(frame, **(SETUP | FEES | overrides))


@pytest.mark.parametrize('overrides', [
    {'base_transaction_cost_bps': True}, {'base_transaction_cost_bps': -1},
    {'base_transaction_cost_bps': 156.25}, {'base_transaction_cost_bps': 200},
    {'higher_transaction_cost_bps': 0}, {'higher_transaction_cost_bps': 10_000},
    {'higher_transaction_cost_bps': math.inf}, {'higher_transaction_cost_bps': 5e-324},
    {'initial_equity': 0}, {'initial_equity': math.nan},
])
def test_fee_comparison_rejects_invalid_rates_before_native_load(monkeypatch, overrides):
    monkeypatch.setattr(replay, '_loaded', lambda: pytest.fail('invalid inputs reached native load'))
    with pytest.raises(replay.QuantReplayError) as error:
        run(_frame(), **overrides)
    assert error.value.code == 'QUANT_REPLAY_INVALID_INPUT'


def switched_frame():
    frame = _frame(6)
    frame['return_a'] = [0.125, -0.0625, 0.125, 0.25, -0.25, -0.0625]
    frame['return_b'] = [0.0, -0.25, 0.125, 0.125, 0.25, 0.125]
    frame['weight_a'] = [1.0, 0.0, 0.5, 0.0, 0.125, 0.125]
    frame['weight_b'] = [0.0, 1.0, 0.25, 0.0, 0.875, 0.875]
    return frame


@pytest.mark.parametrize('base,higher', [(0.0, 156.25), (156.25, 625.0)])
def test_fee_comparison_matches_both_fraction_ledgers(verified_native, base, higher):
    frame = switched_frame()
    result = run(frame, base_transaction_cost_bps=base, higher_transaction_cost_bps=higher)
    assert result['contract_version'] == 'quant_replay_fee_comparison_v1'
    assert result['engine']['build_identity_sha256'] == verified_native['build_identity_sha256']
    assert result['inputs']['base_transaction_cost_bps'] == base
    assert result['inputs']['higher_transaction_cost_bps'] == higher
    assert result['inputs']['asset_count'] == 2 and result['inputs']['period_count'] == len(frame)
    assert result['assumptions']['scope'] == 'offline_simulation'
    assert result['assumptions']['source_vintage_verified'] is False
    assert result['assumptions']['comparison_direction'] == 'higher_minus_base'
    for name, bps in (('base', base), ('higher', higher)):
        exact = _exact_replay(frame, Fraction(bps) / 10_000)
        path = result['series'][name]
        assert path['privacy'] == 'local_only' and not path['truncated']
        assert len(path['rows']) == path['total_rows'] == len(frame)
        peak = Fraction(100)
        drawdowns = []
        for index, (reported, expected) in enumerate(zip(path['rows'], exact, strict=True)):
            assert (reported['row'], reported['execution_time'], reported['end_time']) == (index, str(index + 1), str(index + 2))
            for field, value in expected.items():
                assert reported[field] == pytest.approx(float(value), **TOLERANCE)
            peak = max(peak, expected['ending_equity'])
            drawdowns.append((peak - expected['ending_equity']) / peak)
            assert reported['drawdown'] == pytest.approx(float(drawdowns[-1]), **TOLERANCE)
        metrics = result['metrics'][name]
        expected = {
            'initial_equity': Fraction(100), 'final_equity': exact[-1]['ending_equity'],
            'cumulative_net_return': exact[-1]['ending_equity'] / 100 - 1,
            'total_fees': sum(row['fees'] for row in exact),
            'total_traded_notional': sum(row['traded_notional'] for row in exact),
            'max_drawdown': max(drawdowns),
            'max_gross_exposure': max(row['gross_exposure'] for row in exact),
            'max_net_exposure': max(row['net_exposure'] for row in exact),
        }
        assert metrics == pytest.approx({key: float(value) for key, value in expected.items()}, **TOLERANCE)
    assert result['metrics']['higher_minus_base'] == pytest.approx({
        field: result['metrics']['higher'][field] - result['metrics']['base'][field]
        for field in ('final_equity', 'cumulative_net_return', 'total_fees', 'total_traded_notional', 'max_drawdown')
    }, **TOLERANCE)
    json.dumps(result, allow_nan=False)


def test_fee_comparison_prepares_each_matrix_once_and_aligns_bounded_paths(verified_native, monkeypatch):
    original = replay._numeric_matrix
    inputs = []

    def record(frame, columns):
        inputs.append(columns)
        return original(frame, columns)

    monkeypatch.setattr(replay, '_numeric_matrix', record)
    frame = _frame(300)
    result = run(frame)
    assert inputs == [tuple(OPTIONS['return_columns']), tuple(OPTIONS['weight_columns'])]
    for name, bps in (('base', 0.0), ('higher', 156.25)):
        separate = replay.run_replay(frame, **(SETUP | {'transaction_cost_bps': bps}))
        assert result['series'][name] == separate['series']
        assert result['metrics'][name] == separate['metrics']
        assert len(result['series'][name]['rows']) == replay.MAX_SERIES_POINTS
        assert result['series'][name]['truncated'] and result['series'][name]['total_rows'] == 300


def test_fee_comparison_preserves_no_turnover_and_terminal_loss(verified_native):
    frame = _frame(2).assign(weight_a=0.0, weight_b=0.0)
    result = run(frame)
    assert result['metrics']['base'] == result['metrics']['higher']
    assert set(result['metrics']['higher_minus_base'].values()) == {0.0}

    frame = frame.assign(weight_a=1.0, return_a=[0.0, -1.0])
    result = run(frame)
    for scenario in ('base', 'higher'):
        assert result['metrics'][scenario]['final_equity'] == 0.0
        assert result['metrics'][scenario]['max_drawdown'] == 1.0
    frame['return_a'] = [-1.0, 0.0]
    with pytest.raises(replay.QuantReplayError) as error:
        run(frame)
    assert (error.value.code, error.value.row) == ('QUANT_REPLAY_NONPOSITIVE_EQUITY', 1)


def test_fee_comparison_identifies_failure_specific_to_higher_fee_path(verified_native):
    frame = _frame(2).assign(weight_a=[1.0, 0.0], weight_b=0.0, return_a=0.0, return_b=0.0)
    equity = 1e-308
    base = replay.run_replay(frame, **(SETUP | {'initial_equity': equity, 'transaction_cost_bps': 0.0}))
    assert base['metrics']['final_equity'] == equity
    with pytest.raises(replay.QuantReplayError, match='Higher-fee scenario') as error:
        run(frame, initial_equity=equity, higher_transaction_cost_bps=math.nextafter(10_000.0, 0.0))
    assert (error.value.code, error.value.row) == ('QUANT_REPLAY_NUMERICAL', 1)


def native_call(library, frame, *, poll=None, overlap=False):
    times, _ = replay._time_matrix(frame, ('signal', 'execute', 'end'))
    returns = replay._numeric_matrix(frame, tuple(OPTIONS['return_columns']))
    weights = replay._numeric_matrix(frame, tuple(OPTIONS['weight_columns']))
    rows, width = returns.shape
    output = np.full((2, rows, replay._OUTPUT_COLUMNS), -9471.0)
    targets = output.ravel()[:weights.size] if overlap else weights
    row = replay._SIZE(replay._NO_ROW)
    status = library.arboris_quant_replay_fee_comparison(
        rows, width, times.ctypes.data_as(replay._I64), times.size,
        returns.ctypes.data_as(replay._DOUBLE), returns.size, targets.ctypes.data_as(replay._DOUBLE), targets.size,
        0.0, 1 / 64, 100.0, output.ctypes.data_as(replay._DOUBLE), output.size,
        ctypes.byref(row), replay._CHECKPOINT() if poll is None else poll,
    )
    return status, row.value, output


def test_fee_comparison_abi_both_paths_equal_separate_replay_bytes(verified_native):
    library, _ = replay._loaded()
    frame = switched_frame()
    status, row, output = native_call(library, frame)
    assert (status, row) == (0, replay._NO_ROW)
    times, _ = replay._time_matrix(frame, ('signal', 'execute', 'end'))
    returns = replay._numeric_matrix(frame, tuple(OPTIONS['return_columns']))
    weights = replay._numeric_matrix(frame, tuple(OPTIONS['weight_columns']))
    for packed, rate in zip(output, (0.0, 1 / 64), strict=True):
        separate = replay._native_call(library, times, returns, weights, rate, 100.0)
        assert packed.tobytes() == separate.tobytes()


def test_fee_comparison_leaves_both_abi_paths_unwritten_on_failure(verified_native):
    library, _ = replay._loaded()
    frame = _frame(130)
    checks = 0

    @replay._CHECKPOINT
    def poll():
        nonlocal checks
        checks += 1
        return int(checks == 3)

    status, row, output = native_call(library, frame, poll=poll)
    assert (status, row, checks) == (11, replay._NO_ROW, 3)
    assert np.all(output == -9471.0)
    status, row, output = native_call(library, frame, overlap=True)
    assert (status, row) == (1, replay._NO_ROW) and np.all(output == -9471.0)
    frame.loc[70, 'signal'] = frame.loc[70, 'execute']
    status, row, output = native_call(library, frame)
    assert (status, row) == (3, 70) and np.all(output == -9471.0)


def test_fee_comparison_rethrows_cancellation_from_inside_native_replay(verified_native):
    checks = 0
    stopped = RuntimeError('cancel fee comparison')

    def poll():
        nonlocal checks
        checks += 1
        if checks == 4:
            raise stopped

    with cancellation_scope(poll), pytest.raises(RuntimeError) as error:
        run(_frame(300))
    assert error.value is stopped
