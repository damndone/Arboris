"""Opt-in original-binary64 exact moments; small functional proofs, no clocks."""
from itertools import combinations_with_replacement
import asyncio
import hashlib
import importlib
import inspect
import math
import os
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from workbench.checks import ar_confidence as reference
from workbench.checks.ar_cancellation import cancellation_scope, current_check
from workbench.checks.ar_polynomials import certify_set


def test_moments_has_an_explicit_entrypoint_without_replacing_the_default():
    native = importlib.import_module('workbench.native_ar')
    assert callable(getattr(native, 'robust_polynomials_moments', None)), 'explicit moments implementation missing'
    assert list(inspect.signature(native.robust_polynomials).parameters) == ['y', 'x', 'z', 'w', 'critical']


@pytest.fixture
def native():
    module = importlib.import_module('workbench.native_ar')
    if not module._MOMENTS_BINARY.exists():
        if os.environ.get('NATIVE_AR_MOMENTS_REQUIRED') == '1':
            pytest.fail('build explicitly: native/ar_exact/build.py --engine moments')
        pytest.skip('optional exact moments extension not built')
    module._moments_kernel()
    return module


def case(p=4, q=2, rows=13, seed=659):
    rng = np.random.default_rng(seed + p + q)
    data = rng.integers(-9, 10, (rows, p + 2)).astype(float) / 8
    return data[:, 0], data[:, 1:2], data[:, -q:], data[:, 2:-q]


