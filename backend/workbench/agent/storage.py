"""Small atomic JSONL primitives shared by agent stores."""

from __future__ import annotations

import json
import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    records: list[dict[str, Any]] = []
    lines = raw.splitlines(keepends=True)
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            # An interrupted append can leave an unterminated final record.
            # It is safe to discard only that record; corruption anywhere
            # else must remain visible to the caller instead of being silently
            # converted into a different operation history.
            if index == len(lines) - 1 and not line.endswith(("\n", "\r")):
                break
            raise ValueError(f"invalid JSONL record at line {index + 1}") from exc
        if not isinstance(value, dict):
            raise ValueError(f"JSONL record at line {index + 1} is not an object")
        records.append(value)
    return records


@contextmanager
def _exclusive_jsonl_lock(path: Path) -> Iterator[None]:
    """Serialize read-then-replace appends across worker processes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(f".{path.name}.lock")
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def append_jsonl_atomic(path: Path, value: dict[str, Any]) -> None:
    with _exclusive_jsonl_lock(path):
        existing = path.read_bytes() if path.exists() else b""
        line = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(existing)
            handle.write(line)
        os.replace(temp_path, path)
