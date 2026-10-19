"""Private original tool-return WAL; never derives results or executes tools.

Core supplies the final payload after its repeat/budget annotations. Receipt
durability starts here, separately from any handler's already-committed effect.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ..jsonl_store import _exclusive_jsonl_lock
from .session import JsonlSessionRepository, SessionTreeEntry, _payload_digest

SCHEMA = "agent.tool_receipt.v1"
RECEIPT_STAGE = "original_tool_receipt"
MESSAGE_STAGE = "tool_result"


class ToolReceiptError(ValueError):
    """A missing, conflicting or unverified original receipt cannot be used."""


def _canonical(value: Any) -> str:
    if type(value) is dict:
        if any(type(key) is not str for key in value):
            raise ToolReceiptError("tool receipt requires string JSON keys")
        for item in value.values():
            _canonical(item)
    elif type(value) is list:
        for item in value:
            _canonical(item)
    elif value is not None and type(value) not in {str, int, float, bool}:
        raise ToolReceiptError("tool receipt requires JSON values")
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise ToolReceiptError("invalid tool receipt JSON") from exc


def tool_call_sha256(tool_call: dict[str, Any]) -> str:
    """Hash every field of the original call, including nested provider data."""
    if (type(tool_call) is not dict or not {"tool_call_id", "tool_id", "arguments"} <= set(tool_call)
            or type(tool_call["tool_call_id"]) is not str or type(tool_call["tool_id"]) is not str):
        raise ToolReceiptError("invalid original tool call")
    return hashlib.sha256(_canonical(tool_call).encode("utf-8")).hexdigest()


def _identity(*, session_id: str, command_id: str, provider_step: int,
              tool_call_id: str, invocation_id: str, tool_call: dict[str, Any]) -> dict[str, Any]:
    if (any(type(value) is not str or not value.strip() for value in (session_id, command_id, invocation_id))
            or len(invocation_id) > 512 or type(provider_step) is not int or provider_step < 1
            or type(tool_call_id) is not str):
        raise ToolReceiptError("invalid tool receipt identity")
    digest = tool_call_sha256(tool_call)
    if tool_call["tool_call_id"] != tool_call_id:
        raise ToolReceiptError("tool receipt call identity mismatch")
    return {"schema_version": SCHEMA, "session_id": session_id, "command_id": command_id,
            "provider_step": provider_step, "tool_call_id": tool_call_id, "invocation_id": invocation_id,
            "tool_call_sha256": digest, "tool_id": tool_call["tool_id"]}


def _validate_result(payload: Any) -> None:
    if (type(payload) is not dict or not {"ok", "output", "error"} <= set(payload)
            or type(payload["ok"]) is not bool
            or (payload["error"] is not None and type(payload["error"]) is not str)):
        raise ToolReceiptError("invalid original ToolResult payload")
    _canonical(payload)


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ToolReceiptError("duplicate tool receipt JSON field")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ToolReceiptError("non-finite tool receipt JSON value")


def read(
    repository: JsonlSessionRepository, *, session_id: str, command_id: str, provider_step: int,
    tool_call_id: str, invocation_id: str, tool_call: dict[str, Any],
) -> SessionTreeEntry | None:
    """Read a unique exact receipt on the current branch, without mutation.

    Historical off-branch identities are conflicts, not missing receipts. A
    logged WAL whose append intent has not committed its branch pointer must
    first be completed with the repository's explicit append-once recovery.
    """
    identity = _identity(session_id=session_id, command_id=command_id, provider_step=provider_step,
                         tool_call_id=tool_call_id, invocation_id=invocation_id, tool_call=tool_call)
    repository.get_metadata(session_id)
    path = repository._session_path(session_id)
    with repository._lock, _exclusive_jsonl_lock(path):
        try:
            rows = [json.loads(line, object_pairs_hook=_unique_object, parse_constant=_invalid_constant)
                    for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
            entries = [SessionTreeEntry.from_dict(row) for row in rows]
        except (ValueError, TypeError, KeyError, UnicodeError) as exc:
            raise ToolReceiptError("invalid tool receipt session log") from exc
        matches = [(row, entry) for row, entry in zip(rows, entries)
                   if (entry.entry_type == "tool_receipt" and entry.payload.get("invocation_id") == invocation_id)
                   or (entry.idempotency is not None and entry.idempotency["key"] == invocation_id
                       and entry.idempotency["stage"] == RECEIPT_STAGE)]
        if not matches:
            return None
        if len(matches) != 1:
            raise ToolReceiptError("duplicate original tool receipt identity")
        row, entry = matches[0]
        envelope = entry.payload
        if (entry.entry_type != "tool_receipt" or entry.session_id != session_id
                or set(envelope) != {*identity, "tool_result"}
                or _canonical({key: envelope[key] for key in identity}) != _canonical(identity)
                or _canonical(row) != _canonical(entry.to_dict())):
            raise ToolReceiptError("original tool receipt identity or call digest conflict")
        _validate_result(envelope["tool_result"])
        if entry.idempotency != {"key": invocation_id, "stage": RECEIPT_STAGE,
                                 "payload_sha256": _payload_digest("tool_receipt", envelope)}:
            raise ToolReceiptError("original tool receipt payload digest conflict")
        if sum(candidate.entry_id == entry.entry_id for candidate in entries) != 1:
            raise ToolReceiptError("duplicate original tool receipt entry")
        if not any(candidate.session_id == session_id and candidate.entry_id == entry.entry_id
                   for candidate in repository.get_branch(session_id)):
            raise ToolReceiptError("original tool receipt is on an off-branch historical entry or pending append")
        return entry


def persist(
    repository: JsonlSessionRepository, *, session_id: str, command_id: str, provider_step: int,
    tool_call_id: str, invocation_id: str, tool_call: dict[str, Any], payload: dict[str, Any],
) -> SessionTreeEntry:
    """Persist the caller's complete final payload once, without annotating it."""
    identity = _identity(session_id=session_id, command_id=command_id, provider_step=provider_step,
                         tool_call_id=tool_call_id, invocation_id=invocation_id, tool_call=tool_call)
    _validate_result(payload)
    envelope = json.loads(_canonical({**identity, "tool_result": payload}))
    repository.append_once(session_id, "tool_receipt", envelope, key=invocation_id, stage=RECEIPT_STAGE)
    entry = read(repository, session_id=session_id, command_id=command_id, provider_step=provider_step,
                 tool_call_id=tool_call_id, invocation_id=invocation_id, tool_call=tool_call)
    if entry is None:
        raise ToolReceiptError("persisted original tool receipt is missing")
    return entry


def repair_message(
    repository: JsonlSessionRepository, *, session_id: str, command_id: str, provider_step: int,
    tool_call_id: str, invocation_id: str, tool_call: dict[str, Any],
) -> SessionTreeEntry:
    """Append the exact original tool message from WAL, never from domain state.

    Core retains session/turn ownership across this read and append. This is
    append-once message repair, not cross-store fencing or handler recovery.
    """
    entry = read(repository, session_id=session_id, command_id=command_id, provider_step=provider_step,
                 tool_call_id=tool_call_id, invocation_id=invocation_id, tool_call=tool_call)
    if entry is None:
        raise ToolReceiptError("original tool receipt is missing; handler replay is not allowed")
    return repository.append_once(session_id, "message", {
        "role": "tool", "tool_call_id": tool_call_id, "name": entry.payload["tool_id"],
        "command_id": command_id,
        "content": json.dumps(entry.payload["tool_result"], ensure_ascii=False, sort_keys=True),
    }, key=invocation_id, stage=MESSAGE_STAGE)
