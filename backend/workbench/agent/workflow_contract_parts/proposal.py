"""Outer proposal and authorization contract for composed workflows."""
from __future__ import annotations

from typing import Any

from ...contracts.common.errors import OperationValidationError
from .contracts import WORKFLOW_OPERATION_ID, WORKFLOW_OPERATION_VERSION
from .registry import workflow_step_operations
from .graph import validate_workflow_steps

def workflow_authorization(
    *,
    workflow_id: str,
    confirmation_id: str,
    step_id: str,
    plan_fingerprint: str,
) -> dict[str, str]:
    values = {
        "workflow_id": workflow_id,
        "workflow_confirmation_id": confirmation_id,
        "workflow_step_id": step_id,
        "workflow_plan_fingerprint": plan_fingerprint,
    }
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("workflow authorization values must be non-empty strings")
    return {
        **values,
        "confirmation_mode": "single_workflow_confirmation",
    }


def workflow_proposal_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "operation_id",
            "target",
            "preconditions",
            "changes",
            "evidence_refs",
            "expected_effect",
            "risks",
        ],
        "properties": {
            "operation_id": {"const": WORKFLOW_OPERATION_ID},
            "operation_version": {"const": WORKFLOW_OPERATION_VERSION},
            "target": {
                "type": "object",
                "required": ["run_id", "node_ref", "artifact_id"],
                "properties": {
                    "run_id": {"type": "string", "minLength": 1},
                    "node_ref": {"type": "string", "minLength": 1},
                    "artifact_id": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            "preconditions": {
                "type": "object",
                "required": [
                    "context_version",
                    "context_fingerprint",
                    "active_head_run_id",
                    "owner_resolution",
                ],
                "properties": {
                    "context_version": {"type": "string", "minLength": 1},
                    "context_fingerprint": {"type": "string", "minLength": 1},
                    "active_head_run_id": {"type": "string", "minLength": 1},
                    "owner_resolution": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            # An Agent-composed step list is the only accepted form. A named
            # preset used to be a second one, and its bindings were one
            # assignment's variables (a "poverty_column", a fixed year set)
            # frozen into the server. Removing it removes the only place where
            # a specific exercise could be privileged over any other.
            "changes": {
                "type": "object",
                "required": ["steps"],
                "properties": {
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["step_id", "operation_id", "spec"],
                            "properties": {
                                "step_id": {"type": "string", "minLength": 1},
                                "operation_id": {
                                    "type": "string",
                                    # The registry contains set-derived P7
                                    # declarations. Publish stable order across
                                    # interpreter restarts without changing IDs.
                                    "enum": sorted(workflow_step_operations()),
                                },
                                "spec": {"type": "object"},
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "string", "minLength": 1},
                                },
                                "expected_artifacts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "expected_effect": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }


def validate_workflow_operation(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    missing_target = {key for key in ("run_id", "node_ref", "artifact_id") if not target.get(key)}
    if missing_target:
        raise OperationValidationError(
            "operation.multi_step target missing: " + ", ".join(sorted(missing_target))
        )
    missing_preconditions = {
        key
        for key in (
            "context_version",
            "context_fingerprint",
            "active_head_run_id",
            "owner_resolution",
        )
        if not preconditions.get(key)
    }
    if missing_preconditions:
        raise OperationValidationError(
            "operation.multi_step preconditions missing: "
            + ", ".join(sorted(missing_preconditions))
        )
    if "steps" not in changes:
        raise OperationValidationError(
            "operation.multi_step changes must contain a steps list"
        )
    unknown = set(changes) - {"steps", "workflow_template"}
    if unknown:
        raise OperationValidationError(
            "operation.multi_step changes contain unknown field(s): "
            + ", ".join(sorted(unknown))
        )
    validate_workflow_steps(changes["steps"])
