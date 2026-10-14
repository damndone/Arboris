"""Durable, replayable events emitted by an AgentCore run."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..jsonl_store import _exclusive_jsonl_lock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class AgentEvent:
    event_id: str
    session_id: str
    seq: int
    event_type: str
    payload: dict[str, Any]
    command_id: str | None
    created_at: str
    schema_version: str = "agent.event.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "session_id": self.session_id,
            "seq": self.seq,
            "event_type": self.event_type,
            "payload": self.payload,
            "command_id": self.command_id,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "AgentEvent":
        return cls(
            event_id=str(value["event_id"]),
            session_id=str(value["session_id"]),
            seq=int(value["seq"]),
            event_type=str(value["event_type"]),
            payload=dict(value.get("payload") or {}),
            command_id=value.get("command_id"),
            created_at=str(value["created_at"]),
            schema_version=str(value.get("schema_version", "agent.event.v1")),
        )


class AgentEventStream:
    """A per-session JSONL event stream with idempotent event emission."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.events_dir = self.root / "agent-events"
        if create:
            self.events_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        # Per log: how far it has been read, its last seq and the ids in it.
        # Streaming emits one event per token, and re-reading and rewriting the
        # whole log for each (as before) cost 23 ms per token on a 2 MB log.
        self._tails: dict[Path, _Tail] = {}

    def _path(self, session_id: str) -> Path:
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("session_id must be a non-empty path-safe identifier")
        return self.events_dir / f"{session_id}.jsonl"

    def emit(
        self,
        session_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        command_id: str | None = None,
        event_id: str | None = None,
    ) -> AgentEvent:
        if not event_type:
            raise ValueError("event_type must not be empty")
        # The file lock serializes emitters in other requests and processes;
        # the instance lock alone would let two of them take the same seq.
        path = self._path(session_id)
        with self._lock, _exclusive_jsonl_lock(path):
            tail = self._tail(path)
            requested_id = event_id or uuid4().hex
            if requested_id in tail.ids:
                return next(event for event in self._read(session_id) if event.event_id == requested_id)
            event = AgentEvent(
                event_id=requested_id,
                session_id=session_id,
                seq=tail.last_seq + 1,
                event_type=event_type,
                payload=dict(payload),
                command_id=command_id,
                created_at=_now(),
            )
            line = (json.dumps(event.to_dict(), ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
            # One write of one complete line, under the file lock. A crash can
            # leave at most a partial last line, which reading skips.
            with path.open("ab") as handle:
                handle.write(line)
            tail.size += len(line)
            tail.last_seq = event.seq
            tail.ids.add(event.event_id)
            return event

    def _tail(self, path: Path) -> "_Tail":
        """The log's end state, reading only what was appended since last time."""

        size = path.stat().st_size if path.exists() else 0
        cached = self._tails.get(path)
        if cached is not None and cached.size == size:
            return cached
        if cached is None or cached.size > size:
            cached = _Tail()
        chunk = b""
        if size:
            with path.open("rb") as handle:
                handle.seek(cached.size)
                chunk = handle.read(size - cached.size)
        # Only complete lines move the read position forward.
        complete = chunk[: chunk.rfind(b"\n") + 1]
        for raw in complete.splitlines():
            if not raw.strip():
                continue
            value = json.loads(raw)
            cached.last_seq = max(cached.last_seq, int(value["seq"]))
            cached.ids.add(str(value["event_id"]))
        cached.size += len(complete)
        if cached.size != size:
            # A partial last line from an interrupted write: the next append
            # starts on a fresh line so both stay readable.
            with path.open("ab") as handle:
                handle.write(b"\n")
            cached.size = size + 1
        self._tails[path] = cached
        return cached

    def replay(self, session_id: str, *, after_seq: int = 0) -> list[AgentEvent]:
        with self._lock:
            return [event for event in self._read(session_id) if event.seq > after_seq]

    def _read(self, session_id: str) -> list[AgentEvent]:
        path = self._path(session_id)
        if not path.exists():
            return []
        events: list[AgentEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                events.append(AgentEvent.from_dict(json.loads(line)))
            except json.JSONDecodeError:
                continue  # a line cut short by an interrupted write
        return events


@dataclass
class _Tail:
    size: int = 0
    last_seq: int = 0
    ids: set[str] = field(default_factory=set)

