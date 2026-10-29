"""Finite-pair Spearman: native exact ranks, public NumPy/SciPy arithmetic.

The public numerical reference is NumPy 2.5.0 corrcoef and SciPy 1.18.0
stats.spearmanr; its BSD notice is in native/spearman_ranks/SCIPY_LICENSE.txt.
Only average ranking is native. Public column_stack promotion, F-layout
corrcoef reduction, t expression and stdtr order remain unchanged. Unsafe
integer promotion explicitly selects public SciPy; no new precision contract.

Build explicitly with native/spearman_ranks/build.py. Only an absent extension
selects reference; present broken/foreign ABI and native failures propagate.
No runtime compiler, environment path or numerical tuning configuration.
Caller buffers must not be concurrently written. Native work owns a key
snapshot; the GIL is held during snapshot and released for radix/output work.
Explicit owner checks poll between native passes/columns and around public
math, never inside a single NumPy/SciPy call. This module writes no artifacts.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import importlib.util
import logging
from pathlib import Path
import sysconfig
from typing import Any

import numpy as np
import scipy
from scipy import special, stats

_LOG = logging.getLogger(__name__)
EXT_SUFFIX = sysconfig.get_config_var('EXT_SUFFIX')
_NUMPY_VERSION = '2.5.0'
_SCIPY_VERSION = '1.18.0'
MAX_ROWS = 1_000_000
MAX_COLUMNS = 32


@dataclass(frozen=True)
class SpearmanOutcome:
    statistic: Any
    pvalue: Any
    engine: str
    reason: str | None
    native_public_promotion_refused: bool = False


def _extension_directory():
    return Path(__file__).resolve().parents[2]/'local/native-spearman-ranks'


def _load_extension(path):
    spec = importlib.util.spec_from_file_location('_spearman_rank',path)
    if spec is None or spec.loader is None:
        raise ImportError('native Spearman extension loader is unavailable')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    version = getattr(module,'ABI_VERSION',None)
    if type(version) is not int or version != 1:
        raise RuntimeError('native Spearman ABI mismatch; rebuild with this interpreter')
    if not callable(getattr(module,'rank_matrix',None)) or not callable(getattr(module,'workspace_info',None)):
        raise RuntimeError('native Spearman ABI entry points missing; rebuild current source')
    return module


@lru_cache(maxsize=1)
def _load_native():
    directory = _extension_directory()
    path = directory/('_spearman_rank'+EXT_SUFFIX)
    if path.is_file():
        return _load_extension(path)
    if path.is_symlink() or any(directory.glob('_spearman_rank*')):
        raise RuntimeError('native Spearman interpreter ABI mismatch/broken binary; rebuild current source')
    return None


def backend_info():
    native = _load_native()
    return {'engine':'native-average-rank' if native is not None else 'scipy-public',
            'reason':None if native is not None else 'extension-not-built',
            'numpy_version':np.__version__,'scipy_version':scipy.__version__,'abi':1,
            'max_rows':MAX_ROWS,'max_columns':MAX_COLUMNS,'kernel_threads':1,
            'rank_output':'immutable native binary64 bytes, Fortran (rows, columns)',
            'cancellation':'owner checks between native passes/columns and public math calls; snapshot GIL held'}


def workspace_info():
    """Always-on requested heap high-water; Python output ownership separate.

    Only cpp_peak_requested_bytes is untraced heap. Python output bytes are
    already visible to tracemalloc; adding them again double-counts. These are
    requested sizes, not allocator usable-size/RSS; fixed stack is separate.
    """
    native = _load_native()
    return native.workspace_info() if native is not None else None


def average_ranks(matrix, *, check_cancel=None):
    native = _load_native()
    if native is None:
        raise RuntimeError('native Spearman average ranks unavailable; build native/spearman_ranks/build.py')
    raw = native.rank_matrix(matrix,check_cancel)
    if type(raw) is not bytes or len(raw) != matrix.shape[0]*matrix.shape[1]*8:
        raise RuntimeError('native Spearman returned an invalid rank byte buffer')
    return np.frombuffer(raw,dtype=np.float64).reshape(matrix.shape,order='F')


def _integer_promotion_exact(values,promoted):
    if values.dtype.kind not in 'iu' or promoted.kind != 'f':
        return True
    floats = values.astype(promoted,copy=False)
    if values.dtype.kind == 'i':
        if np.any(floats >= float(1 << 63)) or np.any(floats < -float(1 << 63)):
            return False
    elif np.any(floats >= float(1 << 64)) or np.any(floats < 0.):
        return False
    return np.array_equal(floats.astype(values.dtype),values)


def _admission_reason(a,b):
    if np.__version__ != _NUMPY_VERSION or scipy.__version__ != _SCIPY_VERSION:
        return 'public-library-version-unverified'
    if type(a) is not np.ndarray or type(b) is not np.ndarray:
        return 'non-ndarray-input'
    if a.ndim != 1 or b.ndim != 1 or a.shape != b.shape:
        return 'pair-shape-outside-envelope'
    if len(a) < 3 or len(a) > MAX_ROWS:
        return 'sample-size-outside-envelope'
    if any(array.dtype.kind not in 'fiu' or array.dtype.itemsize != 8 for array in (a,b)):
        return 'dtype-outside-native64-envelope'
    if any(not array.dtype.isnative for array in (a,b)):
        return 'non-native-byte-order'
    if not np.isfinite(a).all() or not np.isfinite(b).all():
        return 'nonfinite-input'
    promoted = np.result_type(a.dtype,b.dtype)
    if promoted.kind not in 'fiu' or promoted.itemsize != 8 or not promoted.isnative:
        return 'public-promotion-outside-native64-envelope'
    if not _integer_promotion_exact(a,promoted) or not _integer_promotion_exact(b,promoted):
        return 'public-integer-promotion-unsafe'
    return None


def _record(statistic,pvalue,engine,reason):
    _LOG.info('Spearman implementation selected',extra={'spearman_engine':engine,'spearman_reason':reason})
    return SpearmanOutcome(statistic,pvalue,engine,reason,
                           native_public_promotion_refused=(reason=='public-integer-promotion-unsafe'))


def evaluate_spearman(a,b,*,alternative='two-sided',check_cancel=None):
    """Concrete 1-D pair adapter with explicit public-reference selection."""
    if check_cancel is not None:
        check_cancel()
    reason = _admission_reason(a,b)
    if reason is None and alternative not in ('less','greater','two-sided'):
        reason = 'public-options'
    matrix = None
    if reason is None:
        # Public SciPy first stacks the pair; preserve its dtype promotion.
        matrix = np.column_stack((a,b))
        if np.any(np.all(matrix == matrix[0,:],axis=0)):
            reason = 'constant-input'
    if reason is None and _load_native() is None:
        reason = 'extension-not-built'
    if reason is not None:
        if check_cancel is not None:
            check_cancel()
        reference = stats.spearmanr(a,b,alternative=alternative)
        if check_cancel is not None:
            check_cancel()
        return _record(reference.statistic,reference.pvalue,'scipy-public',reason)
    ranks = average_ranks(matrix,check_cancel=check_cancel)
    if check_cancel is not None:
        check_cancel()
    correlation = np.corrcoef(ranks,rowvar=0)
    dof = matrix.shape[0]-2
    with np.errstate(divide='ignore'):
        t = correlation*np.sqrt((dof/((correlation+1.0)*(1.0-correlation))).clip(0))
    if alternative == 'less':
        probability = special.stdtr(dof,t)
    elif alternative == 'greater':
        probability = special.stdtr(dof,-t)
    else:
        probability = 2*special.stdtr(dof,-np.abs(t))
    if check_cancel is not None:
        check_cancel()
    return _record(correlation[1,0],probability[1,0],'native-average-rank',None)
