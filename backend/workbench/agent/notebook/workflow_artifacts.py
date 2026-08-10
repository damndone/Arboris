"""Notebook-owned identities for auditable composed-workflow results.

The workflow runtime owns operation-specific artifacts whose identifiers are
derived only after compilation.  A Notebook option nevertheless needs one
stable artifact identity before confirmation.  This module provides that
identity without inventing a model result or weakening the exact-id artifact
contract.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ...artifacts import read_json, write_json
from ...canonical import sha256_canonical
from ...services.server_run_artifacts import register_server_owned_run_artifact


WORKFLOW_RESULT_ARTIFACT_TYPE = "notebook_workflow_result"


def workflow_result_artifact_id(
    *,
    notebook_id: str,
    option_id: str,
    proposal_hash: str,
) -> str:
    """Return the stable contract identity for one typed workflow proposal."""

    for label, value in (
        ("notebook_id", notebook_id),
        ("option_id", option_id),
        ("proposal_hash", proposal_hash),
    ):
        if not isinstance(value, str) or not value or "/" in value or "\\" in value:
            raise ValueError(f"{label} must be a non-path string")
    token = sha256_canonical(
        {
            "schema_version": "notebook-workflow-result-identity/v1",
            "notebook_id": notebook_id,
            "option_id": option_id,
            "proposal_hash": proposal_hash,
        }
    )[:32]
    return f"notebook_workflow_result_{token}"


def p7_capability_ids_from_steps(steps: Any) -> frozenset[str]:
    """Return only live P7 operations present in one declared step list."""

    from ..p7_pack_registry import p7_pack_registry

    registered = frozenset(p7_pack_registry.operation_ids())
    if not isinstance(steps, (list, tuple)):
        return frozenset()
    operation_ids = (
        step.get("operation_id")
        if isinstance(step, Mapping)
        else getattr(step, "operation_id", None)
        for step in steps
    )
    return frozenset(str(item) for item in operation_ids if item in registered)


def persist_workflow_result_manifest(
    project_root: Path,
    *,
    artifact_id: str,
    workflow: Any,
    state: Any,
    produced_artifacts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Persist one exact, bounded receipt for all completed P7 step outputs."""

    if str(state.status) != "completed":
        raise ValueError("a Notebook workflow result requires completed execution")
    p7_capabilities = p7_capability_ids_from_steps(workflow.steps)
    if not p7_capabilities:
        raise ValueError("a Notebook P7 workflow result requires at least one P7 step")

    steps_by_id = {str(step.step_id): step for step in workflow.steps}
    p7_artifact_ids = sorted(
        {
            str(raw_id).split(":", 1)[-1]
            for step_id, step_state in state.steps.items()
            if (
                step_state.status == "completed"
                and step_id in steps_by_id
                and str(steps_by_id[step_id].operation_id) in p7_capabilities
            )
            for raw_id in step_state.artifact_ids
        }
    )
    records_by_id = {
        str(record.get("artifact_id")): dict(record)
        for record in produced_artifacts
        if str(record.get("artifact_id")) in p7_artifact_ids
    }
    if set(records_by_id) != set(p7_artifact_ids):
        raise ValueError("completed P7 workflow output is missing from the artifact index")

    output_artifacts = [
        {
            "artifact_id": artifact_id_value,
            "artifact_type": str(records_by_id[artifact_id_value].get("artifact_type")),
            "sha256": str(records_by_id[artifact_id_value].get("sha256")),
            "step": str(records_by_id[artifact_id_value].get("step")),
        }
        for artifact_id_value in p7_artifact_ids
    ]
    if any(
        item["artifact_type"] != "p7_analysis"
        or len(item["sha256"]) != 64
        for item in output_artifacts
    ):
        raise ValueError("completed P7 workflow output identity is invalid")

    source_run_id = str(workflow.target["run_id"])
    run_root = project_root / "runs" / source_run_id
    result_path = (
        run_root / "artifacts" / "notebook_workflow_results" / f"{artifact_id}.json"
    )
    payload = {
        "schema_version": "workbench.notebook.workflow-result/v1",
        "workflow": {
            "workflow_id": str(workflow.workflow_id),
            "plan_fingerprint": str(workflow.plan_fingerprint),
            "status": str(state.status),
            "source": {
                "run_id": source_run_id,
                "node_ref": str(workflow.target["node_ref"]),
                "artifact_id": str(workflow.target["artifact_id"]),
            },
            "p7_capability_ids": sorted(p7_capabilities),
        },
        "output_artifacts": output_artifacts,
    }
    if result_path.exists():
        if read_json(result_path) != payload:
            raise ValueError("Notebook workflow result artifact path is occupied")
    else:
        write_json(result_path, payload)

    return register_server_owned_run_artifact(
        project_root,
        source_run_id,
        artifact_id=artifact_id,
        artifact_path=result_path,
        artifact_type=WORKFLOW_RESULT_ARTIFACT_TYPE,
        step="notebook.workflow.result",
        inputs=p7_artifact_ids,
    )


__all__ = [
    "WORKFLOW_RESULT_ARTIFACT_TYPE",
    "p7_capability_ids_from_steps",
    "persist_workflow_result_manifest",
    "workflow_result_artifact_id",
]
