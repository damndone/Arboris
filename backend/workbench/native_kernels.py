"""Rust math kernels (native/kernels), bit-identical to the NumPy code they replace.

The kernels repeat NumPy's generator and its summation order, so a result never depends on
whether they are built. An absent library selects the Python path. A broken one fails. Those
bits depend on this build of NumPy, so the library proves itself once against NumPy and stands
aside if they disagree. Negative zero selects the Python path, because partition does not
order it against zero.
"""
from __future__ import annotations

import ctypes
from functools import lru_cache
import logging
from pathlib import Path
import sys

import numpy as np

_LOG = logging.getLogger(__name__)
_NAME = 'libarboris_kernels.' + {'darwin': 'dylib', 'win32': 'dll'}.get(sys.platform, 'so')
_DOUBLE = ctypes.POINTER(ctypes.c_double)
_U64 = ctypes.POINTER(ctypes.c_uint64)
_I64 = ctypes.POINTER(ctypes.c_int64)
_SIZE = ctypes.c_size_t
_STATISTICS = {'mean': 0, 'median': 1, 'difference_in_means': 0, 'difference_in_medians': 1}


def _doubles(array):
    return array.ctypes.data_as(_DOUBLE)


def _open(path):
    library = ctypes.CDLL(str(path))
    library.arboris_kernels_abi.restype = ctypes.c_int32
    if library.arboris_kernels_abi() != 2:
        raise RuntimeError('native kernels ABI mismatch; rebuild with native/kernels/build.py')
    library.arboris_bootstrap.argtypes = [_DOUBLE, _SIZE, _U64, _SIZE, ctypes.c_int32, _DOUBLE]
    library.arboris_permutation.argtypes = [_DOUBLE, _SIZE, _SIZE, _U64, _SIZE, ctypes.c_int32, _DOUBLE]
    library.arboris_min_distances.argtypes = [_DOUBLE, _SIZE, _SIZE, _DOUBLE, _SIZE, _DOUBLE]
    library.arboris_lloyd_step.argtypes = [_DOUBLE, _SIZE, _SIZE, _DOUBLE, _SIZE, _I64, _DOUBLE]
    library.arboris_ph_sweep.argtypes = [_DOUBLE, _SIZE, _SIZE, _DOUBLE, _DOUBLE, _I64,
                                         ctypes.POINTER(ctypes.c_uint8), _DOUBLE, _DOUBLE]
    library.arboris_python_sum.argtypes = [_DOUBLE, _SIZE, _DOUBLE]
    for function in (library.arboris_bootstrap, library.arboris_permutation, library.arboris_min_distances,
                     library.arboris_lloyd_step, library.arboris_ph_sweep, library.arboris_python_sum):
        function.restype = ctypes.c_int32
    return library


def _checked(status):
    if status != 0:
        raise RuntimeError('native kernel failed')


def _library_bootstrap(library, values, seeds, statistic):
    keys = np.asarray(seeds, dtype=np.uint64)
    out = np.empty(len(keys))
    _checked(library.arboris_bootstrap(_doubles(values), len(values), keys.ctypes.data_as(_U64),
                                       len(keys), _STATISTICS[statistic], _doubles(out)))
    return out


def _library_permutation(library, pooled, left, seeds, statistic):
    keys = np.asarray(seeds, dtype=np.uint64)
    out = np.empty(len(keys))
    _checked(library.arboris_permutation(_doubles(pooled), len(pooled), left, keys.ctypes.data_as(_U64),
                                         len(keys), _STATISTICS[statistic], _doubles(out)))
    return out


def _library_lloyd(library, values, centers):
    labels = np.empty(len(values), dtype=np.int64)
    updated = np.empty_like(centers)
    _checked(library.arboris_lloyd_step(_doubles(values), len(values), values.shape[1], _doubles(centers),
                                        len(centers), labels.ctypes.data_as(_I64), _doubles(updated)))
    return labels, updated


def _library_min(library, values, centers):
    out = np.empty(len(values))
    _checked(library.arboris_min_distances(_doubles(values), len(values), values.shape[1],
                                           _doubles(centers), len(centers), _doubles(out)))
    return out


def _library_ph_sweep(library, x, weights, g, rows, event):
    size, width = x.shape
    score, information = np.zeros(width), np.zeros((2 * width, 2 * width))
    flags = np.asarray(event, dtype=np.uint8)
    _checked(library.arboris_ph_sweep(_doubles(x), size, width, _doubles(weights), _doubles(g),
                                      rows.ctypes.data_as(_I64), flags.ctypes.data_as(ctypes.POINTER(ctypes.c_uint8)),
                                      _doubles(score), _doubles(information)))
    return score, information


def _library_python_sum(library, values):
    out = np.empty(1)
    _checked(library.arboris_python_sum(_doubles(values), len(values), _doubles(out)))
    return float(out[0])


def _same(left, right):
    return np.asarray(left, dtype=float).tobytes() == np.asarray(right, dtype=float).tobytes()


