import ctypes
import math
from pathlib import Path

import numpy as np
import pytest

from workbench.native_build import artifact_names, default_output, manifest_path, verify_build


ROOT = Path(__file__).resolve().parents[1]
from tests.native_stationarity_reference import STATA_ADDON_TOLERANCE, TOLERANCE, cases, executable, reference


MODULE = ROOT / 'native/time_series'
DOUBLE = ctypes.POINTER(ctypes.c_double)
SIZE = ctypes.c_size_t
INT = ctypes.c_int32
INDEX = ctypes.POINTER(SIZE)
POLL = ctypes.CFUNCTYPE(INT)
ADF, KPSS = 0, 1
SENTINEL = -78301.


@pytest.fixture(scope='module')
def library():
    output = default_output(MODULE)
    if not manifest_path(output).is_file():
        pytest.skip("build with native/time_series/build.py to exercise native stationarity")
    manifest = verify_build(MODULE, output)
    library = ctypes.CDLL(str(output / artifact_names(MODULE)[0]))
    assert library.arboris_time_series_abi() == manifest['abi_version']
    return library


def native_call(library, values, method, lag, *, count=None, size=None, poll=None):
    values = np.require(values, dtype=np.float64, requirements=['C', 'A'])
    size = (3 if method == ADF else 1) if size is None else size
    output = np.full(size, SENTINEL)
    error = SIZE()
    kernel = getattr(library, 'arboris_stationarity_constant_fixed', None)
    assert kernel is not None, 'fixed-lag native stationarity ABI is unavailable'
    kernel.argtypes = [DOUBLE, SIZE, ctypes.c_uint32, SIZE, DOUBLE, SIZE, INDEX, POLL]
    kernel.restype = INT
    status = kernel(values.ctypes.data_as(DOUBLE), values.size if count is None else count, method, lag,
                    output.ctypes.data_as(DOUBLE), output.size, ctypes.byref(error), POLL() if poll is None else poll)
    return status, error.value, output


@pytest.mark.parametrize('runtime', ['R', 'Stata'])
@pytest.mark.parametrize('name', ['registered_gate', 'stable_zero_lags', 'random_walk', 'maximum_lags', 'minimum_residual_df'])
def test_fixed_intercept_statistics_match_real_independent_engines(library, runtime, name):
    if executable(runtime) is None:
        pytest.skip(f'{runtime} is not installed')
    values, p, q = cases()[name]
    adf_status, _, adf = native_call(library, values, ADF, p)
    kpss_status, _, kpss = native_call(library, values, KPSS, q)
    assert adf_status == kpss_status == 0
    expected = reference(runtime, values, p, q)
    assert expected['adf_n'] == len(values) - p - 1
    assert expected['adf_df'] == len(values) - 2 * p - 3
    np.testing.assert_allclose(adf, [expected['adf'], expected['gamma'], expected['se']], **TOLERANCE)
    np.testing.assert_allclose(kpss[0], expected['kpss'], **TOLERANCE)
    if runtime == 'Stata' and expected['addon_available'] and q:
        assert expected['addon_kpss'] is not None
        np.testing.assert_allclose(kpss[0], expected['addon_kpss'], **STATA_ADDON_TOLERANCE)


def test_hand_adf_regression_coefficient_standard_error_and_tau(library):
    values = [0, 1, 2, 1] * 5
    status, _, output = native_call(library, values, ADF, 0)
    assert status == 0
    np.testing.assert_allclose(output, [-math.sqrt(19), -1, 1 / math.sqrt(19)], **TOLERANCE)


@pytest.mark.parametrize('lag,wanted', [(0, .025), (1, .5)])
def test_hand_kpss_includes_both_zero_padding_boundaries(library, lag, wanted):
    status, _, output = native_call(library, [-1, 1] * 10, KPSS, lag)
    assert status == 0
    np.testing.assert_allclose(output, [wanted], **TOLERANCE)


@pytest.mark.parametrize('method', [ADF, KPSS])
def test_finite_extreme_scale_and_intercept_shift_preserve_statistic(library, method):
    values = np.resize([1., -1., .25, .5, -.75, .125, -.25], 100)
    expected = native_call(library, values, method, 2)
    for changed in (values * np.finfo(float).max, values * 2**42 + 2**55, values * 2.**-1020):
        status, _, output = native_call(library, changed, method, 2)
        assert expected[0] == status == 0
        np.testing.assert_allclose(output, expected[2], **TOLERANCE)


@pytest.mark.parametrize('method,lag,status', [(ADF, 0, 7), (ADF, 1, 4), (KPSS, 4, 0)])
def test_deterministic_input_preserves_separate_method_admission(library, method, lag, status):
    found, _, output = native_call(library, np.arange(60.), method, lag)
    assert found == status
    assert np.all(output == SENTINEL) if status else output[0] > 0


@pytest.mark.parametrize('method', [ADF, KPSS])
def test_constant_and_nonfinite_observation_fail_without_partial_outputs(library, method):
    found, _, output = native_call(library, np.ones(60), method, 4)
    assert found == 6 and np.all(output == SENTINEL)
    values = np.arange(60.)
    values[41] = np.inf
    found, index, output = native_call(library, values, method, 4)
    assert (found, index) == (3, 41)
    assert np.all(output == SENTINEL)


@pytest.mark.parametrize('method,lag,options', [
    (ADF, 4, {'count': 19}), (ADF, 7, {'count': 20}), (ADF, 21, {}), (ADF, 4, {'size': 1}),
    (KPSS, 20, {'count': 20}), (KPSS, 21, {}), (KPSS, 4, {'count': 20_001}), (KPSS, 4, {'size': 3}), (2, 4, {}),
])
def test_wrong_options_or_small_effective_sample_leave_output_untouched(library, method, lag, options):
    values = cases()['stable_zero_lags'][0]
    status, _, output = native_call(library, values, method, lag, **options)
    assert status == 1 and np.all(output == SENTINEL)


@pytest.mark.parametrize('method', [ADF, KPSS])
def test_cancellation_during_numerical_work_preserves_output_sentinel(library, method):
    values = np.resize(cases()['stable_zero_lags'][0], 20_000)
    polls, stop = 0, None

    @POLL
    def check():
        nonlocal polls
        polls += 1
        return int(polls == stop)

    status, _, _ = native_call(library, values, method, 20, poll=check)
    assert status == 0 and polls > 20
    stop, polls = polls - 2, 0
    status, _, output = native_call(library, values, method, 20, poll=check)
    assert status == 5 and polls == stop
    assert np.all(output == SENTINEL)
