"""Kendall tau-b selection, with the original public SciPy path retained.

Numerical reference: SciPy 1.18.0 stats/_stats_py.py::_kendalltau,
_get_pvalue and _SimpleNormal. The corresponding BSD-3-Clause notice is retained
in native/kendall_counts/SCIPY_LICENSE.txt. Only admitted native-64-bit tau-b
asymptotic branch uses native exact pair counts. Tie sizes remain in rank order
and NumPy repeats SciPy's floating tie expressions and summation order, rather
than replacing them with differently rounded exact integer sums.

The local extension is built explicitly with native/kendall_counts/build.py;
there is no runtime compiler/install. Native ABI/load/compute errors propagate.
Absence or an inapplicable public option selects the original implementation
with a logged reason. Observations are never logged. Caller buffers must not be
concurrently written. Native work owns its snapshot and releases the GIL; an
interruptible workflow can discard a cancelled worker's pure result, but this
entry point does not bound native sort cancellation or peak RSS.

Public precision boundary: SciPy 1.18.0 _stats_py.py:5703 applies
xp_promote(x, y, force_floating=True). For integer x=[2**53,2**53+1,2**53+2,
2**53+3], y=[1,3,2,4], its tau/p are 0.5477225575051662/0.2785986718379625;
exact integer ranks give 0.6666666666666669/0.1742313882480251 in SciPy's
arithmetic order. To preserve the existing public result contract, integer
observations outside [-2**53,2**53] explicitly select the public reference with
reason public-integer-promotion (strict native refuses). The C++ count API
still preserves the entire signed/unsigned 64-bit range without any float cast.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import importlib
import importlib.util
import logging
from pathlib import Path
import sysconfig

import numpy as np
import scipy
from scipy import special, stats

_LOG = logging.getLogger(__name__)
_SCIPY_VERSION = '1.18.0'
_FLOAT_FORMATS = ('d', '@d', '=d')
_INTEGER_FORMATS = ('q', '@q', '=q', 'Q', '@Q', '=Q') + (
    ('l', '@l', 'L', '@L') if sysconfig.get_config_var('SIZEOF_LONG') == 8 else ())


class CandidateNotApplicable(ValueError):
    pass


@dataclass(frozen=True)
class KendallOutcome:
    statistic: float
    pvalue: float
    engine: str
    reason: str | None
    workspace_bytes: int = 0


@lru_cache(maxsize=1)
def _load_native():
    try:
        module = importlib.import_module('_kendall_counts')
    except ModuleNotFoundError as error:
        if error.name != '_kendall_counts':
            raise
        root = Path(__file__).resolve().parents[2]
        path = root / 'local/native-kendall' / ('_kendall_counts' + sysconfig.get_config_var('EXT_SUFFIX'))
        if not path.is_file():
            foreign = sorted(item.name for item in path.parent.glob('_kendall_counts*')
                             if item.is_file() and item.suffix in ('.so', '.pyd', '.dylib'))
            if foreign:
                raise RuntimeError('native Kendall ABI mismatch: expected ' + path.name
                                   + '; found ' + ', '.join(foreign))
            return None
        spec = importlib.util.spec_from_file_location('_kendall_counts', path)
        if spec is None or spec.loader is None:
            raise RuntimeError('native Kendall extension loader is unavailable')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    version = getattr(module, 'API_VERSION', None)
    if type(version) is not int or version != 4:
        raise RuntimeError('native Kendall API_VERSION mismatch; rebuild the current source')
    return module


def workspace_bytes():
    """Fresh-process owned-vector requested-byte peak, including concurrent calls.

    This is an always-on allocation counter, not total RSS and not a resettable
    product setting. Sum it with traced allocation peak only in a memory lane.
    """
    native = _load_native()
    return native.workspace_bytes() if native is not None else 0


def _input_reason(x, y):
    views = []
    for value in (x, y):
        if isinstance(value, np.ndarray) and type(value) is not np.ndarray:
            return 'array-subclass'
        try:
            view = memoryview(value)
        except TypeError:
            return 'input-format'
        if view.format not in _FLOAT_FORMATS + _INTEGER_FORMATS or view.itemsize != 8:
            return 'input-format'
        if view.ndim != 1 or not view.c_contiguous:
            return 'input-layout'
        views.append(view)
    if len(views[0]) != len(views[1]):
        return 'input-length'
    if len(views[0]) < 3:
        return 'sample-too-small'
    if len(views[0]) > 1_000_000:
        return 'input-limit'
    if any(view.format in _FLOAT_FORMATS and np.isnan(np.asarray(value)).any()
           for value, view in zip((x, y), views)):
        return 'nan-input'
    return None


def _tie_float_statistics(raw):
    sizes = np.frombuffer(raw, dtype=np.uint32).astype(np.int64)
    return (int((sizes * (sizes - 1.) * (sizes - 2)).sum()),
            int((sizes * (sizes - 1.) * (2 * sizes + 5)).sum()))


def _record(statistic, pvalue, engine, reason, *, n, method, workspace_bytes=0):
    _LOG.info('Kendall implementation selected', extra={
        'kendall_engine': engine, 'kendall_reason': reason,
        'kendall_scipy_version': scipy.__version__, 'kendall_n': n,
        'kendall_method': method,
    })
    return KendallOutcome(statistic, pvalue, engine, reason, workspace_bytes)


def evaluate(x, y, *, method='auto', variant='b', alternative='two-sided',
             nan_policy='propagate', engine='auto'):
    """Return values and explicit selection metadata; never hide native failures.

