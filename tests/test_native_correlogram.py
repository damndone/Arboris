import ctypes
from math import comb
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


MODULE = Path(__file__).resolve().parents[1] / 'native/time_series'
TOLERANCE = {'atol': 2e-12, 'rtol': 2e-12}


@pytest.fixture(scope='module')
def native_manifest():
    output = default_output(MODULE)
    artifacts = [manifest_path(output), *(output / name for name in artifact_names(MODULE))]
    if not any(path.exists() or path.is_symlink() for path in artifacts):
        pytest.skip('run native/time_series/build.py for the real Rust checks')
    return verify_build(MODULE, output)


def correlogram(values, max_lag=1, time=None):
    frame = pd.DataFrame({'t': range(len(values)) if time is None else time, 'y': values})
    return native_time_series.run_correlogram(frame, time_col='t', outcome='y', max_lag=max_lag)


@pytest.mark.parametrize('dtype,first', [('int64', 2**53), ('uint64', 2**63), ('Int64', -(2**53 + 7))])
def test_native_time_series_rejects_lossy_integer_observations_before_fitting(native_manifest, dtype, first):
    values = pd.Series([first + i for i in range(8)], dtype=dtype)
    frame = pd.DataFrame({'t': range(len(values)), 'y': values})
    for operation, options in (
        (native_time_series.run_correlogram, {'max_lag': 2}),
        (native_time_series.run_arima, {'ar_order': 0, 'differences': 1, 'deterministic': 'drift'}),
    ):
        with pytest.raises(TimeSeriesPackError, match='binary64'):
            operation(frame, time_col='t', outcome='y', **options)


def test_correlogram_matches_exact_manual_fixture(native_manifest):
    result = correlogram([1, 2, 4, 5], max_lag=3)

    assert result['model'] == 'correlogram'
    assert result['n_observations'] == 4
    assert result['lags'] == [0, 1, 2, 3]
    assert result['acf'][0] == 1.0
    assert result['pacf'][0] is None
    np.testing.assert_allclose(result['acf'], [1, 3 / 10, -2 / 5, -2 / 5], **TOLERANCE)
    np.testing.assert_allclose(result['pacf'][1:], [3 / 10, -7 / 13, -1 / 12], **TOLERANCE)
    assert result['policy']['acf_method'] == 'demeaned_common_n'
    assert result['policy']['pacf_method'] == 'yule_walker_durbin_levinson'
    assert result['policy']['assumption'] == 'weak_stationarity'
    for key in ('source_sha256', 'binary_sha256', 'build_identity_sha256'):
        assert result['engine'][key] == native_manifest[key]


@pytest.mark.parametrize('max_lag', [24, 200])
def test_correlogram_agrees_with_independent_r_stats(native_manifest, max_lag):
    rscript = shutil.which('Rscript')
    if rscript is None:
        pytest.skip('Rscript is required for the independent stats oracle')
    rng = np.random.default_rng(912)
    noise = rng.standard_normal(900)
    values = noise.copy()
    if max_lag == 200:
        for index in range(2, len(values)):
            values[index] += 0.7 * values[index - 1] - 0.35 * values[index - 2] + 0.25 * noise[index - 1]
    values = values[100:]

    expected = subprocess.run(
        [rscript, '--vanilla', '-e', '''
            x <- scan(file("stdin"), quiet = TRUE)
            k <- as.integer(commandArgs(trailingOnly = TRUE)[1])
            a <- stats::acf(x, lag.max = k, plot = FALSE)$acf
            p <- stats::pacf(x, lag.max = k, plot = FALSE)$acf
            cat(sprintf("%.17g", c(a, p)), sep = "\n")
        ''', str(max_lag)],
        input='\n'.join(format(value, '.17g') for value in values),
        text=True, capture_output=True, check=True, timeout=20,
    )
    expected_values = np.fromstring(expected.stdout, dtype=float, sep=' ')
    result = correlogram(values, max_lag=max_lag)
    np.testing.assert_allclose(result['acf'], expected_values[:max_lag + 1], **TOLERANCE)
    np.testing.assert_allclose(result['pacf'][1:], expected_values[max_lag + 1:], **TOLERANCE)


@pytest.mark.parametrize('values', [
    (np.finfo(float).max / 2) * np.array([-2, -1, 1, 2]),
    np.nextafter(0.0, 1.0) * np.array([0, 1, 3, 4]),
    1e300 + np.spacing(1e300) * np.array([0, 1, 3, 4]),
])
def test_centering_and_scaling_preserve_correlations_at_float_extremes(native_manifest, values):
    result = correlogram(values, max_lag=3)

    np.testing.assert_allclose(result['acf'], [1, 3 / 10, -2 / 5, -2 / 5], **TOLERANCE)
    np.testing.assert_allclose(result['pacf'][1:], [3 / 10, -7 / 13, -1 / 12], **TOLERANCE)


