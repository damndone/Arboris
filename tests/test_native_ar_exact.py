"""Original-input integer equality, independent of root isolation tolerances."""
import importlib
import os

import numpy as np
import pytest

from workbench.checks import ar_confidence as ar


def _native(require_kernel=True):
    native = importlib.import_module('workbench.native_ar')
    if require_kernel and native._kernel is None:
        if os.environ.get('NATIVE_AR_REQUIRED') == '1':
            pytest.fail('native AR build is required; run native/ar_exact/build.py')
        pytest.skip('optional native AR kernel not built')
    return native


def _case(n=13, p=3, q=2, seed=239):
    rng = np.random.default_rng(seed)
    r = rng.normal(size=(n, p))
    return rng.normal(size=n), rng.normal(size=(n, 1)), r[:, -q:], r[:, :-q]


def test_native_ar_hand_computed_integer_gram():
    native = _native()
    y = np.array([.5, 1.5, -2.])
    x = np.array([[1.], [-.5], [0.]])
    z = np.array([[1.], [2.], [-1.]])
    w = np.empty((3, 0))
    scale, gram, cy, cx = native.sufficient_statistics(y, x, z, w)
    assert (scale, gram, cy, cx) == (1, [[24]], [22], [0])
    # A=1,D=24,U=22,V=0; E=(-20,-16,-52), F=(48,-24,0), K=(2,4,-2).
    m = native.covariance_polynomial(y, x, z, w, scale, [[1]], 24, [22], [0])
    assert m == [[[16512, -4608, 18432]]]
    assert native.robust_polynomials(y, x, z, w, 4.) == ([212736, 18432, -73728], [16512, -4608, 18432])


@pytest.mark.parametrize('p,q', [(1, 1), (3, 1), (3, 2), (5, 4), (12, 4)])
def test_native_ar_polynomials_equal_python_integer_by_integer(p, q):
    native = _native()
    values = _case(n=17, p=p, q=q)
    assert native.robust_polynomials(*values, 7.814727903251179) == ar.robust_polynomials_reference(*values, 7.814727903251179)


@pytest.mark.parametrize('seed', range(10))
def test_native_ar_each_exact_layer_equals_python_reference(seed):
    native = _native()
    values = _case(n=11, p=3, q=2, seed=seed)
    yy, xx, rr = ar._integer_data(*values)
    scale, gram, cy, cx = native.sufficient_statistics(*values)
    assert 2**scale == max(float(v).as_integer_ratio()[1] for array in values for v in array.flat)
    assert gram == [[sum(row[i]*row[j] for row in rr) for j in range(3)] for i in range(3)]
    assert cy == [sum(row[j]*v for row, v in zip(rr, yy)) for j in range(3)]
    assert cx == [sum(row[j]*v for row, v in zip(rr, xx)) for j in range(3)]
    a, d = ar._inverse_integer(gram)
    u = [sum(t*c for t, c in zip(row, cy)) for row in a]
    v = [sum(t*c for t, c in zip(row, cx)) for row in a]
    ref_a, ref_u, ref_v, ref_d, ee, ff = ar._projection(yy, xx, rr)
    assert (a, u, v, d) == (ref_a, ref_u, ref_v, ref_d)
    m = [[[0, 0, 0] for _ in range(2)] for _ in range(2)]
    for row, e, f in zip(rr, ee, ff):
        k = [sum(t*c for t, c in zip(aa, row)) for aa in ref_a[-2:]]
        for i in range(2):
            for j in range(2):
                for power, term in enumerate([e*e, -2*e*f, f*f]):
                    m[i][j][power] += k[i]*k[j]*term
    assert native.covariance_polynomial(*values, scale, a, d, u, v) == m


def test_native_ar_max_finite_exponents_and_near_dependent_columns():
    native = _native()
    y, x, z, w = _case(n=7, p=2, q=1)
    y[0], x[1, 0] = np.finfo(float).max, -np.finfo(float).tiny
    w[:, 0] = z[:, 0]
    w[0, 0] = np.nextafter(w[0, 0], np.inf)
    assert native.robust_polynomials(y, x, z, w, 3.84) == ar.robust_polynomials_reference(y, x, z, w, 3.84)


def test_native_ar_subnormal_signed_zero_extreme_exponents():
    native = _native()
    y = np.array([np.nextafter(0., 1.), -0., 2.**-900, -2.**900, 1.])
    x = np.array([[2.**-1070], [0.], [-2.**800], [2.**-800], [2.]])
    z = np.array([[1.], [0.], [2.], [3.], [-1.]])
    w = np.empty((5, 0))
    values = (y, x, z, w)
    yy, xx, rr = ar._integer_data(*values)
    scale, gram, cy, cx = native.sufficient_statistics(*values)
    assert scale == 1074
    assert gram == [[sum(row[0]**2 for row in rr)]]
    assert cy == [sum(row[0]*v for row, v in zip(rr, yy))]
    assert cx == [sum(row[0]*v for row, v in zip(rr, xx))]
    assert native.robust_polynomials(*values, 3.84) == ar.robust_polynomials_reference(*values, 3.84)


