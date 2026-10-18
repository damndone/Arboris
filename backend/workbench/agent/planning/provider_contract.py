"""Closed provider tool schemas for typed Notebook planning."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from ..operations import OperationRegistry


def _provider_workflow_steps_schema() -> dict[str, Any]:
    """Project the executable step list into the provider's closed schema."""

    changes = OperationRegistry().require(
        "operation.multi_step"
    ).proposal_schema["properties"]["changes"]
    return deepcopy(changes["properties"]["steps"])


_INSPECTION_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["inspection_id", "target_ref", "arguments"],
    "properties": {
        "inspection_id": {
            "type": "string",
            "enum": [
                "profile.v1",
                "quality.v1",
                "time_index.v1",
                "sample.v1",
                "forecast_rolling_origin.v1",
            ],
        },
        "target_ref": {"type": "string", "minLength": 1},
        # Inspection-specific arguments are validated again by the registered
        # inspection executor.  The request envelope itself remains closed.
        "arguments": {"type": "object"},
        "why_needed": {"type": "string", "minLength": 1},
    },
}

_TYPED_PROPOSAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "proposal_id",
        "proposal_revision",
        "operation_id",
        "operation_version",
        "target",
        "preconditions",
        "changes",
    ],
    "properties": {
        "proposal_id": {"type": "string", "minLength": 1},
        "proposal_revision": {"type": "integer", "minimum": 1},
        "operation_id": {
            "type": "string",
            "enum": [
                "model.custom",
                "model.genesis",
                "model.rerun",
                "operation.multi_step",
            ],
        },
        "operation_version": {"type": "string", "const": "v1"},
        "target": {"type": "object"},
        "preconditions": {"type": "object"},
        "changes": {
            "type": "object",
            "description": (
                "For model.genesis use only table_params, model_params, and/or "
                "model_options as nested objects. For model.rerun use only the "
                "model_options nested object. For model.custom use only operation, "
                "input_handle, parameters, and consumer_slots. The server injects "
                "capability_ref and binding_ref. For operation.multi_step use only "
                "steps. Never put executable source, "
                "entrypoints, or trust/admission fields here."
            ),
            "properties": {
                "table_params": {"type": "object"},
                "model_params": {"type": "object"},
                "model_options": {"type": "object"},
                "operation": {"type": "string", "minLength": 1},
                "input_handle": {"type": "string", "minLength": 1},
                "parameters": {"type": "object"},
                "consumer_slots": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                },
                "steps": _provider_workflow_steps_schema(),
            },
            "additionalProperties": False,
        },
    },
}

_EXPECTED_ARTIFACT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["artifact_id", "artifact_type", "required", "count", "step"],
    "properties": {
        "artifact_id": {"type": "string", "minLength": 1},
        "artifact_type": {"type": "string", "minLength": 1},
        "required": {"type": "boolean"},
        "count": {"type": "integer", "minimum": 0},
        "step": {"type": ["string", "null"]},
    },
}

_EVIDENCE_REF_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["evidence_id", "result_hash", "source_refs"],
    "properties": {
        "evidence_id": {"type": "string", "minLength": 1},
        "result_hash": {"type": "string", "minLength": 1},
        "source_refs": {"type": "array", "items": {"type": "string", "minLength": 1}},
    },
}

_OPTION_SUBMISSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "rank",
        "rationale",
        "proposal",
        "evidence_refs",
        "comparative_claims",
        "capability_id",
        "option_id",
    ],
    "properties": {
        "rank": {"type": "integer", "minimum": 1, "maximum": 3},
        "rationale": {"type": "string", "minLength": 1},
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "proposal": _TYPED_PROPOSAL_SCHEMA,
        "expected_artifacts": {"type": "array", "items": _EXPECTED_ARTIFACT_SCHEMA},
        "evidence_refs": {"type": "array", "items": _EVIDENCE_REF_SCHEMA},
        "comparative_claims": {"type": "array", "items": {"type": "string", "minLength": 1}},
        "option_id": {"type": "string", "minLength": 1},
        "capability_id": {"type": "string", "minLength": 1},
    },
}


NOTEBOOK_TOOLS: tuple[dict[str, Any], ...] = (
    {
        "tool_id": "request_notebook_inspections",
        "description": (
            "Request registered, bounded evidence inspections. Use only the "
            "inspection_id enum in the schema and never invent an id."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["requests"],
            "properties": {
                "requests": {"type": "array", "maxItems": 5, "items": _INSPECTION_REQUEST_SCHEMA},
            },
        },
    },
    {
        "tool_id": "submit_notebook_option_batch",
        "description": (
            "Submit 1 to 3 typed analysis options. Every option must cite "
            "completed evidence and preserve the server-provided execution pins."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["options"],
            "properties": {
                "options": {"type": "array", "minItems": 1, "maxItems": 3, "items": _OPTION_SUBMISSION_SCHEMA},
            },
        },
    },
    {
        "tool_id": "decline_notebook_plan",
        "description": (
            "Decline to propose an executable plan when the request is ambiguous, "
            "missing required information, asks for unsupported causal inference, "
            "contains unsafe instructions, or has no eligible capability. This is "
            "terminal: do not submit a Draft in the same turn."
        ),
        "input_schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["reason_code", "message"],
            "properties": {
                "reason_code": {
                    "type": "string",
                    "enum": [
                        "ambiguous_request",
                        "missing_required_information",
                        "unsupported_causal_claim",
                        "unsafe_instruction",
                        "no_eligible_capability",
                    ],
                },
                "message": {"type": "string", "minLength": 1, "maxLength": 2000},
            },
        },
    },
)


def _notebook_tools_for(
    max_options: int,
    *,
    include_inspection: bool = True,
) -> tuple[dict[str, Any], ...]:
    """Publish the closed tool vocabulary with a mode-specific batch cap."""

    if max_options not in {1, 2, 3}:
        raise ValueError("Notebook option limit must be between 1 and 3")
    tools_by_id = {tool["tool_id"]: tool for tool in NOTEBOOK_TOOLS}
    inspection_tool = tools_by_id["request_notebook_inspections"]
    submit_tool = tools_by_id["submit_notebook_option_batch"]
    decline_tool = tools_by_id["decline_notebook_plan"]
    options_schema = submit_tool["input_schema"]["properties"]["options"]
    bounded_submit_tool = {
        **submit_tool,
        "description": (
            f"Submit 1 to {max_options} typed analysis option"
            f"{'s' if max_options != 1 else ''}. Every option must cite completed "
            "evidence and preserve the server-provided execution pins."
        ),
        "input_schema": {
            **submit_tool["input_schema"],
            "properties": {
                **submit_tool["input_schema"]["properties"],
                "options": {**options_schema, "maxItems": max_options},
            },
        },
    }
    if not include_inspection:
        return (bounded_submit_tool, dict(decline_tool))
    return (dict(inspection_tool), bounded_submit_tool, dict(decline_tool))
