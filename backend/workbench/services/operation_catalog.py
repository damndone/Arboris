"""Read-only projection of the same declarations used by Agent execution.

Discovery never asserts that an arbitrary, unvalidated spec is executable.
The execution service must recheck source ownership, freshness and admission.
"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

from ..agent.capability_contract import capability_inventory
from ..agent.operations import OperationRegistry
from ..agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS
from .operation_presentation import present


def _field_hints(schema: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    hints = {}
    required = schema.get("required", [])
    for name, field in schema.get("properties", {}).items():
        kind = field.get("type")
        if isinstance(kind, list):
            kind = next((value for value in kind if value != "null"), None)
        control = "select" if "enum" in field else {
            "number": "number", "integer": "number", "boolean": "checkbox",
            "array": "list", "object": "object",
        }.get(kind, "text")
        hints[name] = {"control": control, "required": name in required}
    return hints


def _target_availability(
    project_root: str | None,
    source_run_id: str | None,
    source_node_id: str | None,
    source_artifact_id: str | None,
) -> dict[str, str]:
    target = (project_root, source_run_id, source_node_id, source_artifact_id)
    if not all(target):
        return {"status": "needs_target", "reason_code": "TARGET_REQUIRED",
                "message": "Select a project, dataset run, dataset node and its artifact."}
    from ..statistical_exploration import resolve_statistical_source

    try:
        resolve_statistical_source(
            Path(str(project_root)), source_run_id=str(source_run_id),
            source_node_id=str(source_node_id), source_artifact_id=str(source_artifact_id),
        )
    except (OSError, ValueError, KeyError) as exc:
        return {"status": "unavailable", "reason_code": "TARGET_INVALID", "message": str(exc)}
    return {"status": "needs_parameters", "reason_code": "SPEC_VALIDATION_REQUIRED",
            "message": "Source ownership is verified; supply parameters for operation-specific validation and confirmation."}


def _selected_target(project_root: str | None, target: Mapping[str, Any]):
    """Validate the same target as execution without materializing uploads."""
    if not project_root:
        return {"status": "needs_target", "reason_code": "PROJECT_REQUIRED",
                "message": "Select a project for this target."}, None
    from .manual_operations import _resolve_target
    from ..agent.postestimation_steps import _load_kernel, model_id_from_ref
    from ..cli_commands import CommandError

    try:
        _resolve_target(Path(project_root).expanduser().resolve(), target)
        kernel = None
        if target["kind"] == "model_node":
            kernel = _load_kernel(Path(project_root).expanduser().resolve() / "runs" / target["run_id"],
                                  model_id_from_ref(target["node_id"]))
    except (OSError, ValueError, KeyError, CommandError, RuntimeError) as exc:
        return {"status": "unavailable", "reason_code": "TARGET_INVALID", "message": str(exc)}, None
    return {"status": "needs_parameters", "reason_code": "SPEC_VALIDATION_REQUIRED",
            "message": "Target ownership is verified; preview validates parameters and execution conditions."}, kernel


def _model_availability(operation_id: str, contract: Any, state: dict, kernel: Any) -> dict:
    if not contract.model_reference_fields or state["status"] == "unavailable":
        return dict(state)
    if kernel is None:
        return {"status": "needs_parameters", "reason_code": "MODEL_REFERENCE_REQUIRED",
                "message": "Select a completed model, or bind model_ref to a producing step in this workflow."}
    from ..agent.postestimation_steps import OPERATION_PREFIX
    from ..postestimation.core import PostestimationRefusal, _require_interface
    from ..postestimation.registry import OPERATIONS, require_validated

    operation = operation_id.removeprefix(OPERATION_PREFIX)
    declaration = OPERATIONS.get(operation)
    if declaration is not None:
        try:
            for interface in declaration.requires:
                _require_interface(kernel, interface, operation)
            require_validated(str(kernel["model_type"]), operation)
        except PostestimationRefusal as exc:
            return {"status": "unavailable", "reason_code": exc.code, "message": exc.message}
    return dict(state)


def operation_catalog(
    *, project_root: str | None = None, source_run_id: str | None = None,
    source_node_id: str | None = None, source_artifact_id: str | None = None,
    dedicated_operations: Sequence[Mapping[str, Any]] = (),
    target: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Publish every registered identity, including composition-only steps."""
    registry = OperationRegistry()
    capabilities: dict[str, list[str]] = {}
    for item in capability_inventory():
        for operation_id in set((*item.proposed_by, *item.composable_as)):
            capabilities.setdefault(operation_id, []).append(item.capability_id)
    target_state = _target_availability(project_root, source_run_id, source_node_id, source_artifact_id)
    kernel = None
    if target is not None:
        target_state, kernel = _selected_target(project_root, target)
    dedicated = {item["id"]: item for item in dedicated_operations}
    entries = {}
    for operation_id in registry.operation_ids():
        definition = registry.require(operation_id)
        contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id)
        schema = contract.to_schema() if contract is not None else deepcopy(definition.editable_schema)
        execution: dict[str, Any] = {"kind": "workflow", "method": "POST", "path": "/operations/run"}
        availability = (_model_availability(operation_id, contract, target_state, kernel)
                        if contract is not None and target_state["status"] != "needs_target" else dict(target_state))
        if operation_id in dedicated:
            binding = dedicated[operation_id]
            execution = deepcopy(binding["execution"])
            availability = {"status": "needs_parameters", "reason_code": "DEDICATED_REQUEST_REQUIRED",
                            "message": "Use the dedicated endpoint's request contract and existing confirmation flow."}
        elif contract is None:
            execution = {"kind": "unavailable", "method": None, "path": None}
            availability = {"status": "unavailable", "reason_code": "MANUAL_LIFECYCLE_REQUIRED",
                            "message": "This standalone operation requires its proposal and confirmation lifecycle; it is not a workflow step."}
        if operation_id == "model.custom":
            if operation_id not in dedicated:
                execution = {"kind": "unavailable", "method": None, "path": None}
            # Authority stays with the dedicated endpoint: it checks the admitted
            # notebook option, the server-owned capability binding and the trusted
            # execution gateway; a generic workflow cannot grant any of them.
            availability = {"status": "unavailable", "reason_code": "AUTHORIZED_GATEWAY_REQUIRED",
                            "message": "Runs only from an admitted option in a notebook, through its own confirmation."}
        summary = contract.summary if contract is not None else definition.ui_description
        entries[operation_id] = {
            "id": operation_id, "version": definition.operation_version,
            "category": operation_id.split(".")[0], **present(operation_id, summary),
            "summary": summary,
            "spec_schema": schema, "field_hints": _field_hints(schema),
            "target_requirements": list(dedicated[operation_id]["target_requirements"])
            if operation_id in dedicated else list(definition.scope_requirements),
            "confirmation_policy": definition.confirmation_policy, "risk_level": definition.risk_level,
            "output_schema_ref": contract.output_schema_ref if contract is not None else None,
            "declaration_source": "WORKFLOW_STEP_SPEC_CONTRACTS" if contract is not None else "OperationRegistry",
            "capability_ids": sorted(set(capabilities.get(operation_id, []))),
            "column_resolver": contract.column_extractor_key if contract is not None else None,
            "execution": execution, "availability": availability,
        }
    for operation_id, binding in dedicated.items():
        if operation_id in entries:
            continue
        schema = deepcopy(binding["execution"]["request_schema"])
        entries[operation_id] = {
            "id": operation_id, "version": "v1", "category": operation_id.split(".")[0],
            **present(operation_id, binding["summary"]), "summary": binding["summary"],
            "spec_schema": schema, "field_hints": _field_hints(schema),
            "target_requirements": binding["target_requirements"],
            "confirmation_policy": binding["confirmation_policy"], "risk_level": "mutating",
            "output_schema_ref": None, "declaration_source": binding["declaration_source"],
            "capability_ids": [], "column_resolver": None, "execution": deepcopy(binding["execution"]),
            "availability": {"status": "needs_parameters", "reason_code": "DEDICATED_REQUEST_REQUIRED",
                             "message": "Use the existing endpoint's request contract; source and parameter checks run there."},
        }
    operations = [entries[key] for key in sorted(entries)]
    return {"catalog_version": "workbench.operations/v1", "total": len(operations), "operations": operations}
