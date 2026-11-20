"""Publish chain tools from explicit handlers without owning execution state."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any

from .tools import ToolDefinition, ToolHandler, ToolRegistry
from .completion import AGENT_CONTRACT_SCHEMA, EVIDENCE_SCHEMA, INSPECT_SCHEMA
from .operation_request_refs import wire_schema


_PROPOSAL_REF_SCHEMA = {"type": "object", "required": ["proposal_id", "revision", "fingerprint"],
    "properties": {"proposal_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,200}$"},
                   "revision": {"type": "integer", "minimum": 1},
                   "fingerprint": {"type": "string", "pattern": "^[0-9a-f]{64}$"}},
    "additionalProperties": False}


def _run_schema(operation_schema):
    schema = wire_schema(operation_schema)
    prepare = {"type": "boolean", "const": True}
    schema["properties"].update(prepare_only=prepare, proposal_ref=_PROPOSAL_REF_SCHEMA)
    for branch in schema["oneOf"]:
        properties = branch["properties"]
        if properties.get("operation_id", {}).get("const") == "operation.multi_step":
            properties["prepare_only"] = prepare
    schema["oneOf"].append({"type": "object", "required": ["proposal_ref"],
        "properties": {"proposal_ref": _PROPOSAL_REF_SCHEMA}, "additionalProperties": False})
    return schema


def _model_run_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The run_operation declaration the model sees: only the operations it can call.

    The envelope's operation_id enum names the operations enabled for natural language; the
    declaration also carried a full branch for every other typed operation (seven data.* ones on
    2026-11-13), which no call could select: half of the 38 KB sent with every request.
    Arguments are still validated against the complete declaration.
    """

    allowed = schema.get("properties", {}).get("operation_id", {}).get("enum")
    if not isinstance(allowed, list):
        return schema

    def callable_branch(branch):
        operation = branch.get("properties", {}).get("operation_id", {}).get("const")
        return operation is None or operation in allowed

    return {**schema, "oneOf": [branch for branch in schema["oneOf"] if callable_branch(branch)]}


_UPDATE_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    # A first plan needs its question and steps (the server refuses one without them);
    # later updates may leave question, criteria and steps out to keep them.
    "properties": {
        "question": {"type": "string"},
        "completion": AGENT_CONTRACT_SCHEMA,
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
                    "operation_ids": {"type": "array", "items": {"type": "string"},
                        "description": "For a composed workflow, list the operation IDs inside changes.steps."},
                    "depends_on": {"type": "array", "items": {"type": "string"}},
                    "expected_outputs": {"type": "array", "items": {"type": "string"}},
                    "proposal_ref": {"oneOf": [_PROPOSAL_REF_SCHEMA, {"type": "null"}]},
                    "status": {"type": "string", "enum": ["pending", "running", "awaiting", "done", "skipped", "failed"]},
                },
                "additionalProperties": False,
            },
        },
        "budget": {"type": "object", "properties": {"steps": {"type": "integer"}, "wall_s": {"type": "integer"},
                                                     "inferential": {"type": "integer"}}, "additionalProperties": False},
        "allowed_classes": {"type": "array", "items": {"type": "string", "enum": ["analyze", "derive", "modify"]},
                            "description": "Omit while drafting an Auto plan. Workbench derives the approval classes "
                                           "from the concrete operations. Omit on progress updates to keep them."},
    },
    "additionalProperties": False,
}


def plan_tool_view(plan: dict[str, Any]) -> dict[str, Any]:
    """Keep editable steps copyable without losing their server-owned audit evidence.

    The NVIDIA open.r3 recording copied returned steps into update_plan and was
    refused for added_after_results/permission_class. Input validation remains
    strict; this output view separates those fields from the writable steps.
    """
    writable = _UPDATE_PLAN_SCHEMA["properties"]["steps"]["items"]["properties"]
    return {**plan,
            "steps": [{key: value for key, value in step.items() if key in writable}
                      for step in plan["steps"]],
            "step_state": {step["step_id"]: {key: value for key, value in step.items() if key not in writable}
                           for step in plan["steps"]}}


