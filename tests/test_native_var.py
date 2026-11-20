import ctypes
from pathlib import Path
import shutil
import subprocess

import numpy as np
import pytest

from workbench.native_build import artifact_names, default_output, manifest_path, verify_build


MODULE = Path(__file__).resolve().parents[1] / 'native/time_series'
POINTER = ctypes.POINTER(ctypes.c_double)
SIZE = ctypes.c_size_t
POLL = ctypes.CFUNCTYPE(ctypes.c_int32)
TOLERANCE = {'rtol': 2e-12, 'atol': 2e-12}
SENTINEL = -91827.0
ROTATION = [[0, 0], [1, 1], [-1, 1], [-1, -1], [1, -1], [1, 1], [-1, 1]]


@pytest.fixture(scope='module')
def library():
    output = default_output(MODULE)
    path = output / artifact_names(MODULE)[0]
    if not any(item.exists() or item.is_symlink() for item in (path, manifest_path(output))):
        pytest.skip('run native/time_series/build.py for the Rust checks')
    verify_build(MODULE, output)
    return ctypes.CDLL(str(path))


def var_call(library, values, lag=1, intercept=False, horizon=4, *, training=None, capacity=None, poll=None, **limits):
    values = np.require(values, dtype=np.float64, requirements=['C', 'A'])
    rows, series = values.shape
    training = rows if training is None else training
    predictors = lag * series + int(intercept)
    if capacity is None:
        capacity = 2 + predictors * series + series**2 + horizon * (series + series**2)
    output = np.full(capacity, SENTINEL)
    error_index = SIZE()
    kernel = library.arboris_var_fit
    kernel.argtypes = [POINTER, SIZE, SIZE, SIZE, SIZE, SIZE, ctypes.c_int32, SIZE,
                       POINTER, SIZE, ctypes.POINTER(SIZE), POLL]
    kernel.restype = ctypes.c_int32
    status = kernel(
        values.ctypes.data_as(POINTER), limits.get('values_len', values.size), limits.get('rows', rows),
        limits.get('series', series), training, lag, int(intercept), horizon, output.ctypes.data_as(POINTER),
        output.size, ctypes.byref(error_index), POLL() if poll is None else poll,
    )
    return status, error_index.value, output


def unpack(output, series, lag, intercept):
    predictors = series * lag + int(intercept)
    coefficient_end = 2 + predictors * series
    covariance_end = coefficient_end + series**2
    forecast = output[covariance_end:].reshape(-1, series + series**2)
    return {
        'contraction': output[0], 'minimum_pivot_ratio': output[1],
        'coefficients': output[2:coefficient_end].reshape(predictors, series),
        'innovation_covariance': output[coefficient_end:covariance_end].reshape(series, series),
        'means': forecast[:, :series],
        'forecast_covariances': forecast[:, series:].reshape(-1, series, series),
    }


def test_exact_rotation_fixture_keeps_cross_equation_forecast_covariance(library):
    status, _, output = var_call(library, ROTATION)

    assert status == 0
    fit = unpack(output, 2, 1, False)
    np.testing.assert_allclose(fit['coefficients'], [[0, 1], [-1, 0]], **TOLERANCE)
    np.testing.assert_allclose(fit['innovation_covariance'], np.full((2, 2), .25), **TOLERANCE)
    np.testing.assert_allclose(fit['means'], [[-1, -1], [1, -1], [1, 1], [-1, 1]], **TOLERANCE)
    np.testing.assert_allclose(fit['forecast_covariances'], [
        [[.25, .25], [.25, .25]], [[.5, 0], [0, .5]], [[.75, .25], [.25, .75]], [[1, 0], [0, 1]],
    ], **TOLERANCE)
    assert fit['contraction'] == pytest.approx(1, **{'rel': 2e-12, 'abs': 2e-12})
    assert 0 < fit['minimum_pivot_ratio'] <= 1


