"""Allowlisted tool descriptors and provider-neutral tool execution."""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

# Bounds for the validation feedback handed back to the model. Messages embed
# the offending value, which is the model's own argument — echoing it back is
# not a leak, but an unbounded blob would be.
MAX_VALIDATION_ERRORS = 5
MAX_VALIDATION_MESSAGE_CHARS = 240


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True))


def _project_value(value: Any, budget: int) -> Any:
    """Recursively keep a useful prefix of an oversized JSON value."""

    if _json_size(value) <= budget:
        return value
    if isinstance(value, Mapping):
        projected: dict[str, Any] = {}
        for key, item in value.items():
            candidate = dict(projected)
            candidate[str(key)] = _project_value(item, max(budget // 2, 64))
            if _json_size(candidate) <= budget:
                projected[str(key)] = candidate[str(key)]
        return projected
    if isinstance(value, list):
        projected: list[Any] = []
        for item in value:
            candidate = [*projected, _project_value(item, max(budget // 2, 64))]
            if _json_size(candidate) > budget:
                break
            projected.append(candidate[-1])
        return projected
    if isinstance(value, str):
        marker = "… [truncated]"
        return value[: max(0, budget - len(json.dumps(marker, ensure_ascii=False))) - 2] + marker
    return value


def _bounded_tool_output(value: Any, budget: int) -> Any:
    """Return partial evidence instead of discarding an oversized tool result."""

    if _json_size(value) <= budget:
        return value
    if not isinstance(value, Mapping):
        return _project_value(value, budget)

    # Keep identifiers and lifecycle facts first; large tables/previews are
    # omitted as named sections so the Agent can request a narrower inspection.
    priority = (
        "request_id",
        "tool_id",
        "op_type",
        "model_type",
        "node",
        "canonical",
        "lineage",
        "result_summary",
        "time_series_summary",
    )
    projected: dict[str, Any] = {"status": "partial", "omitted_sections": []}
    omitted: list[str] = []
    keys = [key for key in priority if key in value]
    keys.extend(key for key in value if key not in keys and key not in {"status", "omitted_sections"})
    for key in keys:
        candidate_value = _project_value(value[key], max(budget // 2, 64))
        candidate = dict(projected)
        candidate[str(key)] = candidate_value
        if _json_size(candidate) <= budget:
            projected[str(key)] = candidate_value
        else:
            omitted.append(str(key))
    projected["omitted_sections"] = omitted
    if _json_size(projected) > budget:
        # The normal tool budgets are large enough for this envelope. Keep a
        # deterministic last-resort response for unusually small test budgets.
        projected = {"status": "partial", "omitted_sections": omitted}
    return projected


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


def _is_agent_input_fault(exc: BaseException) -> bool:
    """Whether the model must read this message to make progress.

    Deliberately narrow: only refusals of agent-supplied input qualify.
    Internal faults keep surfacing a bare class name so no server detail
    reaches the provider.
    """

    from .context_tools import OperationContractUnavailableError
    from .operations import OperationValidationError
    from ..analysis_loop.resolver import AnalysisLoopSourceResolutionError

    return isinstance(
        exc,
        (
            OperationValidationError,
            OperationContractUnavailableError,
            AnalysisLoopSourceResolutionError,
        ),
    )


class ToolVisibleError(ValueError):
    """An error whose message is written for the model, not for a log.

    A tool failure normally surfaces only its exception class name, which is
    right for internal faults: a model can do nothing with a stack detail and
    should not see one. But a *refusal* — "this patch is illegal, here is the
    code" — is useless unless the model reads it. A live DeepSeek turn proved
    the cost: the pack refused an auto-mode patch with a specific code, the
    model received the bare string "ValueError", and it burned its remaining
    steps guessing before the turn died. Raise this when the message is the
    actionable part.
    """


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
                    output = _bounded_tool_output(output, definition.max_output_budget)
                    serialized = json.dumps(output, ensure_ascii=False, sort_keys=True)
                    if len(serialized) > definition.max_output_budget:
                        return ToolResult(
                            tool_call_id=call_id,
                            tool_id=tool_id,
                            ok=False,
                            error="tool_output_budget_exceeded",
                            error_details=[
                                {
                                    "message": "tool output could not be projected within the declared budget"
                                }
                            ],
                        )
            return ToolResult(tool_call_id=call_id, tool_id=tool_id, ok=True, output=output)
        except ToolVisibleError as exc:
            return ToolResult(
                tool_call_id=call_id,
                tool_id=tool_id,
                ok=False,
                error=type(exc).__name__,
                error_details=[{"message": str(exc)}],
            )
        except Exception as exc:
            # A refusal of the AGENT'S OWN submission is useless without its
            # reason: surfacing only the class name leaves the model nothing to
            # correct, so it re-submits the same broken payload until the step
            # budget is gone. That exact loop was observed on a live turn.
            return ToolResult(
                tool_call_id=call_id,
                tool_id=tool_id,
                ok=False,
                error=type(exc).__name__,
                error_details=(
                    [{"message": str(exc)}] if _is_agent_input_fault(exc) else None
                ),
            )