def _question_scope_has_no_playbooks(arguments: dict[str, Any]) -> dict[str, Any]:
    """A question-scope plan may only have an empty playbook list, so leaving it out says the same (24 refusals)."""
    from .tools import tool_note

    completion = arguments.get("completion")
    if not isinstance(completion, dict) or completion.get("scope") != "question" or "playbooks" in completion:
        return arguments
    tool_note("completion.playbooks is empty for a question-scope plan; filled in.")
    return {**arguments, "completion": {**completion, "playbooks": []}}


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

    def normalize_operation(arguments: dict[str, Any]) -> dict[str, Any]:
        prepare = arguments.get("prepare_only")
        if (arguments.get("operation_id") == "operation.multi_step"
                and isinstance(prepare, str) and prepare.lower() == "true"):
            # Treat the observed wire spelling as preparation only. A false
            # or ambiguous value must never turn preparation into execution.
            arguments = {**arguments, "prepare_only": True}
        return normalize_target(arguments) if normalize_target is not None else arguments

    registry.register(
        ToolDefinition(
            tool_id="update_plan",
            version="v1",
            input_schema=_UPDATE_PLAN_SCHEMA,
            side_effect="proposal",
            scope_requirements=("chain",),
            handler=update_plan,
            normalize=_question_scope_has_no_playbooks,
            description=(
                "Write or revise the analysis plan: the research question, the judgement criteria fixed "
                "before any result is seen, and typed steps (workflow operation ids, dependencies, expected "
                "outputs, statuses). In Auto mode the person approves it once and planned steps then run "
                "without a card. For full analysis, bind textual promises in completion.requirements to exact "
                "registered step specifications; attach original producer records and artifact refs in "
                "completion_evidence.requirements. To check an exact step before approval, first call "
                "run_operation with prepare_only and put its proposal_ref on the step. Omit unchanged references. "
                "Future inputs and unsupported checks stay deferred."
            ),
        )
    )

    registry.register(ToolDefinition(
        tool_id="run_operation", version="v1", input_schema=(run_schema := _run_schema(proposal_tool_schema())),
        model_schema=_model_run_schema(run_schema), max_output_budget=24_000,
        side_effect="proposal", scope_requirements=("chain",), handler=run_operation, normalize=normalize_operation,
        description=(
            "Run one typed operation under the current permissions, or return its reviewable proposal. "
            "Required top-level fields: operation_id, target, preconditions, changes, evidence_refs, "
            "expected_effect, risks. changes must be a JSON object, never a JSON-encoded string. "
            "Put operation inputs inside changes; keep evidence_refs, expected_effect "
            "and risks alongside changes, never inside it. A step's own fields (step_id, operation_id, spec, "
            "depends_on, expected_artifacts) go on that step in changes.steps, never on changes itself. "
            "evidence_refs names inspected source evidence; "
            "use the bound target and preconditions, and never invent references."
            " For plan preflight, add prepare_only: true to a workflow request. This only prepares its exact "
            "proposal_ref. Bind the ref with update_plan and later submit only proposal_ref to run the "
            "same revision under normal permissions."
            " Alternatively submit only request_ref from inspect_analysis_completion's operation_requests; "
            "a reference needs the usual execution permission. For the planned delivery report, use its "
            "request_ref after fitting the needed models so the report includes the verified results. "
            "If delivery_check.status is requirements_met, answer from the registered evidence and report."
        )
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
        description="Recheck the plan's delivery scope and target: a focused question needs its source-bound computed "
                    "answer; a full analysis still needs fitted models, computed diagnostics, "
                    "distinct sensitivity fits and a source-bound report. Missing evidence means partial; "
                    "requirements met does not certify scientific validity. Optionally pass a source artifact reference "
                    "to discover its verified dataset sha256 before declaring the plan. Read-only; no model call."
                    " When operation_requests contains a server-bound request_ref, choose the recommendation "
                    "that answers the question and pass only that request_ref to run_operation."
    ))
    return registry
