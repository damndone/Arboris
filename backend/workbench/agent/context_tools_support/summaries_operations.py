"""Summaries: bounded read-only context projection. (operations)."""

from __future__ import annotations

from typing import Any
from ..operations import OperationRecord
from ..operation_outcome import produced_run
from .requests import _PROJECT_RUN_ID_RE


def _bounded_artifact_manifest(
    manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    allowed = (
        "expected",
        "available",
        "readable",
        "artifact_id",
        "filename",
        "schema_valid",
        "model_id",
        "available_count",
        "legacy_debug_only",
    )
    bounded: dict[str, dict[str, Any]] = {}
    for section, value in manifest.items():
        if not isinstance(section, str) or not isinstance(value, dict):
            continue
        bounded[section] = {key: value[key] for key in allowed if key in value}
    return bounded


def _operation_artifact_ids(record: OperationRecord) -> list[str]:
    """Collect only artifact ids already recorded as this operation's output."""

    artifact_ids: list[str] = []
    direct = record.outputs.get("artifact_ids")
    if isinstance(direct, list):
        artifact_ids.extend(item for item in direct if isinstance(item, str) and item)
    workflow_state = record.outputs.get("workflow_state")
    steps = workflow_state.get("steps") if isinstance(workflow_state, dict) else None
    if isinstance(steps, dict):
        for step in steps.values():
            step_artifacts = step.get("artifact_ids") if isinstance(step, dict) else None
            if isinstance(step_artifacts, list):
                artifact_ids.extend(
                    item for item in step_artifacts if isinstance(item, str) and item
                )
    return list(dict.fromkeys(artifact_ids))


def _operation_artifact_source(record: OperationRecord, artifact_id: str) -> tuple[str, str] | None:
    """Bind an emitted qualified id to the same completed step's model branch.

    A run prefix alone is not authority to read another run. Both the step's
    emitted id and its persisted branch's local artifact list must agree.
    """

    if record.status != "completed" or artifact_id not in _operation_artifact_ids(record):
        return None
    state = record.outputs.get("workflow_state")
    steps = state.get("steps") if isinstance(state, dict) else None
    for step in steps.values() if isinstance(steps, dict) else ():
        if (not isinstance(step, dict) or step.get("status") != "completed"
                or artifact_id not in (step.get("artifact_ids") or ())):
            continue
        branches = step.get("model_branches")
        for branch in branches if isinstance(branches, list) else ():
            if not isinstance(branch, dict):
                continue
            run_id, local_ids = branch.get("run_id"), branch.get("artifact_ids")
            if not isinstance(run_id, str) or not _PROJECT_RUN_ID_RE.fullmatch(run_id):
                continue
            for local_id in local_ids if isinstance(local_ids, list) else ():
                if isinstance(local_id, str) and local_id and artifact_id == f"{run_id}:{local_id}":
                    return run_id, local_id
    return None


def _operation_model_branches(step: dict[str, Any]) -> list[dict[str, str]]:
    """Only the durable model ids needed by the existing coefficient reader."""

    branches = step.get("model_branches")
    return [
        {key: branch[key] for key in ("branch_id", "run_id", "model_id")
         if isinstance(branch.get(key), str) and len(branch[key]) <= 300}
        for branch in (branches if isinstance(branches, list) else [])[:16]
        if isinstance(branch, dict) and isinstance(branch.get("run_id"), str)
        and _PROJECT_RUN_ID_RE.fullmatch(branch["run_id"])
        and step.get("status") == "completed"
    ]


def _bounded_completed_operation(record: OperationRecord) -> dict[str, Any]:
    workflow_state = record.outputs.get("workflow_state")
    steps = workflow_state.get("steps") if isinstance(workflow_state, dict) else None
    workflow_steps: list[dict[str, Any]] = []
    if isinstance(steps, dict):
        for step_id, step in sorted(steps.items()):
            if not isinstance(step_id, str) or not isinstance(step, dict):
                continue
            artifact_ids = step.get("artifact_ids")
            row_counts = step.get("row_counts")
            model_branches = _operation_model_branches(step)
            workflow_steps.append(
                {
                    "step_id": step_id,
                    "status": str(step.get("status") or "unknown"),
                    "artifact_ids": [
                        item
                        for item in (artifact_ids if isinstance(artifact_ids, list) else [])
                        if isinstance(item, str) and item
                    ][:16],
                    **({"model_branches": model_branches} if model_branches else {}),
                    "row_counts": {
                        str(key): value
                        for key, value in (row_counts.items() if isinstance(row_counts, dict) else ())
                        if isinstance(value, int) and not isinstance(value, bool)
                    },
                }
            )
    produced = produced_run(record.to_dict())
    return {
        "operation_record_id": record.record_id,
        "operation_id": record.operation_id,
        "operation_version": record.operation_version,
        "status": record.status,
        "artifact_ids": _operation_artifact_ids(record)[:16],
        # A rerun's result is a new run, not artifacts of this node: read it
        # with inspect_project_model_coefficients(run_ids=[produced_run_id]).
        **({"produced_run_id": produced} if produced else {}),
        "workflow": {
            "workflow_id": (
                workflow_state.get("workflow_id")
                if isinstance(workflow_state, dict)
                and isinstance(workflow_state.get("workflow_id"), str)
                else None
            ),
            "status": (
                workflow_state.get("status")
                if isinstance(workflow_state, dict)
                and isinstance(workflow_state.get("status"), str)
                else None
            ),
            "steps": workflow_steps[:16],
        },
    }
