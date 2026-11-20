"""Conditional volatility checks against native ABI, arch, R, and analytic recurrences."""
from __future__ import annotations

import ctypes
from io import StringIO
import math
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest

from workbench import native_time_series
from workbench.checks.ar_cancellation import cancellation_scope
from workbench.engine.packs.time_series.errors import TimeSeriesPackError
from workbench.native_build import artifact_names, default_output, manifest_path, verify_build

CASES = {
    "arch_1": (0.60, 0.40, 0.00, 0.00),
    "garch_1_1": (0.15, 0.15, 0.00, 0.70),
    "gjr_garch_1_1_1": (0.10, 0.12, 0.22, 0.65),
    "gjr_garch_negative": (0.18, 0.26, -0.14, 0.63),
}


def synthetic(params, *, seed=20261105, size=2400, burn=600):
    omega, alpha, gamma, beta = params
    persistence = alpha + gamma / 2 + beta
    variance = omega / (1 - persistence)
    draws = np.random.default_rng(seed).standard_normal(size + burn)
    result = np.empty(draws.size)
    for i, draw in enumerate(draws):
        shock = math.sqrt(variance) * float(draw)
        result[i] = shock
        variance = omega + (alpha + gamma * (shock < 0)) * shock**2 + beta * variance
    return result[burn:]


def manual_forecasts(values, train_rows, params, periods, backcast):
    omega, alpha, gamma, beta = params
    persistence = alpha + gamma / 2 + beta
    variance = omega + persistence * backcast
    path = np.empty(len(values))
    for i, shock in enumerate(values):
        path[i] = variance
        variance = omega + (alpha + gamma * (shock < 0)) * shock**2 + beta * variance
    future = np.empty(periods)
    for i in range(periods):
        future[i] = variance
        variance = omega + persistence * variance
    return path[:train_rows], path[train_rows:], future


def arch_reference(values, family, holdout=24, periods=5):
    arch_model = pytest.importorskip("arch").arch_model
    train_rows = len(values) - holdout
    rms = math.sqrt(np.mean(values[:train_rows] ** 2))
    scaled = values / rms
    asymmetric = family.startswith("gjr_garch")
    options = dict(mean="Zero", vol="GARCH", p=1, o=int(asymmetric), q=int(family != "arch_1"),
                   power=2.0, dist="normal", rescale=False)
    model = arch_model(scaled[:train_rows], **options)
    fitted = model.fit(disp="off", show_warning=False, options={"ftol": 1e-12, "maxiter": 1000})
    if fitted.convergence_flag:
        raise RuntimeError(f"arch fit did not converge for {family}: {fitted.optimization_result}")
    omega, alpha = map(float, (fitted.params["omega"], fitted.params["alpha[1]"]))
    gamma, beta = map(float, (fitted.params.get("gamma[1]", 0), fitted.params.get("beta[1]", 0)))
    raw_params = omega * rms**2, alpha, gamma, beta
    raw_backcast = float(model.volatility.backcast(scaled[:train_rows])) * rms**2
    train, heldout, future = manual_forecasts(values, train_rows, raw_params, periods, raw_backcast)
    fixed = arch_model(scaled, **options).fix(fitted.params)
    arch_predictions = fixed.forecast(horizon=periods, start=train_rows - 1, align="origin").variance.to_numpy() * rms**2
    np.testing.assert_allclose(train, np.square(fitted.conditional_volatility) * rms**2, rtol=2e-12)
    np.testing.assert_allclose(heldout, arch_predictions[:-1, 0], rtol=2e-12)
    np.testing.assert_allclose(future, arch_predictions[-1], rtol=2e-12)
    nll = .5 * np.mean(np.log(2 * np.pi * heldout) + values[train_rows:] ** 2 / heldout)
    return raw_params, float(fitted.loglikelihood - train_rows * math.log(rms)), heldout, future, nll


