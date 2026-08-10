"""Integration guards for the declaration-driven workflow capability seam."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from workbench.agent.workflow import WorkflowExecutionError, compile_workflow
from workbench.agent.workflow_runtime import (
    build_workflow_step_executor,
    collect_post_estimation_results,
)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "y": [float(index + 1) for index in range(24)],
            "x": [float((index * 3) % 11 + 1) for index in range(24)],
            "z": [float((index * 5) % 13 + 2) for index in range(24)],
        }
    )


def _compile(project, run_id: str, artifact_id: str, frame: pd.DataFrame, steps: list[dict]):
    return compile_workflow(
        workflow_id="wf-generic-capability-runtime",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:generic-capability-runtime",
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        steps=steps,
        available_columns=list(frame.columns),
    )


def test_generic_analysis_is_persisted_and_projected_with_replay_evidence(tmp_path) -> None:
    """One generic analysis step remains visible after the workflow returns."""

    frame = _frame()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile(
        project,
        run_id,
        artifact_id,
        frame,
        [
            {
                "step_id": "correlation",
                "operation_id": "test.correlations",
                "spec": {
                    "input_mode": "frame",
                    "column_bindings": {"columns": ["x", "y"]},
                    "options": {},
                },
            }
        ],
    )

    result = build_workflow_step_executor(project, draft)(draft.steps[0], {})

    assert len(result.artifact_ids) == 1
    artifact_id = result.artifact_ids[0]
    artifact_path = project / "runs" / run_id / "artifacts" / "workflow_capability" / f"{artifact_id}.json"
    envelope = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert envelope["source"]["artifact_id"] == "source_data"
    assert envelope["request"]["operation_id"] == "test.correlations"
    assert envelope["request_fingerprint"].startswith("sha256:")
    assert envelope["result_sha256"]

    projected = collect_post_estimation_results(project, run_id)
    assert len(projected) == 1
    assert projected[0]["operation_id"] == "test.correlations"
    assert projected[0]["source_sha256"] == envelope["source"]["sha256"]
    assert projected[0]["request_fingerprint"] == envelope["request_fingerprint"]


def test_generic_dataset_output_is_resolvable_and_role_checked(tmp_path) -> None:
    """A prepared dataset can feed a model, and its role survives persistence."""

    frame = _frame()
    frame.loc[3, "x"] = None
    frame.loc[11, "z"] = None
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile(
        project,
        run_id,
        artifact_id,
        frame,
        [
            {
                "step_id": "prepare",
                "operation_id": "imputation.mice",
                "spec": {
                    "input_mode": "frame",
                    "column_bindings": {"columns": ["x", "z"]},
                    "options": {"random_seed": 19, "max_iter": 3},
                },
            },
            {
                "step_id": "estimate",
                "operation_id": "model.auto",
                "spec": {
                    "input_mode": "frame",
                    "column_bindings": {"outcome": "y", "features": ["x"]},
                    "options": {},
                    "source": {"from_step": "prepare", "output": "produced_dataset"},
                },
            },
        ],
    )
    execute = build_workflow_step_executor(project, draft)

    prepared = execute(draft.steps[0], {})
    estimated = execute(draft.steps[1], {"prepare": prepared})

    binding = prepared.payload["produced_dataset"]
    assert binding["dataset_kind"] == "prepared_data"
    assert binding["artifact_id"] in prepared.artifact_ids
    assert estimated.payload["result"]["selected_model_type"] == "ols"
    projected = collect_post_estimation_results(project, run_id)
    assert [entry["operation_id"] for entry in projected] == ["model.auto"]
    assert projected[0]["source_sha256"] == binding["content_sha256"]


def test_generic_dataset_schema_cannot_be_overwritten_after_replay(tmp_path) -> None:
    """A replay must refuse a changed server-owned dataset schema."""

    frame = _frame()
    frame.loc[3, "x"] = None
    frame.loc[11, "z"] = None
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile(
        project,
        run_id,
        artifact_id,
        frame,
        [
            {
                "step_id": "prepare",
                "operation_id": "imputation.mice",
                "spec": {
                    "input_mode": "frame",
                    "column_bindings": {"columns": ["x", "z"]},
                    "options": {"random_seed": 19, "max_iter": 3},
                },
            }
        ],
    )
    execute = build_workflow_step_executor(project, draft)
    execute(draft.steps[0], {})

    schema_path = next((project / "runs" / run_id).rglob("*.schema.json"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["dtypes"]["x"] = "tampered"
    schema_path.write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(WorkflowExecutionError, match="schema path is occupied"):
        execute(draft.steps[0], {})


def test_generic_capability_failure_is_not_committed(tmp_path) -> None:
    """A blocked adapter leaves no completed artifact for the failed step."""

    frame = _frame()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile(
        project,
        run_id,
        artifact_id,
        frame,
        [
            {
                "step_id": "bad_resample",
                "operation_id": "resample.smote",
                "spec": {
                    "input_mode": "frame",
                    "column_bindings": {"outcome": "y", "features": ["x"]},
                    "options": {"random_seed": 19},
                },
            }
        ],
    )

    with pytest.raises(WorkflowExecutionError, match="discrete target"):
        build_workflow_step_executor(project, draft)(draft.steps[0], {})

    assert not list((project / "runs" / run_id / "artifacts").glob("workflow_capability/**"))
    assert collect_post_estimation_results(project, run_id) == []


def test_registered_post_estimation_artifact_is_not_silently_dropped(tmp_path) -> None:
    """A registered evidence record must surface corruption instead of disappearing."""
    frame = _frame()
    project, run_id, _artifact_id = _source_project(tmp_path, frame)
    index_path = project / "runs" / run_id / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["artifacts"].append(
        {
            "artifact_id": "broken_post_estimation",
            "path": "artifacts/p7_analysis/broken.json",
            "artifact_type": "p7_analysis",
            "step": "broken",
        }
    )
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkflowExecutionError, match="registered post-estimation artifact"):
        collect_post_estimation_results(project, run_id)


def test_registered_post_estimation_record_must_be_an_object(tmp_path) -> None:
    """Corrupt registry entries fail as evidence errors, not raw attribute errors."""

    frame = _frame()
    project, run_id, _artifact_id = _source_project(tmp_path, frame)
    index_path = project / "runs" / run_id / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index["artifacts"].append("not-an-artifact-record")
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(WorkflowExecutionError, match="record must be an object"):
        collect_post_estimation_results(project, run_id)


def test_post_estimation_projection_rejects_a_malformed_artifact_index(
    tmp_path: Path,
) -> None:
    """A malformed compiler registry becomes a typed evidence error."""

    run_root = tmp_path / "runs" / "run_malformed"
    run_root.mkdir(parents=True)
    (run_root / "artifacts_index.json").write_text("[]", encoding="utf-8")

    with pytest.raises(WorkflowExecutionError, match="artifact index"):
        collect_post_estimation_results(tmp_path, "run_malformed")


def test_post_estimation_projection_rejects_a_changed_registered_file(tmp_path) -> None:
    """A registered result cannot be projected after its file fingerprint changes."""

    frame = _frame()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile(
        project,
        run_id,
        artifact_id,
        frame,
        [
            {
                "step_id": "correlation",
                "operation_id": "test.correlations",
                "spec": {
                    "input_mode": "frame",
                    "column_bindings": {"columns": ["x", "y"]},
                    "options": {},
                },
            }
        ],
    )
    result = build_workflow_step_executor(project, draft)(draft.steps[0], {})
    index_path = project / "runs" / run_id / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    record = next(item for item in index["artifacts"] if item["artifact_id"] == result.artifact_ids[0])
    artifact_path = project / "runs" / run_id / record["path"]
    artifact_path.write_text(artifact_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(WorkflowExecutionError, match="fingerprint"):
        collect_post_estimation_results(project, run_id)


def test_post_estimation_projection_refuses_to_silently_truncate(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A bounded projection reports overflow instead of hiding later evidence."""
    from workbench.agent import workflow_runtime

    records = [
        {"artifact_id": "first", "artifact_type": "post_estimation"},
        {"artifact_id": "second", "artifact_type": "post_estimation"},
    ]
    (tmp_path / "runs" / "source").mkdir(parents=True)
    monkeypatch.setattr(
        workflow_runtime,
        "_read_artifacts_index",
        lambda _run_dir: {"artifacts": records},
    )
    monkeypatch.setattr(
        workflow_runtime,
        "_read_post_estimation_entry",
        lambda _run_dir, record: {
            "artifact_id": record["artifact_id"],
            "run_id": "run",
            "model_run_id": "",
        },
    )

    with pytest.raises(WorkflowExecutionError, match="exceeds projection limit"):
        collect_post_estimation_results(
            root=tmp_path,
            run_id="run",
            limit=1,
        )
