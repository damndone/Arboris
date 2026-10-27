"""Allowlisted tool descriptors and provider-neutral tool execution."""

from __future__ import annotations

import inspect
import asyncio
import contextvars
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import best_match

from ..analysis_loop.lifecycle import AnalysisLoopSelectionError

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


#: An unexpected field's error lists the allowed ones when there are this few.
MAX_ALLOWED_PROPERTIES = 24


def _format_validation_error(error) -> dict[str, Any]:
    message = error.message
    if len(message) > MAX_VALIDATION_MESSAGE_CHARS:
        message = message[:MAX_VALIDATION_MESSAGE_CHARS] + "… [truncated]"
    formatted: dict[str, Any] = {
        "path": ".".join(str(part) for part in error.absolute_path) or "<root>",
        "message": message,
        "constraint": str(error.validator),
    }
    if error.validator == "additionalProperties":
        formatted.update(_unexpected_field_help(error))
    return formatted


def _unexpected_field_help(error) -> dict[str, Any]:
    """Name the allowed fields and the likely intended one for each unexpected field.

    In the v1.9.1 smoke the model wrote ``dependencies`` and ``required_steps``
    for ``depends_on`` and had to guess again; the allowed names end the guess.
    """

    import difflib

    allowed = sorted((error.schema.get("properties") or {}) if isinstance(error.schema, dict) else ())
    instance = error.instance if isinstance(error.instance, dict) else {}
    unexpected = [key for key in instance if key not in allowed]
    if not allowed or len(allowed) > MAX_ALLOWED_PROPERTIES:
        return {}
    help_: dict[str, Any] = {"allowed_fields": allowed}
    guesses = {key: match[0] for key in unexpected
               if (match := difflib.get_close_matches(str(key), allowed, n=1, cutoff=0.6))}
    if guesses:
        help_["did_you_mean"] = guesses
    return help_


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
    # Identity selects the error branch even when another constraint (such as
    # operation_version) is invalid. Requiring every const first sent callers
    # to an unrelated target schema and made them add then remove fields.
    constants = [(branch, {key: spec['const'] for key, spec in (branch.get('properties') or {}).items()
                          if isinstance(spec, dict) and 'const' in spec})
                 for branch in branches if isinstance(branch, dict)]
    identities = {key for _, values in constants for key in values
                  if len({json.dumps(values[key], sort_keys=True) for _, values in constants if key in values}) > 1}
    matches = [branch for branch, values in constants
               if any(key in instance and instance[key] == values[key] for key in identities & values.keys())
               and all(key not in instance or instance[key] == values[key] for key in identities & values.keys())]
    if len(matches) == 1:
        return matches[0]
    # Some compatibility unions have no const discriminator. Prefer the one
    # branch that recognizes the most supplied keys; never infer a different
    # operation when a const discriminator exists but does not match.
    has_consts = any("const" in spec for branch in branches if isinstance(branch, dict)
        for spec in (branch.get("properties") or {}).values() if isinstance(spec, dict))
    if not has_consts:
        scored = [(len(set(instance) & set(branch.get("properties") or {})), branch)
                  for branch in branches if isinstance(branch, dict)]
        best = max((score for score,_ in scored), default=0)
        matches = [branch for score,branch in scored if score == best and score > 0]
        if len(matches) == 1:
            return matches[0]
    return None


def _operation_change_example(schema, arguments):
    """Suggest shape only: preserve source/intent and leave opaque options alone."""
    if not isinstance(arguments, dict) or not isinstance(arguments.get("changes"), dict):
        return None
    try:
        encoded = json.dumps(arguments, ensure_ascii=False, allow_nan=False)
        if len(encoded) > 4000:
            return None
        example = json.loads(encoded)
    except (TypeError, ValueError):
        return None
    branch = _discriminated_branch(schema, arguments) or schema
    contract = (branch.get("properties") or {}).get("changes")
    if not isinstance(contract, dict):
        return None
    def reshape(value, declared):
        selected = _discriminated_branch(declared, value) if isinstance(value, dict) else None
        declared = selected or declared
        if (declared.get("type") == "string" and isinstance(value,dict)
                and set(value) == {"old","new"} and isinstance(value["new"],str)):
            return value["new"]
        if isinstance(value,dict):
            fields = declared.get("properties") or {}
            return {key:reshape(item,fields[key]) if key in fields else item for key,item in value.items()}
        return value
    example["changes"] = reshape(example["changes"],contract)
    if example == arguments or not Draft202012Validator(schema).is_valid(example):
        return None
    return example


