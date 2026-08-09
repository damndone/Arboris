"""P7 must travel through one generic compiled-workflow execution seam."""

from __future__ import annotations

import json

import pandas as pd

from workbench.lineage.run_inputs import write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes
from tests.test_p7_adoption_calls import _cases
from tests.test_data_column_cast import _source_project
from workbench.agent.workflow import WorkflowExecutor, compile_workflow
from workbench.agent.workflow_runtime import (
    build_workflow_step_executor,
    collect_post_estimation_results,
)
from workbench.artifacts import sha256_file


def _compile_p7(project_run: tuple[str, str], frame: pd.DataFrame):
    run_id, artifact_id = project_run
    return compile_workflow(
        workflow_id="wf-p7-generic-runtime",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:p7-runtime-source",
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        steps=[
            {
                "step_id": "categorical_association",
                "operation_id": "categorical.cramers_v",
                "spec": {
                    "input_mode": "typed",
                    "column_bindings": {"row": "row", "column": "column"},
                    "options": {"correction": False, "exact": False},
                },
            }
        ],
        available_columns=list(frame.columns),
    )


def test_p7_step_uses_generic_runtime_and_persists_provenance(tmp_path) -> None:
    """A P7 call is executable and its result remains traceable to its source."""

    frame = pd.DataFrame(
        {
            "row": ["a"] * 12 + ["b"] * 12,
            "column": ["x"] * 10 + ["y"] * 2 + ["x"] * 3 + ["y"] * 9,
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile_p7((run_id, artifact_id), frame)

    state = WorkflowExecutor(project).execute(
        draft,
        build_workflow_step_executor(project, draft),
    )

    assert state.status == "completed", state.steps["categorical_association"].error
    result = state.steps["categorical_association"]
    assert result.artifact_ids
    artifact_id_out = result.artifact_ids[0]
    index = json.loads((project / "runs" / run_id / "artifacts_index.json").read_text())
    record = next(item for item in index["artifacts"] if item["artifact_id"] == artifact_id_out)
    assert record["artifact_type"] == "p7_analysis"
    payload = json.loads((project / "runs" / run_id / record["path"]).read_text())
    assert payload["schema_version"] == "workbench.workflow.p7-pack/v1"
    assert payload["source"]["operation_id"] == "categorical.cramers_v"
    assert payload["source"]["pack_family"] == "categorical"
    assert payload["source"]["artifact_id"] == artifact_id
    source_path = project / "runs" / run_id / "data.csv"
    assert payload["source"]["sha256"] == sha256_file(source_path)
    assert payload["result"]["operation_id"] == "categorical.cramers_v"
    assert payload["result"]["contract"] == "categorical_count.result"
    projected = collect_post_estimation_results(project, run_id)
    assert len(projected) == 1
    assert projected[0]["artifact_type"] == "p7_analysis"
    assert projected[0]["pack_family"] == "categorical"
    assert projected[0]["workflow_step_id"] == "categorical_association"
    assert projected[0]["result"] == payload["result"]


def test_every_registered_p7_operation_completes_through_compiled_workflow(tmp_path) -> None:
    """Every registered operation reaches the same generic Workbench runtime."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    cases = _cases()
    operation_ids = set(p7_pack_registry.operation_ids())
    assert {key for key in cases if ":" not in key} == operation_ids
    failures: list[str] = []
    for operation_id in sorted(operation_ids):
        frame, request = cases[operation_id]
        source_frame = (
            pd.DataFrame({"fixture_placeholder": [0]}) if frame is None else frame
        )
        project, run_id, artifact_id = _source_project(
            tmp_path / operation_id.replace(".", "_"), source_frame
        )
        step_id = operation_id.replace(".", "_")
        draft = compile_workflow(
            workflow_id=f"wf-p7-{step_id}",
            target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
            preconditions={
                "context_version": "node-operation-context/v1",
                "context_fingerprint": f"sha256:p7-{step_id}",
                "active_head_run_id": run_id,
                "owner_resolution": "single_candidate",
            },
            steps=[
                {
                    "step_id": step_id,
                    "operation_id": operation_id,
                    "spec": {
                        "input_mode": request["input_mode"],
                        "column_bindings": request["column_bindings"],
                        "options": request["options"],
                    },
                }
            ],
            available_columns=list(source_frame.columns),
        )
        try:
            state = WorkflowExecutor(project).execute(
                draft,
                build_workflow_step_executor(project, draft),
            )
            step_state = state.steps[step_id]
            assert state.status == "completed", step_state.error
            assert step_state.artifact_ids
            index = json.loads(
                (project / "runs" / run_id / "artifacts_index.json").read_text()
            )
            record = next(
                item for item in index["artifacts"]
                if item["artifact_id"] == step_state.artifact_ids[0]
            )
            payload = json.loads(
                (project / "runs" / run_id / record["path"]).read_text()
            )
            assert record["artifact_type"] == "p7_analysis"
            assert payload["schema_version"] == "workbench.workflow.p7-pack/v1"
            assert payload["source"]["run_id"] == run_id
            assert payload["source"]["artifact_id"] == artifact_id
            assert payload["source"]["sha256"] == sha256_file(
                project / "runs" / run_id / "data.csv"
            )
            assert payload["source"]["operation_id"] == operation_id
            assert payload["result"]["operation_id"] == operation_id
        except Exception as exc:  # report all unreachable runtime calls together
            failures.append(f"{operation_id}: {type(exc).__name__}: {exc}")
    assert not failures, "P7 compiled workflow calls failed:\n" + "\n".join(failures)


def test_p7_step_composes_with_model_genesis_in_one_workflow(tmp_path) -> None:
    """A P7 step and a model step share the generic workflow authorization seam."""

    frame = pd.DataFrame(
        {
            "row": ["a"] * 30 + ["b"] * 30,
            "column": (["x"] * 20 + ["y"] * 10) * 2,
            "outcome": [100.0 + index * 0.5 for index in range(60)],
            "predictor": [float(index % 12) for index in range(60)],
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    upload_sha = store_upload_bytes(
        project,
        frame.to_csv(index=False).encode("utf-8"),
        filename="p7-model-composition.csv",
    )
    write_run_inputs(
        project / "runs" / run_id,
        form={"model_type": "auto", "y": "", "x": ""},
        upload={"sha256": upload_sha, "filename": "p7-model-composition.csv"},
        rerun_of=None,
        from_node=None,
        rerun_reason="initial",
        override_hash=None,
        dag_hash="p7-model-composition-dag",
    )
    draft = compile_workflow(
        workflow_id="wf-p7-with-model-genesis",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:p7-model-composition",
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        steps=[
            {
                "step_id": "association",
                "operation_id": "categorical.cramers_v",
                "spec": {
                    "input_mode": "typed",
                    "column_bindings": {"row": "row", "column": "column"},
                    "options": {"correction": False, "exact": False},
                },
            },
            {
                "step_id": "estimate",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "ols",
                    "branches": [
                        {
                            "branch_id": "main",
                            "outcome": "outcome",
                            "predictors": ["predictor"],
                        }
                    ],
                },
            },
        ],
        available_columns=list(frame.columns),
    )

    state = WorkflowExecutor(project).execute(
        draft,
        build_workflow_step_executor(project, draft),
    )

    assert state.status == "completed", state.steps["estimate"].error
    assert state.steps["association"].artifact_ids
    assert state.steps["estimate"].artifact_ids
    projected = collect_post_estimation_results(project, run_id)
    assert {entry["operation_id"] for entry in projected} >= {"categorical.cramers_v"}