MODULE = Path(native_time_series.__file__).resolve().parents[2] / "native/time_series"
FAMILIES = {"arch_1": 0, "garch_1_1": 1, "gjr_garch_1_1_1": 2, "gjr_garch_negative": 2}
DOUBLE = ctypes.POINTER(ctypes.c_double)
SIZE = ctypes.c_size_t
CHECK = ctypes.CFUNCTYPE(ctypes.c_int32)
NO_ROW = SIZE(-1).value
HEADER = 19
(OMEGA, ALPHA, GAMMA, BETA, PERSISTENCE, LONG_RUN, BACKCAST, RMS, LL, Z_MEAN, Z_RMS,
 ITERATIONS, EVALUATIONS, KKT, CURVATURE, BOUNDARY, CONVERGED_STARTS, HOLDOUT_NLL, HOLDOUT_MAE) = range(HEADER)


@pytest.fixture(scope="module")
def native_manifest():
    out = default_output(MODULE)
    artifacts = [manifest_path(out), *(out / name for name in artifact_names(MODULE))]
    if not any(path.exists() or path.is_symlink() for path in artifacts):
        pytest.skip("build the Rust time-series library offline")
    return verify_build(MODULE, out)


@pytest.fixture(scope="module")
def call(native_manifest):
    library = native_time_series._loaded()[0]
    function = library.arboris_volatility_fit
    function.argtypes = [DOUBLE, SIZE, SIZE, SIZE, SIZE, DOUBLE, SIZE, DOUBLE, SIZE, ctypes.POINTER(SIZE), CHECK]
    function.restype = ctypes.c_int32

    def invoke(values, *, family=2, train=None, horizon=5, summary_len=HEADER, variance_len=None, poll=None,
               alias_summary=False):
        x = np.ascontiguousarray(values, dtype=np.float64)
        train = len(x) - 24 if train is None else train
        count = len(x) - train + horizon if variance_len is None else variance_len
        summary = x[:HEADER] if alias_summary else np.full(max(HEADER, summary_len), np.nan)
        variances = np.full(max(1, count), np.nan)
        error = SIZE(NO_ROW)
        status = function(x.ctypes.data_as(DOUBLE), len(x), train, family, horizon,
                          summary.ctypes.data_as(DOUBLE), summary_len, variances.ctypes.data_as(DOUBLE), count,
                          ctypes.byref(error), poll if poll is not None else CHECK())
        return status, error.value, summary, variances

    return invoke


@pytest.mark.parametrize("family", tuple(CASES))
def test_gaussian_conditional_mle_agrees_with_arch_and_manual_forecasts(call, family):
    values = synthetic(CASES[family])
    expected, expected_ll, holdout, future, nll = arch_reference(values, family)
    status, row, summary, variances = call(values, family=FAMILIES[family])
    assert (status, row) == (0, NO_ROW)
    assert np.isfinite(summary).all() and np.isfinite(variances).all()
    np.testing.assert_allclose(summary[:4], expected, atol=1e-4, rtol=0)
    assert summary[LL] == pytest.approx(expected_ll, abs=2e-5)
    np.testing.assert_allclose(variances, np.r_[holdout, future], rtol=3e-4, atol=2e-6)
    assert summary[HOLDOUT_NLL] == pytest.approx(nll, abs=2e-5)
    omega, alpha, gamma, beta = summary[:4]
    assert omega > 0 and alpha >= 0 and alpha + gamma >= 0 and beta >= 0
    assert summary[PERSISTENCE] == pytest.approx(alpha + gamma / 2 + beta, abs=2e-15)
    assert summary[PERSISTENCE] <= .999 + 2e-15
    assert summary[LONG_RUN] == pytest.approx(omega / (1 - summary[PERSISTENCE]), rel=2e-14)
    assert 0 <= summary[KKT] <= 1e-7
    assert summary[CURVATURE] > 0 and 1 <= summary[CONVERGED_STARTS] <= 3
    assert summary[ITERATIONS].is_integer() and summary[EVALUATIONS].is_integer()
    assert 0 <= summary[ITERATIONS] <= summary[EVALUATIONS]
    if FAMILIES[family] < 2:
        assert summary[GAMMA] == 0
    else:
        assert summary[GAMMA] * CASES[family][2] > 0
    if family == "arch_1":
        assert summary[BETA] == 0

    train_size = len(values) - 24
    train, manual_holdout, manual_future = manual_forecasts(values, train_size, summary[:4], 5, summary[BACKCAST])
    np.testing.assert_allclose(variances, np.r_[manual_holdout, manual_future], rtol=2e-12, atol=2e-12)
    np.testing.assert_allclose(summary[LL], -.5 * np.sum(np.log(2 * np.pi * train) + values[:train_size] ** 2 / train), atol=2e-9)
    np.testing.assert_allclose(summary[HOLDOUT_MAE], np.mean(np.abs(values[train_size:] ** 2 - manual_holdout)), rtol=2e-12)


