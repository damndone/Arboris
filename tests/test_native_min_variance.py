"""Independent variance, simplex KKT, and as-of cut evidence for the isolated quant build."""
from __future__ import annotations

import ctypes
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.optimize import minimize

from workbench import native_build
from workbench import native_quant_replay as replay


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "native/quant_replay"
OUT = native_build.default_output(MODULE)
SIZE = ctypes.c_size_t
DOUBLE = ctypes.POINTER(ctypes.c_double)
I64 = ctypes.POINTER(ctypes.c_int64)
CHECK = ctypes.CFUNCTYPE(ctypes.c_int32)
NO_ROW = SIZE(-1).value
SUMMARY = 10
SAMPLE_VARIANCE, OBJECTIVE_VARIANCE, RAW_RANK, RANK_TOL, RAW_MIN_EIG, EFFECTIVE_MIN_EIG, SCALE, ITERATIONS, KKT, SUM_ERROR = range(SUMMARY)


@pytest.fixture(scope="module")
def native():
    if not native_build.manifest_path(OUT).is_file():
        pytest.skip("build with native/quant_replay/build.py to exercise the native optimizer")
    manifest = native_build.verify_build(MODULE, OUT)
    library = replay._open(OUT / native_build.artifact_names(MODULE)[0])
    method = library.arboris_quant_min_variance
    method.argtypes = [SIZE, SIZE, SIZE, I64, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, ctypes.POINTER(SIZE), CHECK]
    method.restype = ctypes.c_int32
    return method, library, manifest


def _call(native, returns, *, times=None, bps=0, poll=None, size_override=None, alias=False):
    method, _, _ = native
    x = np.ascontiguousarray(returns, dtype=np.float64)
    window, width = x.shape
    time = np.arange(window, dtype=np.int64) if times is None else np.ascontiguousarray(times, dtype=np.int64)
    size = width + 2 * width**2 + SUMMARY if size_override is None else size_override
    output = x.reshape(-1)[:size] if alias else np.full(size, np.nan)
    row = SIZE(NO_ROW)
    status = method(window, width, bps, time.ctypes.data_as(I64), time.size, x.ctypes.data_as(DOUBLE), x.size,
                    output.ctypes.data_as(DOUBLE), output.size, ctypes.byref(row), poll if poll is not None else CHECK())
    return status, row.value, output


def _success(native, returns, **options):
    status, row, output = _call(native, returns, **options)
    assert (status, row) == (0, NO_ROW)
    assert np.isfinite(output).all()
    width = returns.shape[1]
    after_raw = width + width**2
    weights = output[:width]
    raw = output[width:after_raw].reshape(width, width)
    effective = output[after_raw:after_raw + width**2].reshape(width, width)
    evidence = output[-SUMMARY:]
    assert np.all((0 <= weights) & (weights <= 1)) and abs(weights.sum() - 1) <= 1e-12
    gradient = effective @ weights / evidence[SCALE]
    multiplier = weights @ gradient
    residual = np.where(weights > 0, np.abs(gradient - multiplier), np.maximum(multiplier - gradient, 0))
    assert np.max(residual) <= 1e-9
    assert evidence[KKT] == pytest.approx(np.max(residual), abs=2e-15)
    assert evidence[SAMPLE_VARIANCE] == pytest.approx(weights @ raw @ weights, abs=2e-14)
    assert evidence[OBJECTIVE_VARIANCE] == pytest.approx(weights @ effective @ weights, abs=2e-14)
    return weights, raw, effective, evidence


def _orthogonal():
    return np.array([-1., -1., 1., 1.]), np.array([-1., 1., -1., 1.])


def test_two_asset_analytic_solution_and_shared_sample_covariance(native):
    a, b = _orthogonal()
    x = np.column_stack((a, 2*b))
    w, cov, effective, evidence = _success(native, x)
    np.testing.assert_allclose(w, [.8, .2], rtol=0, atol=2e-15)
    np.testing.assert_allclose(cov, np.diag([4/3, 16/3]), rtol=0, atol=2e-15)
    _, rolling_covariance = replay._risk_native_call(native[1], np.arange(4, dtype=np.int64).reshape(-1, 1), x, 4)
    np.testing.assert_array_equal(cov, rolling_covariance)
    np.testing.assert_array_equal(cov, effective)
    assert evidence[RAW_RANK] == 2
    assert evidence[RANK_TOL] == pytest.approx(1e-10)


def test_high_positive_covariance_has_exact_long_only_corner(native):
    a, b = _orthogonal()
    x = np.column_stack((a, 2*a+b))
    w, raw, _, evidence = _success(native, x)
    np.testing.assert_array_equal(w, [1., 0.])
    assert raw[0, 1] > raw[0, 0]
    assert evidence[OBJECTIVE_VARIANCE] == pytest.approx(4/3)


