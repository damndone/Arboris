"""Independent Gaussian EGARCH likelihood and one-step forecast evidence."""
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
(OMEGA, ALPHA, GAMMA, BETA, SCALED_OMEGA, LOG_BACKCAST, RMS, LL, Z_MEAN, Z_RMS, ITERATIONS, EVALUATIONS,
 KKT, CURVATURE, BOUNDARY, STARTS, HOLDOUT_NLL, HOLDOUT_MAE, INITIAL_LOG_VARIANCE) = range(HEADER)
CASES = [(-.06, .22, -.14, .80), (-.05, .25, .16, .76), (-.04, -.16, .11, .65)]
CENTER = math.sqrt(2 / math.pi)


@pytest.fixture(scope="module")
def native():
    if not native_build.manifest_path(OUT).is_file():
        pytest.skip("build with native/time_series/build.py to exercise EGARCH")
    native_build.verify_build(MODULE, OUT)
    module = ctypes.CDLL(str(OUT / native_build.artifact_names(MODULE)[0]))
    function = module.arboris_egarch_fit
    function.argtypes = [DOUBLE, SIZE, SIZE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, ctypes.POINTER(SIZE), CHECK]
    function.restype = ctypes.c_int32
    return function


def synthetic(parameters, seed=2309, rows=2400, burn=700):
    omega, alpha, gamma, beta = parameters
    state = omega / (1 - beta)
    draws = np.random.default_rng(seed).standard_normal(rows + burn)
    result = np.empty(len(draws))
    for i, z in enumerate(draws):
        result[i] = math.exp(state / 2) * z
        state = omega + beta * state + alpha * (abs(z) - CENTER) + gamma * z
    return result[burn:]


def call(native, values, *, train=None, horizon=1, header=HEADER, forecast_size=None, check=None):
    values = np.ascontiguousarray(values, dtype=np.float64)
    train = len(values) - 24 if train is None else train
    count = 2 * (len(values) - train + horizon) if forecast_size is None else forecast_size
    output = np.full(max(count, 2), np.nan)
    receipt = np.full(max(HEADER, header), np.nan)
    row = SIZE(NO_ROW)
    status = native(values.ctypes.data_as(DOUBLE), len(values), train, horizon, receipt.ctypes.data_as(DOUBLE),
                    header, output.ctypes.data_as(DOUBLE), count, ctypes.byref(row), check if check is not None else CHECK())
    return status, row.value, receipt, output


def success(native, values, **kwargs):
    status, row, result, forecast = call(native, values, **kwargs)
    assert (status, row) == (0, NO_ROW)
    assert np.isfinite(result).all() and np.isfinite(forecast).all()
    assert 0 <= result[KKT] <= 1e-7
    assert result[CURVATURE] > 0 and 1 <= result[STARTS] <= 4
    assert result[ITERATIONS] <= result[EVALUATIONS]
    return result, forecast.reshape(-1, 2)


def manual_path(values, parameters, raw_backcast):
    omega, alpha, gamma, beta = parameters
    state = omega + beta * raw_backcast
    path = []
    for shock in values:
        path.append(state)
        z = shock * math.exp(-state / 2)
        state = omega + beta * state + alpha * (abs(z) - CENTER) + gamma * z
    return np.array([*path, state])


@pytest.mark.parametrize("parameters", CASES)
def test_arch_8_gaussian_objective_and_one_step_analytical_forecasts(native, parameters):
    arch_model = pytest.importorskip("arch").arch_model
    values = synthetic(parameters)
    train = len(values) - 24
    rms = math.sqrt(np.mean(values[:train]**2))
    scaled = values / rms
    options = dict(mean="Zero", vol="EGARCH", p=1, o=1, q=1, dist="normal", rescale=False)
    reference = arch_model(scaled[:train], **options).fit(disp="off", show_warning=False,
                                                         options={"ftol": 1e-12, "maxiter": 1000})
    assert reference.convergence_flag == 0
    expected = reference.params.to_numpy().copy()
    expected[0] += 2 * (1 - expected[3]) * math.log(rms)
    result, forecasts = success(native, values)
    np.testing.assert_allclose(result[:4], expected, rtol=0, atol=2e-4)
    assert result[GAMMA] * parameters[2] > 0
    assert result[LL] == pytest.approx(reference.loglikelihood - train * math.log(rms), abs=2e-5)
    fixed = arch_model(scaled, **options).fix(reference.params)
    arch_forecasts = fixed.forecast(horizon=1, start=train-1, align="origin", method="analytic").variance.to_numpy()[:, 0]
    np.testing.assert_allclose(forecasts[:, 1], arch_forecasts * rms**2, rtol=3e-4, atol=2e-6)
    weights = .94 ** np.arange(75)
    backcast = math.log(np.dot(weights, values[:75]**2) / weights.sum())
    path = manual_path(values, result[:4], backcast)
    assert result[LOG_BACKCAST] == pytest.approx(backcast, abs=3e-14)
    assert result[INITIAL_LOG_VARIANCE] == pytest.approx(path[0], abs=3e-14)
    np.testing.assert_allclose(forecasts[:, 0], path[train:], rtol=0, atol=2e-12)
    np.testing.assert_allclose(forecasts[:, 1], np.exp(path[train:]), rtol=2e-12)
    nll = .5*(math.log(2*math.pi) + path[:-1] + values**2 / np.exp(path[:-1]))
    assert result[LL] == pytest.approx(-nll[:train].sum(), abs=2e-9)
    assert result[HOLDOUT_NLL] == pytest.approx(nll[train:].mean(), abs=2e-12)
    assert result[HOLDOUT_MAE] == pytest.approx(np.mean(np.abs(values[train:]**2 - forecasts[:-1, 1])), abs=2e-12)


