"""General large-sample exact selection; no million-row arithmetic or timing."""
import asyncio
import hashlib
import importlib
import os
import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from workbench.checks import ar_confidence as ar
from workbench.checks.ar_cancellation import cancellation_scope, current_check


@pytest.fixture
def native():
    module = importlib.import_module('workbench.native_ar')
    loader = module._moments_kernel
    loader.cache_clear()
    yield module
    loader.cache_clear()


def views(n=1_000_000, p=4, q=2):
    # These views export the real native-binary64 shapes without allocating or
    # reading N observations. Dispatch spies never calculate on these values.
    return (np.broadcast_to(np.array([1.]), (n,)),
            np.broadcast_to(np.array([[2.]]), (n, 1)),
            np.broadcast_to(np.arange(q, dtype=float)[None, :], (n, q)),
            np.broadcast_to(np.arange(p - q, dtype=float)[None, :], (n, p - q)))


def moments_kernel(native, calculate=lambda *args: None):
    return SimpleNamespace(ABI_VERSION=1, MAX_P=4, SNAPSHOT_ROWS=256,
        PYTHON_MAJOR=sys.version_info.major, PYTHON_MINOR=sys.version_info.minor,
        SOURCE_SHA256=hashlib.sha256(native._MOMENTS_SOURCE.read_bytes()).hexdigest(), moments=calculate)


def row_kernel(native):
    return SimpleNamespace(ABI_VERSION=2, SOURCE_SHA256=hashlib.sha256(native._SOURCE.read_bytes()).hexdigest())


@pytest.mark.parametrize('n,p,q', [(1_000_000, 4, 2), (1_000_001, 1, 1),
                                  (1_250_000, 2, 2), (2_000_000, 3, 1), (1_000_000, 4, 4)])
def test_general_large_sample_status_matches_actual_dispatch(native, monkeypatch, n, p, q):
    kernel = moments_kernel(native)
    monkeypatch.setattr(native, '_moments_kernel', lambda: kernel)
    called = []
    answer = ([1, 2], [3, 4])
    def calculate(*args):
        called.append(args)
        return answer
    monkeypatch.setattr(native, 'robust_polynomials_moments', calculate)
    def forbidden(*args):
        pytest.fail('selected moments must not enter row arithmetic')
    monkeypatch.setattr(native, 'sufficient_statistics', forbidden)
    values = views(n, p, q)
    status = native.engine_status(*values)
    assert status['engine'] == 'native_cpp_exact' and status['engine_algorithm'] == 'moments'
    assert status['engine_abi'] == 1 and status['engine_source_sha256'] == kernel.SOURCE_SHA256
    assert status['performance_evidence_scope'] == 'fixed_input_1m_p4_q2_component'
    assert status['other_shapes_performance_certified'] is False
    assert native.robust_polynomials(*values, 4.) is answer
    assert len(called) == 1 and all(actual is expected for actual, expected in zip(called[0][:4], values))


@pytest.mark.parametrize('n,p,q', [(999_999, 4, 2), (1_000_000, 5, 2), (1_000_000, 12, 4)])
def test_small_or_wide_inputs_do_not_probe_moments(native, monkeypatch, n, p, q):
    monkeypatch.setattr(native, '_kernel', row_kernel(native))
    def forbidden():
        pytest.fail('unselected optional moments must stay unloaded')
    monkeypatch.setattr(native, '_moments_kernel', forbidden)
    status = native.engine_status(*views(n, p, q))
    assert status['engine_algorithm'] == 'row_exact' and status['engine_abi'] == 2


def test_no_argument_status_still_describes_row_primitives(native, monkeypatch):
    monkeypatch.setattr(native, '_kernel', row_kernel(native))
    def forbidden():
        pytest.fail('primitive status cannot load the optional moments engine')
    monkeypatch.setattr(native, '_moments_kernel', forbidden)
    assert native.engine_status()['engine_algorithm'] == 'row_exact'


