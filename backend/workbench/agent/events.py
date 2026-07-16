"""Durable, replayable events emitted by an AgentCore run."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4


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
        with self._lock:
            events = self._read(session_id)
            requested_id = event_id or uuid4().hex
            for event in events:
                if event.event_id == requested_id:
                    return event
            event = AgentEvent(
                event_id=requested_id,
                session_id=session_id,
                seq=(events[-1].seq + 1 if events else 1),
                event_type=event_type,
                payload=dict(payload),
                command_id=command_id,
                created_at=_now(),
            )
            self._atomic_append(self._path(session_id), event.to_dict())
            return event

    def replay(self, session_id: str, *, after_seq: int = 0) -> list[AgentEvent]:
        with self._lock:
            return [event for event in self._read(session_id) if event.seq > after_seq]

    def _read(self, session_id: str) -> list[AgentEvent]:
        path = self._path(session_id)
        if not path.exists():
            return []
        events: list[AgentEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                events.append(AgentEvent.from_dict(json.loads(line)))
        return events

    @staticmethod
    def _atomic_append(path: Path, value: dict[str, Any]) -> None:
        existing = path.read_bytes() if path.exists() else b""
        line = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(existing)
            handle.write(line)
        os.replace(temp_path, path)
