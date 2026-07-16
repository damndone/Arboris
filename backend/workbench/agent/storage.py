"""Small atomic JSONL primitives shared by agent stores."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


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


def append_jsonl_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_bytes() if path.exists() else b""
    line = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(existing)
        handle.write(line)
    os.replace(temp_path, path)
