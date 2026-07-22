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


# A transcript entry longer than this is a machine payload -- a context
# envelope or a tool result -- not prose someone reads top to bottom. Those are
# folded away so the shape of the session stays visible.
_INLINE_CONTENT_LIMIT = 300

_AUDIT_STYLE = """
:root { color-scheme: light dark; }
body { margin: 0 auto; padding: 2rem 1.25rem; max-width: 60rem;
  font: 15px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
h1 { font-size: 1.5rem; margin: 0 0 .25rem; }
h2 { font-size: 1.1rem; margin: 2rem 0 .5rem; padding-bottom: .25rem;
  border-bottom: 1px solid rgba(128,128,128,.35); }
dl { display: grid; grid-template-columns: max-content 1fr; gap: .2rem .75rem; margin: .5rem 0 0; }
dt { font-weight: 600; }
dd { margin: 0; }
ol.entries { list-style: none; padding: 0; margin: 0; }
ol.entries > li { padding: .5rem 0; border-bottom: 1px solid rgba(128,128,128,.18); }
time { font-variant-numeric: tabular-nums; opacity: .7; margin-right: .5rem; }
.label { font-weight: 600; margin-right: .4rem; }
code, pre { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
pre { overflow-x: auto; padding: .6rem .75rem; border-radius: 6px;
  background: rgba(128,128,128,.12); white-space: pre-wrap; word-break: break-word; }
details > summary { cursor: pointer; opacity: .8; }
.op { margin: 0 0 1rem; padding: .75rem 1rem; border-radius: 6px;
  background: rgba(128,128,128,.09); }
.empty { opacity: .7; font-style: italic; }
"""


def _content_html(content: object) -> str:
    """Render entry content inline, folding machine payloads behind a summary."""
    if content is None or content == "":
        return '<span class="empty">(no text content)</span>'
    text = str(content)
    if len(text) <= _INLINE_CONTENT_LIMIT and "\n" not in text:
        return escape(text)
    return (
        f"<details><summary>{len(text)} characters</summary>"
        f"<pre>{escape(text)}</pre></details>"
    )


def render_agent_audit_html(audit: dict[str, object]) -> str:
    """Render the audit as an actual HTML document.

    This used to be the Markdown rendering escaped inside a single ``<pre>``,
    so choosing HTML got a wall of monospace text with literal ``#`` and ``**``
    still in it, and every context envelope inlined at full length. Same
    evidence, in a document a reader can move around: headings, a transcript
    list, and long machine payloads folded away rather than dropped.
    """
    session = dict(audit["session"])
    parts = [
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
        "<title>Agent audit</title>",
        f"<style>{_AUDIT_STYLE}</style></head><body>",
        "<h1>Agent audit</h1>",
        "<dl>",
        f"<dt>Session</dt><dd><code>{escape(str(session['session_id']))}</code></dd>",
        f"<dt>Chain</dt><dd><code>{escape(str(session.get('chain_id')))}</code></dd>",
    ]
    for key in ("role", "status"):
        if session.get(key) is not None:
            parts.append(
                f"<dt>{escape(key.title())}</dt>"
                f"<dd>{escape(str(session[key]))}</dd>"
            )
    parts.append(
        f"<dt>Raw record</dt><dd><code>{escape(str(session.get('raw_reference')))}"
        "</code></dd></dl>"
    )

    entries = list(audit["entries"])
    parts.append(f"<h2>Transcript ({len(entries)})</h2>")
    if not entries:
        parts.append('<p class="empty">No transcript entries.</p>')
    else:
        parts.append('<ol class="entries">')
        for entry in entries:
            item = dict(entry)
            label = item.get("role") or item.get("message_type") or item["entry_type"]
            parts.append(
                "<li>"
                f"<time>{escape(str(item['created_at']))}</time>"
                f'<span class="label">{escape(str(label))}</span>'
                f"{_content_html(item.get('content'))}"
                "</li>"
            )
        parts.append("</ol>")

    operations = list(audit["operations"])
    parts.append(f"<h2>Operations ({len(operations)})</h2>")
    if not operations:
        parts.append('<p class="empty">No operations were recorded.</p>')
    for operation in operations:
        item = dict(operation)
        terminal = dict(item["terminal_result"])
        parts.append(
            '<div class="op">'
            f"<div><code>{escape(str(item['operation_id']))}</code> / "
            f"<code>{escape(str(item['record_id']))}</code> — "
            f"<strong>{escape(str(item['status']))}</strong></div><dl>"
        )
        child = item.get("child_session")
        if isinstance(child, dict):
            parts.append(
                "<dt>Child session</dt>"
                f"<dd><code>{escape(str(child.get('session_id')))}</code></dd>"
            )
        parts.append(
            f"<dt>Terminal result</dt><dd>{escape(str(terminal.get('status')))} "
            f"(source: {escape(str(terminal.get('source')))})</dd>"
        )
        if terminal.get("reason"):
            parts.append(
                f"<dt>Reason</dt><dd>{escape(str(terminal['reason']))}</dd>"
            )
        outputs = terminal.get("outputs")
        if isinstance(outputs, dict) and outputs.get("target_run_id"):
            parts.append(
                "<dt>Child run</dt>"
                f"<dd><code>{escape(str(outputs['target_run_id']))}</code></dd>"
            )
        parts.append("</dl></div>")

    parts.append("</body></html>")
    return "".join(parts)


__all__ = [
    "build_agent_audit",
    "render_agent_audit_html",
    "render_agent_audit_markdown",
]