def raw_oracle(values, raw):
    y, x, z, w = values
    ratios = [[float(value).as_integer_ratio() for value in
               [y[i], x[i, 0], *w[i], *z[i]]] for i in range(len(y))]
    denominator = max(d for row in ratios for _, d in row)
    rows = [[n * (denominator // d) for n, d in row] for row in ratios]
    assert raw['scale'] == denominator.bit_length() - 1
    columns = raw['p'] + 2
    for degree, field in ((2, 'second'), (4, 'fourth')):
        keys = [key for key in combinations_with_replacement(range(columns), degree)
                if degree == 2 or sum(index >= 2 for index in key) >= 2]
        assert list(raw[field]) == keys
        for key in keys:
            assert raw[field][key] == sum(math.prod(row[i] for i in key) for row in rows)


@pytest.mark.parametrize('p,q', [(1, 1), (2, 1), (2, 2), (3, 1), (3, 2),
                                 (3, 3), (4, 1), (4, 2), (4, 3), (4, 4)])
def test_every_integer_layer_and_complete_certificate_match_original(native, p, q):
    values = case(p, q)
    raw = native._moments_kernel().moments(*values)
    raw_oracle(values, raw)
    components = native._moments_components(raw, q)
    yy, xx, rows = reference._integer_data(*values)
    a, u, v, d, ee, ff = reference._projection(yy, xx, rows)
    gram = [[sum(row[i] * row[j] for row in rows) for j in range(p)] for i in range(p)]
    cy = [sum(row[j] * y for row, y in zip(rows, yy)) for j in range(p)]
    cx = [sum(row[j] * x for row, x in zip(rows, xx)) for j in range(p)]
    assert (components['gram'], components['cy'], components['cx']) == (gram, cy, cx)
    assert (components['a'], components['u'], components['v'], components['d']) == (a, u, v, d)
    covariance = [[[0, 0, 0] for _ in range(q)] for _ in range(q)]
    for row, e, f in zip(rows, ee, ff):
        k = [sum(t * c for t, c in zip(line, row)) for line in a[-q:]]
        for j in range(q):
            for h in range(q):
                for power, residual in enumerate((e * e, -2 * e * f, f * f)):
                    covariance[j][h][power] += k[j] * k[h] * residual
    assert components['m'] == covariance
    critical = 3.841458820694124
    expected = reference.robust_polynomials_reference(*values, critical)
    actual = native.robust_polynomials_moments(*values, critical)
    assert actual == expected
    assert certify_set(*actual) == certify_set(*expected)


def test_p4_extreme_products_carries_and_signed_cancellation(native):
    largest, tiny = np.finfo(float).max, np.nextafter(0., 1.)
    pattern = np.array([largest, -largest, tiny, -tiny, 2.**1023, -0., 0., 1.])
    columns = [np.resize(np.roll(pattern, i), 257) for i in range(6)]
    values = (columns[0], columns[1][:, None], np.column_stack(columns[4:]), np.column_stack(columns[2:4]))
    raw = native._moments_kernel().moments(*values)
    assert (raw['p'], raw['second_term_count'], raw['fourth_term_count']) == (4, 21, 105)
    assert raw['limb_bits_per_signed_sum'] >= (257 * (int(largest) << 1074)**4).bit_length()
    raw_oracle(values, raw)


def test_strides_subnormal_negative_zero_and_exact_rank_failure(native):
    values = tuple(array[::-1] for array in case())
    values[0][:5] = [np.nextafter(0., 1.), -0., 2.**-900, -2.**900, 1.]
    assert native.robust_polynomials_moments(*values, 3.84) == reference.robust_polynomials_reference(*values, 3.84)
    y, x, z, w = case()
    z[:, 1] = z[:, 0]
    z[0, 1] = np.nextafter(z[0, 1], np.inf)
    assert native.robust_polynomials_moments(y, x, z, w, 3.84) == reference.robust_polynomials_reference(y, x, z, w, 3.84)
    z[:, 1] = z[:, 0]
    with pytest.raises(ValueError, match='rank_deficient_auxiliary_design'):
        native.robust_polynomials_moments(y, x, z, w, 3.84)


@pytest.mark.parametrize('bad', [np.nan, np.inf, -np.inf])
def test_nonfinite_input_fails_instead_of_returning_a_certificate(native, bad):
    y, x, z, w = case()
    y[0] = bad
    with pytest.raises(ValueError, match='nonfinite_original_binary64'):
        native.robust_polynomials_moments(y, x, z, w, 3.84)


def test_invalid_dtype_shape_and_p5_are_explicit_without_default_dispatch(native, monkeypatch):
    def forbidden(*args):
        pytest.fail('explicit moments must not silently call the default engine')
    monkeypatch.setattr(native, 'robust_polynomials', forbidden)
    y, x, z, w = case()
    with pytest.raises((TypeError, ValueError), match='binary64'):
        native.robust_polynomials_moments(y.astype(np.float32), x, z, w, 3.84)
    with pytest.raises(ValueError, match='shape'):
        native.robust_polynomials_moments(y[:-1], x, z, w, 3.84)
    with pytest.raises(ValueError, match='exact_moments_envelope'):
        native.robust_polynomials_moments(*case(p=5), 3.84)


@pytest.mark.parametrize('at', [1, 2, 3, 4, 67, 129])
def test_native_block_and_output_cancel_preserves_owner_exception(native, at):
    original = asyncio.CancelledError('exact moments owner')
    calls = 0
    def owner():
        nonlocal calls
        calls += 1
        if calls == at:
            raise original
    with pytest.raises(asyncio.CancelledError) as caught:
        native._moments_kernel().moments(*case(rows=513), owner)
    assert caught.value is original and calls == at
    assert native._moments_kernel().moments(*case(rows=2))['rows'] == 2


@pytest.mark.parametrize('target', ['_inverse_integer', 'contract', 'determinant', 'divide', 'isolate'])
def test_same_owner_cancels_matrix_contraction_determinants_and_certificate(native, target):
    original = RuntimeError('owner cancelled in ' + target)
    def owner():
        caller = inspect.currentframe().f_back
        if caller.f_code.co_name == 'check_cancellation':
            caller = caller.f_back
        if caller.f_code.co_name == target:
            raise original
    with pytest.raises(RuntimeError) as caught:
        with cancellation_scope(owner):
            result = native.robust_polynomials_moments(*case(), 3.84)
            certify_set(*result)
    assert caught.value is original and current_check() is None


def test_moments_native_identity_is_bound_to_source_and_interpreter(native):
    kernel = native._moments_kernel()
    assert kernel.ABI_VERSION == 1 and kernel.MAX_P == 4 and kernel.SNAPSHOT_ROWS == 256
    assert kernel.SOURCE_SHA256 == hashlib.sha256(native._MOMENTS_SOURCE.read_bytes()).hexdigest()
    assert (kernel.PYTHON_MAJOR, kernel.PYTHON_MINOR) == sys.version_info[:2]


@pytest.mark.parametrize('field,value', [('ABI_VERSION', True), ('ABI_VERSION', 2), ('MAX_P', 5),
                                       ('SNAPSHOT_ROWS', 512), ('PYTHON_MINOR', -1), ('SOURCE_SHA256', 'stale')])
def test_moments_abi_or_source_error_never_downgrades(native, field, value):
    original = native._moments_kernel()
    fields = {name: getattr(original, name) for name in ('ABI_VERSION', 'MAX_P', 'SNAPSHOT_ROWS',
              'PYTHON_MAJOR', 'PYTHON_MINOR', 'SOURCE_SHA256', 'moments')}
    fields[field] = value
    with pytest.raises(RuntimeError, match='native_ar_moments_'):
        native._validate_moments_kernel(SimpleNamespace(**fields))


def test_moments_missing_foreign_and_corrupt_builds_are_distinct(tmp_path, monkeypatch):
    native = importlib.import_module('workbench.native_ar')
    expected = tmp_path / native._MOMENTS_BINARY.name
    monkeypatch.setattr(native, '_MOMENTS_BINARY', expected)
    native._moments_kernel.cache_clear()
    try:
        with pytest.raises(RuntimeError, match='moments_not_built'):
            native.robust_polynomials_moments(*case(), 3.84)
        (tmp_path / '_ar_moments_exact.cpython-foreign-abi.so').write_bytes(b'foreign')
        with pytest.raises(RuntimeError, match='foreign_interpreter_abi_present'):
            native.robust_polynomials_moments(*case(), 3.84)
        expected.write_bytes(b'corrupt')
        with pytest.raises(RuntimeError, match='extension_load_failed'):
            native.robust_polynomials_moments(*case(), 3.84)
    finally:
        native._moments_kernel.cache_clear()


def test_current_default_does_not_load_opt_in_moments(native, monkeypatch):
    from workbench.checks import ar_verified
    def forbidden():
        pytest.fail('the default exact path must not load the opt-in engine')
    def uncertain(*args):
        raise ar_verified.VerificationUncertain('exercise accepted default')
    monkeypatch.setattr(native, '_moments_kernel', forbidden)
    monkeypatch.setattr(ar_verified, 'verified_set', uncertain)
    values = case(p=1, q=1)
    expected = native.robust_polynomials(*values, 3.84)
    assert reference.robust_polynomials(*values, 3.84) == expected
    assert reference.robust_set(*values)['computation']['engine'] == 'native_cpp_exact'


def test_moments_existing_owner_context_crosses_to_thread_without_new_scope(native):
    original = RuntimeError('execution owner in worker thread')
    def owner():
        if inspect.currentframe().f_back.f_code.co_name == '_inverse_integer':
            raise original
    async def scenario():
        with cancellation_scope(owner):
            before = current_check()
            with pytest.raises(RuntimeError) as caught:
                await asyncio.to_thread(native.robust_polynomials_moments, *case(), 3.84)
            assert caught.value is original and current_check() is before
    asyncio.run(scenario())
    assert current_check() is None


def test_moments_runtime_arithmetic_error_is_not_silently_replaced(native, monkeypatch):
    original = ArithmeticError('native moment computation failed')
    def broken(*args):
        raise original
    def forbidden(*args):
        pytest.fail('runtime failure must not call the default exact engine')
    monkeypatch.setattr(native, '_moments_kernel', lambda: SimpleNamespace(moments=broken))
    monkeypatch.setattr(native, 'robust_polynomials', forbidden)
    with pytest.raises(ArithmeticError) as caught:
        native.robust_polynomials_moments(*case(), 3.84)
    assert caught.value is original