def reference_r(values, lag, intercept, horizon):
    rscript = shutil.which('Rscript')
    if rscript is None:
        pytest.skip('Rscript is required for independent VAR regression and covariance')
    script = '''
        parameters <- as.integer(commandArgs(trailingOnly = TRUE))
        p <- parameters[1]; constant <- parameters[2]; d <- parameters[3]; h <- parameters[4]
        y <- matrix(scan(file("stdin"), quiet = TRUE), ncol = d, byrow = TRUE)
        n <- nrow(y)
        response <- y[(p+1):n, , drop = FALSE]
        predictors <- do.call(cbind, lapply(seq_len(p), function(j) y[(p+1-j):(n-j), , drop = FALSE]))
        if (constant == 1L) predictors <- cbind(1, predictors)
        fit <- stats::lm.fit(predictors, response)
        stopifnot(fit$rank == ncol(predictors))
        coefficients <- fit$coefficients
        sigma <- crossprod(fit$residuals) / fit$df.residual
        companion <- matrix(0, d*p, d*p)
        companion[seq_len(d), ] <- t(coefficients[seq_len(d*p) + constant, , drop = FALSE])
        if (p > 1L) companion[(d+1):(d*p), seq_len(d*(p-1L))] <- diag(d*(p-1L))
        drift <- numeric(d*p)
        if (constant == 1L) drift[seq_len(d)] <- coefficients[1, ]
        impulse <- matrix(0, d*p, d*p)
        impulse[seq_len(d), seq_len(d)] <- sigma
        state <- as.vector(t(y[n - seq_len(p) + 1L, , drop = FALSE]))
        covariance <- matrix(0, d*p, d*p)
        forecast <- numeric()
        for (step in seq_len(h)) {
            state <- drop(companion %*% state) + drift
            covariance <- companion %*% covariance %*% t(companion) + impulse
            forecast <- c(forecast, state[seq_len(d)], as.vector(t(covariance[seq_len(d), seq_len(d)])))
        }
        cat(sprintf("%.17g", c(as.vector(t(coefficients)), as.vector(t(sigma)), forecast)), sep = "\\n")
    '''
    completed = subprocess.run(
        [rscript, '--vanilla', '-e', script, *map(str, (lag, int(intercept), values.shape[1], horizon))],
        input='\n'.join(format(value, '.17g') for value in values.ravel()), text=True,
        capture_output=True, check=True, timeout=20,
    )
    return np.fromstring(completed.stdout, sep=' ')


def synthetic_series():
    noise = np.random.default_rng(497).multivariate_normal([0, 0, 0], [[1, .4, -.2], [.4, 2, .3], [-.2, .3, 1]], 320)
    values = noise.copy()
    transition = np.array([[.25, .05, 0], [0, .3, .1], [-.1, 0, .2]])
    for row in range(2, len(values)):
        values[row] += transition @ values[row - 1] + .07 * values[row - 2] + np.array([.3, -.2, .1])
    return values[50:] * np.array([.2, 25, 3])


@pytest.mark.parametrize('lag,intercept', [(1, False), (2, True)])
def test_matches_r_common_sample_fit_and_companion_forecast(library, lag, intercept):
    values = synthetic_series()
    horizon = 13
    expected = reference_r(values[:-horizon], lag, intercept, horizon)
    status, _, output = var_call(library, values, lag, intercept, horizon, training=len(values) - horizon)

    assert status == 0
    np.testing.assert_allclose(output[2:], expected, **TOLERANCE)
    fit = unpack(output, values.shape[1], lag, intercept)
    assert fit['contraction'] < 1
    assert np.array_equal(fit['forecast_covariances'], fit['forecast_covariances'].transpose(0, 2, 1))


def test_holdout_changes_do_not_change_fitted_or_forecast_bits(library):
    values = synthetic_series()
    changed = values.copy()
    changed[-7:] *= -900
    baseline = var_call(library, values, 3, True, 7, training=len(values) - 7)
    perturbed = var_call(library, changed, 3, True, 7, training=len(values) - 7)

    assert baseline[0] == perturbed[0] == 0
    np.testing.assert_array_equal(baseline[2].view(np.uint64), perturbed[2].view(np.uint64))


@pytest.mark.parametrize('values', [
    np.column_stack([np.arange(20), np.arange(20)]),
    np.column_stack([np.arange(20) % 3, np.ones(20)]),
    np.column_stack([np.sin(np.arange(20)), np.sin(np.arange(20)) + 1e-16 * np.arange(20) / 20]),
])
def test_rank_deficient_or_numerically_singular_designs_fail(library, values):
    status, rank, output = var_call(library, values, 1, True)

    assert status == 4 and rank < 3
    assert np.all(output == SENTINEL)


@pytest.mark.parametrize('options', [
    {'lag': 0}, {'lag': 9}, {'horizon': 0}, {'horizon': 201}, {'series': 1}, {'series': 9},
    {'values_len': 13}, {'rows': 20_001}, {'intercept': 2}, {'training': 3},
    {'training': 6}, {'capacity': 4},
])
def test_invalid_input_shape_fails_before_writing(library, options):
    status, _, output = var_call(library, ROTATION, **options)

    assert status == 1
    assert np.all(output == SENTINEL)


def test_nonfinite_holdout_is_bound_to_original_flat_index(library):
    status, index, output = var_call(library, [*ROTATION, [3, np.inf]], horizon=1, training=len(ROTATION))

    assert status == 3 and index == 2 * len(ROTATION) + 1
    assert np.all(output == SENTINEL)


def test_native_fit_and_forecast_can_be_cancelled_without_publishing(library):
    checks = 0

    @POLL
    def stop():
        nonlocal checks
        checks += 1
        return int(checks == 5)

    status, _, output = var_call(library, synthetic_series(), 3, True, 20, poll=stop)

    assert status == 5 and checks == 5
    assert np.all(output == SENTINEL)
