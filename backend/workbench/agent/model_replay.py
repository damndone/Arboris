"""Opt-in local provider journals and strict offline ModelAdapter replay.

The caller supplies an existing absolute directory and one new file name.
Journals contain model-visible requests and normalized events, including usage.
They are never enabled implicitly and replay has no upstream adapter.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Mapping
from dataclasses import fields, replace
import hashlib
import json
import math
import os
from pathlib import Path
import stat
from typing import Any

from ..identity.root import open_validated_project_root
from .model import ModelAdapter, ModelRequest, ModelStreamEvent


class RecordingError(ValueError):
    """A request, stream, or local journal cannot be recorded faithfully."""


class ReplayError(RecordingError):
    """An offline replay cannot satisfy the current request."""


class ReplayMismatch(ReplayError):
    pass


class ReplayExhausted(ReplayError):
    pass


class ReplayIncomplete(ReplayError):
    pass


_HEADER = {"kind": "header", "schema": "workbench.model-replay", "version": 1}
_REQUEST_FIELDS = {field.name for field in fields(ModelRequest)} - {"request_id", "abort_event"}
_EVENT_FIELDS = {field.name for field in fields(ModelStreamEvent)}


def _json_snapshot(value: Any) -> Any:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if isinstance(value, Mapping):
        if any(type(key) is not str for key in value):
            raise RecordingError("recording object keys must be strings")
        return {key: _json_snapshot(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_snapshot(item) for item in value]
    raise RecordingError("recording requires finite, JSON-compatible values")


def _encode(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _request(request: ModelRequest) -> dict[str, Any]:
    # New semantic ModelRequest fields automatically participate in matching.
    return _json_snapshot({name: getattr(request, name) for name in _REQUEST_FIELDS})


def _event(value: Mapping[str, Any]) -> ModelStreamEvent:
    if set(value) != _EVENT_FIELDS:
        raise RecordingError("recorded event fields do not match ModelStreamEvent")
    if not all(type(value[key]) is str for key in ("type", "request_id", "delta")) or not value["type"]:
        raise RecordingError("recorded event has invalid string fields")
    for key in ("finish_reason", "provider_request_id", "error"):
        if value[key] is not None and type(value[key]) is not str:
            raise RecordingError("recorded event has invalid optional string fields")
    for key in ("tool_call", "usage"):
        if value[key] is not None and not isinstance(value[key], dict):
            raise RecordingError("recorded event has invalid object fields")
    return ModelStreamEvent(**value)


def _termination(event: ModelStreamEvent) -> str:
    if event.error == "aborted" or event.finish_reason == "aborted":
        return "aborted"
    if event.type == "done" and event.finish_reason in {"length", "max_tokens", "incomplete"}:
        return "truncated"
    return event.type


class _Journal:
    """Directory-FD admission plus exclusive creation and checked append."""

    def __init__(self, root: Path | str, name: str, *, create: bool):
        self.root = Path(root)
        if (not self.root.is_absolute() or ".." in self.root.parts
                or type(name) is not str or not name or name in {".", ".."}
                or any(char in name for char in ("/", "\\", "\0"))):
            raise RecordingError("recording path must remain inside the explicit absolute directory")
        self.name = name
        self.binding = None
        self.file_identity = None
        self.size = 0
        self.index = 0
        self.previous = None
        try:
            with open_validated_project_root(self.root) as admitted:
                if admitted.validated.path != self.root:
                    raise RecordingError("recording directory must not contain symlinks")
                self.binding = admitted.validated.binding_key
                if create:
                    fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=admitted.fd)
                    try:
                        self.file_identity = self._identity(fd)
                    finally:
                        os.close(fd)
                    os.fsync(admitted.fd)
        except (OSError, ValueError) as error:
            raise RecordingError("recording path is unsafe, unavailable, or already exists") from error
        if create:
            self.append(_HEADER)

    @staticmethod
    def _identity(fd: int):
        observed = os.fstat(fd)
        if not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
            raise RecordingError("recording must be one regular file without hardlinks")
        return observed.st_dev, observed.st_ino

    def _open(self, admitted, flags: int) -> int:
        if admitted.validated.path != self.root or admitted.validated.binding_key != self.binding:
            raise RecordingError("recording directory binding changed")
        fd = os.open(self.name, flags | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=admitted.fd)
        try:
            identity = self._identity(fd)
            if self.file_identity is not None and identity != self.file_identity:
                raise RecordingError("recording file binding changed")
            return fd
        except BaseException:
            os.close(fd)
            raise

    def append(self, payload: dict[str, Any]) -> None:
        body = {"index": self.index, "previous_sha256": self.previous, "payload": payload}
        digest = hashlib.sha256(_encode(body)).hexdigest()
        raw = _encode({**body, "sha256": digest}) + b"\n"
        try:
            with open_validated_project_root(self.root) as admitted:
                fd = self._open(admitted, os.O_WRONLY | os.O_APPEND)
                # Reuse Python's complete buffered writer on an admitted FD;
                # path-based replace/JSONL helpers allow overwrite or partial-tail recovery.
                with os.fdopen(fd, "ab") as handle:
                    if os.fstat(handle.fileno()).st_size != self.size:
                        raise RecordingError("recording changed outside its writer")
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.fsync(admitted.fd)
        except (OSError, ValueError) as error:
            raise RecordingError("recording append failed closed") from error
        self.index += 1
        self.previous = digest
        self.size += len(raw)

    def read(self) -> bytes:
        try:
            with open_validated_project_root(self.root) as admitted:
                fd = self._open(admitted, os.O_RDONLY)
                with os.fdopen(fd, "rb") as handle:
                    before = os.fstat(handle.fileno())
                    raw = handle.read()
                    after = os.fstat(handle.fileno())
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise RecordingError("recording changed while reading")
                    return raw
        except (OSError, ValueError) as error:
            raise RecordingError("recording read failed closed") from error


class _Aborted(Exception):
    pass


async def _next(iterator, abort_event):
    if abort_event is None:
        return await anext(iterator)
    if abort_event.is_set():
        raise _Aborted
    pending = asyncio.ensure_future(anext(iterator))
    aborted = asyncio.ensure_future(abort_event.wait())
    try:
        await asyncio.wait({pending, aborted}, return_when=asyncio.FIRST_COMPLETED)
        if abort_event.is_set():
            raise _Aborted
        return pending.result()
    finally:
        for task in (pending, aborted):
            if not task.done():
                task.cancel()
        await asyncio.gather(pending, aborted, return_exceptions=True)


class RecordingAdapter:
    """Wrap one explicitly provided adapter; create a new private journal."""

    def __init__(self, adapter: ModelAdapter, *, root: Path | str, name: str):
        self.adapter = adapter
        self._journal = _Journal(root, name, create=True)
        self._turn = 0
        self._active = None

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if self._active is not None:
            raise RecordingError("a recording stream is already active")
        packet = _request(request)
        token = object()
        self._active = token
        turn = self._turn
        self._turn += 1
        ended = False
        iterator = None
        termination = "consumer_closed"
        exception = None
        try:
            self._journal.append({"kind": "request", "turn": turn,
                                  "request_id": request.request_id, "request": packet})
            if request.abort_event is not None and request.abort_event.is_set():
                raise _Aborted
            iterator = self.adapter.stream(request).__aiter__()
            terminal = None
            while True:
                try:
                    event = await _next(iterator, request.abort_event)
                except StopAsyncIteration:
                    if terminal is None:
                        termination = "missing_terminal"
                        raise RecordingError("provider stream ended without a terminal event")
                    termination = _termination(terminal)
                    complete = termination in {"done", "error"}
                    self._journal.append({"kind": "end", "turn": turn, "complete": complete,
                                          "termination": termination, "exception": None})
                    ended = True
                    self._active = None
                    if termination == "truncated":
                        raise RecordingError("provider completion was truncated")
                    # AgentCore stops consuming at the terminal event. The journal
                    # and upstream EOF must therefore be settled before yielding it.
                    yield terminal
                    return
                if not isinstance(event, ModelStreamEvent):
                    termination = "invalid_event"
                    raise RecordingError("provider did not return a ModelStreamEvent")
                raw_event = _json_snapshot({field.name: getattr(event, field.name) for field in fields(event)})
                self._journal.append({"kind": "event", "turn": turn, "event": raw_event})
                event = _event(raw_event)
                if terminal is not None or event.request_id != request.request_id:
                    termination = "invalid_event"
                    raise RecordingError("provider event followed a terminal event or changed request identity")
                if event.type in {"done", "error"}:
                    terminal = event
                else:
                    yield event
        except _Aborted:
            termination = "aborted"
            event = ModelStreamEvent.from_error(request.request_id, "aborted")
            self._journal.append({"kind": "event", "turn": turn,
                                  "event": _json_snapshot({field.name: getattr(event, field.name) for field in fields(event)})})
            self._journal.append({"kind": "end", "turn": turn, "complete": False,
                                  "termination": termination, "exception": None})
            ended = True
            if self._active is token:
                self._active = None
            yield event
        except asyncio.CancelledError:
            termination = "cancelled"
            raise
        except GeneratorExit:
            termination = "consumer_closed"
            raise
        except BaseException as error:
            exception = type(error).__name__
            if termination == "consumer_closed":
                termination = "exception"
            raise
        finally:
            try:
                if not ended:
                    self._journal.append({"kind": "end", "turn": turn, "complete": False,
                                          "termination": termination, "exception": exception})
            finally:
                if self._active is token:
                    self._active = None
                close = getattr(iterator, "aclose", None)
                if close is not None:
                    await close()


def _unique_object(items):
    result = {}
    for key, value in items:
        if key in result:
            raise RecordingError("duplicate JSON field in recording")
        result[key] = value
    return result


def _load(raw: bytes) -> list[dict[str, Any]]:
    if not raw or not raw.endswith(b"\n"):
        raise RecordingError("recording is empty or has a truncated final line")
    turns = []
    current = None
    previous = None
    try:
        for index, line in enumerate(raw.decode("utf-8").splitlines()):
            envelope = json.loads(line, object_pairs_hook=_unique_object)
            _json_snapshot(envelope)
            if set(envelope) != {"index", "previous_sha256", "payload", "sha256"}:
                raise RecordingError("recording envelope fields are invalid")
            digest = envelope.pop("sha256")
            if (type(envelope["index"]) is not int or envelope["index"] != index
                    or envelope["previous_sha256"] != previous
                    or digest != hashlib.sha256(_encode(envelope)).hexdigest()):
                raise RecordingError("recording content checksum or sequence is invalid")
            previous = digest
            payload = envelope["payload"]
            if index == 0:
                if payload != _HEADER or type(payload.get("version")) is not int:
                    raise RecordingError("recording schema or version is unsupported")
                continue
            if not isinstance(payload, dict) or payload.get("turn") != len(turns) or type(payload.get("turn")) is not int:
                raise RecordingError("recording turn sequence is invalid")
            kind = payload.get("kind")
            if kind == "request" and current is None:
                if (set(payload) != {"kind", "turn", "request", "request_id"}
                        or set(payload["request"]) != _REQUEST_FIELDS or type(payload["request_id"]) is not str):
                    raise RecordingError("recording request fields are invalid")
                current = {**payload, "events": []}
            elif kind == "event" and current is not None:
                if set(payload) != {"kind", "turn", "event"}:
                    raise RecordingError("recording event envelope fields are invalid")
                event = _event(payload["event"])
                current["events"].append(event)
            elif kind == "end" and current is not None:
                if (set(payload) != {"kind", "turn", "complete", "termination", "exception"}
                        or type(payload["complete"]) is not bool
                        or payload["termination"] not in {"done", "error", "aborted", "truncated", "missing_terminal", "exception", "cancelled", "consumer_closed", "invalid_event"}
                        or (payload["exception"] is not None and type(payload["exception"]) is not str)):
                    raise RecordingError("recording completion fields are invalid")
                events = current["events"]
                if payload["complete"]:
                    if (not events or events[-1].type not in {"done", "error"}
                            or any(event.type in {"done", "error"} for event in events[:-1])
                            or any(event.request_id != current["request_id"] for event in events)
                            or _termination(events[-1]) != payload["termination"]
                            or payload["termination"] not in {"done", "error"}
                            or payload["exception"] is not None):
                        raise RecordingError("recording claims completion without a valid terminal stream")
                turns.append({**current, **payload})
                current = None
            else:
                raise RecordingError("recording stream boundaries are invalid")
    except (ValueError, TypeError, KeyError, UnicodeError) as error:
        raise RecordingError("recording content is corrupt or unsupported") from error
    if current is not None:
        raise RecordingError("recording contains a stream without its completion record")
    return turns


class ReplayAdapter:
    """Replay local records in order; never call or discover a provider."""

    def __init__(self, *, root: Path | str, name: str):
        self._turns = _load(_Journal(root, name, create=False).read())
        self._cursor = 0
        self._delivered_terminals = 0
        self._active = None

    @property
    def remaining(self) -> int:
        return len(self._turns) - self._cursor

    def assert_complete(self) -> None:
        """Reject any incomplete recorded stream before executing a replay."""
        for turn in self._turns:
            if not turn['complete']:
                raise ReplayIncomplete(f"recorded stream is incomplete: {turn['termination']}")

    def assert_consumed(self) -> None:
        """Require a complete journal and no unused provider requests."""
        self.assert_complete()
        if self._active is not None or self.remaining or self._delivered_terminals != len(self._turns):
            raise ReplayError('provider recording has unconsumed requests')

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        if self._active is not None:
            raise ReplayError("a replay stream is already active")
        if request.abort_event is not None and request.abort_event.is_set():
            yield ModelStreamEvent.from_error(request.request_id, "aborted")
            return
        if not self.remaining:
            raise ReplayExhausted("provider recording is exhausted")
        turn = self._turns[self._cursor]
        if _encode(_request(request)) != _encode(turn["request"]):
            raise ReplayMismatch(f"provider request mismatch at recorded turn {self._cursor}")
        if not turn["complete"]:
            raise ReplayIncomplete(f"recorded stream is incomplete: {turn['termination']}")
        token = object()
        self._active = token
        self._cursor += 1
        try:
            for index, event in enumerate(turn["events"]):
                await asyncio.sleep(0)
                if request.abort_event is not None and request.abort_event.is_set():
                    self._active = None
                    yield ModelStreamEvent.from_error(request.request_id, "aborted")
                    return
                if index == len(turn["events"]) - 1:
                    self._active = None
                    self._delivered_terminals += 1
                # Clone nested values so a consumer cannot mutate later replays.
                copy = _json_snapshot({field.name: getattr(event, field.name) for field in fields(event)})
                yield replace(_event(copy), request_id=request.request_id)
        finally:
            if self._active is token:
                self._active = None