@pytest.mark.parametrize('time,kind', [
    ([2**53 - 2, 2**53 - 1], 'numeric'),
    (pd.date_range('2262-04-10', periods=2), 'datetime'),
    (['2024-01-31', '2024-02-29', '2024-03-31'], 'calendar'),
])
def test_uses_historical_cadence_without_extrapolating_time(native_manifest, time, kind):
    result = correlogram(range(len(time)), time=time)

    assert result['policy']['cadence']['kind'] == kind
    assert result['n_observations'] == len(time)


@pytest.mark.parametrize('values,max_lag,time,reason', [
    ([1], 1, None, 'TIME_SERIES_TOO_FEW_OBSERVATIONS'),
    (np.arange(100_001), 1, None, 'TIME_SERIES_SIZE_LIMIT'),
    ([1, 2, 4], 3, None, 'TIME_SERIES_INVALID_OPTION'),
    ([1, 2, 4], 0, None, 'TIME_SERIES_INVALID_OPTION'),
    ([1, 2, 4], True, None, 'TIME_SERIES_INVALID_OPTION'),
    (np.arange(202), 201, None, 'TIME_SERIES_INVALID_OPTION'),
    ([1, 2, 4], 1, [0, 0, 1], 'TIME_SERIES_ORDER_INVALID'),
    ([1, 2, 4], 1, [0, 1, 3], 'TIME_SERIES_IRREGULAR_TIME'),
    ([1, 2, 4], 1, [0, np.nan, 2], 'TIME_SERIES_NON_FINITE_TIME'),
    ([False, True, True], 1, None, 'TIME_SERIES_NON_NUMERIC_VALUE'),
])
def test_invalid_shape_lag_and_time_fail_before_loading_native(monkeypatch, values, max_lag, time, reason):
    monkeypatch.setattr(native_time_series, '_loaded', lambda: pytest.fail('loaded with invalid input'))

    with pytest.raises(TimeSeriesPackError) as error:
        correlogram(values, max_lag=max_lag, time=time)
    assert error.value.reason_code == reason


@pytest.mark.parametrize('value', [np.nan, np.inf, -np.inf, pd.NA])
def test_nonfinite_values_report_original_row(native_manifest, value):
    values = pd.Series([1.0, value, 5.0], dtype='Float64')

    with pytest.raises(TimeSeriesPackError, match='row 1') as error:
        correlogram(values)
    assert error.value.reason_code == 'TIME_SERIES_NON_FINITE_VALUE'


def test_constant_series_fails_with_a_distinct_reason(native_manifest):
    with pytest.raises(TimeSeriesPackError) as error:
        correlogram([7, 7, 7])
    assert error.value.reason_code == 'TIME_SERIES_CONSTANT_SERIES'


def test_ill_conditioned_yule_walker_fails_instead_of_publishing_partial_output(native_manifest):
    values = [(-1) ** index * comb(127, index) for index in range(128)]

    with pytest.raises(TimeSeriesPackError, match='Yule-Walker.*lag') as error:
        correlogram(np.asarray(values, dtype=np.float64), max_lag=70)
    assert error.value.reason_code == 'TIME_SERIES_NUMERIC_FAILURE'


def test_missing_build_reports_native_failure_without_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(native_time_series, 'default_output', lambda _: tmp_path)
    monkeypatch.setattr(native_time_series, '_load_once', native_time_series._load_once.__wrapped__)

    with pytest.raises(TimeSeriesPackError) as error:
        correlogram([1, 2, 4])
    assert error.value.reason_code == 'TIME_SERIES_NATIVE_BUILD_MISSING'


def test_native_boundary_rejects_a_short_buffer_without_writing(native_manifest):
    library, _ = native_time_series._loaded()
    values = np.array([1.0, 2.0, 4.0])
    output = np.full(4, -99.0)
    error_index = ctypes.c_size_t()
    pointer = ctypes.POINTER(ctypes.c_double)

    status = library.arboris_correlogram(
        values.ctypes.data_as(pointer), values.size, 2,
        output.ctypes.data_as(pointer), output.size, ctypes.byref(error_index), native_time_series._CHECKPOINT(),
    )

    assert status == 1
    np.testing.assert_array_equal(output, np.full(4, -99.0))


def test_cancellation_while_native_code_is_running_preserves_original_exception(native_manifest, monkeypatch):
    library, engine = native_time_series._loaded()
    running_native = False
    native_checks = 0
    cancelled = InterruptedError('cancel correlogram')

    class ObservedLibrary:
        def arboris_correlogram(self, *args):
            nonlocal running_native
            running_native = True
            try:
                return library.arboris_correlogram(*args)
            finally:
                running_native = False

    def check():
        nonlocal native_checks
        if running_native:
            native_checks += 1
            if native_checks == 4:
                raise cancelled

    monkeypatch.setattr(native_time_series, '_loaded', lambda: (ObservedLibrary(), engine))
    with cancellation_scope(check), pytest.raises(InterruptedError) as error:
        correlogram(np.arange(100), max_lag=20)

    assert error.value is cancelled
    assert native_checks == 4
