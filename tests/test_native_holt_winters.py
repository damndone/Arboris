import ctypes
from pathlib import Path
import shutil
from statistics import NormalDist
import subprocess

import numpy as np
import pytest

from workbench.native_build import artifact_names, default_output, manifest_path, verify_build


MODULE = Path(__file__).resolve().parents[1] / 'native/time_series'
ORACLE = Path(__file__).with_name('fixtures') / 'holt_winters_additive_oracle.R'
TOLERANCE = {'rtol': 2e-12, 'atol': 2e-12}
POINTER = ctypes.POINTER(ctypes.c_double)
SIZE = ctypes.c_size_t
POLL = ctypes.CFUNCTYPE(ctypes.c_int32)
SENTINEL = -112233.0


@pytest.fixture(scope='module')
def library():
    output = default_output(MODULE)
    path = output / artifact_names(MODULE)[0]
    if not any(item.exists() or item.is_symlink() for item in (path, manifest_path(output))):
        pytest.skip('run native/time_series/build.py for the Rust checks')
    verify_build(MODULE, output)
    return ctypes.CDLL(str(path))


def output_len(n, period, horizon):
    return 6 + 2 * period + 5 * min(512, n - 2 * period) + 2 * horizon


def unpack(output, period, horizon):
    start_trace = 6 + 2 * period
    forecast = output[-2 * horizon:].reshape(horizon, 2)
    return {
        'summary': output[:6], 'initial_season': output[6:6 + period],
        'final_season': output[6 + period:start_trace],
        'trace': output[start_trace:-2 * horizon].reshape(-1, 5),
        'forecast_means': forecast[:, 0], 'forecast_variances': forecast[:, 1],
    }


def fixed_call(library, values, period, horizon, weights, *, capacity=None, count=None, poll=None):
    values = np.require(values, dtype=np.float64, requirements=['C', 'A'])
    output = np.full(output_len(len(values), period, horizon) if capacity is None else capacity, SENTINEL)
    error_index = SIZE()
    kernel = library.arboris_holt_winters_additive
    kernel.argtypes = [POINTER, SIZE, SIZE, SIZE, *([ctypes.c_double] * 3), POINTER, SIZE, ctypes.POINTER(SIZE), POLL]
    kernel.restype = ctypes.c_int32
    status = kernel(
        values.ctypes.data_as(POINTER), len(values) if count is None else count, period, horizon, *weights,
        output.ctypes.data_as(POINTER), output.size, ctypes.byref(error_index), POLL() if poll is None else poll,
    )
    return status, error_index.value, output


def r_holt_winters(values, period, horizon, weights, confidence):
    rscript = shutil.which('Rscript')
    if rscript is None:
        pytest.skip('Rscript is required for the independent Holt-Winters oracle')
    args = [str(value) for value in (period, horizon, *weights, confidence)]
    result = subprocess.run(
        [rscript, '--vanilla', str(ORACLE), *args],
        input='\n'.join(format(value, '.17g') for value in values), text=True,
        capture_output=True, check=True, timeout=20,
    )
    return {name: np.fromstring(wire, sep='\t') for name, wire in (line.split('\t', 1) for line in result.stdout.splitlines())}


def test_matches_exact_manual_additive_fit_and_forecast(library):
    status, _, output = fixed_call(library, [8, 13, 10, 15, 13, 17], 2, 4, (.5, .5, .5))

    assert status == 0
    result = unpack(output, 2, 4)
    np.testing.assert_array_equal(result['summary'], [13, 1, 15.375, 1.0625, 1.5625, 1.53125])
    np.testing.assert_array_equal(result['initial_season'], [-2, 2])
    np.testing.assert_array_equal(result['final_season'], [-1.75, 1.8125])
    np.testing.assert_array_equal(result['trace'], [[12, 1, 14.5, 1.25, -1.75], [17.75, -.75, 15.375, 1.0625, 1.8125]])
    np.testing.assert_array_equal(result['forecast_means'], [14.6875, 19.3125, 16.8125, 21.4375])
    np.testing.assert_array_equal(result['forecast_variances'], [1.53125, 2.392578125, 4.78515625, 7.177734375])


@pytest.mark.parametrize('period,horizon,weights', [(4, 13, (.4, .25, .35)), (12, 26, (.85, 0, 0))])
def test_independent_r_filter_predictions_and_covariance(library, period, horizon, weights):
    clock = np.arange(5 * period + 1)
    values = 30 + .4 * clock + np.sin(2 * np.pi * (clock % period) / period) + .3 * np.cos(.7 * clock)
    confidence = .9
    expected = r_holt_winters(values, period, horizon, weights, confidence)
    status, _, output = fixed_call(library, values, period, horizon, weights)

    assert status == 0
    actual = unpack(output, period, horizon)
    for name, values in actual.items():
        np.testing.assert_allclose(values.ravel(), expected[name], **TOLERANCE, err_msg=name)
    margin = NormalDist().inv_cdf((1 + confidence) / 2) * np.sqrt(actual['forecast_variances'])
    np.testing.assert_allclose(actual['forecast_means'] - margin, expected['forecast_lower'], **TOLERANCE)
    np.testing.assert_allclose(actual['forecast_means'] + margin, expected['forecast_upper'], **TOLERANCE)