def _specific_validation_errors(schema, arguments, prefix=()):
    selected = _discriminated_branch(schema, arguments) or schema
    for error in Draft202012Validator(selected).iter_errors(arguments):
        nested = _discriminated_branch(error.schema, error.instance) if error.context else None
        if nested is not None:
            yield from _specific_validation_errors(nested,error.instance,prefix+tuple(error.absolute_path))
        else:
            yield best_match(error.context) if error.context else error, prefix


def validation_details(schema: dict[str, Any], arguments: Any) -> list[dict[str, Any]]:
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
    details: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    errors = sorted(_specific_validation_errors(schema,arguments),
                    key=lambda pair:[str(p) for p in (*pair[1],*pair[0].absolute_path)])
    for error, prefix in errors:
        formatted = _format_validation_error(error)
        formatted["path"] = ".".join(str(p) for p in (*prefix,*error.absolute_path)) or "<root>"
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
    from ..analysis_loop.plan import PlanValidationError
    from ..analysis_loop.resolver import AnalysisLoopSourceResolutionError
    from .operation_definitions import UnknownOperationError

    # PlanValidationError rejects the Agent's own Analysis Loop intent with a code
    # and a message; shown as its class name only, the Agent retried blind twice
    # (free-route round, panel_fe.specific).
    return isinstance(
        exc,
        (
            OperationValidationError,
            OperationContractUnavailableError,
            AnalysisLoopSourceResolutionError,
            PlanValidationError,
            UnknownOperationError,
        ),
    )


def _with_help(message: str) -> str:
    from .contract_help import help_for

    return message + help_for(message)


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


#: Corrections the Workbench made to one tool call (e.g. an ignored identity
#: field), handed back with the result so the model learns the right call.
_TOOL_NOTES: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("workbench_tool_notes", default=None)
#: Node identity arguments a read tool that does not take them can ignore.
_READ_IDENTITY_FIELDS = frozenset({"active_head_run_id", "op_node_id", "owner_run_id"})


def tool_note(text: str) -> None:
    """Record a correction the Workbench made to the current tool call."""
    notes = _TOOL_NOTES.get()
    if notes is not None and text not in notes:
        notes.append(text)


def _wrap_single_strings(definition: "ToolDefinition", arguments: dict[str, Any]) -> dict[str, Any]:
    """A string given where the schema wants a list of strings means that one-item list.

    A weaker model sent playbooks 'iv' for ['iv'] and lost a turn to the refusal (free-route
    no-thinking round, iv_weak). Only top-level and nested object fields are wrapped, never
    inside a oneOf/anyOf branch, and only when the list's items are strings.
    """
    from copy import deepcopy

    wrapped, paths = None, []
    for error in Draft202012Validator(definition.input_schema).iter_errors(arguments):
        items = error.schema.get("items") if isinstance(error.schema, dict) else None
        if (error.validator == "type" and error.validator_value == "array" and isinstance(error.instance, str)
                and isinstance(items, dict) and items.get("type") == "string"
                and not any(part in {"oneOf", "anyOf"} for part in error.schema_path)):
            wrapped = wrapped if wrapped is not None else deepcopy(arguments)
            target = wrapped
            path = list(error.absolute_path)
            for key in path[:-1]:
                target = target[key]
            if path:
                target[path[-1]] = [error.instance]
                paths.append(".".join(map(str, path)))
    if wrapped is None:
        return arguments
    tool_note(f"{', '.join(paths)} takes a list; the single value was used as a one-item list.")
    return wrapped


_MARKER = re.compile(r"</?(?:tool_sep|arg_key|arg_value)(?::[^>]*)?>")
_LEAKED_VALUE = re.compile(r"<arg_value(?::[^>]*)?>(.*?)</arg_value(?::[^>]*)?>", re.S)


def _split_leaked_markers(arguments: dict[str, Any]) -> dict[str, Any]:
    """Arguments a model wrote in its own tool-call markup, split back into fields.

    Hy3 (free-route Auto iv_weak, 2026-10-23) sent update_plan one key
    ``completion<tool_sep:ID><arg_value:ID>{...}</arg_value:ID><arg_key:ID>completion_evidence``
    holding the completion_evidence value, and lost the step to the refusal. A key
    is split only when it parses completely into as many names as values and no
    name is already present; anything else is left for validation to refuse.
    """

    def decoded(text: Any) -> Any:
        if not isinstance(text, str):
            return text
        try:
            value = json.loads(text)
        except ValueError:
            return text.strip()
        return value if isinstance(value, (dict, list)) else text.strip()

    repaired, split = dict(arguments), []
    for key, last in arguments.items():
        if not isinstance(key, str) or not _MARKER.search(key):
            continue
        values = _LEAKED_VALUE.findall(key)
        names = [part.strip() for part in _MARKER.split(_LEAKED_VALUE.sub("", key)) if part.strip()]
        if (len(names) != len(values) + 1 or not all(name.isidentifier() for name in names)
                or len(set(names)) != len(names) or any(name in repaired for name in names)):
            continue
        del repaired[key]
        repaired.update({name: decoded(value) for name, value in zip(names, [*values, last])})
        split.extend(names)
    if split:
        tool_note("arguments " + ", ".join(split) + " arrived inside tool-call markup in one field name; split into "
                  "separate fields. Send each argument as its own JSON field.")
    return repaired


