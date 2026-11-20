import ctypes
from pathlib import Path

import numpy as np
import pytest

from workbench.native_build import artifact_names, default_output, manifest_path, verify_build

from tests.varma11_fixed_ma_reference import TOLERANCE, compare, fixture, kalman_reference, r_reference


MODULE = Path(__file__).resolve().parents[1] / 'native/time_series'
DOUBLE = ctypes.POINTER(ctypes.c_double)
SIZE = ctypes.c_size_t
INT = ctypes.c_int32
SCALAR = ctypes.c_double
POLL = ctypes.CFUNCTYPE(INT)
INDEX = ctypes.POINTER(SIZE)
SENTINEL = -94073.
RESPONSE_LIMIT = 1e6


@pytest.fixture(scope='module')
def library():
    output = default_output(MODULE)
    if not manifest_path(output).is_file():
        pytest.skip("build with native/time_series/build.py to exercise VARMA")
    verify_build(MODULE, output)
    return ctypes.CDLL(str(output / artifact_names(MODULE)[0]))


def kernel_signature(kernel, arguments):
    kernel.argtypes = arguments
    kernel.restype = INT
    return kernel


def varma_call(library, values, theta=.55, intercept=True, horizon=13, *, training=None, irf=0, limit=RESPONSE_LIMIT,
               size=None, rows=None, values_len=None, poll=None):
    values = np.require(values, dtype=np.float64, requirements=['C', 'A'])
    rows = len(values) if rows is None else rows
    training = len(values) if training is None else training
    if size is None:
        size = 15 + 6 * horizon + (8 * (irf + 1) if irf else 0)
    output = np.full(size, SENTINEL)
    error = SIZE()
    symbol = getattr(library, 'arboris_varma11_fixed_ma', None)
    assert symbol is not None, 'fixed-scalar-MA VARMA ABI is unavailable'
    kernel = kernel_signature(symbol, [DOUBLE, SIZE, SIZE, SIZE, INT, SCALAR, SIZE, SIZE, SCALAR, DOUBLE, SIZE, INDEX, POLL])
    status = kernel(values.ctypes.data_as(DOUBLE), values.size if values_len is None else values_len,
                    rows, training, int(intercept), theta, horizon, irf, limit, output.ctypes.data_as(DOUBLE),
                    output.size, ctypes.byref(error), POLL() if poll is None else poll)
    return status, error.value, output


def unpack(output, horizon):
    tail = 15 + 6 * horizon
    return {'conditional_log_likelihood': output[2], 'intercept': output[3:5], 'ar': output[5:9].reshape(2, 2),
            'innovation_covariance': output[9:13].reshape(2, 2), 'last_innovation': output[13:15],
            'forecast': output[15:tail].reshape(horizon, 6), 'irf': output[tail:].reshape(-1, 2, 2, 2)}


def companion_irf(fit, theta, horizon):
    identity, zeros = np.eye(2), np.zeros((2, 2))
    transition = np.block([[fit['ar'], theta * identity], [zeros, zeros]])
    selection = np.vstack((identity, identity))
    covariance = np.zeros((2, 2))
    rows = []
    for step in range(horizon + 1):
        response = (np.linalg.matrix_power(transition, step) @ selection)[:2]
        rows.append([response, covariance])
        covariance = covariance + response @ fit['innovation_covariance'] @ response.T
    return np.array(rows)


@pytest.mark.parametrize('seed,theta,intercept,scales', [
    (719, .55, True, [1, 1]), (858, -.6, False, [.25, 5]), (906, .95, True, [2, .6]), (173, 0, True, [1, 1]),
])
def test_conditional_varma_fit_forecast_and_irf_match_independent_oracles(library, seed, theta, intercept, scales):
    values = fixture(seed, theta, intercept) * scales
    horizon = 13
    training = len(values) - horizon
    status, index, output = varma_call(library, values, theta, intercept, horizon, training=training, irf=horizon)
    assert status == 0, (status, index)
    actual = unpack(output, horizon)
    actual['n_fit'] = training - 1
    expected = r_reference(values[:training], theta, intercept, horizon)
    compare(actual, expected)
    compare(actual, kalman_reference(values[:training], actual, theta, horizon))
    np.testing.assert_allclose(actual['irf'], companion_irf(actual, theta, horizon), **TOLERANCE)
    np.testing.assert_array_equal(actual['irf'][0], [np.eye(2), np.zeros((2, 2))])
    np.testing.assert_array_equal(actual['irf'][1:, 1].reshape(horizon, 4), actual['forecast'][:, 2:])
    assert 0 < output[1] <= 1
    assert actual['forecast'][0, 3] != 0
    assert np.min(np.linalg.eigvalsh(actual['irf'][1:, 1])) > 0


def _var1(library, values, intercept, horizon, training):
    predictors = 2 + int(intercept)
    base_end = 2 + 2 * predictors + 4 + 6 * horizon
    wire = np.empty(base_end + 2 + predictors + 2 * predictors + 4 + predictors**2)
    error = SIZE()
    fit = kernel_signature(library.arboris_var_fit_with_evidence,
                           [DOUBLE, SIZE, SIZE, SIZE, SIZE, SIZE, INT, SIZE, DOUBLE, SIZE, INDEX, POLL])
    status = fit(values.ctypes.data_as(DOUBLE), values.size, len(values), 2, training, 1, int(intercept), horizon,
                 wire.ctypes.data_as(DOUBLE), wire.size, ctypes.byref(error), POLL())
    assert status == 0, (status, error.value)
    receipt = wire[base_end:]
    irf = kernel_signature(library.arboris_var_irf, [DOUBLE, SIZE, SIZE, SIZE, INT, SIZE, SCALAR, DOUBLE, SIZE, INDEX, POLL])
    response = np.empty((horizon + 1, 2, 2, 2))
    status = irf(receipt.ctypes.data_as(DOUBLE), receipt.size, 2, 1, int(intercept), horizon, RESPONSE_LIMIT,
                 response.ctypes.data_as(DOUBLE), response.size, ctypes.byref(error), POLL())
    assert status == 0, (status, error.value)
    return wire[:base_end], response


