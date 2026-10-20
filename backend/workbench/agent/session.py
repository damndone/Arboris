"""Append-only session trees used by the agent harness.

Sessions are local append-only logs. A new session can point at an entry in a
previous session instead of copying that history, which makes chat and graph
forks cheap and preserves a single provenance identity for every message.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

from ..jsonl_store import _exclusive_jsonl_lock


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionAppendConflict(ValueError):
    """An append-once identity conflicts with content or the current branch."""


class SessionAppendPendingError(ValueError):
    """A pending append intent must be explicitly verified before proceeding."""


def _append_identity(key: str, stage: str, digest: str) -> dict[str, str]:
    if any(not isinstance(value, str) or not value.strip() or len(value) > 512
           for value in (key, stage)):
        raise ValueError("append-once key and stage must be bounded non-empty strings")
    if not isinstance(digest, str) or len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
        raise ValueError("append-once payload digest is invalid")
    return {"key": key, "stage": stage, "payload_sha256": digest}


def _identity_from(value: Any) -> dict[str, str]:
    if not isinstance(value, dict) or set(value) != {"key", "stage", "payload_sha256"}:
        raise ValueError("append-once identity metadata is invalid")
    return _append_identity(value["key"], value["stage"], value["payload_sha256"])


def _payload_digest(entry_type: str, payload: dict[str, Any]) -> str:
    def validate(value: Any) -> None:
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise ValueError("append-once payload requires string JSON keys")
            for item in value.values():
                validate(item)
        elif type(value) is list:
            for item in value:
                validate(item)
        elif value is not None and type(value) not in {str, int, float, bool}:
            raise ValueError("append-once payload must contain JSON values")
    if not isinstance(entry_type, str) or not entry_type or type(payload) is not dict:
        raise ValueError("append-once requires an entry type and JSON payload object")
    validate(payload)
    encoded = json.dumps({"entry_type": entry_type, "payload": payload}, ensure_ascii=False,
                         sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise SessionAppendPendingError("pending append intent contains duplicate fields")
        value[key] = item
    return value


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
    idempotency: dict[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "entry_id": self.entry_id,
            "session_id": self.session_id,
            "entry_type": self.entry_type,
            "payload": self.payload,
            "parent_ref": self.parent_ref.to_dict() if self.parent_ref else None,
            "created_at": self.created_at,
        }
        if self.idempotency is not None:
            value["idempotency"] = dict(self.idempotency)
        return value

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
            idempotency=_identity_from(value["idempotency"]) if value.get("idempotency") is not None else None,
        )


class SessionHasBranchesError(ValueError):
    """Other conversations continue from this one; deleting it would cut them."""

    def __init__(self, branches: list[str]) -> None:
        super().__init__(f"{len(branches)} other conversation(s) continue from this one")
        self.branches = branches


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

    def _append_intent_path(self, session_id: str) -> Path:
        self._validate_session_id(session_id)
        return self.sessions_dir / f"{session_id}.append-once.intent.json"

    def _refuse_pending_append(self, session_id: str) -> None:
        path = self._append_intent_path(session_id)
        if path.exists() or path.is_symlink():
            raise SessionAppendPendingError("pending append requires explicit append-once recovery")

    @staticmethod
    def _pointer_state(metadata: dict[str, Any]) -> dict[str, Any]:
        return {key: metadata.get(key) for key in ("root_entry_id", "leaf_entry_id", "inherited_parent_ref")}

    @staticmethod
    def _parent_ref(metadata: dict[str, Any], session_id: str) -> EntryRef | None:
        leaf = metadata.get("leaf_entry_id")
        if leaf:
            return EntryRef(session_id, leaf)
        inherited = metadata.get("inherited_parent_ref")
        return EntryRef.from_dict(inherited) if inherited else None

    def _load_append_intent(self, session_id: str) -> dict[str, Any] | None:
        path = self._append_intent_path(session_id)
        if path.is_symlink():
            raise SessionAppendPendingError("pending append intent is not a regular document")
        try:
            value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
        except FileNotFoundError:
            return None
        except (ValueError, UnicodeError) as exc:
            raise SessionAppendPendingError("pending append intent is corrupt") from exc
        expected = {"schema_version", "session_id", "entry_id", "entry_type", "parent_ref", "created_at",
                    "idempotency", "base"}
        try:
            if not isinstance(value, dict) or set(value) != expected:
                raise ValueError
            if value["schema_version"] != "agent.session_append_intent.v1" or value["session_id"] != session_id:
                raise ValueError
            for key in ("entry_id", "entry_type", "created_at"):
                if not isinstance(value[key], str) or not value[key]:
                    raise ValueError
            _identity_from(value["idempotency"])
            base = value["base"]
            if not isinstance(base, dict) or set(base) != {"root_entry_id", "leaf_entry_id", "inherited_parent_ref"}:
                raise ValueError
            for key in ("root_entry_id", "leaf_entry_id"):
                if base[key] is not None and (not isinstance(base[key], str) or not base[key]):
                    raise ValueError
            for ref in (value["parent_ref"], base["inherited_parent_ref"]):
                if ref is not None and (not isinstance(ref, dict) or set(ref) != {"session_id", "entry_id"}
                                        or any(not isinstance(item, str) or not item for item in ref.values())):
                    raise ValueError
            parent = self._parent_ref(base, session_id)
            if value["parent_ref"] != (parent.to_dict() if parent else None):
                raise ValueError
        except (ValueError, TypeError, KeyError) as exc:
            raise SessionAppendPendingError("pending append intent is invalid") from exc
        return value

    def _clear_append_intent(self, session_id: str) -> None:
        self._append_intent_path(session_id).unlink()
        self._sync_directory(self.sessions_dir)

    def append_once(self, session_id: str, entry_type: str, payload: dict[str, Any], *,
                    key: str, stage: str) -> SessionTreeEntry:
        """Append one exact JSON message per session/key/stage, or return it.

        A compact write-ahead intent fixes identity and parent before the log
        write. An off-branch historical key is refused, never made active again.
        Idempotency metadata stays outside the model-visible payload.
        """
        identity = _append_identity(key, stage, _payload_digest(entry_type, payload))
        # Detach from caller mutation before the intent can become durable.
        payload = json.loads(json.dumps(payload, ensure_ascii=False, allow_nan=False))
        with self._lock, _exclusive_jsonl_lock(self._session_path(session_id)):
            intent = self._load_append_intent(session_id)
            if intent is not None:
                if intent["idempotency"] != identity:
                    raise SessionAppendPendingError("pending append belongs to a different key, stage or payload")
                return self._finish_append_intent(session_id, intent, payload=payload)
            entries = self._read_entries(session_id)
            matches = [entry for entry in entries if entry.idempotency is not None
                       and (entry.idempotency["key"], entry.idempotency["stage"]) == (key, stage)]
            if matches:
                if len(matches) != 1:
                    raise SessionAppendConflict("append-once identity conflict: duplicate recorded entries")
                existing = matches[0]
                if (existing.idempotency != identity
                        or _payload_digest(existing.entry_type, existing.payload) != identity["payload_sha256"]):
                    raise SessionAppendConflict("append-once payload conflict")
                if not any(entry.session_id == session_id and entry.entry_id == existing.entry_id
                           for entry in self.get_branch(session_id)):
                    raise SessionAppendConflict("append-once key is on an off-branch historical entry")
                return existing
            metadata = self.get_metadata(session_id)
            parent = self._parent_ref(metadata, session_id)
            intent = {"schema_version": "agent.session_append_intent.v1", "session_id": session_id,
                      "entry_id": uuid4().hex, "entry_type": entry_type,
                      "parent_ref": parent.to_dict() if parent else None, "created_at": _now(),
                      "idempotency": identity, "base": self._pointer_state(metadata)}
            self._atomic_write_json(self._append_intent_path(session_id), intent)
            return self._finish_append_intent(session_id, intent, payload=payload)

    def recover_append_once(self, session_id: str) -> SessionTreeEntry | None:
        """Complete only the exact logged entry named by a verified intent.

        If no entry was written, the compact intent cannot reconstruct content:
        retry append_once with the original complete payload instead.
        """
        with self._lock, _exclusive_jsonl_lock(self._session_path(session_id)):
            intent = self._load_append_intent(session_id)
            return self._finish_append_intent(session_id, intent) if intent is not None else None

    def _finish_append_intent(self, session_id: str, intent: dict[str, Any], *,
                              payload: dict[str, Any] | None = None) -> SessionTreeEntry:
        """Caller owns the session file lock; do not acquire a nested flock."""
        metadata = self.get_metadata(session_id)
        base = intent["base"]
        committed = {**base, "root_entry_id": base["root_entry_id"] or intent["entry_id"],
                     "leaf_entry_id": intent["entry_id"]}
        current = self._pointer_state(metadata)
        if current != base and current != committed:
            raise SessionAppendPendingError("pending append does not match the current metadata branch")
        entries = self._read_entries(session_id)
        matches = [entry for entry in entries if entry.entry_id == intent["entry_id"]]
        same_keys = [entry for entry in entries if entry.idempotency is not None
                     and (entry.idempotency["key"], entry.idempotency["stage"]) == (
                         intent["idempotency"]["key"], intent["idempotency"]["stage"])]
        if len(matches) > 1 or any(entry.entry_id != intent["entry_id"] for entry in same_keys):
            raise SessionAppendPendingError("pending append identity conflicts with the recorded log")
        if matches:
            entry = matches[0]
            if (entry.session_id != session_id or entry.entry_type != intent["entry_type"]
                    or entry.created_at != intent["created_at"] or entry.idempotency != intent["idempotency"]
                    or (entry.parent_ref.to_dict() if entry.parent_ref else None) != intent["parent_ref"]
                    or _payload_digest(entry.entry_type, entry.payload) != intent["idempotency"]["payload_sha256"]):
                raise SessionAppendPendingError("pending append content conflicts with the exact recorded entry")
        else:
            if payload is None:
                raise SessionAppendPendingError("pending append requires the original matching payload")
            if current != base or _payload_digest(intent["entry_type"], payload) != intent["idempotency"]["payload_sha256"]:
                raise SessionAppendPendingError("pending append cannot reconstruct an unknown log state")
            parent = EntryRef.from_dict(intent["parent_ref"]) if intent["parent_ref"] else None
            entry = SessionTreeEntry(entry_id=intent["entry_id"], session_id=session_id,
                                     entry_type=intent["entry_type"], payload=payload, parent_ref=parent,
                                     created_at=intent["created_at"], idempotency=dict(intent["idempotency"]))
            self._atomic_append(self._session_path(session_id), entry.to_dict())
        metadata.update(committed)
        self._atomic_write_json(self._metadata_path(session_id), metadata)
        self._clear_append_intent(session_id)
        return entry

    def create_session(
        self,
        session_id: str,
        *,
        chain_id: str,
        role: str,
        inherited_parent_ref: EntryRef | None = None,
        status: str = "idle",
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
                "status": status,
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
        with self._lock, _exclusive_jsonl_lock(self._session_path(session_id)):
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
        # Every request builds its own repository, so the instance lock alone
        # does not serialize two requests writing one session; the file lock
        # does (threads and processes alike).
        with self._lock, _exclusive_jsonl_lock(self._session_path(session_id)):
            self._refuse_pending_append(session_id)
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

    def rewind(self, session_id: str, to_entry: EntryRef) -> dict[str, Any]:
        """Make an earlier entry of the current branch the session's leaf.

        Nothing is deleted: entries after it stay in the log and the next
        append branches from here. An entry before a fork point re-anchors
        the session's inheritance at that entry. Refused while a turn runs.
        """

        with self._lock, _exclusive_jsonl_lock(self._session_path(session_id)):
            self._refuse_pending_append(session_id)
            metadata = self.get_metadata(session_id)
            if metadata.get("status") == "running":
                raise ValueError("a turn is running; wait for it or stop it before rewinding")
            branch = self.get_branch(session_id)
            if not any(entry.entry_id == to_entry.entry_id and entry.session_id == to_entry.session_id for entry in branch):
                raise KeyError(f"entry is not on this session's branch: {to_entry.entry_id}")
            if to_entry.session_id == session_id:
                metadata["leaf_entry_id"] = to_entry.entry_id
            else:
                metadata["leaf_entry_id"] = None
                metadata["root_entry_id"] = None
                metadata["inherited_parent_ref"] = to_entry.to_dict()
            chapters = metadata.get("chapters") or []
            on_branch = {entry.entry_id for entry in self.get_branch(session_id, leaf_entry_id=metadata["leaf_entry_id"])} \
                if metadata["leaf_entry_id"] else {to_entry.entry_id}
            metadata["chapters"] = [chapter for chapter in chapters if chapter.get("entry_id") in on_branch]
            self._atomic_write_json(self._metadata_path(session_id), metadata)
            return metadata.copy()

    def set_chapters(self, session_id: str, chapters: list[dict[str, Any]]) -> dict[str, Any]:
        """Replace the session's pinned chapters (entry id, title, time)."""

        with self._lock, _exclusive_jsonl_lock(self._session_path(session_id)):
            metadata = self.get_metadata(session_id)
            metadata["chapters"] = [dict(chapter) for chapter in chapters]
            self._atomic_write_json(self._metadata_path(session_id), metadata)
            return metadata.copy()

    def update_metadata(self, session_id: str, **fields: Any) -> dict[str, Any]:
        """Set display fields (title, archived) and the conversation's permission
        grants (v1.9.1 "don't ask again"); the log itself is untouched."""

        allowed = {"title", "archived", "permission_grants", "execution_mode", "analysis_rewind"}
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"not editable: {sorted(unknown)}")
        with self._lock, _exclusive_jsonl_lock(self._session_path(session_id)):
            metadata = self.get_metadata(session_id)
            for key, value in fields.items():
                if value is None:
                    metadata.pop(key, None)
                else:
                    metadata[key] = value
            self._atomic_write_json(self._metadata_path(session_id), metadata)
            return metadata.copy()

    def branches_of(self, session_id: str) -> list[str]:
        """Sessions that continue from an entry of this one (fork children)."""

        return [
            str(metadata["session_id"])
            for metadata in self.list_metadata()
            if (metadata.get("inherited_parent_ref") or {}).get("session_id") == session_id
            and metadata.get("session_id") != session_id
        ]

    def delete_session(self, session_id: str) -> None:
        """Remove a conversation's log. Refused while a turn runs or while
        another conversation continues from it (it would lose its start)."""

        with self._lock, _exclusive_jsonl_lock(self._session_path(session_id)):
            self._refuse_pending_append(session_id)
            metadata = self.get_metadata(session_id)
            if metadata.get("status") == "running":
                raise ValueError("a turn is running; stop it before deleting the conversation")
            branches = self.branches_of(session_id)
            if branches:
                raise SessionHasBranchesError(branches)
            self._session_path(session_id).unlink(missing_ok=True)
            self._metadata_path(session_id).unlink(missing_ok=True)
        lock = self._session_path(session_id)
        lock.with_name(f".{lock.name}.lock").unlink(missing_ok=True)

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
        # Each session file is read once per call, not once per entry: the
        # branch is rebuilt every model step and grows with the conversation.
        indexes: dict[str, dict[str, SessionTreeEntry]] = {}
        with self._lock:
            while current is not None:
                if current in visited:
                    raise ValueError("cycle detected in agent session tree")
                visited.add(current)
                index = indexes.get(current.session_id)
                if index is None:
                    index = {entry.entry_id: entry for entry in self._read_entries(current.session_id)}
                    indexes[current.session_id] = index
                entry = index.get(current.entry_id)
                if entry is None:
                    raise KeyError(f"unknown session entry: {current.session_id}/{current.entry_id}")
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
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
                temp_path = Path(handle.name)
                handle.write(existing)
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            JsonlSessionRepository._sync_directory(path.parent)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=path.parent, delete=False
            ) as handle:
                temp_path = Path(handle.name)
                json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
            JsonlSessionRepository._sync_directory(path.parent)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    @staticmethod
    def _sync_directory(path: Path) -> None:
        directory_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
