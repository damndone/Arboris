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


_STRING_MARKER = "… [truncated]"


def _truncation_note(original: Any, projected: Any) -> str:
    if isinstance(original, list) and isinstance(projected, list):
        return f"kept {len(projected)} of {len(original)}"
    return "shortened"


def _is_empty_projection(value: Any) -> bool:
    if isinstance(value, (Mapping, list)):
        return not value
    return isinstance(value, str) and value in {"", _STRING_MARKER}


def _fit_entries(
    entries: list[tuple[str, Any]],
    budget: int,
    *,
    omitted_key: str,
    truncated_key: str,
    fixed: Mapping[str, Any] | None = None,
    already_omitted: list[str] | None = None,
) -> dict[str, Any]:
    """Fit named sections into ``budget``, naming every section that was cut.

    Sections small enough for an equal share are kept whole first, so a large
    early section cannot crowd out a status flag after it. The remaining room
    then goes to the large sections in order, each taking what is left: the
    caller's order is its priority. A section that does not fit whole is
    shortened or omitted, and the result says which, so the reader never takes
    a cut section for an absent one.
    """

    order = [key for key, _ in entries]
    share = budget // max(len(entries), 1)
    kept: dict[str, Any] = {key: item for key, item in entries if _json_size({key: item}) <= share}
    large = [(key, item) for key, item in entries if key not in kept]
    # Every large section starts as omitted, so the room its name needs in the
    # marker is reserved before any section is allowed to use it.
    omitted = [key for key, _ in large]
    truncated: dict[str, str] = {}

    def assemble() -> dict[str, Any]:
        out: dict[str, Any] = dict(fixed or {})
        out.update((key, kept[key]) for key in order if key in kept)
        names = [*(already_omitted or []), *omitted]
        if names or omitted_key in (fixed or {}):
            out[omitted_key] = names
        if truncated:
            out[truncated_key] = dict(truncated)
        return out

    for key, item in large:
        omitted.remove(key)
        whole_room = budget - _json_size(assemble()) - len(json.dumps(key, ensure_ascii=False)) - 2
        if _json_size(item) <= whole_room:
            kept[key] = item
            continue
        # Leave room for this section's own entry in the truncation marker.
        note_room = len(json.dumps({key: "kept 99999 of 99999"}, ensure_ascii=False)) + len(truncated_key) + 6
        room = whole_room - note_room
        projected = _project_value(item, room) if room > 16 else None
        if projected is None or _is_empty_projection(projected):
            omitted.append(key)
            continue
        kept[key] = projected
        truncated[key] = _truncation_note(item, projected)

    result = assemble()
    # The reservations above are estimates; drop sections from the end until
    # the envelope fits, recording each one.
    for key in reversed(order):
        if _json_size(result) <= budget:
            break
        if key in kept:
            del kept[key]
            truncated.pop(key, None)
            omitted.append(key)
            result = assemble()
    return result


def _project_value(value: Any, budget: int) -> Any:
    """Recursively keep a useful prefix of an oversized JSON value.

    A mapping that loses keys or shortens values names them under
    ``_omitted_keys`` and ``_truncated_keys``; a shortened list keeps a prefix
    and its parent says how many items were kept.
    """

    if _json_size(value) <= budget:
        return value
    if isinstance(value, Mapping):
        return _fit_entries(
            [(str(key), item) for key, item in value.items()],
            budget,
            omitted_key="_omitted_keys",
            truncated_key="_truncated_keys",
        )
    if isinstance(value, list):
        projected: list[Any] = []
        for item in value:
            room = budget - _json_size(projected) - 2
            if room <= 2:
                break
            candidate = _project_value(item, room)
            if _json_size([*projected, candidate]) > budget:
                break
            # Rows are kept whole; only a list whose first row is already too
            # large shows a shortened one, so the reader sees its shape.
            if projected and candidate is not item:
                break
            projected.append(candidate)
        return projected
    if isinstance(value, str):
        return value[: max(0, budget - len(json.dumps(_STRING_MARKER, ensure_ascii=False))) - 2] + _STRING_MARKER
    return value


def _bounded_tool_output(value: Any, budget: int) -> Any:
    """Return partial evidence instead of discarding an oversized tool result."""

    if _json_size(value) <= budget:
        return value
    if not isinstance(value, Mapping):
        return _project_value(value, budget)

    # Keep identifiers and lifecycle facts first; large tables/previews are
    # omitted or shortened as named sections so the Agent can request a
    # narrower inspection.
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
    keys = [key for key in priority if key in value]
    keys.extend(key for key in value if key not in keys and key not in {"status", "omitted_sections"})
    # Sections the tool itself left out stay listed after the budget cut.
    declared = value.get("omitted_sections")
    already_omitted = [str(item) for item in declared] if isinstance(declared, list) else []
    projected = _fit_entries(
        [(str(key), value[key]) for key in keys],
        budget,
        omitted_key="omitted_sections",
        truncated_key="truncated_sections",
        fixed={"status": "partial", "omitted_sections": []},
        already_omitted=already_omitted,
    )
    if _json_size(projected) > budget:
        # The normal tool budgets are large enough for this envelope. Keep a
        # deterministic last-resort response for unusually small test budgets.
        projected = {"status": "partial", "omitted_sections": [*already_omitted, *map(str, keys)]}
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
    from ..contracts.common.errors import OperationValidationError
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
    description: str = ""

    def descriptor(self) -> dict[str, Any]:
        descriptor: dict[str, Any] = {
            "tool_id": self.tool_id,
            "version": self.version,
            "input_schema": self.input_schema,
            "side_effect": self.side_effect,
            "scope_requirements": list(self.scope_requirements),
            "max_output_budget": self.max_output_budget,
        }
        if self.description:
            # The model selects tools from this descriptor alone, so evidence a
            # tool carries has to be stated here or it is unreachable in practice.
            descriptor["description"] = self.description
        return descriptor


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
            # A misspelled model-emitted tool is a rejected request, not an
            # internal runtime fault. Preserve the allowlist boundary, but give
            # the model bounded feedback so it can correct itself next round.
            # Treating this as an exception causes AgentCore to terminate the
            # whole turn as `tool_runtime_error`, even though no tool ran.
            available = sorted(self._definitions)
            visible = ", ".join(available[:24]) or "(none)"
            suffix = ", …" if len(available) > 24 else ""
            requested = tool_id[:200]
            return ToolResult(
                tool_call_id=call_id,
                tool_id=tool_id,
                ok=False,
                error="unknown_tool",
                error_details=[
                    {
                        "message": (
                            f"tool is not registered: {requested}. "
                            f"Use one of the registered tools: {visible}{suffix}"
                        )
                    }
                ],
            )
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