@pytest.mark.parametrize('count,period,horizon,weights,capacity', [
    (5, 2, 4, (.5, .5, .5), 30), (100_001, 2, 4, (.5, .5, .5), 30),
    (6, 1, 4, (.5, .5, .5), 30), (6, 367, 4, (.5, .5, .5), 30),
    (6, 2, 0, (.5, .5, .5), 30), (6, 2, 201, (.5, .5, .5), 30),
    (6, 2, 4, (0, .5, .5), 28), (6, 2, 4, (.5, np.inf, .5), 28),
    (6, 2, 4, (.5, .5, 1.1), 28), (6, 2, 4, (.5, .5, .5), 27),
])
def test_invalid_native_shapes_and_options_do_not_write(library, count, period, horizon, weights, capacity):
    status, _, output = fixed_call(library, [8, 13, 10, 15, 13, 17], period, horizon, weights,
                                   capacity=capacity, count=count)

    assert status == 1
    assert np.all(output == SENTINEL)


def test_null_and_misaligned_native_buffers_are_rejected(library):
    values = np.array([8, 13, 10, 15, 13, 17], dtype=np.float64)
    assert fixed_call(library, values, 2, 4, (.5, .5, .5))[0] == 0
    output = np.full(output_len(6, 2, 4), SENTINEL)
    error_index = SIZE()
    invalid = [POINTER(), ctypes.cast(values.ctypes.data + 1, POINTER)]

    for pointer in invalid:
        status = library.arboris_holt_winters_additive(
            pointer, len(values), 2, 4, .5, .5, .5, output.ctypes.data_as(POINTER),
            output.size, ctypes.byref(error_index), POLL(),
        )
        assert status == 1
        assert np.all(output == SENTINEL)


@pytest.mark.parametrize('bad,position', [(np.nan, 0), (np.inf, 4), (-np.inf, 5)])
def test_reports_original_nonfinite_row_without_writing(library, bad, position):
    values = np.array([8, 13, 10, 15, 13, 17], dtype=float)
    values[position] = bad
    status, index, output = fixed_call(library, values, 2, 4, (.5, .5, .5))

    assert status == 3 and index == position
    assert np.all(output == SENTINEL)


@pytest.mark.parametrize('values,expected_status,expected_index', [
    ([0, 0, 0, 0, 1e200, -1e200], 2, 4), ([0, 0, 0, 0, 1e151, -1e151], 4, 88),
])
def test_distinguishes_fit_row_and_forecast_horizon_overflow(library, values, expected_status, expected_index):
    status, index, output = fixed_call(library, values, 2, 200, (1, 1, 0))

    assert (status, index) == (expected_status, expected_index)
    assert np.all(output == SENTINEL)


def test_zero_residual_variance_is_explicit_and_forecasts_remain_exact(library):
    status, _, output = fixed_call(library, [8, 13, 10, 15, 12, 17], 2, 4, (1, 0, 0))

    assert status == 0
    result = unpack(output, 2, 4)
    np.testing.assert_array_equal(result['summary'][-2:], [0, 0])
    np.testing.assert_array_equal(result['forecast_means'], [14, 19, 16, 21])
    np.testing.assert_array_equal(result['forecast_variances'], [0, 0, 0, 0])


def test_long_period_and_horizon_keep_only_512_scored_rows(library):
    clock = np.arange(1_300)
    status, _, output = fixed_call(library, clock + clock % 366, 366, 200, (.5, .5, .5))

    assert status == 0 and np.isfinite(output).all()
    result = unpack(output, 366, 200)
    assert result['trace'].shape == (512, 5)
    assert result['forecast_means'].shape == (200,)


def test_cancellation_stops_the_kernel_without_partial_output(library):
    checks = 0

    @POLL
    def stop():
        nonlocal checks
        checks += 1
        return int(checks == 4)

    status, _, output = fixed_call(library, np.arange(2_500), 2, 200, (.5, .5, .5), poll=stop)

    assert status == 5 and checks == 4
    assert np.all(output == SENTINEL)