@pytest.mark.parametrize('intercept', [True, False])
def test_theta_zero_nests_same_sample_var1_and_converts_covariance_divisor(library, intercept):
    horizon = 9
    values = fixture(719, .55, True) * [.35, 3]
    training = len(values) - horizon
    reference, irf = _var1(library, values, intercept, horizon, training)
    status, index, output = varma_call(library, values, 0, intercept, horizon, training=training, irf=horizon)
    assert status == 0, (status, index)
    actual = unpack(output, horizon)
    predictors = 2 + int(intercept)
    coefficients = reference[2:2 + 2 * predictors].reshape(predictors, 2)
    expected_intercept = coefficients[0] if intercept else np.zeros(2)
    np.testing.assert_array_equal(output[:2], reference[:2])
    np.testing.assert_array_equal(actual['intercept'], expected_intercept)
    np.testing.assert_array_equal(actual['ar'], coefficients[-2:].T)
    np.testing.assert_array_equal(actual['irf'][:, 0], irf[:, 0])
    forecast = reference[-6 * horizon:].reshape(horizon, 6)
    np.testing.assert_array_equal(actual['forecast'][:, :2], forecast[:, :2])
    ratio = (training - 1 - predictors) / (training - 1)
    np.testing.assert_allclose(actual['innovation_covariance'].ravel(), ratio * reference[-6 * horizon - 4:-6 * horizon], **TOLERANCE)
    np.testing.assert_allclose(actual['forecast'][:, 2:], ratio * forecast[:, 2:], **TOLERANCE)
    np.testing.assert_allclose(actual['irf'][:, 1], ratio * irf[:, 1], **TOLERANCE)


def test_holdout_changes_cannot_change_training_fit_state_or_irf_bits(library):
    values = fixture(719, .55, True)
    modified = values.copy()
    modified[-13:] *= -700
    training = len(values) - 13
    first = varma_call(library, values, training=training, irf=17)
    second = varma_call(library, modified, training=training, irf=17)
    assert first[0] == second[0] == 0
    np.testing.assert_array_equal(first[2].view(np.uint64), second[2].view(np.uint64))


def test_irf_response_limit_rejects_first_excessive_step_without_clipping(library):
    values = fixture(719, .55, True) * [1, 40]
    status, _, output = varma_call(library, values, irf=17)
    assert status == 0
    irf = unpack(output, 13)['irf'][:, 0]
    excess = np.flatnonzero(np.abs(irf).max(axis=(1, 2)) > 1)
    assert len(excess) > 0
    status, index, failed = varma_call(library, values, irf=17, limit=1)
    assert (status, index) == (7, excess[0])
    assert np.all(failed == SENTINEL)


def test_forecast_and_irf_admit_the_maximum_horizon_at_negative_theta_boundary(library):
    values = fixture(719, -.95, True)
    status, index, output = varma_call(library, values, theta=-.95, horizon=200, irf=200)
    assert status == 0, (status, index)
    assert np.isfinite(output).all()
    actual = unpack(output, 200)
    np.testing.assert_array_equal(actual['forecast'][:, 2:], actual['irf'][1:, 1].reshape(200, 4))


@pytest.mark.parametrize('case,status', [('duplicate', 4), ('noise_free', 8), ('common_shock', 8)])
def test_rank_and_innovation_degeneracy_fail_closed(library, case, status):
    values = fixture(719, .55, True)[:, 0]
    if case == 'duplicate':
        values = np.column_stack((values, 2 * values + 1))
    elif case == 'noise_free':
        values = np.column_stack((np.arange(len(values)), np.tile([-1., 1.], len(values) // 2)))
    else:
        values = np.column_stack((values, np.cumsum(values)))
    found, _, output = varma_call(library, values)
    assert found == status
    assert np.all(output == SENTINEL)


@pytest.mark.parametrize('invalid', [
    {'theta': np.nan}, {'theta': .95000001}, {'theta': -.95000001}, {'intercept': 2}, {'training': 7},
    {'training': 319}, {'horizon': 0}, {'horizon': 201}, {'rows': 20_001}, {'irf': 201}, {'irf': 2, 'limit': .9},
    {'irf': 2, 'limit': np.inf}, {'size': 8}, {'values_len': 318},
])
def test_invalid_lengths_and_fixed_model_admission_fail_closed(library, invalid):
    status, _, output = varma_call(library, fixture(719, .55, True), **invalid)
    assert status == 1
    assert np.all(output == SENTINEL)


def test_invalid_heldout_value_preserves_flat_row_order(library):
    values = fixture(719, .55, True)
    values[-4, 1] = np.nan
    status, index, output = varma_call(library, values, training=len(values) - 13)
    assert (status, index) == (3, 2 * (len(values) - 4) + 1)
    assert np.all(output == SENTINEL)


def test_cancellation_after_polling_does_not_publish_partial_output(library):
    values = fixture(719, .55, True)
    count = 0
    stop_at = None

    @POLL
    def poll():
        nonlocal count
        count += 1
        return int(count == stop_at)

    status, _, _ = varma_call(library, values, irf=17, poll=poll)
    assert status == 0 and count > 20
    thresholds = (1, 7, count - 2)
    for stop_at in thresholds:
        count = 0
        status, _, output = varma_call(library, values, irf=17, poll=poll)
        assert status == 5 and count == stop_at
        assert np.all(output == SENTINEL)
