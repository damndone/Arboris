"""Allowlisted tool descriptors and provider-neutral tool execution."""

from __future__ import annotations

import inspect
import json
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

# Bounds for the validation feedback handed back to the model. Messages embed
# the offending value, which is the model's own argument — echoing it back is
# not a leak, but an unbounded blob would be.
MAX_VALIDATION_ERRORS = 5
MAX_VALIDATION_MESSAGE_CHARS = 240


class ToolError(RuntimeError):
    """Base class for tool registry failures."""


class UnknownToolError(ToolError):
    """The model requested a tool that is not allowlisted."""


ToolHandler = Callable[[dict[str, Any], "ToolContext"], Any | Awaitable[Any]]


@dataclass(frozen=True)
class ToolContext:
    session_id: str
    metadata: dict[str, Any] = field(default_factory=dict)


def _format_validation_error(error) -> dict[str, str]:
    message = error.message
    if len(message) > MAX_VALIDATION_MESSAGE_CHARS:
        message = message[:MAX_VALIDATION_MESSAGE_CHARS] + "… [truncated]"
    return {
        "path": ".".join(str(part) for part in error.absolute_path) or "<root>",
        "message": message,
        "constraint": str(error.validator),
    }


def _discriminated_branch(schema: dict[str, Any], instance: Any) -> dict[str, Any] | None:
    """Find the `oneOf` branch the caller meant, via its `const` discriminator.

    `best_match` cannot do this: it ranks errors by a heuristic with no notion
    of a discriminator, so for a `data.columns.cast` proposal it happily
    surfaced model.rerun's "'node_hash' is a required property" — advice for the
    wrong operation entirely. Telling a caller to add a field that does not
    belong to what it is doing is worse than saying nothing.
    """

    branches = schema.get("oneOf")
    if not isinstance(branches, list) or not isinstance(instance, dict):
        return None
    for branch in branches:
        if not isinstance(branch, dict):
            continue
        consts = {
            key: spec["const"]
            for key, spec in (branch.get("properties") or {}).items()
            if isinstance(spec, dict) and "const" in spec
        }
        if consts and all(instance.get(key) == value for key, value in consts.items()):
            return branch
    return None


def validation_details(schema: dict[str, Any], arguments: Any) -> list[dict[str, str]]:
    """Explain why arguments failed a tool's schema, in terms the model can act on.

    Without this a rejection is just `invalid_tool_arguments`, and the model can
    only guess. A live DeepSeek run retried `propose_operation` five times and
    never learned that `casts` had been (wrongly) declared a string.

    A `oneOf` union needs care: it reports one root error that says the instance
    "is not valid under any of the given schemas" and echoes the whole payload —
    useless and large. When the union is discriminated by a `const` (as the
    proposal schema is, by `operation_id`), report against that branch alone;
    otherwise fall back to `best_match` over the per-branch errors. Plain
    schemas are the opposite case: their top-level errors are already specific
    and complete, so keep them all rather than dripping one fix per round trip.
    """

    effective = _discriminated_branch(schema, arguments) or schema
    details: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    errors = sorted(
        Draft202012Validator(effective).iter_errors(arguments),
        key=lambda item: list(item.absolute_path),
    )
    for error in errors:
        if error.context:
            deepest = best_match(error.context)
            if deepest is not None:
                error = deepest
        formatted = _format_validation_error(error)
        key = (formatted["path"], formatted["message"])
        if key in seen:
            continue
        seen.add(key)
        details.append(formatted)
        if len(details) >= MAX_VALIDATION_ERRORS:
            break
    return details


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    tool_id: str
    ok: bool
    output: Any = None
    error: str | None = None
    error_details: list[dict[str, str]] | None = None

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
        }
        # Only present on failures that have something actionable to say, so
        # successful calls keep their existing shape.
        if self.error_details:
            payload["error_details"] = self.error_details
        return payload


class ToolRuntime(Protocol):
    async def execute(
        self,
        tool_call: dict[str, Any],
        *,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        """Execute one already-normalized tool call."""


@dataclass(frozen=True)
class ToolDefinition:
    tool_id: str
    version: str
    input_schema: dict[str, Any]
    side_effect: str
    handler: ToolHandler
    scope_requirements: tuple[str, ...] = ()
    max_output_budget: int | None = None

    def descriptor(self) -> dict[str, Any]:
        return {
            "tool_id": self.tool_id,
            "version": self.version,
            "input_schema": self.input_schema,
            "side_effect": self.side_effect,
            "scope_requirements": list(self.scope_requirements),
            "max_output_budget": self.max_output_budget,
        }


class ToolRegistry:
    """Explicit allowlist; AgentCore never discovers arbitrary functions."""

    def __init__(self) -> None:
        self._definitions: dict[str, ToolDefinition] = {}

    def register(self, definition: ToolDefinition) -> None:
        if definition.tool_id in self._definitions:
            raise ValueError(f"tool already registered: {definition.tool_id}")
        Draft202012Validator.check_schema(definition.input_schema)
        self._definitions[definition.tool_id] = definition

    def descriptors(self) -> list[dict[str, Any]]:
        return [
            self._definitions[tool_id].descriptor()
            for tool_id in sorted(self._definitions)
        ]

    async def execute(
        self,
        tool_call: dict[str, Any],
        *,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> ToolResult:
        tool_id = str(tool_call.get("tool_id", ""))
        call_id = str(tool_call.get("tool_call_id", ""))
        definition = self._definitions.get(tool_id)
        if definition is None:
            raise UnknownToolError(f"tool is not registered: {tool_id}")
        arguments = tool_call.get("arguments") or {}
        details = validation_details(definition.input_schema, arguments)
        if details:
            return ToolResult(
                tool_call_id=call_id,
                tool_id=tool_id,
                ok=False,
                error="invalid_tool_arguments",
                error_details=details,
            )
        try:
            output = definition.handler(
                arguments,
                ToolContext(session_id=session_id, metadata=dict(metadata or {})),
            )
            if inspect.isawaitable(output):
                output = await output
            if definition.max_output_budget is not None:
                serialized = json.dumps(output, ensure_ascii=False, sort_keys=True)
                if len(serialized) > definition.max_output_budget:
                    return ToolResult(
                        tool_call_id=call_id,
                        tool_id=tool_id,
                        ok=False,
                        error="tool_output_budget_exceeded",
                    )
            return ToolResult(tool_call_id=call_id, tool_id=tool_id, ok=True, output=output)
        except Exception as exc:
            return ToolResult(
                tool_call_id=call_id,
                tool_id=tool_id,
                ok=False,
                error=type(exc).__name__,
            )
