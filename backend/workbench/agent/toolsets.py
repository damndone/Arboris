"""Publish chain tools from explicit handlers without owning execution state."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .tools import ToolDefinition, ToolHandler, ToolRegistry
from .completion import CONTRACT_SCHEMA, EVIDENCE_SCHEMA, INSPECT_SCHEMA


_UPDATE_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    # The question is required for a first plan (the server refuses a plan
    # without one); later updates may leave question and criteria out to keep them.
    "required": ["steps"],
    "properties": {
        "question": {"type": "string"},
        "completion": CONTRACT_SCHEMA,
        "completion_evidence": EVIDENCE_SCHEMA,
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
    inspect_analysis_completion: ToolHandler,
    normalize_target: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
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
        side_effect="proposal", scope_requirements=("chain",), handler=run_operation, normalize=normalize_target,
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
    registry.register(ToolDefinition(
        tool_id="inspect_analysis_completion", version="v1", side_effect="none", scope_requirements=("chain",),
        max_output_budget=12_000,
        input_schema=INSPECT_SCHEMA,
        handler=inspect_analysis_completion,
        description="Recheck the current plan against registered source, fitted models, computed diagnostics, "
                    "distinct sensitivity fits and a source-bound report. Missing evidence means partial; "
                    "requirements met does not certify scientific validity. Optionally pass a source artifact reference "
                    "to discover its verified dataset sha256 before declaring the plan. Read-only; no model call."
    ))
    return registry
