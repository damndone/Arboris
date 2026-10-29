"""Small, explicit bridge to the original-binary64 exact AR C++ kernel.

The optional local extension is never built implicitly. Missing builds retain
the exact Python reference through the caller's explicit engine selection;
an existing incompatible or broken extension raises instead of downgrading.
"""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import sysconfig

from .checks.ar_cancellation import cancellation_scope, check_cancellation, current_check

_ROOT = Path(__file__).resolve().parents[2]
_SOURCE = _ROOT / 'native/ar_exact/ar_exact.cpp'
_BINARY = _ROOT / 'local/native-ar' / ('_ar_exact' + sysconfig.get_config_var('EXT_SUFFIX'))


def _load_kernel(binary):
    if not binary.exists() and not binary.is_symlink():
        if any(path.suffix in {'.so', '.pyd'} for path in binary.parent.glob('_ar_exact*')):
            raise RuntimeError('native_ar_foreign_interpreter_abi_present_rebuild_required')
        return None
    try:
        spec = importlib.util.spec_from_file_location('_ar_exact', binary)
        kernel = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(kernel)
        return kernel
    except (ImportError, OSError) as exc:
        raise RuntimeError('native_ar_extension_load_failed') from exc


_kernel = _load_kernel(_BINARY)


def engine_status(*inputs):
    if _kernel is None:
        return {'engine': 'python_exact_reference', 'engine_reason': 'native_ar_not_built'}
    if type(_kernel.ABI_VERSION) is not int or _kernel.ABI_VERSION != 2:
        raise RuntimeError('native_ar_abi_mismatch')
    if _kernel.SOURCE_SHA256 != hashlib.sha256(_SOURCE.read_bytes()).hexdigest():
        raise RuntimeError('native_ar_source_digest_mismatch_rebuild_required')
    try:
        compatible = all(memoryview(array).format in {'d', '=d', '@d'} for array in inputs)
    except TypeError:
        compatible = False  # Old callers may pass y as a Python sequence.
    if not compatible:
        return {'engine': 'python_exact_reference', 'engine_reason': 'native_ar_requires_native_binary64_buffers'}
    return {'engine': 'native_cpp_exact', 'engine_abi': 2, 'engine_source_sha256': _kernel.SOURCE_SHA256}


def sufficient_statistics(y, x, z, w):
    if engine_status()['engine'] != 'native_cpp_exact':
        raise RuntimeError('native_ar_not_built_run_native/ar_exact/build.py')
    return _kernel.sufficient_statistics(y, x, z, w, current_check())


def covariance_polynomial(y, x, z, w, scale, a, d, u, v):
    if engine_status()['engine'] != 'native_cpp_exact':
        raise RuntimeError('native_ar_not_built_run_native/ar_exact/build.py')
    return _kernel.covariance_polynomial(y, x, z, w, scale, a, d, u, v, current_check())


def robust_polynomials(y, x, z, w, critical):
    from .checks.ar_confidence import _inverse_integer, _robust_polynomial_determinants
    scale, gram, cross_y, cross_x = sufficient_statistics(y, x, z, w)
    check_cancellation()
    a, d = _inverse_integer(gram)
    u = [sum(t*c for t, c in zip(row, cross_y)) for row in a]
    v = [sum(t*c for t, c in zip(row, cross_x)) for row in a]
    m = covariance_polynomial(y, x, z, w, scale, a, d, u, v)
    check_cancellation()
    return _robust_polynomial_determinants(m, u[-z.shape[1]:], v[-z.shape[1]:], d, critical)