def test_arch_nonnegative_boundary_recovers_analytic_constant_variance(call):
    values = np.tile([1.0, -2.0], 80)
    status, row, summary, variances = call(values, family=0)
    assert (status, row) == (0, NO_ROW)
    assert summary[ALPHA] == summary[BETA] == summary[GAMMA] == 0
    assert summary[OMEGA] == pytest.approx(2.5, abs=5e-7)
    assert summary[BOUNDARY] > 0
    np.testing.assert_allclose(variances, np.full(len(variances), 2.5), atol=5e-7, rtol=0)


def test_garch_beta_boundary_agrees_with_arch_when_lag_two_response_is_absent(call):
    values = np.tile([1.0, -1.0, 1.0, -3.0, 3.0, -3.0], 150)
    expected, expected_ll, _, _, _ = arch_reference(values, "garch_1_1")
    assert expected[3] < 1e-7
    status, row, summary, _ = call(values, family=1)
    assert (status, row) == (0, NO_ROW)
    assert summary[BETA] == 0 and summary[BOUNDARY] > 0
    np.testing.assert_allclose(summary[:4], expected, atol=1e-4, rtol=0)
    assert summary[LL] == pytest.approx(expected_ll, abs=2e-5)


def test_same_magnitude_positive_and_negative_holdout_shocks_change_only_later_variance(call):
    values = synthetic(CASES["gjr_garch_1_1_1"])
    train = len(values) - 24
    point = train + 4
    positive, negative = values.copy(), values.copy()
    positive[point], negative[point] = 3.0, -3.0
    status, _, summary, up = call(positive)
    assert status == 0 and summary[GAMMA] > 0
    other_status, _, other_summary, down = call(negative)
    assert other_status == 0
    np.testing.assert_array_equal(summary[:HOLDOUT_NLL], other_summary[:HOLDOUT_NLL])
    np.testing.assert_array_equal(up[:5], down[:5])
    assert down[5] - up[5] == pytest.approx(9.0 * summary[GAMMA], rel=2e-13, abs=2e-13)
    assert down[6] - up[6] == pytest.approx((down[5] - up[5]) * summary[BETA], rel=2e-13, abs=2e-13)
    assert summary[HOLDOUT_NLL] != other_summary[HOLDOUT_NLL]


def test_raw_variance_units_and_likelihood_jacobian_are_explicit(call):
    values = synthetic(CASES["garch_1_1"])
    status, _, summary, variances = call(values, family=1)
    larger_status, _, larger, larger_variances = call(values * 100, family=1)
    assert status == larger_status == 0
    np.testing.assert_allclose(larger[[OMEGA, LONG_RUN, BACKCAST, HOLDOUT_MAE]] / 10_000,
                               summary[[OMEGA, LONG_RUN, BACKCAST, HOLDOUT_MAE]], rtol=4e-6)
    np.testing.assert_allclose(larger[ALPHA:BETA + 1], summary[ALPHA:BETA + 1], atol=4e-6, rtol=0)
    np.testing.assert_allclose(larger_variances / 10_000, variances, rtol=4e-6)
    assert larger[LL] == pytest.approx(summary[LL] - (len(values) - 24) * math.log(100), abs=2e-6)
    assert larger[HOLDOUT_NLL] == pytest.approx(summary[HOLDOUT_NLL] + math.log(100), abs=3e-6)


