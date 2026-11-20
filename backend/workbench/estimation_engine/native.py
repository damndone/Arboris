"""In-process calls into the native engine library (native/engine, built by native/engine/build.py).

An absent library means the fast engine is unavailable and the reference runs. A library with
another ABI is an error: it was built from different sources and must be rebuilt.
"""
from __future__ import annotations

import ctypes
from copy import deepcopy
from functools import lru_cache
import os
from pathlib import Path
import sys
from threading import Lock
from typing import Any, Callable

import numpy as np

from workbench.native_build import manifest_path, verify_build

ABI_VERSION = 1
STATUS_OK = 0
STATUS_NOT_IDENTIFIED = 2
STATUS_CANCELLED = 5
COVARIANCE_CODES = {"unadjusted": 0, "robust": 1}
MAX_THREADS = 8
_NAME = "libarboris_engine." + {"darwin": "dylib", "win32": "dll"}.get(sys.platform, "so")
_DOUBLE = ctypes.POINTER(ctypes.c_double)
_COLUMNS = ctypes.POINTER(_DOUBLE)
_SIZE = ctypes.c_size_t
_CANCEL = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)
_LOAD_LOCK = Lock()


def library_directory() -> Path:
    return Path(__file__).resolve().parents[3] / "local/native-engine"


def _open(path: Path):
    library = ctypes.CDLL(str(path))
    library.arboris_engine_abi.restype = ctypes.c_int32
    if library.arboris_engine_abi() != ABI_VERSION:
        raise RuntimeError("native engine ABI mismatch; rebuild with native/engine/build.py")
    library.arboris_iv_2sls_output_len.argtypes = [_SIZE, _SIZE]
    library.arboris_iv_2sls_output_len.restype = _SIZE
    library.arboris_iv_2sls.argtypes = [_SIZE, _DOUBLE, _COLUMNS, _SIZE, _COLUMNS, _SIZE, _COLUMNS, _SIZE,
                                        ctypes.c_int32, _SIZE, _DOUBLE, _SIZE]
    library.arboris_iv_2sls.restype = ctypes.c_int32
    library.arboris_iv_2sls_cancellable.argtypes = [*library.arboris_iv_2sls.argtypes, _CANCEL, ctypes.c_void_p]
    library.arboris_iv_2sls_cancellable.restype = ctypes.c_int32
    return library


@lru_cache(maxsize=1)
def _load_once() -> tuple[Any, dict[str, Any]] | Exception | None:
    path = library_directory() / _NAME
    if not path.is_file():
        if path.is_symlink() or manifest_path(library_directory()).exists() \
                or manifest_path(library_directory()).is_symlink() or any(library_directory().glob("*arboris_engine*")):
            raise RuntimeError("native engine ABI mismatch/broken binary; rebuild with native/engine/build.py")
        return None
    module = Path(__file__).resolve().parents[3] / "native/engine"
    def identity():
        stat = path.stat()
        return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns
    before = identity()
    manifest = verify_build(module, library_directory())
    if identity() != before:
        raise RuntimeError("native engine binary changed during verification; rebuild and restart")
    try:
        library = _open(path)
        if identity() != before:
            raise RuntimeError("native engine binary changed while loading; rebuild and restart")
    except (OSError, RuntimeError, AttributeError) as error:
        # A failed validation after dlopen may leave an image mapped. A retry
        # could receive that handle while verifying a replacement on disk.
        return error
    return library, manifest | {"abi": ABI_VERSION, "manifest": str(manifest_path(library_directory()))}


def _loaded() -> tuple[Any, dict[str, Any]] | None:
    # lru_cache alone permits concurrent calls on a cold miss.
    with _LOAD_LOCK:
        loaded = _load_once()
    if isinstance(loaded, Exception):
        raise RuntimeError(f"{loaded}; restart before loading the native engine") from loaded
    return loaded


def available() -> bool:
    return _loaded() is not None


