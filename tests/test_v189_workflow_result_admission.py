"""v1.8.9 P0 regression coverage for workflow data-result admission."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.agent.workflow import WorkflowExecutor, compile_workflow
from workbench.agent.workflow_runtime import (
    _admit_workflow_host_endpoint_from_supervisor,
    build_workflow_step_executor,
)
from workbench.artifacts import initialize_artifact_index, register_artifact
import workbench.agent.workflow_runtime as workflow_runtime


def _execute_with_admitted_host(project: Path, draft):
    workflow_directory = project / "workbench" / "workflows"
    workflow_directory.mkdir(parents=True, exist_ok=True)
    endpoint_fd = os.open(
        workflow_directory,
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
    )
    try:
        endpoint = _admit_workflow_host_endpoint_from_supervisor(project, endpoint_fd)
        with patch.object(
            workflow_runtime,
            "_deployment_host_endpoint_from_supervisor",
            return_value=endpoint,
        ):
            return WorkflowExecutor(project).execute(
                draft,
                build_workflow_step_executor(project, draft),
            )
    finally:
        os.close(endpoint_fd)


def _data_rename_case(tmp_path: Path):
    project, run_id, source_artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"old": [1, 2, 3], "value": [10, 20, 30]}),
    )
    run_root = project / "runs" / run_id
    initialize_artifact_index(run_root)
    register_artifact(
        run_root,
        source_artifact_id,
        run_root / "data.csv",
        "raw_data",
        "fixture",
        [],
    )
    draft = compile_workflow(
        workflow_id="wf-v189-data-result-admission",
        target={
            "run_id": run_id,
            "node_ref": "stage:source",
            "artifact_id": source_artifact_id,
        },
        preconditions={
            "context_fingerprint": "sha256:v189-data-result-admission",
            "active_head_run_id": run_id,
        },
        steps=[
            {
                "step_id": "renamed",
                "operation_id": "data.rename",
                "spec": {"mapping": {"old": "new"}},
            }
        ],
        available_columns=["old", "value"],
    )
    return project, run_id, draft


def test_data_rename_admits_both_persisted_result_artifacts_to_active_receipt(
    tmp_path: Path,
) -> None:
    project, run_id, draft = _data_rename_case(tmp_path)

    state = _execute_with_admitted_host(project, draft)

    assert state.status == "completed", state.steps["renamed"].error
    result = state.steps["renamed"]
    assert len(result.artifact_ids) == 2

    evidence_path = (
        project
        / "workbench"
        / "workflows"
        / f"{draft.workflow_id}.evidence.jsonl"
    )
    records = [json.loads(line) for line in evidence_path.read_text().splitlines()]
    admissions = {
        item["artifact_id"]: item
        for item in records
        if item.get("record_type") == "workflow_artifact_admission"
    }
    assert set(result.artifact_ids) <= set(admissions)
    for artifact_id in result.artifact_ids:
        admission = admissions[artifact_id]
        assert admission["receipt_id"]
        assert admission["workflow_id"] == draft.workflow_id
        assert admission["workflow_step_id"] == "renamed"
        assert admission["run_id"] == run_id
        assert admission["target_run_id"] == run_id
        assert admission["producer"] == {
            "workflow_id": draft.workflow_id,
            "step_id": "renamed",
            "operation_id": "data.rename",
        }


def test_data_result_admission_rejects_missing_index_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, run_id, draft = _data_rename_case(tmp_path)
    original_apply = workflow_runtime.apply_data_transform

    def apply_without_recipe_registration(*args, **kwargs):
        effect = original_apply(*args, **kwargs)
        index_path = project / "runs" / run_id / "artifacts_index.json"
        index = json.loads(index_path.read_text())
        index["artifacts"] = [
            item
            for item in index["artifacts"]
            if item["artifact_id"] != effect.recipe_artifact_id
        ]
        index_path.write_text(json.dumps(index, indent=2))
        return effect

    monkeypatch.setattr(workflow_runtime, "apply_data_transform", apply_without_recipe_registration)
    state = _execute_with_admitted_host(project, draft)

    assert state.status == "failed"
    assert "not uniquely registered" in (state.steps["renamed"].error or "")


def test_data_result_admission_rejects_tampered_output_digest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _run_id, draft = _data_rename_case(tmp_path)
    original_apply = workflow_runtime.apply_data_transform

    def apply_with_tampered_output(*args, **kwargs):
        effect = original_apply(*args, **kwargs)
        (project / "runs" / draft.target["run_id"] / effect.artifact_path).write_text(
            "tampered\n"
        )
        return effect

    monkeypatch.setattr(workflow_runtime, "apply_data_transform", apply_with_tampered_output)
    state = _execute_with_admitted_host(project, draft)

    assert state.status == "failed"
    assert "project artifact registry is unavailable" in (state.steps["renamed"].error or "")


def test_data_result_admission_rejects_wrong_producer_binding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project, run_id, draft = _data_rename_case(tmp_path)
    original_apply = workflow_runtime.apply_data_transform

    def apply_with_foreign_producer(*args, **kwargs):
        effect = original_apply(*args, **kwargs)
        index_path = project / "runs" / run_id / "artifacts_index.json"
        index = json.loads(index_path.read_text())
        for item in index["artifacts"]:
            if item["artifact_id"] == effect.artifact_id:
                item["step"] = "foreign.producer"
        index_path.write_text(json.dumps(index, indent=2))
        return effect

    monkeypatch.setattr(workflow_runtime, "apply_data_transform", apply_with_foreign_producer)
    state = _execute_with_admitted_host(project, draft)

    assert state.status == "failed"
    assert "producer binding changed" in (state.steps["renamed"].error or "")