@pytest.mark.parametrize("args,expected_status", [
    ({"family": 3}, 1), ({"horizon": 0}, 1), ({"horizon": 201}, 1),
    ({"summary_len": HEADER - 1}, 1), ({"variance_len": 27}, 1), ({"train": 49}, 3),
    ({"train": 73}, 1), ({"poll": CHECK(lambda: 1)}, 7),
])
def test_native_failure_keeps_forecast_buffers_unpublished(call, args, expected_status):
    values = np.tile([1.0, -2.0, 3.0, -1.0], 18)
    status, _, summary, variances = call(values, **({"train": 60} | args))
    assert status == expected_status
    assert np.isnan(summary).all() and np.isnan(variances).all()


@pytest.mark.parametrize("rows,train", [(20_001, 20_001), (251, 50)])
def test_native_bounds_rows_and_holdout_before_evaluation(call, rows, train):
    status, _, summary, variances = call(np.zeros(rows), train=train)
    assert status == 6
    assert np.isnan(summary).all() and np.isnan(variances).all()


def test_native_refuses_overlapping_caller_buffers(call):
    values = synthetic(CASES["garch_1_1"])
    before = values.copy()
    status, _, _, variances = call(values, family=1, alias_summary=True)
    assert status == 1
    np.testing.assert_array_equal(values, before)
    assert np.isnan(variances).all()


@pytest.mark.parametrize("values,status,row", [
    (np.zeros(64), 4, NO_ROW), (np.tile([1.0, -1.0], 32), 4, NO_ROW),
    (np.linspace(.25, 1.0, 64), 4, NO_ROW),
    (np.linspace(-1.0, 1.0, 64) * np.finfo(np.float64).tiny, 2, NO_ROW),
    (np.r_[np.tile([.5, -1.0, 2.0], 20), np.nan, 1.0, 2.0, 3.0], 1, 60),
])
def test_degenerate_nonfinite_and_unrepresentable_variance_fail_closed(call, values, status, row):
    observed, error_row, _, _ = call(values, train=60)
    assert (observed, error_row) == (status, row)


def _run(values, time=None, **options):
    from workbench import native_volatility

    frame = pd.DataFrame({"t": np.arange(len(values)) if time is None else time, "y": values})
    args = {"time_col": "t", "outcome": "y", "family": "garch_1_1", "forecast_periods": 3, "holdout_periods": 5} | options
    return native_volatility.run_volatility(frame, **args)


def test_adapter_rejects_lossy_integer_innovation_before_native_load(monkeypatch):
    from workbench import native_volatility

    monkeypatch.setattr(native_volatility, "_loaded", lambda: pytest.fail("invalid integers entered native fit"))
    with pytest.raises(TimeSeriesPackError):
        _run(pd.array([2**53 + i for i in range(64)], dtype="Int64"))


@pytest.mark.parametrize("new_time", [150, 62])
def test_adapter_rejects_gap_or_duplicate_before_native_load(monkeypatch, new_time):
    from workbench import native_volatility

    monkeypatch.setattr(native_volatility, "_loaded", lambda: pytest.fail("invalid time grid entered native fit"))
    time = np.arange(64)
    time[-1] = new_time
    with pytest.raises(TimeSeriesPackError):
        _run(np.tile([1, -2, 3, -1], 16), time=time)


def test_adapter_numeric_integer_series_agrees_with_equivalent_binary64(native_manifest):
    values = np.tile([1, -2, 1, -1, 2, -1], 40)
    assert _run(values, family="arch_1") == _run(values.astype(np.float64), family="arch_1")


def test_adapter_labels_variance_horizon_and_reports_training_receipt(native_manifest):
    values = synthetic(CASES["gjr_garch_1_1_1"])
    result = _run(values, family="gjr_garch_1_1_1")
    assert result["engine"]["build_identity_sha256"] == native_manifest["build_identity_sha256"]
    assert result["fit"]["n_observed"] == len(values) - 5
    assert result["policy"]["family"] == "gjr_garch_1_1_1"
    assert result["forecast"]["time"] == list(range(len(values), len(values) + 3))
    assert len(result["forecast"]["variance"]) == 3
    assert result["holdout"] is not None


def test_adapter_restores_cancellation_exception(native_manifest):
    class Cancelled(Exception):
        pass

    calls = 0

    def cancel():
        nonlocal calls
        calls += 1
        if calls >= 4:
            raise Cancelled("interrupted during native volatility")

    with cancellation_scope(cancel), pytest.raises(Cancelled, match="interrupted during native volatility"):
        _run(synthetic(CASES["garch_1_1"]))