def _drop_unused_read_identity(definition: "ToolDefinition", arguments: dict[str, Any]) -> dict[str, Any]:
    schema = definition.input_schema
    if definition.side_effect != "none" or schema.get("additionalProperties") is not False:
        return arguments
    unused = sorted(set(arguments) & _READ_IDENTITY_FIELDS - set(schema.get("properties") or {}))
    if not unused:
        return arguments
    tool_note(f"{definition.tool_id} takes no {', '.join(unused)}; ignored.")
    return {key: value for key, value in arguments.items() if key not in unused}


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
    #: Optional deterministic correction of the arguments before validation;
    #: it reports what it changed through tool_note.
    normalize: Callable[[dict[str, Any]], dict[str, Any]] | None = None

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

    def parallel_read_batch(self, calls):
        names = [str(call.get("tool_id", "")) for call in calls]
        return (len(names) > 1 and len(names) == len(set(names))
            and all(name in self._definitions and self._definitions[name].side_effect == "none" for name in names))

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
        notes: list[str] = []
        notes_token = _TOOL_NOTES.set(notes)
        try:
            return self._with_notes(await self._execute_defined(definition, tool_call, session_id=session_id,
                                                                  metadata=metadata), notes)
        finally:
            _TOOL_NOTES.reset(notes_token)

    @staticmethod
    def _with_notes(result: "ToolResult", notes: list[str]) -> "ToolResult":
        if not notes or not result.ok or not isinstance(result.output, dict):
            return result
        return ToolResult(tool_call_id=result.tool_call_id, tool_id=result.tool_id, ok=True,
                          output={**result.output, "workbench_notes": list(notes)})

    async def _execute_defined(self, definition, tool_call, *, session_id, metadata):
        tool_id = str(tool_call.get("tool_id", ""))
        call_id = str(tool_call.get("tool_call_id", ""))
        arguments = tool_call.get("arguments") or {}
        if isinstance(arguments, dict):
            arguments = _split_leaked_markers(arguments)
        arguments = _drop_unused_read_identity(definition, arguments)
        if definition.normalize is not None and isinstance(arguments, dict):
            arguments = definition.normalize(arguments)
        if isinstance(arguments, dict):
            arguments = _wrap_single_strings(definition, arguments)
        details = validation_details(definition.input_schema, arguments)
        if details:
            example = _operation_change_example(definition.input_schema, arguments)
            if example is not None:
                details[0] = {**details[0], "example_arguments": example,
                    "example_scope": "Schema-only format suggestion; not executed. Normal source, method preflight and approval still apply."}
            return ToolResult(
                tool_call_id=call_id,
                tool_id=tool_id,
                ok=False,
                error="invalid_tool_arguments",
                error_details=details,
            )
        try:
            context = ToolContext(session_id=session_id, metadata=dict(metadata or {}))
            if definition.side_effect == "none" and not inspect.iscoroutinefunction(definition.handler):
                output = await asyncio.to_thread(definition.handler, arguments, context)
            else:
                output = definition.handler(arguments, context)
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
        except AnalysisLoopSelectionError as exc:
            # Recovery contains source identities and a read-only next call, never
            # an authorized substitute. It has the same bound as other tool data.
            budget = 8000 if definition.max_output_budget is None else min(8000, definition.max_output_budget)
            output = _bounded_tool_output({"status": "needs_target_decision", "executed": False,
                "code": exc.code, "recovery": exc.details["recovery"]}, budget)
            return ToolResult(tool_call_id=call_id, tool_id=tool_id, ok=False, output=output,
                error=exc.code, error_details=[{"message": str(exc)[:MAX_VALIDATION_MESSAGE_CHARS]}])
        except ToolVisibleError as exc:
            return ToolResult(
                tool_call_id=call_id,
                tool_id=tool_id,
                ok=False,
                error=type(exc).__name__,
                error_details=[{"message": _with_help(str(exc))}],
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
                    [{"message": _with_help(str(exc))}] if _is_agent_input_fault(exc) else None
                ),
            )