def test_positive_and_negative_equal_holdout_shocks_preserve_fit_and_own_forecast(native):
    values = synthetic(CASES[0])
    train = len(values) - 24
    up, down = values.copy(), values.copy()
    up[train+4], down[train+4] = 1.0, -1.0
    a, path_up = success(native, up)
    b, path_down = success(native, down)
    np.testing.assert_array_equal(a[:HOLDOUT_NLL], b[:HOLDOUT_NLL])
    assert a[INITIAL_LOG_VARIANCE] == b[INITIAL_LOG_VARIANCE]
    np.testing.assert_array_equal(path_up[:5], path_down[:5])
    assert path_down[5, 0] - path_up[5, 0] == pytest.approx(-2*a[GAMMA]/math.sqrt(path_up[4, 1]), abs=2e-13)
    assert path_down[5, 1] > path_up[5, 1]


def test_raw_variance_intercept_and_log_likelihood_scale(native):
    values = synthetic(CASES[0])
    result, forecast = success(native, values)
    scaled, larger = success(native, 100 * values)
    np.testing.assert_allclose(scaled[ALPHA:BETA+1], result[ALPHA:BETA+1], rtol=0, atol=6e-6)
    assert scaled[OMEGA] == pytest.approx(result[OMEGA] + 2*(1-result[BETA])*math.log(100), abs=4e-5)
    assert scaled[LL] == pytest.approx(result[LL] - (len(values)-24)*math.log(100), abs=2e-6)
    np.testing.assert_allclose(larger[:, 0] - 2*math.log(100), forecast[:, 0], rtol=0, atol=6e-6)
    np.testing.assert_allclose(larger[:, 1]/10_000, forecast[:, 1], rtol=6e-6)


@pytest.mark.parametrize("kwargs,expected", [
    ({"horizon": 0}, 1), ({"horizon": 2}, 1), ({"header": 18}, 1), ({"forecast_size": 1}, 1),
    ({"train": 49}, 3), ({"check": CHECK(lambda: 1)}, 7),
])
def test_unsupported_horizons_bad_shapes_and_cancellation_do_not_publish(native, kwargs, expected):
    values = np.tile([1.0, -2.0, 3.0, -.5], 20)
    status, _, result, forecast = call(native, values, **({"train": 64} | kwargs))
    assert status == expected
    assert np.isnan(result).all() and np.isnan(forecast).all()


@pytest.mark.parametrize("values,expected,row", [
    (np.ones(72), 4, NO_ROW), (np.linspace(.25, 2.5, 72), 4, NO_ROW),
    (np.r_[np.zeros(75), np.tile([1., -2., .5, -1.], 4)], 4, NO_ROW),
    (np.linspace(-1., 1., 72) * 1e-250, 2, NO_ROW),
    (np.r_[np.tile([1., -2., .5, -1.], 18), np.nan], 1, 72),
])
def test_missing_degenerate_and_raw_range_fail_closed(native, values, expected, row):
    status, error_row, result, forecast = call(native, values, train=len(values)-2)
    assert (status, error_row) == (expected, row)
    assert np.isnan(result).all() and np.isnan(forecast).all()


def test_base_r_independent_bounded_log_variance_optimization(native):
    rscript = shutil.which("Rscript")
    if rscript is None:
        pytest.skip("Rscript is required for the independent EGARCH optimizer")
    values = synthetic(CASES[0])
    result, _ = success(native, values)
    reference = subprocess.run(
        [rscript, "--vanilla", "-e", r'''
r <- scan(file("stdin"), quiet=TRUE)
n <- length(r)
s <- sqrt(mean(r^2))
x <- r / s
w <- 0.94^(0:74)
b <- log(sum(w*x[1:75]^2)/sum(w))
loss <- function(theta) {
    h <- theta[1] + theta[4]*b
    total <- 0
    for (v in x) {
        if (!is.finite(h) || abs(h)>40) return(1e50)
        z <- v*exp(-h/2)
        total <- total + h + z^2
        h <- theta[1] + theta[2]*(abs(z)-sqrt(2/pi)) + theta[3]*z + theta[4]*h
    }
    total / (2*n)
}
a <- optim(c(0,0.25,-0.15,0.7), loss, method="L-BFGS-B", lower=c(-2,-1,-1,0), upper=c(2,1,1,.995),
           control=list(factr=10, pgtol=1e-9, ndeps=rep(1e-6,4), maxit=1000))
if (a$convergence != 0L) stop(a$message)
a$par[1] <- a$par[1] + 2*(1-a$par[4])*log(s)
cat(sprintf("%.17g", c(a$par, -n*(a$value+log(s)+log(2*pi)/2))), sep="\n")
        '''], input="\n".join(format(v, ".17g") for v in values[:-24]), text=True, capture_output=True, check=True, timeout=30,
    )
    expected = np.fromstring(reference.stdout, sep="\n")
    assert expected.shape == (5,)
    np.testing.assert_allclose(result[:4], expected[:4], rtol=0, atol=2e-4)
    assert result[LL] == pytest.approx(expected[4], abs=2e-5)
