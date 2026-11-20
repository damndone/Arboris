import ctypes
import shutil
import subprocess

import numpy as np
import pytest
from scipy.stats import f

from tests.test_native_var import (POINTER, POLL, ROTATION, SENTINEL, SIZE, TOLERANCE,
                                   library, synthetic_series, unpack, var_call)


def fit_with_evidence(library, values, lag, intercept, horizon, training=None):
    values = np.require(values, dtype=np.float64, requirements=['C', 'A'])
    rows, series = values.shape
    training = rows if training is None else training
    predictors = series * lag + int(intercept)
    base_size = 2 + predictors * series + series**2 + horizon * (series + series**2)
    evidence_size = series + predictors + predictors * series + series**2 + predictors**2
    output = np.full(base_size + evidence_size, SENTINEL)
    error_index = SIZE()
    kernel = library.arboris_var_fit_with_evidence
    kernel.argtypes = [POINTER, SIZE, SIZE, SIZE, SIZE, SIZE, ctypes.c_int32, SIZE,
                       POINTER, SIZE, ctypes.POINTER(SIZE), POLL]
    kernel.restype = ctypes.c_int32
    status = kernel(values.ctypes.data_as(POINTER), values.size, rows, series, training, lag,
                    int(intercept), horizon, output.ctypes.data_as(POINTER), output.size,
                    ctypes.byref(error_index), POLL())
    assert status == 0, (status, error_index.value)
    return output[:base_size], output[base_size:]


def granger(library, evidence, series, lag, intercept, fitted_rows, effect, mask, *, poll=None):
    output = np.full(6, SENTINEL)
    error_index = SIZE()
    kernel = library.arboris_var_granger_block
    kernel.argtypes = [POINTER, SIZE, SIZE, SIZE, ctypes.c_int32, SIZE, SIZE, ctypes.c_uint32,
                       POINTER, SIZE, ctypes.POINTER(SIZE), POLL]
    kernel.restype = ctypes.c_int32
    status = kernel(evidence.ctypes.data_as(POINTER), evidence.size, series, lag, int(intercept), fitted_rows,
                    effect, mask, output.ctypes.data_as(POINTER), output.size,
                    ctypes.byref(error_index), POLL() if poll is None else poll)
    return status, error_index.value, output


def irf(library, evidence, series, lag, intercept, horizon, limit, *, poll=None):
    output = np.full((horizon + 1, 2, series, series), SENTINEL)
    error_index = SIZE()
    kernel = library.arboris_var_irf
    kernel.argtypes = [POINTER, SIZE, SIZE, SIZE, ctypes.c_int32, SIZE, ctypes.c_double,
                       POINTER, SIZE, ctypes.POINTER(SIZE), POLL]
    kernel.restype = ctypes.c_int32
    status = kernel(evidence.ctypes.data_as(POINTER), evidence.size, series, lag, int(intercept), horizon, limit,
                    output.ctypes.data_as(POINTER), output.size, ctypes.byref(error_index),
                    POLL() if poll is None else poll)
    return status, error_index.value, output


def test_receipt_fit_preserves_existing_forecast_bytes(library):
    values = synthetic_series()
    ordinary_status, _, ordinary = var_call(library, values, 2, True, 10)
    base, evidence = fit_with_evidence(library, values, 2, True, 10)

    assert ordinary_status == 0
    np.testing.assert_array_equal(base.view(np.uint64), ordinary.view(np.uint64))
    np.testing.assert_array_equal(evidence[:3], np.max(np.abs(values), axis=0))
    np.testing.assert_array_equal(np.sort(evidence[3:10]), np.arange(7))
    np.testing.assert_array_equal(np.tril(evidence[-49:].reshape(7, 7), k=-1), np.zeros((7, 7)))


