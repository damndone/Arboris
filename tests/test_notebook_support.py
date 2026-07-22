"""Shared fixtures for the Gate 4 notebook tests. Contains no tests itself.

Not a `conftest.py`: these are explicit constructors, imported by name, so a
reader of any single test can see exactly which project state it runs against.
The `test_notebook_` prefix is deliberate — Work Order A owns exactly
`tests/test_notebook_*.py`, so a helper module has to live inside that glob.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from workbench.agent.context_compiler import (
    NotebookPlanningContextV1,
    compile_notebook_planning_context,
)
from workbench.agent.trace import TraceWriter

TRACE_VERSIONS = {
    "app_commit": "test-commit",
    "model_id": "test-model",
    "prompt_version": "notebook-plan/1",
    "vocabulary_version": "ts/1",
    "context_profile": "notebook-plan/v1",
}


def make_project(tmp_path: Path, name: str = "proj") -> Path:
    project = tmp_path / name
    (project / "runs").mkdir(parents=True)
    return project


def make_run(project: Path, run_id: str, *, rerun_of: str | None = None) -> Path:
    run_root = project / "runs" / run_id
    run_root.mkdir(parents=True)
    (run_root / "run_inputs.json").write_text(
        json.dumps({"run_input_schema_version": 1, "rerun_of": rerun_of, "form": {}})
    )
    (run_root / "node_index.json").write_text(json.dumps({}))
    (run_root / "run_manifest.json").write_text(
        json.dumps({"run_id": run_id, "mode": "manual", "status": "completed"})
    )
    (run_root / "artifacts_index.json").write_text(json.dumps({"artifacts": []}))
    return run_root


def make_context(
    project: Path,
    *,
    notebook_id: str,
    run_family_id: str,
    active_head_run_id: str | None = None,
    contract_revision: int = 1,
    existing_option_summaries: list[dict[str, Any]] | None = None,
    capabilities: list[str] | None = None,
) -> NotebookPlanningContextV1:
    return compile_notebook_planning_context(
        project,
        notebook_id=notebook_id,
        run_family_id=run_family_id,
        active_head_run_id=active_head_run_id,
        analysis_contract={"revision": contract_revision, "target": "y"},
        user_focus={"selected_text_hash": "sha256:abc"},
        existing_option_summaries=existing_option_summaries or [],
        available_capabilities=capabilities or ["arma_garch_1"],
    )


def make_trace(project: Path, *, notebook_id: str, run_family_id: str) -> TraceWriter:
    return TraceWriter(
        project,
        scope={
            "project_id": project.name,
            "notebook_id": notebook_id,
            "run_family_id": run_family_id,
        },
        versions=dict(TRACE_VERSIONS),
    )


def model_rerun_proposal(
    proposal_id: str = "prop_1",
    *,
    run_id: str = "run_001",
    covariance: str = "robust",
    proposal_revision: int = 1,
) -> dict[str, Any]:
    """A typed proposal that the real `model.rerun` validator accepts."""

    return {
        "proposal_id": proposal_id,
        "proposal_revision": proposal_revision,
        "operation_id": "model.rerun",
        "operation_version": "v1",
        "target": {
            "run_id": run_id,
            "node_ref": "stage:model",
            "node_hash": "nh_1",
            "forest_node_key": "fk_1",
        },
        "preconditions": {
            "context_version": "v1",
            "context_fingerprint": "nocv1:deadbeef",
            "active_head_run_id": run_id,
            "owner_resolution": "active_head",
        },
        "changes": {"model_options": {"covariance": covariance}},
    }