engine='scipy' forces the original path for an inspectable A/B comparison.
engine='native' refuses inapplicable inputs/options instead of selecting SciPy.
    Default auto preserves the listed paired-array options, exact methods and
    degenerate cases; this is not a replacement for SciPy's axis/matrix API.
"""
    if engine not in ('auto', 'native', 'scipy'):
        raise ValueError("engine must be 'auto', 'native', or 'scipy'")
    reason = 'requested-reference' if engine == 'scipy' else None
    if reason is None and scipy.__version__ != _SCIPY_VERSION:
        reason = 'scipy-version'
    if reason is None and (variant != 'b' or method not in ('auto', 'exact', 'asymptotic')
                           or alternative not in ('less', 'greater', 'two-sided')
                           or nan_policy not in ('propagate', 'raise', 'omit')):
        reason = 'public-options'
    if reason is None and method == 'exact':
        reason = 'exact-method'
    if reason is None:
        reason = _input_reason(x, y)
    native = _load_native() if reason is None else None
    if reason is None and native is None:
        reason = 'extension-unavailable'
    counts = native.count_with_ties(x, y) if reason is None else None
    if counts is not None and not counts['public_float_compatible']:
        reason = 'public-integer-promotion'
    if counts is not None and reason is None:
        n, dis = counts['n'], counts['discordant']
        xtie, ytie = counts['x_tie_pairs'], counts['y_tie_pairs']
        total = n * (n - 1) // 2
        if xtie == total or ytie == total:
            return _record(np.float64(np.nan), np.float64(np.nan), 'native-counts', None,
                           n=n, method=method, workspace_bytes=counts['workspace_bytes'])
        if method == 'auto' and not xtie and not ytie and (n <= 33 or min(dis, total - dis) <= 1):
            reason = 'exact-method'
    if reason is not None:
        if engine == 'native':
            raise CandidateNotApplicable(reason)
        if reason == 'public-integer-promotion':
            _LOG.warning('Kendall public-integer-promotion: preserving the original SciPy result; '
                         'exact native integer counts remain available')
        original = stats.kendalltau(x, y, method=method, variant=variant,
                                    alternative=alternative, nan_policy=nan_policy)
        return _record(original.statistic, original.pvalue, 'scipy-public', reason,
                       n=np.size(x), method=method,
                       workspace_bytes=counts['workspace_bytes'] if counts is not None else 0)

    score = total - xtie - ytie + counts['joint_tie_pairs'] - 2 * dis
    tau = score / np.sqrt(total - xtie) / np.sqrt(total - ytie)
    tau = np.minimum(1., max(-1., tau))
    x0, x1 = _tie_float_statistics(counts['x_tie_sizes'])
    y0, y1 = _tie_float_statistics(counts['y_tie_sizes'])
    m = n * (n - 1.)
    variance = ((m * (2 * n + 5) - x1 - y1) / 18 +
                (2 * xtie * ytie) / m + x0 * y0 / (9 * m * (n - 2)))
    z = score / np.sqrt(variance)
    if alternative == 'less':
        pvalue = special.ndtr(z)
    elif alternative == 'greater':
        pvalue = special.ndtr(-z)
    else:
        pvalue = 2 * special.ndtr(-np.abs(z))
    return _record(tau[()], pvalue[()], 'native-counts', None, n=n, method=method,
                   workspace_bytes=counts['workspace_bytes'])
