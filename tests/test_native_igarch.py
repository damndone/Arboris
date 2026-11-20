"""Isolated IGARCH conditional likelihood and integrated variance forecasts."""
from __future__ import annotations

import ctypes
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from workbench import native_build


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "native/time_series"
OUT = native_build.default_output(MODULE)
DOUBLE = ctypes.POINTER(ctypes.c_double)
SIZE = ctypes.c_size_t
CHECK = ctypes.CFUNCTYPE(ctypes.c_int32)
NO_ROW = SIZE(-1).value
HEADER = 19
(OMEGA, ALPHA, BETA, PERSISTENCE, NORMALIZED_OMEGA, BACKCAST, RMS, LL, Z_MEAN, Z_RMS, ITERATIONS, EVALUATIONS,
 KKT, CURVATURE, BOUNDARY, STARTS, HOLDOUT_NLL, HOLDOUT_MAE, INITIAL_VARIANCE) = range(HEADER)


@pytest.fixture(scope="module")
def native():
    if not native_build.manifest_path(OUT).is_file():
        pytest.skip("build with native/time_series/build.py to exercise IGARCH")
    native_build.verify_build(MODULE, OUT)
    module = ctypes.CDLL(str(OUT / native_build.artifact_names(MODULE)[0]))
    fn = module.arboris_igarch_fit
    fn.argtypes = [DOUBLE, SIZE, SIZE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, ctypes.POINTER(SIZE), CHECK]
    fn.restype = ctypes.c_int32
    return fn


def synthetic(rows=1800, omega=.045, alpha=.16, seed=6117):
    rng = np.random.default_rng(seed)
    variance = 1.0
    draws = rng.standard_normal(rows + 400)
    values = np.empty(len(draws))
    for i, z in enumerate(draws):
        shock = z * math.sqrt(variance)
        values[i] = shock
        variance = omega + alpha * shock**2 + (1 - alpha) * variance
    return values[400:]


def call(native, values, *, train=None, horizon=8, header=HEADER, forecast_size=None, check=None, alias=False):
    values = np.ascontiguousarray(values, dtype=np.float64)
    train = len(values) - 20 if train is None else train
    count = len(values) - train + horizon if forecast_size is None else forecast_size
    summary = values[:HEADER] if alias else np.full(max(HEADER, header), np.nan)
    forecasts = np.full(max(count, 1), np.nan)
    row = SIZE(NO_ROW)
    status = native(values.ctypes.data_as(DOUBLE), len(values), train, horizon, summary.ctypes.data_as(DOUBLE),
                    header, forecasts.ctypes.data_as(DOUBLE), count, ctypes.byref(row), check if check is not None else CHECK())
    return status, row.value, summary, forecasts


def success(native, values, **options):
    status, row, summary, forecasts = call(native, values, **options)
    assert (status, row) == (0, NO_ROW)
    assert np.isfinite(summary).all() and np.isfinite(forecasts).all() and (forecasts > 0).all()
    assert summary[PERSISTENCE] == 1.0 and summary[ALPHA] + summary[BETA] == 1.0
    assert summary[BETA] == 1.0 - summary[ALPHA]
    assert summary[OMEGA] > 0 and 0 <= summary[ALPHA] <= 1
    assert 0 <= summary[KKT] <= 1e-7 and summary[CURVATURE] > 0 and 1 <= summary[STARTS] <= 3
    return summary, forecasts


def manual(values, omega, alpha, backcast):
    variance = omega + backcast
    output = []
    for shock in values:
        output.append(variance)
        variance = omega + alpha * shock**2 + (1 - alpha) * variance
    return np.array([*output, variance])


def test_raw_conditional_likelihood_and_forecast_match_analytic_integrated_recursion(native):
    values = synthetic()
    result, forecasts = success(native, values, horizon=200)
    train = len(values) - 20
    decay = .94 ** np.arange(75)
    backcast = np.dot(decay, values[:75]**2) / decay.sum()
    assert result[BACKCAST] == pytest.approx(backcast, rel=2e-14)
    path = manual(values, result[OMEGA], result[ALPHA], backcast)
    expected = np.r_[path[train:-1], path[-1] + np.arange(200)*result[OMEGA]]
    np.testing.assert_allclose(forecasts, expected, rtol=2e-12)
    np.testing.assert_allclose(np.diff(forecasts[20:]), result[OMEGA], rtol=3e-12)
    nll = .5*(np.log(2*math.pi*path[:-1]) + values**2/path[:-1])
    assert result[LL] == pytest.approx(-nll[:train].sum(), abs=2e-9)
    assert result[HOLDOUT_NLL] == pytest.approx(nll[train:].mean(), abs=2e-12)
    assert result[HOLDOUT_MAE] == pytest.approx(np.mean(np.abs(values[train:]**2 - path[train:-1])), abs=2e-12)
    assert result[INITIAL_VARIANCE] == pytest.approx(path[0], rel=2e-14)


def test_fixed_fit_and_point_in_time_holdout_invariance(native):
    values = synthetic()
    train = len(values)-20
    a, prior = success(native, values)
    shifted = values.copy()
    shifted[train+4] = 4.0
    b, updated = success(native, shifted)
    np.testing.assert_array_equal(a[:HOLDOUT_NLL], b[:HOLDOUT_NLL])
    assert a[INITIAL_VARIANCE] == b[INITIAL_VARIANCE]
    np.testing.assert_array_equal(prior[:5], updated[:5])
    assert updated[5] - prior[5] == pytest.approx(a[ALPHA] * (16 - values[train+4]**2), abs=3e-13)
    assert updated[-1] != prior[-1]


