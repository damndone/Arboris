"""Small, explicit bridge to the original-binary64 exact AR C++ kernel.

The optional local extension is never built implicitly. Missing builds retain
the exact Python reference through the caller's explicit engine selection;
an existing incompatible or broken extension raises instead of downgrading.
"""
from __future__ import annotations

import hashlib
import importlib.util
from functools import lru_cache
from itertools import combinations_with_replacement
from pathlib import Path
import sys
import sysconfig

from .checks.ar_cancellation import cancellation_scope, check_cancellation, current_check

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = _ROOT / 'native/ar_exact/ar_exact.cpp'
_BINARY = _ROOT / 'local/native-ar' / ('_ar_exact' + sysconfig.get_config_var('EXT_SUFFIX'))
_MOMENTS_SOURCE = _SOURCE.with_name('ar_moments.cpp')
_MOMENTS_BINARY = _BINARY.with_name('_ar_moments_exact' + sysconfig.get_config_var('EXT_SUFFIX'))
_MOMENTS_MIN_ROWS = 1_000_000


class _MomentsNotBuilt(RuntimeError):
    """Only a genuinely absent optional build permits the old exact path."""


def _load_kernel(binary, *, module_name='_ar_exact', error_prefix='native_ar'):
    if not binary.exists() and not binary.is_symlink():
        if any(path.suffix in {'.so', '.pyd'} for path in binary.parent.glob(module_name+'*')):
            raise RuntimeError(error_prefix+'_foreign_interpreter_abi_present_rebuild_required')
        return None
    try:
        spec = importlib.util.spec_from_file_location(module_name, binary)
        kernel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kernel)
        return kernel
    except (ImportError, OSError) as exc:
        raise RuntimeError(error_prefix+'_extension_load_failed') from exc


_kernel = _load_kernel(_BINARY)


def _row_status():
    if _kernel is None:
        return {'engine': 'python_exact_reference', 'engine_reason': 'native_ar_not_built'}
    if type(_kernel.ABI_VERSION) is not int or _kernel.ABI_VERSION != 2:
        raise RuntimeError('native_ar_abi_mismatch')
    if _kernel.SOURCE_SHA256 != hashlib.sha256(_SOURCE.read_bytes()).hexdigest():
        raise RuntimeError('native_ar_source_digest_mismatch_rebuild_required')
    return {'engine': 'native_cpp_exact', 'engine_algorithm': 'row_exact',
            'engine_abi': 2, 'engine_source_sha256': _kernel.SOURCE_SHA256}


def _moments_shape(views):
    if len(views) != 4:
        return False
    y, x, z, w = views
    if y.ndim not in (1, 2) or (y.ndim == 2 and y.shape[1] != 1):
        return False
    n = y.shape[0]
    return (n >= _MOMENTS_MIN_ROWS and x.shape == (n, 1) and z.ndim == w.ndim == 2
            and z.shape[0] == w.shape[0] == n and 1 <= z.shape[1] <= 4
            and z.shape[1] + w.shape[1] <= 4)


def engine_status(*inputs):
    """Select exact arithmetic; no inputs describes the row primitives.

    Large samples within p<=4 use moments. The general cost rule is broader
    than the fixed-input 1M p4/q2 performance proof; no other shape is thereby
    performance-certified. Buffer metadata is inspected without scanning or
    copying the caller's observations. Existing broken builds always fail.
    """
    row = _row_status()
    try:
        views = tuple(memoryview(array) for array in inputs)
    except TypeError:
        views = None  # Old callers may pass y as a Python sequence.
    if views is None or any(view.itemsize != 8 or view.format not in {'d', '=d', '@d'} for view in views):
        return (row if _kernel is None else
                {'engine': 'python_exact_reference', 'engine_reason': 'native_ar_requires_native_binary64_buffers'})
    if _moments_shape(views):
        try:
            kernel = _moments_kernel()
        except _MomentsNotBuilt:
            return row | {'moments_reason': 'native_ar_moments_not_built'}
        return {'engine': 'native_cpp_exact', 'engine_algorithm': 'moments',
                'engine_abi': kernel.ABI_VERSION, 'engine_source_sha256': kernel.SOURCE_SHA256,
                'performance_evidence_scope': 'fixed_input_1m_p4_q2_component',
                'other_shapes_performance_certified': False}
    return row


def sufficient_statistics(y, x, z, w):
    if engine_status()['engine'] != 'native_cpp_exact':
        raise RuntimeError('native_ar_not_built_run_native/ar_exact/build.py')
    return _kernel.sufficient_statistics(y, x, z, w, current_check())


def covariance_polynomial(y, x, z, w, scale, a, d, u, v):
    if engine_status()['engine'] != 'native_cpp_exact':
        raise RuntimeError('native_ar_not_built_run_native/ar_exact/build.py')
    return _kernel.covariance_polynomial(y, x, z, w, scale, a, d, u, v, current_check())