def test_gjr_likelihood_matches_base_r_constrained_optimizer(call):
    rscript = shutil.which("Rscript")
    if rscript is None:
        pytest.skip("Rscript is required for the independent constrained likelihood oracle")
    values = synthetic(CASES["gjr_garch_1_1_1"])
    compared = subprocess.run(
        [rscript, "--vanilla", "-e", r'''
y <- scan(file("stdin"), quiet=TRUE)
n <- length(y)
rms <- sqrt(mean(y^2))
z <- y / rms
m <- min(75, n)
w <- 0.94^(seq_len(m)-1)
backcast <- sum(w*z[seq_len(m)]^2)/sum(w)
loss <- function(theta) {
    omega <- theta[1]; alpha <- theta[2]; gamma <- theta[3]; beta <- theta[4]
    h <- omega+(alpha+gamma/2+beta)*backcast
    v <- 0
    for (x in z) {
        v <- v + log(h) + x*x/h
        h <- omega + (alpha+gamma*(x<0))*x*x + beta*h
    }
    v/(2*n)
}
constraints <- rbind(c(1,0,0,0), c(-1,0,0,0), c(0,1,0,0), c(0,1,1,0), c(0,0,0,1), c(0,-1,-0.5,-1))
limits <- c(1e-8,-10,0,0,0,-0.999)
fit <- constrOptim(c(0.18,0.18,0.1,0.65), loss, NULL, constraints, limits,
                  method="Nelder-Mead", control=list(maxit=3000, reltol=1e-13), outer.eps=1e-11)
if (fit$convergence != 0L) stop(fit$message)
raw <- fit$par
raw[1] <- raw[1]*rms^2
loglik <- -n*(fit$value+log(rms)+log(2*pi)/2)
cat(sprintf("%.17g", c(raw, loglik)), sep="\n")
        '''],
        input="\n".join(format(value, ".17g") for value in values[:-24]), text=True,
        capture_output=True, check=True, timeout=20,
    )
    expected = np.fromstring(compared.stdout, dtype=np.float64, sep="\n")
    assert expected.shape == (5,)
    status, row, summary, _ = call(values)
    assert (status, row) == (0, NO_ROW)
    np.testing.assert_allclose(summary[:4], expected[:4], rtol=0, atol=5e-5)
    assert summary[LL] == pytest.approx(expected[4], abs=2e-5)


def test_gjr_keeps_the_active_positive_shock_bound_without_losing_tangent_convergence(call):
    innovations = np.random.default_rng(401).standard_normal(320)
    observed = np.empty(320)
    variance = 1.0
    for i, innovation in enumerate(innovations):
        shock = innovation * np.sqrt(variance)
        observed[i] = shock
        variance = 0.05 + (0.07 + 0.14 * (shock < 0)) * shock**2 + 0.78 * variance
    values = pd.read_csv(StringIO(pd.DataFrame({"returns": observed}).to_csv(index=False)))["returns"].to_numpy()
    status, row, summary, forecasts = call(values, train=300, horizon=10)
    assert (status, row) == (0, NO_ROW)
    assert summary[ALPHA] == 0.0 and int(summary[BOUNDARY]) & 4
    assert summary[GAMMA] == pytest.approx(0.418743245, abs=3e-6)
    assert summary[BETA] == pytest.approx(0.697294127, abs=3e-6)
    assert summary[LL] == pytest.approx(-338.2240639477687, abs=5e-8)
    assert summary[KKT] <= 1e-7 and summary[CURVATURE] > 0.0

    decay = .94 ** np.arange(75)
    backcast = np.dot(decay, values[:75] ** 2) / decay.sum()
    train, heldout, future = manual_forecasts(values, 300, summary[:4], 10, backcast)
    expected_ll = -.5 * np.sum(np.log(2 * np.pi * train) + values[:300] ** 2 / train)
    assert summary[LL] == pytest.approx(expected_ll, abs=2e-10)
    np.testing.assert_allclose(forecasts, np.r_[heldout, future], rtol=2e-12, atol=2e-12)
