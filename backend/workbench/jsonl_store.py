"""Small atomic JSONL primitives shared by the Agent, run event and capability stores."""

from __future__ import annotations

import json
import fcntl
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


def jsonl_lines(raw: str | bytes, *, keepends: bool = False) -> list:
    """The lines of a JSON Lines text or byte string, split at ``\\n`` only.

    ``str.splitlines()`` also splits at U+2028, U+2029 and U+0085, which
    ``json.dumps(..., ensure_ascii=False)`` leaves raw inside strings, so one
    such character cut a record in two. A final line without a newline is kept
    (with ``keepends`` it is the one line that does not end in ``\\n``).
    """

    newline = b"\n" if isinstance(raw, bytes) else "\n"
    pieces = raw.split(newline)
    lines = [piece + newline for piece in pieces[:-1]] if keepends else pieces[:-1]
    if pieces[-1]:
        lines.append(pieces[-1])
    return lines


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    raw = path.read_text(encoding="utf-8")
    records: list[dict[str, Any]] = []
    lines = jsonl_lines(raw, keepends=True)
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
            if index == len(lines) - 1 and not line.endswith("\n"):
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
