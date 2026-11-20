"""Tukey p-values through native/studentized_range: same integrals, across threads.

Only QUADPACK's loop moves to C++; the integrand stays SciPy's compiled function, so results
equal scipy.stats.studentized_range bit for bit (tests/test_native_studentized_range.py). Only
an absent extension selects the reference; a broken one fails. The bits depend on how this
SciPy was compiled, so the extension proves itself once and stands aside if SciPy disagrees.
"""
from __future__ import annotations

from functools import lru_cache
import importlib.util
import logging
import os
from pathlib import Path
import sysconfig

import numpy as np
from scipy.stats import _stats, studentized_range

_LOG = logging.getLogger(__name__)
_EXTENSION = "_studentized_range" + sysconfig.get_config_var("EXT_SUFFIX")
_MAX_THREADS = 8


def _cdf(module, q: np.ndarray, k: float, df: float) -> np.ndarray:
    logconst = _stats._studentized_range_cdf_logconst(k, df)
    raw = module.cdf_many(_stats.__pyx_capi__["_studentized_range_cdf"], q.tobytes(), k, df, logconst,
                          min(os.cpu_count() or 1, _MAX_THREADS))
    return np.clip(np.frombuffer(raw), 0, 1)


def _agrees_with_reference(module) -> bool:
    q = np.array([.05, .9, 2.3, 3.7, 5.1, 8.4, 21.0])
    return all(np.array_equal(_cdf(module, q, k, df), studentized_range.cdf(q, k, df))
               for k, df in ((3.0, 100.0), (7.0, 12.0)))


@lru_cache(maxsize=1)
def _native():
    path = Path(__file__).resolve().parents[2] / "local/native-studentized-range" / _EXTENSION
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_studentized_range", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.ABI_VERSION != 1:
        raise RuntimeError("native studentized range ABI mismatch; rebuild with native/studentized_range/build.py")
    if not _agrees_with_reference(module):
        _LOG.warning("native studentized range differs from this SciPy; using the reference")
        return None
    return module


def tukey_pvalue(k, df, q):
    """statsmodels' get_tukey_pvalue. q of 0 is the support's edge, where SciPy returns exactly 1."""
    module = _native()
    values = np.asarray(q, dtype=np.float64)
    if (module is None or values.ndim != 1 or not k > 1 or not 0 < df < 100000
            or not np.all(np.isfinite(values) & (values >= 0))):
        return studentized_range.sf(q, k, df)
    inside = values > 0
    result = np.ones(values.shape)
    result[inside] = 1.0 - _cdf(module, np.ascontiguousarray(values[inside]), float(k), float(df))
    return result


def accelerate_statsmodels_tukey() -> None:
    """A critical value costs about 58 double integrals and depends only on (k, df, alpha)."""
    from statsmodels.sandbox.stats import multicomp

    if not hasattr(multicomp.get_tukeyQcrit2, "cache_info"):
        multicomp.get_tukeyQcrit2 = lru_cache(maxsize=256)(multicomp.get_tukeyQcrit2)
    multicomp.get_tukey_pvalue = tukey_pvalue
