"""Read-only human projections of append-only Agent evidence."""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from .operations import OperationRecord, OperationRecordStore
from .session import JsonlSessionRepository, SessionTreeEntry


def _entry_view(entry: SessionTreeEntry) -> dict[str, object]:
    payload = dict(entry.payload)
    return {
        "entry_id": entry.entry_id,
        "session_id": entry.session_id,
        "entry_type": entry.entry_type,
        "created_at": entry.created_at,
        "role": payload.get("role"),
        "message_type": payload.get("message_type"),
        "content": payload.get("content"),
    }


def _operation_result(
    entries: list[SessionTreeEntry], record_id: str
) -> dict[str, object] | None:
    for entry in reversed(entries):
        result = entry.payload.get("operation_result")
        if isinstance(result, dict) and result.get("record_id") == record_id:
            return dict(result)
    return None


def _child_session(
    repository: JsonlSessionRepository, record: OperationRecord
) -> tuple[dict[str, object] | None, list[SessionTreeEntry]]:
    child_session_id = record.execution.get("child_session_id")
    if not isinstance(child_session_id, str) or not child_session_id:
        return None, []
    try:
        metadata = repository.get_metadata(child_session_id)
        entries = repository.get_branch(child_session_id)
    except KeyError:
        return {"session_id": child_session_id, "status": "missing"}, []
    return {
        "session_id": child_session_id,
        "chain_id": metadata.get("chain_id"),
        "status": metadata.get("status"),
        "entries": [_entry_view(entry) for entry in entries],
    }, entries


def _operation_view(
    repository: JsonlSessionRepository, record: OperationRecord
) -> dict[str, object]:
    child_session, child_entries = _child_session(repository, record)
    child_result = _operation_result(child_entries, record.record_id)
    if child_result is not None:
        terminal_result: dict[str, object] = {
            "source": "child_session",
            "status": child_result.get("status"),
            "outputs": child_result.get("outputs"),
            "error": child_result.get("error"),
        }
    elif child_session is not None:
        terminal_result = {
            "source": "child_session",
            "status": "absent",
            "reason": "The child session terminal result is absent for this operation.",
        }
    else:
        terminal_result = {
            "source": "operation_record",
            "status": "absent",
            "reason": "This operation did not create a child session.",
        }
    references = {
        "operation_record": f"workbench/operation-records/{record.record_id}.jsonl",
    }
    if child_session is not None:
        references["child_session"] = (
            f"workbench/agent-sessions/{child_session['session_id']}.jsonl"
        )
    return {
        "record_id": record.record_id,
        "operation_id": record.operation_id,
        "status": record.status,
        "created_at": record.created_at,
        "updated_at": record.updated_at,
        "target": dict(record.target),
        "child_session": child_session,
        "terminal_result": terminal_result,
        "raw_references": references,
    }


def build_agent_audit(project_root: Path | str, session_id: str) -> dict[str, object]:
    """Assemble a session, its operation records, and child terminal evidence."""

    root = Path(project_root)
    workbench_root = root / "workbench"
    repository = JsonlSessionRepository(workbench_root, create=False)
    metadata = repository.get_metadata(session_id)
    entries = repository.get_branch(session_id)
    store = OperationRecordStore(workbench_root, create=False)
    operations = [
        _operation_view(repository, record)
        for record in store.list_records()
        if record.agent_session_id == session_id
    ]
    return {
        "schema_version": "agent.audit.v1",
        "session": {
            "session_id": session_id,
            "chain_id": metadata.get("chain_id"),
            "role": metadata.get("role"),
            "status": metadata.get("status"),
            "raw_reference": f"workbench/agent-sessions/{session_id}.jsonl",
        },
        "entries": [_entry_view(entry) for entry in entries],
        "operations": operations,
    }


def render_agent_audit_markdown(audit: dict[str, object]) -> str:
    session = dict(audit["session"])
    lines = [
        "# Agent audit",
        "",
        f"Session: `{session['session_id']}`",
        f"Chain: `{session.get('chain_id')}`",
        "",
        "## Transcript",
    ]
    for entry in audit["entries"]:
        item = dict(entry)
        label = item.get("role") or item.get("message_type") or item["entry_type"]
        content = item.get("content")
        lines.append(f"- `{item['created_at']}` **{label}**: {content or '(no text content)'}")
    lines.extend(["", "## Operations"])
    for operation in audit["operations"]:
        item = dict(operation)
        terminal = dict(item["terminal_result"])
        lines.append(
            f"- `{item['operation_id']}` / `{item['record_id']}`: {item['status']}"
        )
        child = item.get("child_session")
        if isinstance(child, dict):
            lines.append(f"  - Child session: `{child.get('session_id')}`")
        lines.append(
            f"  - Terminal result ({terminal.get('source')}): {terminal.get('status')}"
        )
        if terminal.get("reason"):
            lines.append(f"  - {terminal['reason']}")
        outputs = terminal.get("outputs")
        if isinstance(outputs, dict) and outputs.get("target_run_id"):
            lines.append(f"  - Child run: `{outputs['target_run_id']}`")
    return "\n".join(lines) + "\n"


def render_agent_audit_html(audit: dict[str, object]) -> str:
    markdown = render_agent_audit_markdown(audit)
    return (
        "<!doctype html><html><head><meta charset=\"utf-8\"><title>Agent audit</title>"
        "</head><body><pre>"
        f"{escape(markdown)}"
        "</pre></body></html>"
    )


__all__ = [
    "build_agent_audit",
    "render_agent_audit_html",
    "render_agent_audit_markdown",
]
