"""Append-only session trees used by the agent harness.

Sessions are local append-only logs. A new session can point at an entry in a
previous session instead of copying that history, which makes chat and graph
forks cheap and preserves a single provenance identity for every message.
"""

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
class EntryRef:
    session_id: str
    entry_id: str

    def to_dict(self) -> dict[str, str]:
        return {"session_id": self.session_id, "entry_id": self.entry_id}

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "EntryRef":
        return cls(session_id=str(value["session_id"]), entry_id=str(value["entry_id"]))


@dataclass(frozen=True)
class SessionTreeEntry:
    entry_id: str
    session_id: str
    entry_type: str
    payload: dict[str, Any]
    parent_ref: EntryRef | None
    created_at: str
    schema_version: str = "agent.session_entry.v1"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entry_id": self.entry_id,
            "session_id": self.session_id,
            "entry_type": self.entry_type,
            "payload": self.payload,
            "parent_ref": self.parent_ref.to_dict() if self.parent_ref else None,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "SessionTreeEntry":
        parent = value.get("parent_ref")
        return cls(
            entry_id=str(value["entry_id"]),
            session_id=str(value["session_id"]),
            entry_type=str(value["entry_type"]),
            payload=dict(value.get("payload") or {}),
            parent_ref=EntryRef.from_dict(parent) if parent else None,
            created_at=str(value["created_at"]),
            schema_version=str(value.get("schema_version", "agent.session_entry.v1")),
        )


class JsonlSessionRepository:
    """Small file-backed repository with append-only entry semantics."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.sessions_dir = self.root / "agent-sessions"
        if create:
            self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def _validate_session_id(self, session_id: str) -> None:
        if not session_id or Path(session_id).name != session_id:
            raise ValueError("session_id must be a non-empty path-safe identifier")

    def _session_path(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        return self.sessions_dir / f"{session_id}.jsonl"

    def _metadata_path(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        return self.sessions_dir / f"{session_id}.meta.json"

    def create_session(
        self,
        session_id: str,
        *,
        chain_id: str,
        role: str,
        inherited_parent_ref: EntryRef | None = None,
    ) -> dict[str, Any]:
        """Create an empty local log, optionally rooted at another entry."""

        with self._lock:
            path = self._session_path(session_id)
            metadata_path = self._metadata_path(session_id)
            if path.exists() or metadata_path.exists():
                raise ValueError(f"session already exists: {session_id}")
            metadata = {
                "schema_version": "agent.session.v1",
                "session_id": session_id,
                "chain_id": chain_id,
                "role": role,
                "status": "idle",
                "root_entry_id": None,
                "leaf_entry_id": None,
                "inherited_parent_ref": (
                    inherited_parent_ref.to_dict() if inherited_parent_ref else None
                ),
                "created_at": _now(),
            }
            path.touch()
            self._atomic_write_json(metadata_path, metadata)
            return metadata.copy()

    def get_metadata(self, session_id: str) -> dict[str, Any]:
        with self._lock:
            path = self._metadata_path(session_id)
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError as exc:
                raise KeyError(f"unknown session: {session_id}") from exc

    def list_metadata(self) -> list[dict[str, Any]]:
        """Return session metadata without creating the sessions directory."""

        with self._lock:
            if not self.sessions_dir.exists():
                return []
            result: list[dict[str, Any]] = []
            for path in sorted(self.sessions_dir.glob("*.meta.json")):
                value = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(value, dict):
                    raise ValueError(f"session metadata is not an object: {path.name}")
                result.append(dict(value))
            return result

    def update_status(self, session_id: str, status: str) -> dict[str, Any]:
        """Persist session lifecycle state without appending a message entry."""

        if not isinstance(status, str) or not status:
            raise ValueError("status must be a non-empty string")
        with self._lock:
            metadata = self.get_metadata(session_id)
            metadata["status"] = status
            self._atomic_write_json(self._metadata_path(session_id), metadata)
            return metadata.copy()

    def append(
        self,
        session_id: str,
        entry_type: str,
        payload: dict[str, Any],
    ) -> SessionTreeEntry:
        """Append exactly one entry and advance the local leaf pointer."""

        if not entry_type:
            raise ValueError("entry_type must not be empty")
        with self._lock:
            metadata = self.get_metadata(session_id)
            previous = metadata.get("leaf_entry_id")
            parent_ref = EntryRef(session_id, previous) if previous else None
            if parent_ref is None and metadata.get("inherited_parent_ref"):
                parent_ref = EntryRef.from_dict(metadata["inherited_parent_ref"])
            entry = SessionTreeEntry(
                entry_id=uuid4().hex,
                session_id=session_id,
                entry_type=entry_type,
                payload=dict(payload),
                parent_ref=parent_ref,
                created_at=_now(),
            )
            self._atomic_append(self._session_path(session_id), entry.to_dict())
            metadata["root_entry_id"] = metadata["root_entry_id"] or entry.entry_id
            metadata["leaf_entry_id"] = entry.entry_id
            self._atomic_write_json(self._metadata_path(session_id), metadata)
            return entry

    def get_entry(self, ref: EntryRef) -> SessionTreeEntry:
        with self._lock:
            for entry in self._read_entries(ref.session_id):
                if entry.entry_id == ref.entry_id:
                    return entry
        raise KeyError(f"unknown session entry: {ref.session_id}/{ref.entry_id}")

    def get_branch(
        self,
        session_id: str,
        *,
        leaf_entry_id: str | None = None,
    ) -> list[SessionTreeEntry]:
        """Return the resolved branch without copying ancestor entries."""

        metadata = self.get_metadata(session_id)
        leaf = leaf_entry_id or metadata.get("leaf_entry_id")
        current = EntryRef(session_id, leaf) if leaf else None
        if current is None and metadata.get("inherited_parent_ref"):
            current = EntryRef.from_dict(metadata["inherited_parent_ref"])

        branch: list[SessionTreeEntry] = []
        visited: set[EntryRef] = set()
        while current is not None:
            if current in visited:
                raise ValueError("cycle detected in agent session tree")
            visited.add(current)
            entry = self.get_entry(current)
            branch.append(entry)
            current = entry.parent_ref
        branch.reverse()
        return branch

    def _read_entries(self, session_id: str) -> list[SessionTreeEntry]:
        path = self._session_path(session_id)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError as exc:
            raise KeyError(f"unknown session: {session_id}") from exc
        entries: list[SessionTreeEntry] = []
        for line in lines:
            if line.strip():
                entries.append(SessionTreeEntry.from_dict(json.loads(line)))
        return entries

    @staticmethod
    def _atomic_append(path: Path, value: dict[str, Any]) -> None:
        existing = path.read_bytes() if path.exists() else b""
        line = (json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
            temp_path = Path(handle.name)
            handle.write(existing)
            handle.write(line)
        os.replace(temp_path, path)

    @staticmethod
    def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