def robust_polynomials(y, x, z, w, critical):
    check_cancellation()
    if engine_status(y, x, z, w).get('engine_algorithm') == 'moments':
        return robust_polynomials_moments(y, x, z, w, critical)
    from .checks.ar_confidence import _inverse_integer, _robust_polynomial_determinants
    scale, gram, cross_y, cross_x = sufficient_statistics(y, x, z, w)
    check_cancellation()
    a, d = _inverse_integer(gram)
    u = [sum(t*c for t, c in zip(row, cross_y)) for row in a]
    v = [sum(t*c for t, c in zip(row, cross_x)) for row in a]
    m = covariance_polynomial(y, x, z, w, scale, a, d, u, v)
    check_cancellation()
    return _robust_polynomial_determinants(m, u[-z.shape[1]:], v[-z.shape[1]:], d, critical)


def _validate_moments_kernel(kernel):
    expected = {'ABI_VERSION': 1, 'MAX_P': 4, 'SNAPSHOT_ROWS': 256,
                'PYTHON_MAJOR': sys.version_info.major, 'PYTHON_MINOR': sys.version_info.minor}
    for name, value in expected.items():
        if type(getattr(kernel, name, None)) is not int or getattr(kernel, name) != value:
            raise RuntimeError('native_ar_moments_abi_mismatch: '+name)
    if getattr(kernel, 'SOURCE_SHA256', None) != hashlib.sha256(_MOMENTS_SOURCE.read_bytes()).hexdigest():
        raise RuntimeError('native_ar_moments_source_digest_mismatch_rebuild_required')
    if not callable(getattr(kernel, 'moments', None)):
        raise RuntimeError('native_ar_moments_entry_point_missing')


@lru_cache(maxsize=1)
def _moments_kernel():
    # Only selected/explicit moments load this optional extension. Validate its
    # immutable deployed source/ABI once, without scanning observation arrays.
    kernel = _load_kernel(_MOMENTS_BINARY, module_name='_ar_moments_exact', error_prefix='native_ar_moments')
    if kernel is None:
        raise _MomentsNotBuilt('native_ar_moments_not_built_run_native/ar_exact/build.py_--engine_moments')
    _validate_moments_kernel(kernel)
    return kernel


def _moments_components(raw, q):
    """Contract exact integer moments through the existing small-matrix math.

    No observations or rounded sufficient statistics enter this consumer.
    With R=(W,Z), A=D*G^-1, E=DY-U'R and F=DX-V'R, its KE/KF
    quadratic forms contract against exact original-input fourth moments.
    """
    from .checks.ar_confidence import _inverse_integer
    check_cancellation()
    p, second = raw['p'], raw['second']
    gram = [[second[tuple(sorted((i+2, j+2)))] for j in range(p)] for i in range(p)]
    cy, cx = ([second[(column, j+2)] for j in range(p)] for column in (0, 1))
    a, d = _inverse_integer(gram)
    u = [sum(t*c for t, c in zip(row, cy)) for row in a]
    v = [sum(t*c for t, c in zip(row, cx)) for row in a]
    e, f = [d, 0]+[-t for t in u], [0, d]+[-t for t in v]

    def quadratic(left, right):
        return {(i, j): left[i]*right[j]+(left[j]*right[i] if i != j else 0)
                for i, j in combinations_with_replacement(range(len(left)), 2)
                if left[i]*right[j]+(left[j]*right[i] if i != j else 0)}

    ke = [quadratic([0, 0]+row, e) for row in a[-q:]]
    kf = [quadratic([0, 0]+row, f) for row in a[-q:]]

    def contract(left, right):
        check_cancellation()
        return sum(c*b*raw['fourth'][tuple(sorted(i+j))]
                   for i, c in left.items() for j, b in right.items())

    m = [[[0, 0, 0] for _ in range(q)] for _ in range(q)]
    for j in range(q):
        for h in range(j+1):
            m[j][h] = m[h][j] = [contract(ke[j], ke[h]), -2*contract(ke[j], kf[h]), contract(kf[j], kf[h])]
    return dict(gram=gram, cy=cy, cx=cx, a=a, d=d, u=u, v=v, m=m)


def robust_polynomials_moments(y, x, z, w, critical):
    """Explicit exact moments, p<=4, also used by selected large exact calls.

    Missing/stale/broken builds and unsupported inputs fail. Callers retain
    their original binary64 arrays and execution-owned no-writer contract;
    only bounded private native blocks are copied. The existing cancellation
    scope covers native accumulation, matrix contractions and determinants.
    Component timing/resources were accepted on one fixed 1M p4/q2 input.
    Other shapes and full workflow/cancellation latency remain unaccepted.
    """
    from .checks.ar_confidence import _robust_polynomial_determinants
    check_cancellation()
    raw = _moments_kernel().moments(y, x, z, w, current_check())
    q = z.shape[1]
    components = _moments_components(raw, q)
    check_cancellation()
    return _robust_polynomial_determinants(
        components['m'], components['u'][-q:], components['v'][-q:], components['d'], critical)
