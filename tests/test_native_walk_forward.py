"""Point-in-time min-variance replay against independent portfolio accounting."""
from __future__ import annotations

import ctypes
import math

import numpy as np
import pytest

from workbench import native_build, native_quant_replay


SIZE = ctypes.c_size_t
DOUBLE = ctypes.POINTER(ctypes.c_double)
I64 = ctypes.POINTER(ctypes.c_int64)
CHECK = ctypes.CFUNCTYPE(ctypes.c_int32)
NO_ROW = SIZE(-1).value
EVIDENCE = 5
LEDGER = 9


@pytest.fixture(scope="module")
def native():
    if not native_build.manifest_path(native_quant_replay._output_directory()).is_file():
        pytest.skip("build with native/quant_replay/build.py to exercise walk-forward")
    return native_quant_replay._loaded()[0].arboris_quant_walk_forward


def sample():
    values = np.array([
        [-.10, .10], [0., -.20], [.10, .10], [-.03, .02], [.20, 0.],
        [-.10, .25], [.11, -.07], [.03, .12], [-.05, .04],
    ])
    return np.arange(1, len(values) + 1, dtype=np.int64) * 10, values


def call(native, times, returns, *, window=3, first=5, last=None, shrinkage=0, fee=.01, equity=100., callback=None,
         length=None, overlap=False):
    panel = np.ascontiguousarray(returns, dtype=np.float64)
    clock = np.ascontiguousarray(times, dtype=np.int64)
    rows, width = panel.shape
    periods = rows if last is None else last
    shape = width + 2 + max(0, periods-first+1) * (2*LEDGER + width + EVIDENCE)
    packed = np.full(max(shape, panel.size) if overlap else shape, np.nan)
    source = panel
    if overlap:
        packed[:panel.size] = panel.ravel()
        source = packed
    row = SIZE(NO_ROW)
    code = native(periods, width, window, first, shrinkage, clock.ctypes.data_as(I64), periods,
                  source.ctypes.data_as(DOUBLE), periods*width, fee, equity,
                  packed.ctypes.data_as(DOUBLE), shape if length is None else length, ctypes.byref(row),
                  callback if callback is not None else CHECK())
    return code, row.value, packed


def success(native, times, returns, **options):
    status, row, output = call(native, times, returns, **options)
    assert (status, row) == (0, NO_ROW)
    assert np.isfinite(output).all()
    width = returns.shape[1]
    return output[:width+2], output[width+2:].reshape(-1, 2*LEDGER+width+EVIDENCE)


def covariance_and_weights(window, shrinkage):
    matrix = np.cov(window, rowvar=False, ddof=1)
    effective = (1-shrinkage)*matrix + shrinkage*np.trace(matrix)/len(matrix)*np.eye(len(matrix))
    if len(matrix) == 2:
        aa, ab, bb = effective[0,0], effective[0,1], effective[1,1]
        first = min(1., max(0., (bb-ab)/(aa+bb-2*ab)))
        weights = np.array([first, 1.-first])
    else:
        from scipy.optimize import minimize

        def loss(w):
            return (w @ effective @ w) / np.trace(effective)

        result = minimize(loss, np.ones(len(matrix))/len(matrix), method="SLSQP",
                          jac=lambda w: 2*effective @ w/np.trace(effective), bounds=[(0,1)]*len(matrix),
                          constraints={"type":"eq", "fun": lambda w: w.sum()-1., "jac": lambda w: np.ones_like(w)},
                          options={"ftol":1e-14, "maxiter":1000})
        assert result.success, result.message
        weights = result.x
    return matrix, effective, weights


def one_replay_step(prior, start, weights, r, fee):
    cash_weight = math.fsum([1., *(-w for w in weights)])
    low, high = 0., start
    for _ in range(100):
        funded = (low+high)/2
        used = funded + fee*math.fsum(abs(funded*w-old) for w, old in zip(weights, prior, strict=True))
        if used > start:
            high = funded
        else:
            low = funded
    funded = (low+high)/2
    exposure = [funded*w for w in weights]
    notional = math.fsum(abs(value-old) for value, old in zip(exposure, prior, strict=True))
    fees = fee*notional
    pnl = math.fsum(value*ret for value, ret in zip(exposure, r, strict=True))
    marked = np.array([value*(1.+ret) for value, ret in zip(exposure, r, strict=True)])
    end = math.fsum([*marked, funded*cash_weight])
    net = pnl-fees
    return marked, [start, funded, end, 1.-cash_weight, fees, notional, pnl, net, -1. if end == 0 else net/start]