def _agrees_with_reference(library) -> bool:
    rng = np.random.default_rng(20261102)
    seeds = [0, 1, 2**31, 2**32, 2**63 - 1]
    for size in (2, 9, 130, 1001, 1002):
        values = rng.normal(size=size)
        for name, reduce in (('mean', np.mean), ('median', np.median)):
            expected = [reduce(values[np.random.default_rng(seed).integers(0, size, size=size)]) for seed in seeds]
            if not _same(_library_bootstrap(library, values, seeds, name), expected):
                return False
            left = max(1, size // 3)
            shuffled = [np.random.default_rng(seed).permutation(values) for seed in seeds]
            expected = [reduce(item[:left]) - reduce(item[left:]) for item in shuffled]
            if not _same(_library_permutation(library, values, left, seeds, name), expected):
                return False
    for rows, width, clusters in ((60, 1, 3), (200, 3, 4), (300, 9, 5), (150, 20, 2)):
        values = rng.normal(size=(rows, width))
        centers = values[:clusters].copy()
        distances = np.square(values[:, None, :] - centers[None, :, :]).sum(axis=2)
        labels, updated = _library_lloyd(library, values, centers)
        if (not _same(_library_min(library, values, centers), np.min(distances, axis=1))
                or not np.array_equal(labels, np.argmin(distances, axis=1))
                or not _same(updated, [values[labels == c].mean(axis=0) for c in range(clusters)])):
            return False
    for rows, width in ((50, 1), (400, 2), (300, 5)):
        x = rng.normal(size=(rows, width))
        weights = np.exp(x @ np.full(width, .1))
        g = rng.normal(size=rows)
        order = rng.permutation(rows).astype(np.int64)
        event = rng.random(rows) < .7
        score, information = _library_ph_sweep(library, x, weights, g, order, event)
        expected = _reference_ph_sweep(x, weights, g, order, event)
        if not _same(score, expected[0]) or not _same(information, expected[1]):
            return False
    cancelling = np.concatenate([rng.normal(size=500) * 1e16, rng.normal(size=500), -rng.normal(size=500) * 1e16])
    for values in (rng.normal(size=1001), cancelling, np.array([-0.0, -0.0]), np.array([1e308, 1e308, -1.0]),
                   np.array([np.inf, 1.0, -np.inf]), np.array([2.5])):
        if not _same(_library_python_sum(library, values), sum(map(float, values))):
            return False
    return True


def _reference_ph_sweep(x, weights, g, order, event):
    """ph_score_test's loop when no two rows share a failure time."""
    p = x.shape[1]
    score, information = np.zeros(p), np.zeros((2 * p, 2 * p))
    s0, s1, s2 = 0., np.zeros(p), np.zeros((p, p))
    for row in order:
        xr, wr = x[[row]], weights[[row]]
        s0 += wr.sum()
        s1 += xr.T @ wr
        s2 += xr.T @ (xr * wr[:, None])
        if not event[row]:
            continue
        time = g[row]
        score += time * xr.sum(axis=0)
        mean = (s1 - 0. * (xr.T @ wr)) / (s0 - 0. * wr.sum())
        variance = (s2 - 0. * (xr.T @ (xr * wr[:, None]))) / (s0 - 0. * wr.sum()) - np.outer(mean, mean)
        score -= time * mean
        information[:p, :p] += variance
        information[:p, p:] += time * variance
        information[p:, :p] += time * variance
        information[p:, p:] += time * time * variance
    return score, information


@lru_cache(maxsize=1)
def _library():
    path = Path(__file__).resolve().parents[2] / 'local/native-kernels' / _NAME
    if not path.is_file():
        return None
    library = _open(path)
    if not _agrees_with_reference(library):
        _LOG.warning('native kernels differ from this NumPy; using the Python path')
        return None
    return library


def _has_negative_zero(values):
    return bool(np.any((values == 0.0) & np.signbit(values)))


def bootstrap_statistics(values, seeds, statistic):
    """One statistic per seed, or None for the Python path."""
    library = _library()
    if library is None or (statistic == 'median' and _has_negative_zero(values)):
        return None
    return _library_bootstrap(library, np.ascontiguousarray(values, dtype=float), seeds, statistic)


def permutation_statistics(pooled, left, seeds, statistic):
    """One two-sample statistic per seed, or None for the Python path."""
    library = _library()
    if library is None or (statistic == 'difference_in_medians' and _has_negative_zero(pooled)):
        return None
    return _library_permutation(library, np.ascontiguousarray(pooled, dtype=float), left, seeds, statistic)


def lloyd_step(values, centers):
    """Labels and updated centers of one k-means iteration, or None for the Python path."""
    library = _library()
    return None if library is None else _library_lloyd(library, values, centers)


def ph_sweep(x, weights, g, rows, event):
    """Score and information of the Cox time-interaction test with distinct failure times."""
    library = _library()
    if library is None:
        return None
    return _library_ph_sweep(library, np.ascontiguousarray(x, dtype=float), weights, g, rows, event)


def python_sum(values):
    """``sum(map(float, values))`` of a nonempty 1-D float64 array, or None for the Python path."""
    library = _library()
    if (library is None or type(values) is not np.ndarray or values.dtype != np.float64
            or values.ndim != 1 or values.size == 0):
        return None
    return _library_python_sum(library, np.ascontiguousarray(values))


def min_distances(values, centers):
    """Squared distance from each row to its nearest center, or None for the Python path."""
    library = _library()
    return None if library is None else _library_min(library, values, centers)
