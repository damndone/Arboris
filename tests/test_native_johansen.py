import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from scipy.linalg import lstsq, qr, svdvals

from workbench.checks.ar_cancellation import cancellation_scope
from workbench.engine.packs.time_series.errors import TimeSeriesPackError
from workbench.native_build import default_output, manifest_path, verify_build


MODULE = Path(__file__).resolve().parents[1] / 'native/time_series'
TOLERANCE = {'rtol': 2e-12, 'atol': 2e-12}


@pytest.fixture(scope='module')
def native_manifest():
    output = default_output(MODULE)
    if not manifest_path(output).is_file():
        pytest.skip('build with native/time_series/build.py to exercise native Johansen rank diagnostics')
    return verify_build(MODULE, output)


def make_frame(series=3, rows=150):
    rng = np.random.default_rng(382)
    values = rng.normal(size=(rows, series))
    values[:, 0] = values[:, 0].cumsum()
    values[:, -1] += 0.7 * values[:, 0]
    names = [f'series_{i}' for i in range(series)]
    frame = pd.DataFrame(values, columns=names)
    frame['period'] = pd.date_range('2001-01-01', periods=rows, freq='MS').strftime('%Y-%m-%d')
    return frame, names


def reference(values, lag):
    differences = np.diff(values, axis=0)
    current = differences[lag:]
    levels = np.column_stack((values[lag:-1], np.ones(len(current))))
    controls = np.column_stack([differences[lag - i:-i] for i in range(1, lag + 1)])

    def basis(block):
        residuals = block - controls @ lstsq(controls, block)[0]
        return qr(residuals, mode='economic')[0]

    eigenvalues = svdvals(basis(levels).T @ basis(current)) ** 2
    maximum = -len(current) * np.log1p(-eigenvalues)
    trace = np.cumsum(maximum[::-1])[::-1]
    return eigenvalues, trace, maximum


@pytest.mark.parametrize('series,lag', [(3, 1), (3, 4), (4, 1), (4, 4)])
def test_johansen_returns_bounded_uncalibrated_evidence(native_manifest, series, lag):
    from workbench.native_johansen import run_johansen_rank

    frame, names = make_frame(series)
    result = run_johansen_rank(frame, time_col='period', series_columns=names, difference_lags=lag)
    assert result['ranks'] == list(range(series))
    assert result['n_observations'] == len(frame)
    assert result['n_effective'] == len(frame) - lag - 1
    assert result['sample'] == {'start_time': frame['period'].iloc[lag + 1], 'end_time': frame['period'].iloc[-1]}
    assert result['policy'] == {
        'time_col': 'period', 'series_columns': names, 'difference_lags': lag, 'levels_order': lag + 1,
        'cadence': {'kind': 'calendar', 'offset': 'MS', 'input': 'iso8601'},
        'deterministic': 'restricted_constant', 'missing': 'reject',
    }
    assert result['evidence_scope'] == 'statistics_only'
    assert result['rank_criterion'] == 'uncalibrated'
    assert result['scientific_validity'] == 'not_certified'
    assert set(result) == {
        'schema_version', 'model', 'engine', 'ranks', 'canonical_eigenvalues', 'trace_statistics',
        'max_eigenvalue_statistics', 'n_observations', 'n_effective', 'sample', 'policy', 'evidence_scope',
        'rank_criterion', 'scientific_validity',
    }
    assert result['model'] == 'johansen_rank'
    for key in ('build_identity_sha256', 'source_sha256', 'binary_sha256'):
        assert result['engine'][key] == native_manifest[key]
    fields = ('canonical_eigenvalues', 'trace_statistics', 'max_eigenvalue_statistics')
    for field, expected in zip(fields, reference(frame[names].to_numpy(), lag), strict=True):
        np.testing.assert_allclose(result[field], expected, **TOLERANCE)
    json.dumps(result, allow_nan=False)