def verify_path(rows, base, panel, *, first, window, fee, equity, shrinkage):
    width = panel.shape[1]
    strategy_prior, benchmark_prior = np.zeros(width), np.zeros(width)
    strategy_start = benchmark_start = equity
    for row, value in enumerate(rows, start=first-1):
        strategy, benchmark = value[:LEDGER], value[LEDGER:2*LEDGER]
        strategy_weights = value[2*LEDGER:2*LEDGER+width]
        benchmark_weights = base[:width]
        rank, objective, kkt, cash, adjustment = value[-EVIDENCE:]
        fitting = panel[row-1-window:row-1]
        raw, effective, ref_weights = covariance_and_weights(fitting, shrinkage)
        np.testing.assert_allclose(strategy_weights, ref_weights, atol=2e-7, rtol=0)
        assert rank == np.linalg.matrix_rank(raw, tol=np.max(np.linalg.eigvalsh(raw))*1e-10)
        assert objective == pytest.approx(strategy_weights @ effective @ strategy_weights, rel=2e-13)
        assert cash == math.fsum([1., *(-w for w in strategy_weights)])
        assert 0 <= cash <= np.finfo(float).eps and 0 <= adjustment <= 1e-12
        gradient = (effective @ strategy_weights) / np.max(np.diag(raw))
        reduced = gradient - strategy_weights @ gradient
        certified = np.where(strategy_weights > 0, abs(reduced), np.maximum(-reduced, 0)).max()
        assert 0 <= kkt <= 1e-9 and certified <= 1e-9
        assert kkt == pytest.approx(certified, abs=4e-15)
        strategy_prior, ref_strategy = one_replay_step(strategy_prior, strategy_start, strategy_weights, panel[row], fee)
        benchmark_prior, ref_benchmark = one_replay_step(benchmark_prior, benchmark_start, benchmark_weights, panel[row], fee)
        np.testing.assert_allclose(strategy, ref_strategy, atol=1e-12, rtol=1e-13)
        np.testing.assert_allclose(benchmark, ref_benchmark, atol=1e-12, rtol=1e-13)
        strategy_start, benchmark_start = strategy[2], benchmark[2]


@pytest.mark.parametrize("fee", [0., .01])
def test_analytic_two_asset_walk_forward_matches_cost_inclusive_ledger(native, fee):
    times, returns = sample()
    base, rows = success(native, times, returns, fee=fee)
    np.testing.assert_array_equal(base, [.5, .5, 0., 0.])
    np.testing.assert_allclose(rows[0, 2*LEDGER:2*LEDGER+2], [.75, .25], atol=2e-16)
    assert rows[0, 0] == 100 and rows[0, LEDGER] == 100
    assert rows[0, 1] == pytest.approx(100/(1+fee))
    assert rows[0, 2] == pytest.approx(115/(1+fee))
    assert rows[0, LEDGER+2] == pytest.approx(110/(1+fee))
    verify_path(rows, base, returns, first=5, window=3, fee=fee, equity=100., shrinkage=0.)


def test_multivariate_allocations_match_scipy_and_each_applied_weight_is_funded(native):
    rng = np.random.default_rng(5525)
    values = rng.normal(0, .07, size=(35,3)) @ np.array([[1., .4, .2], [0., 1.2, .8], [0., 0., .2]])
    times = np.arange(len(values), dtype=np.int64)*7
    base, rows = success(native, times, values, window=16, first=20, shrinkage=500, fee=.0025)
    np.testing.assert_allclose(base[:3], [1/3]*3, rtol=0, atol=np.finfo(float).eps)
    assert base[3] == math.fsum([1., *(-w for w in base[:3])]) and base[3] >= 0.
    verify_path(rows, base, values, first=20, window=16, fee=.0025, equity=100., shrinkage=.05)


def test_embargo_current_return_and_unselected_suffix_do_not_leak_into_weights(native):
    times, returns = sample()
    base, before = success(native, times, returns, last=7)
    changes = returns.copy()
    changes[3] = [-.75, .9]
    _, after = success(native, times, changes, last=7)
    np.testing.assert_array_equal(after[0], before[0])
    assert not np.array_equal(after[1, 2*LEDGER:2*LEDGER+2], before[1, 2*LEDGER:2*LEDGER+2])

    changes = returns.copy()
    changes[4] = [.8, -.6]
    _, after = success(native, times, changes, last=7)
    np.testing.assert_array_equal(after[:2, 2*LEDGER:], before[:2, 2*LEDGER:])
    assert after[0, 2] != before[0, 2]

    changes[4] = returns[4]
    changes[7:] = np.nan
    times[7:] = -1
    unaffected_base, unaffected = success(native, times, changes, last=7)
    np.testing.assert_array_equal(unaffected_base, base)
    np.testing.assert_array_equal(unaffected, before)


@pytest.mark.parametrize("change,options,status,error_row", [
    ("clock", {}, 2, 3), ("nonfinite", {}, 4, 1), ("below_total_loss", {}, 4, 4),
    ("zero_rank", {}, 9, 4), ("insolvent", {}, 6, 5),
    (None, {"callback": CHECK(lambda:1)}, 11, NO_ROW),
    (None, {"first":4}, 1, NO_ROW), (None, {"last":5}, 1, NO_ROW), (None, {"length":8}, 1, NO_ROW),
    (None, {"fee":1.0}, 1, NO_ROW), (None, {"shrinkage":10001}, 1, NO_ROW),
])
def test_malformed_unidentified_or_interrupted_runs_do_not_publish(native, change, options, status, error_row):
    times, returns = sample()
    if change == "clock":
        times[3] = times[2]
    elif change == "nonfinite":
        returns[1, 1] = np.nan
    elif change == "below_total_loss":
        returns[4, 1] = -1.001
    elif change == "zero_rank":
        returns[:3] = 0.
    elif change == "insolvent":
        returns[4] = -1.
    code, row, candidate = call(native, times, returns, **options)
    assert (code,row) == (status,error_row)
    assert np.isnan(candidate).all()


def test_invalid_alias_is_rejected_before_touching_source(native):
    times, returns = sample()
    original = returns.copy()
    status, row, packed = call(native, times, returns, overlap=True)
    assert (status,row) == (1,NO_ROW)
    np.testing.assert_array_equal(packed[:original.size], original.ravel())
    assert np.isnan(packed[original.size:]).all()


def test_decision_cap_refuses_large_work_before_writing_results(native):
    values = np.zeros((262,2))
    times = np.arange(len(values), dtype=np.int64)
    status, row, candidate = call(native, times, values)
    assert (status,row) == (1,NO_ROW)
    assert np.isnan(candidate).all()
