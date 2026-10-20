"""Publish chain tools from explicit handlers without owning execution state."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .tools import ToolDefinition, ToolHandler, ToolRegistry


_UPDATE_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["question", "steps"],
    "properties": {
        "question": {"type": "string"},
        "criteria": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 40,
            "items": {
                "type": "object",
                "required": ["step_id", "title", "operation_ids"],
                "properties": {
                    "step_id": {"type": "string"},
                    "title": {"type": "string"},
                    "operation_ids": {"type": "array", "items": {"type": "string"}},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "expected_outputs": {"type": "array", "items": {"type": "string"}},
                    "status": {"type": "string", "enum": ["pending", "running", "awaiting", "done", "skipped", "failed"]},
                },
                "additionalProperties": False,
            },
        },
        "budget": {"type": "object", "properties": {"steps": {"type": "integer"}, "wall_s": {"type": "integer"},
                                                     "inferential": {"type": "integer"}}, "additionalProperties": False},
        "allowed_classes": {"type": "array", "items": {"type": "string", "enum": ["analyze", "derive", "modify"]}},
    },
    "additionalProperties": False,
}


def build_chain_tool_registry(
    *,
    context_tools: Iterable[ToolDefinition],
    proposal_tool_schema: Callable[[], dict[str, Any]],
    update_plan: ToolHandler,
    run_operation: ToolHandler,
    plan_analysis: ToolHandler,
) -> ToolRegistry:
    """Keep context reads first, followed by scoped planning and operation tools.

    Handlers retain their caller-owned session and authority checks. Publishing
    the allowlist neither calls those handlers nor creates an operation.
    """

    registry = ToolRegistry()
    for definition in context_tools:
        registry.register(definition)

    registry.register(
        ToolDefinition(
            tool_id="update_plan",
            version="v1",
            input_schema=_UPDATE_PLAN_SCHEMA,
            side_effect="proposal",
            scope_requirements=("chain",),
            handler=update_plan,
            description=(
                "Write or revise the analysis plan: the research question, the judgement criteria fixed "
                "before any result is seen, and typed steps (workflow operation ids, dependencies, expected "
                "outputs, statuses). In Auto mode the person approves it once and planned steps then run "
                "without a card."
            ),
        )
    )

    registry.register(ToolDefinition(
        tool_id="run_operation", version="v1", input_schema=proposal_tool_schema(), max_output_budget=24_000,
        side_effect="proposal", scope_requirements=("chain",), handler=run_operation,
        description="Run one typed operation under the current permissions, or return its reviewable proposal."
    ))
    registry.register(ToolDefinition(
        tool_id="plan_analysis", version="v1", side_effect="proposal", scope_requirements=("chain",),
        max_output_budget=24_000,
        input_schema={"type":"object", "required":["notebook_id", "question"], "properties":{
            "notebook_id":{"type":"string", "minLength":1, "maxLength":200},
            "question":{"type":"string", "minLength":1, "maxLength":4000}}, "additionalProperties":False},
        handler=plan_analysis,
        description="Plan a source-bound Notebook analysis on this same Agent turn and budget; return ordinary proposal cards."
    ))
    return registry
