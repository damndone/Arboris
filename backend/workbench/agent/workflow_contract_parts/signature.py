"""One-line field signatures for composable steps, rendered from the published contract.

The protocol's step index and a step's field refusal both use this text, and both read it from the
view inspect_operation_contract returns, so the prompt cannot teach a field the validator rejects.
In the QRData rounds of 2026-11-02, 13 of 29 refusals were steps whose index line said only
"Required: input_mode, column_bindings, options" and whose fields the Agent then guessed.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

_MAX_DEPTH = 3
_SCALAR_TYPES = frozenset({"string", "number", "integer", "boolean"})


def _value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def schema_text(schema: Any, depth: int = 0) -> str:
    """A JSON Schema written compactly: {name: type, optional?: type}, [items], "a"|"b"."""

    if not isinstance(schema, Mapping):
        return "any"
    if "enum" in schema:
        return "|".join(_value(item) for item in schema["enum"])
    if "const" in schema:
        return _value(schema["const"])
    kind = schema.get("type")
    properties = schema.get("properties")
    if kind == "object" or isinstance(properties, Mapping):
        if not isinstance(properties, Mapping) or not properties or depth >= _MAX_DEPTH:
            return "object"
        required = set(schema.get("required") or ())
        # An optional field keeps its name, its values when they are closed, and its plain scalar type; a nested
        # optional shape is left to the contract, which keeps long option lists short in the prompt. The scalar
        # type was the only thing 7 of round 7's treatment_effects contract lookups added (trim?, seed?).
        return "{" + ", ".join(
            f"{name}: {schema_text(item, depth + 1)}" if name in required
            else f"{name}?: {schema_text(item, depth + 1)}" if isinstance(item, Mapping) and ("enum" in item or "const" in item)
            else f"{name}?: {item['type']}" if isinstance(item, Mapping) and isinstance(item.get("type"), str) and item["type"] in _SCALAR_TYPES
            else f"{name}?" for name, item in properties.items()) + "}"
    if kind == "array":
        low, high = schema.get("minItems"), schema.get("maxItems")
        size = ("" if low is None and high is None else f" ({low})" if low == high
                else f" ({low or 0}-{'n' if high is None else high})")
        return "[" + schema_text(schema.get("items"), depth + 1) + "]" + size
    if isinstance(kind, list):
        return "|".join(map(str, kind))
    return str(kind or "any")


def _field_text(spec: Mapping[str, Any], name: str) -> str | None:
    enum = (spec.get("field_enums") or {}).get(name)
    if enum:
        return "|".join(_value(item) for item in enum)
    schema = (spec.get("field_schemas") or {}).get(name)
    if isinstance(schema, Mapping):
        return schema_text(schema)
    return None


def step_signature(spec: Mapping[str, Any]) -> str | None:
    """The step's fields with their allowed shapes, or None when a required field has no closed shape.

    Free-text fields (formulas, labels) have no shape to show, so such a step keeps its plain index line
    and the Agent reads its contract on demand.
    """

    # input_mode is shown even when it has one value: leaving it to a general note cost 7 refusals
    # ("spec is missing required field(s): input_mode") in the 172d65cd round.
    required = set(spec.get("required") or ())
    parts = []
    for name, declared in (spec.get("field_types") or {}).items():
        shape = _field_text(spec, name)
        if shape is None:
            if name in required:
                return None
            shape = str(declared)
        parts.append(f"{name}{'' if name in required else '?'}: {shape}")
    variants = _branch_text(spec.get("spec_branches"))
    if variants:
        parts.append(variants)
    return "; ".join(parts) if parts else None


def _branch_text(branches: Any) -> str | None:
    """Root variants keyed by one constant field, e.g. ratio -> parameters {numerator, ...}.

    data.feature_recipe published parameters only as "object", and 6 refusals in the 172d65cd round
    were guessed parameter names.
    """

    if not isinstance(branches, (list, tuple)) or not branches:
        return None
    rendered, key = [], None
    for branch in branches:
        properties = branch.get("properties") if isinstance(branch, Mapping) else None
        if not isinstance(properties, Mapping):
            return None
        constant = next(((name, item["const"]) for name, item in properties.items()
                         if isinstance(item, Mapping) and "const" in item), None)
        if constant is None:
            return None
        key = constant[0]
        rest = ", ".join(f"{name}: {schema_text(item)}" for name, item in properties.items() if name != key)
        rendered.append(f"{_value(constant[1])} -> {rest}")
    return f"by {key}: " + "; ".join(rendered)


def published_step_signature(operation_id: str) -> str | None:
    """The signature of one step as inspect_operation_contract publishes it."""

    from ..context_tools_support.node_tools import _step_vocabulary_view
    from .registry import workflow_step_vocabulary

    view = _step_vocabulary_view(workflow_step_vocabulary(), [operation_id])["step_operations"]
    spec = view.get(operation_id)
    return step_signature(spec) if isinstance(spec, Mapping) else None
