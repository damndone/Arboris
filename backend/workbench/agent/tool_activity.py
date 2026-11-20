"""What a tool call was about, in a few words, for the step row in the transcript.

Read from the call's own arguments, bounded, and never raises: a step that cannot
be described still shows its tool. Identifiers of runs and nodes say nothing to a reader.
"""
from __future__ import annotations

from collections.abc import Mapping
import json
from typing import Any

from .proposal_text import step_sentence

_LIMIT = 140
_NAMED_ARGUMENTS = ("operation_id", "column", "columns", "selected_columns", "term", "terms", "query", "dataset", "path")


def _bounded(text: str) -> str:
    text = " ".join(text.split())
    return text if len(text) <= _LIMIT else text[:_LIMIT - 1] + "…"


def _changes(arguments: Mapping[str, Any]) -> Mapping[str, Any]:
    changes = arguments.get("changes")
    if isinstance(changes, str):
        try:
            changes = json.loads(changes)
        except ValueError:  # the model's own sentence below says what it meant
            return {}
    return changes if isinstance(changes, Mapping) else {}


def _operation(arguments: Mapping[str, Any]) -> str | None:
    changes = _changes(arguments)
    steps = changes.get("steps")
    if isinstance(steps, list) and steps:
        sentences = [step_sentence(str(step.get("operation_id")), step.get("spec") or {}) for step in steps if isinstance(step, Mapping)]
        if not sentences:
            return None
        return sentences[0] if len(sentences) == 1 else f"{sentences[0]} +{len(sentences) - 1} more"
    effect = arguments.get("expected_effect")
    effect = effect[0] if isinstance(effect, list) and effect else effect
    if isinstance(effect, str) and effect.strip():
        return effect
    operation = arguments.get("operation_id")
    return step_sentence(str(operation), changes) if operation and changes else None


def describe_tool_call(tool_id: str, arguments: Any) -> str | None:
    if not isinstance(arguments, Mapping):
        return None
    try:
        if tool_id == "run_operation":
            target = _operation(arguments)
            return _bounded(target) if target else None
        if tool_id == "calculate":
            items = arguments.get("calculations") or arguments.get("expressions")
            first = items[0] if isinstance(items, list) and items else arguments.get("expression")
            first = first.get("label") or first.get("expression") if isinstance(first, Mapping) else first
            return _bounded(str(first)) if first else None
        if tool_id == "update_plan":
            return None
        for name in _NAMED_ARGUMENTS:
            value = arguments.get(name)
            if isinstance(value, list) and value:
                return _bounded(", ".join(str(item) for item in value))
            if isinstance(value, str) and value.strip():
                return _bounded(value)
    except Exception:  # noqa: BLE001 - a description must never break the transcript
        return None
    return None
