"""Artifacts service for workflow execution."""

from __future__ import annotations
from pathlib import Path
from ...artifacts import register_artifact, sha256_file
from ..context_compiler import read_workflow_artifact_index
from ..workflow import WorkflowExecutionError


def _ensure_runtime_artifact(
    run_root: Path,
    *,
    artifact_id: str,
    path: Path,
    artifact_type: str,
    step: str,
    inputs: list[str],
) -> None:
    index = read_workflow_artifact_index(run_root)
    matching = [item for item in index.get("artifacts", []) if item.get("artifact_id") == artifact_id]
    digest = sha256_file(path)
    if matching:
        if len(matching) != 1 or matching[0].get("sha256") != digest:
            raise WorkflowExecutionError("workflow-derived artifact binding is not deterministic")
        return
    register_artifact(run_root, artifact_id, path, artifact_type, step, inputs)