@pytest.mark.parametrize("noise", [0.0, 1e-6])
def test_collinearity_is_rejected_or_regularized_only_by_explicit_choice(native, noise):
    a, b = _orthogonal()
    x = np.column_stack((a, 2*a+noise*b))
    status, row, untouched = _call(native, x)
    assert (status, row) == (9, NO_ROW)
    assert np.isnan(untouched).all()
    w, raw, regularized, evidence = _success(native, x, bps=5000)
    assert evidence[RAW_RANK] == 1
    assert evidence[RAW_MIN_EIG] <= evidence[RANK_TOL] < evidence[EFFECTIVE_MIN_EIG]
    np.testing.assert_allclose(regularized, .5*raw + .5*np.trace(raw)/2*np.eye(2), rtol=2e-15, atol=2e-15)
    np.testing.assert_allclose(w, [.75, .25], rtol=0, atol=2e-12)
    equal, _, target, _ = _success(native, x, bps=10000)
    np.testing.assert_array_equal(equal, [.5, .5])
    np.testing.assert_allclose(target, np.trace(raw)/2*np.eye(2), rtol=2e-15, atol=2e-15)


@pytest.mark.parametrize("bps", [0, 1700])
def test_matches_independent_scipy_simplex_optimizer(native, bps):
    rng = np.random.default_rng(1261)
    factors = rng.standard_normal((320, 3))
    loadings = rng.uniform(0., 2., (3, 8))
    x = .002 * (factors @ loadings + rng.standard_normal((320, 8)) * .3)
    w, raw, objective, _ = _success(native, x, bps=bps)
    covariance = np.cov(x, rowvar=False, ddof=1)
    rate = bps/10_000
    expected = (1-rate)*covariance + rate*np.trace(covariance)/8*np.eye(8)
    scale = np.max(np.diag(expected))
    q = expected / scale
    reference = minimize(lambda z: .5*z@q@z, np.full(8, 1/8), jac=lambda z: q@z, method="SLSQP",
                         bounds=[(0, 1)]*8, constraints={"type": "eq", "fun": lambda z: z.sum()-1,
                                                        "jac": lambda _: np.ones(8)}, options={"ftol": 1e-14})
    assert reference.success
    np.testing.assert_allclose(raw, covariance, rtol=3e-15, atol=1e-19)
    np.testing.assert_allclose(objective, expected, rtol=3e-15, atol=1e-19)
    np.testing.assert_allclose(w, reference.x, rtol=0, atol=2e-6)
    assert w@q@w == pytest.approx(reference.x@q@reference.x, abs=2e-12)


def test_fixed_cutoff_excludes_suffix_but_full_source_hash_changes(native):
    original = b"t,a,b\n1,-1,-2\n2,-1,2\n3,1,-2\n4,1,2\n5,-1,100\n6,-1,2\n"
    changed = b"t,a,b\n1,-1,-2\n2,-1,2\n3,1,-2\n4,1,2\n-100,400,\n-200,-6,2\n"

    def fixed_cut(source, end_period):
        frame = pd.read_csv(BytesIO(source))
        cutoff = replay.validate_tail_risk_window(len(frame), 4, end_period)
        times, clock = replay._time_matrix(frame.iloc[:cutoff], ("t",))
        assert clock == "integer_tick"
        assert np.all(times[:-1, 0] < times[1:, 0])
        returns = replay._numeric_matrix(frame.iloc[cutoff-4:cutoff], ("a", "b"))
        return sha256(source).hexdigest(), _call(native, returns, times=times[-4:])

    first_hash, first = fixed_cut(original, 4)
    second_hash, second = fixed_cut(changed, 4)
    assert first_hash != second_hash
    assert first[:2] == second[:2] == (0, NO_ROW)
    np.testing.assert_array_equal(first[2], second[2])
    _, later = fixed_cut(original, 6)
    assert later[0] == 0
    assert not np.array_equal(later[2], first[2])


@pytest.mark.parametrize("bad,bps,times,size,status,row", [
    (None, 10_001, None, None, 1, NO_ROW), (None, 0, None, 11, 1, NO_ROW),
    (None, 0, [1, 2, 2, 4], None, 2, 2), ((2, np.nan), 0, None, None, 4, 2),
    ((0, np.inf), 0, None, None, 4, 0),
])
def test_malformed_input_fails_without_publishing_output(native, bad, bps, times, size, status, row):
    x = np.column_stack(_orthogonal())
    if bad is not None:
        x[bad[0], 0] = bad[1]
    observed, error_row, output = _call(native, x, bps=bps, times=times, size_override=size)
    assert (observed, error_row) == (status, row)
    assert np.isnan(output).all()


def test_zero_variation_cancellation_and_aliased_buffers_are_explicit(native):
    x = np.tile(np.column_stack(_orthogonal()), (8, 1))
    for returns, bps, poll, expected in [(np.ones_like(x), 10_000, None, 9), (x, 0, CHECK(lambda: 1), 11)]:
        status, _, output = _call(native, returns, bps=bps, poll=poll)
        assert status == expected and np.isnan(output).all()
    before = x.copy()
    status, _, _ = _call(native, x, alias=True)
    assert status == 1
    np.testing.assert_array_equal(x, before)