def test_johansen_validation_agrees_with_the_effective_design_bound():
    from workbench.native_johansen import validate_johansen_size

    for columns in (3, 4):
        for lag in range(1, 5):
            minimum = (columns + 1) * lag + 2 * columns + 3
            validate_johansen_size(minimum, columns, lag)
            with pytest.raises(TimeSeriesPackError) as error:
                validate_johansen_size(minimum - 1, columns, lag)
            assert error.value.reason_code == 'TIME_SERIES_TOO_FEW_OBSERVATIONS'
    with pytest.raises(TimeSeriesPackError) as error:
        validate_johansen_size(20_001, 4, 4)
    assert error.value.reason_code == 'TIME_SERIES_SIZE_LIMIT'


@pytest.mark.parametrize('problem,reason', [
    ('duplicate series', 'TIME_SERIES_BAD_INPUT'),
    ('time as series', 'TIME_SERIES_BAD_INPUT'),
    ('missing series', 'TIME_SERIES_MISSING_COLUMN'),
    ('non numeric series', 'TIME_SERIES_NON_NUMERIC_VALUE'),
    ('unsorted time', 'TIME_SERIES_ORDER_INVALID'),
    ('irregular time', 'TIME_SERIES_IRREGULAR_TIME'),
    ('boolean lag', 'TIME_SERIES_INVALID_OPTION'),
])
def test_johansen_rejects_invalid_input_before_loading(monkeypatch, problem, reason):
    from workbench import native_johansen

    monkeypatch.setattr(native_johansen, '_loaded', lambda: pytest.fail('invalid input reached native load'))
    frame, names = make_frame()
    lag = 1
    if problem == 'duplicate series':
        names[-1] = names[0]
    elif problem == 'time as series':
        names[-1] = 'period'
    elif problem == 'missing series':
        names[-1] = 'missing'
    elif problem == 'non numeric series':
        frame[names[-1]] = 'not a number'
    elif problem == 'unsorted time':
        frame = frame.iloc[::-1]
    elif problem == 'irregular time':
        frame = frame.drop(index=10)
    else:
        lag = True
    with pytest.raises(TimeSeriesPackError) as error:
        native_johansen.run_johansen_rank(frame, time_col='period', series_columns=names, difference_lags=lag)
    assert error.value.reason_code == reason


def test_johansen_preserves_nonfinite_row_and_series_identity(native_manifest):
    from workbench.native_johansen import run_johansen_rank

    frame, names = make_frame()
    frame.loc[35, names[-1]] = np.inf
    with pytest.raises(TimeSeriesPackError, match=r"'series_2'.*row 35") as error:
        run_johansen_rank(frame, time_col='period', series_columns=names)
    assert error.value.reason_code == 'TIME_SERIES_NON_FINITE_VALUE'


def test_johansen_rejects_rank_deficiency_and_canonical_boundary(native_manifest):
    from workbench.native_johansen import run_johansen_rank

    frame, names = make_frame()
    frame[names[-1]] = 2 * frame[names[0]] + 1
    with pytest.raises(TimeSeriesPackError, match='lagged differences') as error:
        run_johansen_rank(frame, time_col='period', series_columns=names)
    assert error.value.reason_code == 'TIME_SERIES_JOHANSEN_RANK_DEFICIENT'

    periods = np.arange(len(frame))
    patterns = ([0, 1, 0, -1], [0, 1, 1, 0, -1, -1], [1, -1, 0])
    for name, pattern in zip(names, patterns, strict=True):
        frame[name] = np.array(pattern)[periods % len(pattern)]
    with pytest.raises(TimeSeriesPackError, match='canonical root') as error:
        run_johansen_rank(frame, time_col='period', series_columns=names)
    assert error.value.reason_code == 'TIME_SERIES_JOHANSEN_CANONICAL_UNRESOLVED'


def test_johansen_cancellation_reaches_the_native_factorization(native_manifest):
    from workbench.native_johansen import run_johansen_rank

    frame, names = make_frame(4)
    interrupted = RuntimeError('cancelled during Johansen rank diagnostics')
    calls = 0

    def check():
        nonlocal calls
        calls += 1
        if calls == 16:
            raise interrupted

    with cancellation_scope(check), pytest.raises(RuntimeError) as error:
        run_johansen_rank(frame, time_col='period', series_columns=names, difference_lags=4)
    assert error.value is interrupted
    assert calls == 16
