"""Verified dataset sources, decoded once per content and kept within a byte budget.

Hashing and decoding use the same open file. Before publishing a result, verify that the
file and its dtype sidecar still match the generations used to read it. Only the Data view's
paging path reuses the verified digest and decoded frame within the byte budget.
"""

from __future__ import annotations

import hashlib
import os
import threading
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

import pandas as pd

from .specs import DataColumnCastValidationError

MAX_CACHED_BYTES = 512 * 2**20
_MAX_VERIFIED = 512
_FileState = tuple[int, int, int, int, int]
_lock = threading.Lock()
_verified: OrderedDict[tuple[str, _FileState], str] = OrderedDict()
_frames: OrderedDict[tuple[str, str, _FileState | None], tuple[pd.DataFrame, int]] = OrderedDict()
_cached_bytes = 0


def _state(stat: os.stat_result) -> _FileState:
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def _path_state(path: Path) -> _FileState | None:
    try:
        return _state(path.stat())
    except FileNotFoundError:
        return None


def load_verified_frame(
    path: Path,
    schema_path: Path,
    expected_sha: str | None,
    read: Callable[[BinaryIO], pd.DataFrame],
    *,
    cached: bool,
) -> tuple[str, pd.DataFrame]:
    """Return a verified digest and its decoded table, optionally reusing a cached frame."""
    global _cached_bytes
    try:
        stream = path.open("rb")
    except (FileNotFoundError, IsADirectoryError) as exc:
        raise DataColumnCastValidationError("source artifact fingerprint changed during read") from exc
    with stream:
        file_state = _state(os.fstat(stream.fileno()))
        schema_state = _path_state(schema_path)
        digest_key = (str(path), file_state)
        try:
            digest = None
            if cached:
                with _lock:
                    digest = _verified.get(digest_key)
            if digest is None:
                digest = hashlib.file_digest(stream, "sha256").hexdigest()
            if expected_sha and expected_sha != digest:
                raise DataColumnCastValidationError("source artifact fingerprint changed")
            if not cached:
                stream.seek(0)
                return digest, read(stream)

            frame_key = (str(path), digest, schema_state)
            with _lock:
                entry = _frames.get(frame_key)
            if entry is None:
                stream.seek(0)
                frame = read(stream)
                size = int(frame.memory_usage(index=True, deep=True).sum())
            else:
                frame, size = entry
        finally:
            if (
                _state(os.fstat(stream.fileno())) != file_state
                or _path_state(path) != file_state
                or _path_state(schema_path) != schema_state
            ):
                raise DataColumnCastValidationError("source artifact fingerprint changed during read")

    with _lock:
        _verified[digest_key] = digest
        _verified.move_to_end(digest_key)
        while len(_verified) > _MAX_VERIFIED:
            _verified.popitem(last=False)
        if size <= MAX_CACHED_BYTES:
            if frame_key not in _frames:
                _frames[frame_key] = (frame, size)
                _cached_bytes += size
            _frames.move_to_end(frame_key)
            while _cached_bytes > MAX_CACHED_BYTES and _frames:
                _, (_, evicted) = _frames.popitem(last=False)
                _cached_bytes -= evicted
    return digest, frame.copy(deep=False)


def clear() -> None:
    global _cached_bytes
    with _lock:
        _verified.clear()
        _frames.clear()
        _cached_bytes = 0


def cached_bytes() -> int:
    return _cached_bytes