def test_missing_moments_is_an_explicit_old_exact_selection(native, monkeypatch, tmp_path):
    monkeypatch.setattr(native, '_MOMENTS_BINARY', tmp_path / native._MOMENTS_BINARY.name)
    monkeypatch.setattr(native, '_kernel', row_kernel(native))
    values = views(p=1, q=1)
    status = native.engine_status(*values)
    assert status['engine_algorithm'] == 'row_exact'
    assert status['moments_reason'] == 'native_ar_moments_not_built'
    calls = []
    def sufficient(*args):
        calls.append('row_gram')
        return 1, [[24]], [22], [0]
    def covariance(*args):
        calls.append('row_covariance')
        return [[[16512, -4608, 18432]]]
    monkeypatch.setattr(native, 'sufficient_statistics', sufficient)
    monkeypatch.setattr(native, 'covariance_polynomial', covariance)
    assert native.robust_polynomials(*values, 4.) == ([212736, 18432, -73728], [16512, -4608, 18432])
    assert calls == ['row_gram', 'row_covariance']
    with pytest.raises(RuntimeError, match='moments_not_built'):
        native.robust_polynomials_moments(*values, 4.)


def test_both_missing_keep_the_explicit_python_reference(native, monkeypatch, tmp_path):
    monkeypatch.setattr(native, '_kernel', None)
    monkeypatch.setattr(native, '_MOMENTS_BINARY', tmp_path / native._MOMENTS_BINARY.name)
    values = views()
    status = native.engine_status(*values)
    assert status['engine'] == 'python_exact_reference'
    assert status['engine_reason'] == 'native_ar_not_built'
    assert status['moments_reason'] == 'native_ar_moments_not_built'
    result = ([1], [1])
    monkeypatch.setattr(ar, 'robust_polynomials_reference', lambda *args: result)
    assert ar.robust_polynomials(*values, 4.) is result


def test_moments_does_not_require_the_optional_row_binary(native, monkeypatch):
    monkeypatch.setattr(native, '_kernel', None)
    kernel = moments_kernel(native)
    monkeypatch.setattr(native, '_moments_kernel', lambda: kernel)
    result = ([1], [1])
    monkeypatch.setattr(native, 'robust_polynomials_moments', lambda *args: result)
    values = views()
    assert native.engine_status(*values)['engine_algorithm'] == 'moments'
    assert ar.robust_polynomials(*values, 4.) is result


@pytest.mark.parametrize('failure', ['corrupt', 'foreign', 'abi', 'source'])
def test_present_invalid_moments_never_falls_back(native, monkeypatch, tmp_path, failure):
    expected = tmp_path / native._MOMENTS_BINARY.name
    monkeypatch.setattr(native, '_MOMENTS_BINARY', expected)
    if failure == 'foreign':
        (tmp_path / '_ar_moments_exact.cpython-foreign-abi.so').write_bytes(b'foreign')
        error = 'foreign_interpreter_abi_present'
    elif failure == 'corrupt':
        expected.write_bytes(b'corrupt')
        error = 'extension_load_failed'
    else:
        kernel = moments_kernel(native)
        if failure == 'abi':
            kernel.ABI_VERSION = -1
            error = 'moments_abi_mismatch'
        else:
            kernel.SOURCE_SHA256 = 'stale'
            error = 'moments_source_digest_mismatch'
        monkeypatch.setattr(native, '_load_kernel', lambda *args, **kwargs: kernel)
    with pytest.raises(RuntimeError, match=error):
        native.engine_status(*views())


def test_moments_computation_error_is_not_replaced_by_rows(native, monkeypatch):
    original = ArithmeticError('selected moments computation failed')
    def broken(*args):
        raise original
    monkeypatch.setattr(native, '_moments_kernel', lambda: moments_kernel(native, broken))
    def forbidden(*args):
        pytest.fail('a moments error cannot start row arithmetic')
    monkeypatch.setattr(native, 'sufficient_statistics', forbidden)
    with pytest.raises(ArithmeticError) as caught:
        ar.robust_polynomials(*views(), 4.)
    assert caught.value is original


def test_public_exact_set_records_the_selected_algorithm(native, monkeypatch):
    from workbench.checks import ar_verified
    kernel = moments_kernel(native)
    monkeypatch.setattr(native, '_moments_kernel', lambda: kernel)
    calls = []
    def calculate(*args):
        calls.append(args)
        return [1], [1]
    def uncertain(*args):
        raise ar_verified.VerificationUncertain('exercise exact dispatch metadata')
    monkeypatch.setattr(native, 'robust_polynomials_moments', calculate)
    monkeypatch.setattr(ar_verified, 'verified_set', uncertain)
    result = ar.robust_set(*views())
    assert len(calls) == 1 and result['computation']['path'] == 'exact_fallback'
    assert result['computation']['engine_algorithm'] == 'moments'
    assert result['computation']['engine_abi'] == 1
    assert result['computation']['engine_source_sha256'] == kernel.SOURCE_SHA256
    assert result['global_certification']['arithmetic'] == 'exact_binary64_input_rationals'


