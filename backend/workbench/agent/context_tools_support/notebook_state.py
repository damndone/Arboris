"""Bounded plan metadata, separate from committed workflow result receipts."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..notebook.store import NotebookStore
from ..tools import ToolContext, ToolDefinition


def read_notebook_state(project_root: Path, notebook_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"nb_[A-Za-z0-9_-]{1,160}", notebook_id):
        raise ValueError("Invalid notebook identifier")
    root = project_root.resolve()
    directory = root / "notebooks" / notebook_id
    # Never follow persisted links out of the explicitly scoped project.
    if not directory.resolve().is_relative_to(root):
        raise ValueError("Notebook is outside the project scope")
    for path in [directory / "notebook.jsonl", *(directory / "options").glob("*.jsonl")]:
        if not path.resolve().is_relative_to(root):
            raise ValueError("Notebook record is outside the project scope")
    store = NotebookStore(root, create=False)
    notebook = store.get_notebook(notebook_id)
    identifiers = store.option_ids(notebook_id)
    options = []
    for identifier in identifiers[:16]:
        option = store.read_option(notebook_id, identifier)
        options.append({
            "option_id": option.option_id,
            "revision": option.current_revision.option_revision,
            "lifecycle_status": option.lifecycle_status,
        })
    return {
        "notebook_id": notebook.notebook_id,
        "active_head_run_id": notebook.active_head_run_id,
        "focused_run_id": notebook.focused_run_id,
        "last_attempt_run_id": notebook.last_attempt_run_id,
        "option_count": len(identifiers),
        "options": options,
        "options_omitted": max(0, len(identifiers) - len(options)),
        "execution_authorized": False,
        "execution_note": "Metadata is not execution approval. Validate the current revision and obtain confirmation before execution.",
        "omitted_sections": ["raw_rows", "proposal_payloads", "private_memory"],
    }


def notebook_state_tool(project_root: Path, *, session_id: str) -> ToolDefinition:
    def inspect(arguments: dict[str, Any], context: ToolContext) -> dict[str, Any]:
        if context.session_id != session_id:
            raise ValueError("Tool session is outside the registered project scope")
        return read_notebook_state(project_root, arguments["notebook_id"])

    return ToolDefinition(
        tool_id="inspect_notebook_state", version="v1",
        description="Read a named Notebook's current plan option count, revisions and lifecycle statuses, including unexecuted plans. Workflow result receipts alone cannot establish whether plans exist. Does not authorize execution.",
        input_schema={"type": "object", "required": ["notebook_id"], "properties": {
            "notebook_id": {"type": "string", "pattern": "^nb_[A-Za-z0-9_-]{1,160}$"},
        }, "additionalProperties": False},
        side_effect="none", scope_requirements=("project",),
        max_output_budget=8192, handler=inspect,
    )