def fit_call(library, values, period, holdout, weights, *, poll=None):
    values = np.require(values, dtype=np.float64, requirements=['C', 'A'])
    output = np.full(21 + output_len(len(values) - holdout, period, holdout), SENTINEL)
    error_index = SIZE()
    kernel = library.arboris_holt_winters_fit_alpha
    kernel.argtypes = [POINTER, SIZE, SIZE, SIZE, ctypes.c_double, ctypes.c_double,
                       POINTER, SIZE, ctypes.POINTER(SIZE), POLL]
    kernel.restype = ctypes.c_int32
    status = kernel(values.ctypes.data_as(POINTER), len(values), period, holdout, *weights,
                    output.ctypes.data_as(POINTER), output.size, ctypes.byref(error_index), POLL() if poll is None else poll)
    return status, error_index.value, output


@pytest.mark.parametrize('last_training_value,expected_alpha,ties', [
    (17.5, .5, [.5]), (18.25, 1.0, [1.0]), (17.125, .1, [.1, .15]),
])
def test_alpha_grid_finds_interior_endpoint_and_exact_tie(library, last_training_value, expected_alpha, ties):
    values = [8, 13, 10, 15, 13, last_training_value, 15.5, 20, 16]
    status, _, output = fit_call(library, values, 2, 3, (0, 0))

    assert status == 0 and output[0] == expected_alpha
    expected_grid = np.arange(1, 21) / 20
    objectives = output[1:21]
    np.testing.assert_allclose(objectives, 1 + (last_training_value - 17 - expected_grid) ** 2, **TOLERANCE)
    np.testing.assert_array_equal(expected_grid[objectives == objectives.min()], ties)
    fixed_status, _, fixed = fixed_call(library, values[:6], 2, 3, (expected_alpha, 0, 0))
    assert fixed_status == 0
    np.testing.assert_array_equal(output[21:], fixed)


def test_holdout_suffix_does_not_affect_grid_states_variance_or_predictions(library):
    training = [8, 13, 10, 15, 13, 17, 16]
    first = fit_call(library, [*training, 19, 18, 21], 2, 3, (.3, .2))
    changed = fit_call(library, [*training, -3, 102, 8], 2, 3, (.3, .2))

    assert first[0] == changed[0] == 0
    np.testing.assert_array_equal(first[2].view(np.uint64), changed[2].view(np.uint64))


def test_independent_r_checks_every_training_objective_and_holdout_forecast(library):
    period, holdout, weights, confidence = 4, 7, (.25, .35), .9
    clock = np.arange(6 * period + 1)
    training = 30 + .4 * clock + np.sin(2 * np.pi * (clock % period) / period) + .3 * np.cos(.7 * clock)
    expected = r_holt_winters(training, period, holdout, ('NaN', *weights), confidence)
    values = np.concatenate((training, np.arange(holdout)))
    status, _, output = fit_call(library, values, period, holdout, weights)

    assert status == 0
    np.testing.assert_allclose(output[:21], expected['grid'], **TOLERANCE)
    actual = unpack(output[21:], period, holdout)
    for name, values in actual.items():
        np.testing.assert_allclose(values.ravel(), expected[name], **TOLERANCE, err_msg=name)
    margin = NormalDist().inv_cdf((1 + confidence) / 2) * np.sqrt(actual['forecast_variances'])
    np.testing.assert_allclose(actual['forecast_means'] - margin, expected['forecast_lower'], **TOLERANCE)
    np.testing.assert_allclose(actual['forecast_means'] + margin, expected['forecast_upper'], **TOLERANCE)


def test_flat_alpha_grid_has_no_identified_choice(library):
    status, index, output = fit_call(library, [8, 13, 10, 15, 12, 17.125, 15], 2, 1, (0, 0))

    assert status == 6 and index == SIZE(-1).value
    assert np.all(output == SENTINEL)


def test_a_numeric_candidate_failure_invalidates_the_grid(library):
    training = [0, 0, 0, 0, 5e153, -8e153]
    assert fixed_call(library, training, 2, 1, (.05, 0, 0))[0] == 0
    status, index, output = fit_call(library, [*training, 1], 2, 1, (0, 0))

    assert status == 2 and index == 5
    assert np.all(output == SENTINEL)


def test_nonfinite_holdout_is_rejected_with_the_original_row(library):
    status, index, output = fit_call(library, [8, 13, 10, 15, 13, 17, 15, np.nan], 2, 2, (.2, .3))

    assert status == 3 and index == 7
    assert np.all(output == SENTINEL)


def test_cancelling_during_grid_search_does_not_publish_partial_results(library):
    checks = 0

    @POLL
    def stop():
        nonlocal checks
        checks += 1
        return int(checks == 8)

    status, _, output = fit_call(library, [8, 13, 10, 15, 13, 17, 15, 16], 2, 2, (.2, .3), poll=stop)

    assert status == 5 and checks == 8
    assert np.all(output == SENTINEL)