def build_record() -> dict[str, Any] | None:
    loaded = _loaded()
    return None if loaded is None else deepcopy(loaded[1])


def _column_pointers(columns: list[np.ndarray]):
    array = (_DOUBLE * max(len(columns), 1))()
    for index, column in enumerate(columns):
        array[index] = column.ctypes.data_as(_DOUBLE)
    return array


def _threads(rows: int) -> int:
    return 1 if rows < 200_000 else min(MAX_THREADS, os.cpu_count() or 1)


def iv_2sls(y: np.ndarray, exog: list[np.ndarray], endog: list[np.ndarray], instruments: list[np.ndarray],
            covariance: str, *, check_cancel: Callable[[], None] | None = None) -> np.ndarray | None:
    """The engine's output vector (layout in native/engine/src/lib.rs), or None when the data do not identify the model."""
    from workbench.checks.ar_cancellation import current_check
    if check_cancel is None:
        check_cancel = current_check()
    if check_cancel is not None:
        check_cancel()  # preprocessing is not interruptible inside individual NumPy calls
    loaded = _loaded()
    if loaded is None:
        raise RuntimeError("native engine is not built")
    library = loaded[0]
    contiguous = [np.ascontiguousarray(column, dtype=float) for column in (y, *exog, *endog, *instruments)]
    y, rest = contiguous[0], contiguous[1:]
    exog, endog, instruments = rest[:len(exog)], rest[len(exog):len(exog) + len(endog)], rest[len(exog) + len(endog):]
    k, n_endog = len(exog) + len(endog), len(endog)
    expected_length = k + k * k + 2 + n_endog + 5
    if library.arboris_iv_2sls_output_len(len(exog), n_endog) != expected_length:
        raise RuntimeError("native engine returned an invalid output length; rebuild")
    out = np.full(expected_length, np.nan)
    arguments = (
        len(y), y.ctypes.data_as(_DOUBLE), _column_pointers(exog), len(exog), _column_pointers(endog), len(endog),
        _column_pointers(instruments), len(instruments), COVARIANCE_CODES[covariance], _threads(len(y)),
        out.ctypes.data_as(_DOUBLE), len(out))
    if check_cancel is None:
        status = library.arboris_iv_2sls(*arguments)
    else:
        failure = []
        @_CANCEL
        def checkpoint(_context):
            try:
                check_cancel()
            except BaseException as error:
                if not failure:
                    failure.append(error)  # preserve the exact execution-owner exception
                return 1
            return 0
        status = library.arboris_iv_2sls_cancellable(*arguments, checkpoint, None)
        if failure:
            raise failure[0]  # C has returned only after all scoped native helpers joined
        if status == STATUS_CANCELLED:
            raise RuntimeError("native engine cancelled without an owner interruption")
    if status == STATUS_NOT_IDENTIFIED:
        if check_cancel is not None:
            check_cancel()
        return None
    if status != STATUS_OK:
        raise RuntimeError(f"native engine failed with status {status}")
    if check_cancel is not None:
        check_cancel()  # only a valid completion proceeds to result validation/publication
    # Validate once at the foreign-function boundary. Undefined specification statistics retain NaN.
    cursor = k + k * k
    covariance_matrix = out[k:cursor].reshape(k, k)
    required = list(out[:cursor + n_endog + 4])
    if len(instruments) > n_endog:
        required.append(out[cursor + n_endog + 4])  # Wooldridge overidentification
        if covariance == "unadjusted":
            required.append(out[cursor + n_endog + 5])  # Sargan
    if covariance == "unadjusted" and len(y) > len(exog) + 2 * n_endog:
        required.append(out[-1])  # Wu-Hausman, when its denominator degrees of freedom are defined
    if not np.isfinite(required).all() or np.any(np.diag(covariance_matrix) < 0) \
            or np.any(out[cursor:cursor + 2] < 0) or out[cursor + n_endog + 2] <= 0:
        raise RuntimeError("native engine returned invalid/non-finite defined output")
    return out