def test_raw_return_scale_and_log_likelihood_jacobian(native):
    values = synthetic()
    base, before = success(native, values)
    other, after = success(native, 100*values)
    assert other[ALPHA] == pytest.approx(base[ALPHA], abs=6e-6)
    assert other[OMEGA]/10_000 == pytest.approx(base[OMEGA], rel=6e-6)
    assert other[LL] == pytest.approx(base[LL] - (len(values)-20)*math.log(100), abs=2e-6)
    np.testing.assert_allclose(after/10_000, before, rtol=6e-6)


def test_base_r_independent_bounded_integrated_likelihood(native):
    rscript = shutil.which("Rscript")
    if rscript is None:
        pytest.skip("Rscript is required for the independent IGARCH optimizer")
    values = synthetic()
    result, _ = success(native, values)
    reference = subprocess.run(
        [rscript, "--vanilla", "-e", r'''
r <- scan(file("stdin"), quiet=TRUE)
n <- length(r)
s <- sqrt(mean(r^2)); x <- r / s
w <- 0.94^(0:74)
b <- sum(w*x[1:75]^2)/sum(w)
loss <- function(theta) {
    omega <- exp(theta[1]); alpha <- theta[2]; beta <- 1-alpha
    h <- omega + b
    total <- 0
    for (v in x) {
        total <- total + log(h) + v^2/h
        h <- omega + alpha*v^2 + beta*h
    }
    total / (2*n)
}
a <- optim(c(log(.1),.25), loss, method="L-BFGS-B", lower=c(log(1e-8),0), upper=c(log(10),1),
           control=list(factr=10, pgtol=1e-9, ndeps=c(1e-6,1e-6), maxit=1200))
if (a$convergence != 0L) stop(a$message)
cat(sprintf("%.17g", c(exp(a$par[1])*s*s, a$par[2], -n*(a$value+log(s)+log(2*pi)/2))), sep="\n")
        '''], input="\n".join(format(v, ".17g") for v in values[:-20]), text=True, capture_output=True, check=True, timeout=30,
    )
    expected = np.fromstring(reference.stdout, sep="\n")
    assert expected.shape == (3,)
    np.testing.assert_allclose(result[:2], expected[:2], rtol=0, atol=3e-5)
    assert result[LL] == pytest.approx(expected[2], abs=2e-5)


@pytest.mark.parametrize("kwargs,expected", [
    ({"horizon": 0}, 1), ({"horizon": 201}, 1), ({"header": 18}, 1), ({"forecast_size": 1}, 1),
    ({"train": 49}, 3), ({"check": CHECK(lambda: 1)}, 7),
])
def test_shape_limits_and_cancellation_do_not_publish(native, kwargs, expected):
    values = np.tile([1.0, -2.0, 3.0, -.5], 20)
    status, _, result, forecast = call(native, values, **({"train": 64} | kwargs))
    assert status == expected
    assert np.isnan(result).all() and np.isnan(forecast).all()


def test_degenerate_range_nonfinite_and_alias_refusals(native):
    values = np.tile([1.0, -2.0, 3.0, -.5], 20)
    cases = [(np.ones(80), 4, NO_ROW), (values*1e-250, 2, NO_ROW), (np.r_[values, np.nan], 1, 80)]
    for data, expected, row in cases:
        status, error_row, result, forecast = call(native, data)
        assert (status, error_row) == (expected, row)
        assert np.isnan(result).all() and np.isnan(forecast).all()
    before = values.copy()
    status, _, _, forecast = call(native, values, alias=True)
    assert status == 1 and np.isnan(forecast).all()
    np.testing.assert_array_equal(values, before)


def test_zero_arch_boundary_matches_independent_inward_and_tangent_conditions(native):
    from scipy.optimize import brentq

    clock = np.arange(1, 321, dtype=np.float64)
    squared = 1 + .005 * clock + .6 * (-1) ** clock
    values = np.sqrt(squared) * (-1) ** clock
    result, forecast = success(native, values, train=len(values), horizon=3)
    decay = .94 ** np.arange(75)
    backcast = np.dot(decay, squared[:75]) / decay.sum()

    def tangent_derivative(omega):
        variance = backcast + clock * omega
        return .5 * np.mean(clock * (variance - squared) / variance**2)

    omega = brentq(tangent_derivative, 1e-10, .02, xtol=1e-14)
    assert result[ALPHA] == 0.0 and result[BETA] == 1.0 and int(result[BOUNDARY]) & 4
    assert result[OMEGA] == pytest.approx(omega, abs=5e-9)
    np.testing.assert_allclose(forecast, backcast + (len(values)+np.arange(1, 4))*omega, atol=2e-7, rtol=0)

    def mean_loss(alpha):
        variance = manual(values, omega, alpha, backcast)[:-1]
        return .5*np.mean(np.log(variance) + squared/variance)

    assert (mean_loss(1e-6) - mean_loss(0.0)) / 1e-6 > 0