def test_selected_public_set_matches_real_integer_polynomials_and_certificate(native, monkeypatch):
    if not native._MOMENTS_BINARY.exists():
        if os.environ.get('NATIVE_AR_MOMENTS_REQUIRED') == '1':
            pytest.fail('build native/ar_exact/build.py --engine moments')
        pytest.skip('optional moments extension not built')
    from workbench.checks import ar_verified
    rng = np.random.default_rng(874)
    data = rng.integers(-9, 10, (17, 6)).astype(float) / 8
    values = data[:, 0], data[:, 1:2], data[:, 3:], data[:, 2:3]
    # Only the cost threshold is reduced for this small functional test.
    # The real public dispatch, native kernel and certificate remain intact.
    monkeypatch.setattr(native, '_MOMENTS_MIN_ROWS', len(data))
    observed = []
    original = native.robust_polynomials_moments
    def calculate(*args):
        result = original(*args)
        assert result == ar.robust_polynomials_reference(*args)
        observed.append(result)
        return result
    def uncertain(*args):
        raise ar_verified.VerificationUncertain('small real selected-engine integration')
    monkeypatch.setattr(native, 'robust_polynomials_moments', calculate)
    monkeypatch.setattr(ar_verified, 'verified_set', uncertain)
    result = ar.robust_set(*values)
    assert len(observed) == 1
    assert result['computation']['engine_algorithm'] == 'moments'
    assert result['computation']['engine_abi'] == 1
    assert result['computation']['engine_source_sha256'] == native._moments_kernel().SOURCE_SHA256
    expected = ar.certify_set(*observed[0])
    assert all(result[key] == value for key, value in expected.items())


def test_selected_real_moments_preserves_owner_before_reading_rows(native, monkeypatch):
    if not native._MOMENTS_BINARY.exists():
        if os.environ.get('NATIVE_AR_MOMENTS_REQUIRED') == '1':
            pytest.fail('build native/ar_exact/build.py --engine moments')
        pytest.skip('optional moments extension not built')
    values = views(n=1_000_001, p=3, q=1)
    assert native.engine_status(*values)['engine_algorithm'] == 'moments'
    original = asyncio.CancelledError('real selected moments entry')
    entered = []
    def owner():
        # A C++ callback returns directly to this Python frame. Python-side
        # checks have an intervening check_cancellation frame instead.
        if sys._getframe(1).f_code is native.robust_polynomials_moments.__code__:
            entered.append(True)
            raise original
    def forbidden(*args):
        pytest.fail('real moments entry must not start the row engine')
    monkeypatch.setattr(native, 'sufficient_statistics', forbidden)
    with cancellation_scope(owner):
        with pytest.raises(asyncio.CancelledError) as caught:
            native.robust_polynomials(*values, 4.)
    assert entered == [True] and caught.value is original and current_check() is None


def test_default_iv_still_does_not_compute_ar_or_load_moments(native, monkeypatch):
    from workbench.checks.context import build_context
    from workbench.checks.iv_checks import FIRST_STAGE_STRENGTH, first_stage_strength
    from workbench.econometrics.runner import run_iv_2sls
    def forbidden():
        pytest.fail('default IV must not load moments')
    monkeypatch.setattr(native, '_moments_kernel', forbidden)
    rng = np.random.default_rng(281)
    frame = pd.DataFrame(rng.normal(size=(41, 4)), columns=['y', 'x', 'z', 'w'])
    _, fitted = run_iv_2sls(frame, y='y', exog=['w'], endog=['x'], instruments=['z'], model_id='iv_2sls_1')
    context = build_context(model_id='iv_2sls_1', model_type='iv_2sls', fitted=fitted, kernel=None, nobs=41)
    result = first_stage_strength(context, FIRST_STAGE_STRENGTH)
    assert result.evidence['anderson_rubin_95'] == {'kind': 'not_computed', 'reason': 'request_ar_confidence_explicitly'}