def test_native_ar_strided_input_and_exact_rank_failure():
    native = _native()
    y, x, z, w = _case(p=2, q=1)
    values = tuple(a[::-2] for a in (y, x, z, w))
    assert native.robust_polynomials(*values, 3.84) == ar.robust_polynomials_reference(*values, 3.84)
    z[:] = w
    with pytest.raises(ValueError, match='rank_deficient_auxiliary_design'):
        native.robust_polynomials(y, x, z, w, 3.84)


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), -float('inf')])
def test_native_ar_rejects_nonfinite_original_inputs(bad):
    native = _native()
    y, x, z, w = _case()
    y[0] = bad
    with pytest.raises(ValueError, match='nonfinite_original_binary64'):
        native.sufficient_statistics(y, x, z, w)


def test_native_ar_enforces_dtype_and_envelope():
    native = _native()
    y, x, z, w = _case()
    with pytest.raises((ValueError, TypeError), match='binary64'):
        native.sufficient_statistics(y.astype(np.float32), x, z, w)
    with pytest.raises(ValueError, match='shape'):
        native.sufficient_statistics(y[:-1], x, z, w)
    with pytest.raises(ValueError, match='envelope'):
        native.sufficient_statistics(*_case(p=13, q=4))


def test_native_ar_on_demand_fallback_uses_native_and_preserves_target(monkeypatch):
    native = _native()
    from workbench.checks import ar_verified
    values = _case(n=9, p=1, q=1)
    expected = native.robust_polynomials(*values, 3.841458820694124)
    calls = []

    def uncertain(*args):
        raise ar_verified.VerificationUncertain('forced exact test')

    def calculate(*args):
        calls.append(args)
        return expected

    monkeypatch.setattr(ar_verified, 'verified_set', uncertain)
    monkeypatch.setattr(native, 'robust_polynomials', calculate)
    result = ar.robust_set(*values)
    assert len(calls) == 1
    assert result['computation']['path'] == 'exact_fallback'
    assert result['computation']['certification_target'] == 'original_binary64_observations'


def test_native_ar_abi_mismatch_is_explicit(monkeypatch):
    native = _native()
    monkeypatch.setattr(native._kernel, 'ABI_VERSION', -1)
    with pytest.raises(RuntimeError, match='native_ar_abi_mismatch'):
        native.sufficient_statistics(*_case())


def test_native_ar_missing_extension_uses_explicit_exact_reference(monkeypatch):
    native = _native(require_kernel=False)
    from workbench.checks import ar_verified
    values = _case(n=9, p=1, q=1)
    monkeypatch.setattr(native, '_kernel', None)
    assert ar.robust_polynomials(*values, 3.84) == ar.robust_polynomials_reference(*values, 3.84)

    def uncertain(*args):
        raise ar_verified.VerificationUncertain('forced missing extension')

    monkeypatch.setattr(ar_verified, 'verified_set', uncertain)
    result = ar.robust_set(*values)
    assert result['computation']['engine'] == 'python_exact_reference'
    assert result['computation']['engine_reason'] == 'native_ar_not_built'
    assert result['global_certification']['arithmetic'] == 'exact_binary64_input_rationals'


def test_native_ar_source_mismatch_and_kernel_error_do_not_downgrade(monkeypatch):
    native = _native()
    with monkeypatch.context() as patch:
        patch.setattr(native._kernel, 'SOURCE_SHA256', 'old build')
        with pytest.raises(RuntimeError, match='source_digest_mismatch'):
            ar.robust_polynomials(*_case(), 3.84)

    def broken(*args):
        raise RuntimeError('native arithmetic failure')

    monkeypatch.setattr(native._kernel, 'sufficient_statistics', broken)
    with pytest.raises(RuntimeError, match='native arithmetic failure'):
        ar.robust_polynomials(*_case(), 3.84)


def test_native_ar_product_preserves_mixed_integer_input_compatibility():
    native = _native()
    y = np.array([2., 0., 2.])
    x = np.array([[1], [-1], [0]], dtype=np.int64)
    z, w = x.copy(), np.empty((3, 0))
    assert native.engine_status(y, x, z, w) == {
        'engine': 'python_exact_reference', 'engine_reason': 'native_ar_requires_native_binary64_buffers'}
    assert ar.robust_polynomials(y, x, z, w, 4.) == ar.robust_polynomials_reference(y, x, z, w, 4.)


def test_native_ar_product_preserves_y_sequence_input_compatibility():
    _native()
    y, x, z, w = _case(n=9, p=1, q=1)
    assert ar.robust_polynomials(list(y), x, z, w, 3.84) == ar.robust_polynomials_reference(list(y), x, z, w, 3.84)


def test_native_ar_foreign_interpreter_binary_is_not_treated_as_missing(tmp_path):
    native = _native(require_kernel=False)
    expected = tmp_path/native._BINARY.name
    assert native._load_kernel(expected) is None
    (tmp_path/'_ar_exact.cpython-foreign-abi.so').write_bytes(b'foreign binary')
    with pytest.raises(RuntimeError, match='foreign_interpreter_abi_present'):
        native._load_kernel(expected)


def test_native_ar_corrupt_expected_binary_is_not_treated_as_missing(tmp_path):
    native = _native(require_kernel=False)
    expected = tmp_path/native._BINARY.name
    expected.write_bytes(b'corrupt expected binary')
    with pytest.raises(RuntimeError, match='extension_load_failed'):
        native._load_kernel(expected)


def test_native_ar_float_abi_version_is_rejected(monkeypatch):
    native = _native()
    monkeypatch.setattr(native._kernel, 'ABI_VERSION', 2.)
    with pytest.raises(RuntimeError, match='native_ar_abi_mismatch'):
        native.engine_status()