def r_diagnostics(values, lag, horizon, effect, excluded):
    rscript = shutil.which('Rscript')
    if rscript is None:
        pytest.skip('Rscript is required for the independent VAR diagnostics oracle')
    script = '''
        arguments <- as.integer(commandArgs(trailingOnly = TRUE))
        p <- arguments[1]; d <- arguments[2]; h <- arguments[3]; response <- arguments[4]
        excluded <- arguments[-seq_len(4)]
        y <- matrix(scan(file("stdin"), quiet = TRUE), ncol = d, byrow = TRUE)
        n <- nrow(y)
        responses <- y[(p+1):n, , drop = FALSE]
        x <- cbind(1, do.call(cbind, lapply(seq_len(p), function(j) y[(p+1-j):(n-j), , drop = FALSE])))
        drop <- unlist(lapply(seq_len(p), function(j) 1+(j-1)*d+excluded))
        full <- stats::lm.fit(x, responses)
        restricted <- stats::lm.fit(x[, -drop, drop = FALSE], responses[, response])
        full_ssr <- sum(full$residuals[, response]^2)
        restricted_ssr <- sum(restricted$residuals^2)
        df1 <- length(drop); df2 <- full$df.residual
        f <- ((restricted_ssr-full_ssr) / df1) / (full_ssr / df2)
        sigma <- crossprod(full$residuals) / df2
        dimension <- d*p
        companion <- matrix(0, dimension, dimension)
        companion[seq_len(d), ] <- t(full$coefficients[-1, , drop = FALSE])
        if (p > 1L) companion[(d+1):dimension, seq_len(d*(p-1L))] <- diag(d*(p-1L))
        shock <- matrix(0, dimension, dimension)
        shock[seq_len(d), seq_len(d)] <- sigma
        power <- diag(dimension)
        covariance <- matrix(0, dimension, dimension)
        result <- c(f, df1, df2, full_ssr, restricted_ssr, restricted_ssr-full_ssr, stats::pf(f, df1, df2, lower.tail = FALSE))
        for (step in 0:h) {
            result <- c(result, as.vector(t(power[seq_len(d), seq_len(d)])),
                        as.vector(t(covariance[seq_len(d), seq_len(d)])))
            power <- companion %*% power
            covariance <- companion %*% covariance %*% t(companion) + shock
        }
        cat(sprintf("%.17g", result), sep = "\\n")
    '''
    command = [rscript, '--vanilla', '-e', script, *map(str, (lag, values.shape[1], horizon, effect + 1,
                                                            *(index + 1 for index in excluded)))]
    result = subprocess.run(command, input='\n'.join(format(value, '.17g') for value in values.ravel()),
                            text=True, capture_output=True, check=True, timeout=20)
    return np.fromstring(result.stdout, sep=' ')


def test_granger_block_and_irf_agree_with_independent_r(library):
    values = synthetic_series()
    lag, horizon, effect, excluded = 2, 7, 1, [0, 2]
    training = len(values) - horizon
    base, evidence = fit_with_evidence(library, values, lag, True, horizon, training)
    expected = r_diagnostics(values[:training], lag, horizon, effect, excluded)
    status, _, tests = granger(library, evidence, 3, lag, True, training - lag, effect,
                               sum(1 << index for index in excluded))
    impulse_status, _, responses = irf(library, evidence, 3, lag, True, horizon, 1e4)

    assert status == impulse_status == 0
    np.testing.assert_allclose(tests, expected[:6], **TOLERANCE)
    assert f.sf(*tests[:3]) == pytest.approx(expected[6], rel=2e-12, abs=2e-12)
    np.testing.assert_allclose(responses.ravel(), expected[7:], **TOLERANCE)
    np.testing.assert_array_equal(responses[1:, 1].view(np.uint64),
                                  unpack(base, 3, lag, True)['forecast_covariances'].view(np.uint64))


def test_reduced_form_unit_shock_has_identity_at_horizon_zero(library):
    _, evidence = fit_with_evidence(library, ROTATION, 1, False, 4)
    status, _, response = irf(library, evidence, 2, 1, False, 4, 2)

    assert status == 0
    np.testing.assert_allclose(response[:, 0], [np.eye(2), [[0, -1], [1, 0]], -np.eye(2),
                                              [[0, 1], [-1, 0]], np.eye(2)], **TOLERANCE)
    np.testing.assert_array_equal(response[0, 1], np.zeros((2, 2)))


def test_response_limit_rejects_first_excessive_horizon_without_clipping(library):
    values = np.asarray(ROTATION, dtype=float) * np.array([1, 1, 2, 4, 8, 16, 32])[:, None]
    _, evidence = fit_with_evidence(library, values, 1, False, 2)
    status, index, output = irf(library, evidence, 2, 1, False, 5, 3)

    assert (status, index) == (7, 2)
    assert np.all(output == SENTINEL)


@pytest.mark.parametrize('mask', [0, 2, 10, 16])
def test_invalid_exclusion_masks_fail_closed(library, mask):
    _, evidence = fit_with_evidence(library, synthetic_series(), 2, True, 4)
    status, _, output = granger(library, evidence, 3, 2, True, 268, 1, mask)

    assert status == 1
    assert np.all(output == SENTINEL)


def test_invalid_permutation_or_triangular_receipt_fails_closed(library):
    _, evidence = fit_with_evidence(library, synthetic_series(), 2, True, 4)
    duplicate_permutation = evidence.copy()
    duplicate_permutation[3] = duplicate_permutation[4]
    nontriangular = evidence.copy()
    nontriangular[-42] = 1.0

    assert granger(library, duplicate_permutation, 3, 2, True, 268, 1, 1)[0] == 1
    assert irf(library, nontriangular, 3, 2, True, 1, 1e5)[0] == 1


def test_granger_cancellation_leaves_no_partial_test(library):
    _, evidence = fit_with_evidence(library, synthetic_series(), 2, True, 4)
    checkpoints = 0

    @POLL
    def stop():
        nonlocal checkpoints
        checkpoints += 1
        return int(checkpoints == 3)

    status, _, output = granger(library, evidence, 3, 2, True, 268, 1, 5, poll=stop)

    assert status == 5 and checkpoints == 3
    assert np.all(output == SENTINEL)
