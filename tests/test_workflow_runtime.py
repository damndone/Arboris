"""Native execution of compiled workflow steps, on a composed plan.

These invariants belong to the runtime: exploration steps materialize without
any code execution, the OLS step goes through Genesis, and the report step
emits one complete artifact pack. None of them depend on which assignment the
plan answers, so the fixture is deliberately generic.
"""

from __future__ import annotations

import dataclasses
import json

import pandas as pd
import pytest

from tests.test_data_column_cast import _source_project
from tests.workflow_fixtures import composed_plan
from workbench.agent.workflow import (
    WorkflowExecutor,
    WorkflowStepResult,
    compile_workflow,
)
from workbench.agent.workflow_runtime import (
    _execute_ols_branches,
    _execute_workflow_report,
    build_workflow_step_executor,
)
from workbench.lineage.run_inputs import write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes


def _frame(rows: int = 24) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "wave": [1 + (index % 3) for index in range(rows)],
            "outcome": [100.0 + index * 1.5 for index in range(rows)],
            "rate_a": [10 + index % 20 for index in range(rows)],
            "rate_b": [20 + (index * 3) % 60 for index in range(rows)],
            "size": [200 + index * 10 for index in range(rows)],
        }
    )


def _compile(project_run, frame, *, workflow_id, steps=None):
    run_id, artifact_id = project_run
    return compile_workflow(
        workflow_id=workflow_id,
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:runtime-source",
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        steps=composed_plan() if steps is None else steps,
        available_columns=list(frame.columns),
    )


def test_native_exploration_steps_materialize_without_code_execution(tmp_path) -> None:
    frame = _frame()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile((run_id, artifact_id), frame, workflow_id="wf-runtime")

    execute = build_workflow_step_executor(project, draft)
    previous: dict[str, WorkflowStepResult] = {}
    for step in draft.steps:
        if step.operation_id in {"model.genesis", "report.compose"}:
            continue
        result = execute(step, previous)
        assert result.artifact_ids, f"{step.step_id} produced no artifact"
        previous[step.step_id] = result

    # The derived split reports one row count per derived group.
    assert set(previous["split"].row_counts) == {"small_unit", "large_unit"}
    assert previous["detail"].result_fingerprint
    # The threshold is traced back to the step that actually reported it.
    assert previous["split"].payload["threshold_source"]["result_fingerprint"] == (
        previous["detail"].result_fingerprint
    )
    assert previous["split"].payload["threshold_source"]["step_id"] == "detail"
    assert all(value > 0 for value in previous["compare"].row_counts.values())
    assert len(previous["scatter"].artifact_ids) >= 2
    # No step may reach execution through the arbitrary-code path.
    assert not list(project.glob("**/code-execute*"))


def test_ols_step_uses_native_genesis_and_persists_one_run_per_branch(tmp_path) -> None:
    frame = _frame(60)
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    upload_sha = store_upload_bytes(
        project, frame.to_csv(index=False).encode("utf-8"), filename="fixture.csv"
    )
    write_run_inputs(
        project / "runs" / run_id,
        form={"model_type": "auto", "y": "", "x": ""},
        upload={"sha256": upload_sha, "filename": "fixture.csv"},
        rerun_of=None,
        from_node=None,
        rerun_reason="initial",
        override_hash=None,
        dag_hash="fixture-dag",
    )
    draft = _compile((run_id, artifact_id), frame, workflow_id="wf-ols-runtime")
    model_step = next(
        step for step in draft.steps if step.operation_id == "model.genesis"
    )

    result = _execute_ols_branches(
        project, draft, {"source_sha256": upload_sha}, frame, model_step
    )

    assert len(result.payload["branches"]) == 2
    assert all(branch["run_id"] for branch in result.payload["branches"])
    assert all("ols_1" in branch["artifact_ids"] for branch in result.payload["branches"])


def test_declared_post_estimation_steps_materialize_reproducible_model_evidence(
    tmp_path,
) -> None:
    """A model workflow can test declared terms without accepting formulas or code."""

    rows = 48
    exposure = [float(index - 24) for index in range(rows)]
    frame = pd.DataFrame(
        {
            "response": [
                20.0
                + 1.8 * value
                - 0.12 * value**2
                + (2.0 if index % 2 else -1.0)
                + ((index % 5) - 2) * 0.05
                for index, value in enumerate(exposure)
            ],
            "exposure": exposure,
            "segment": ["lower" if index % 2 else "upper" for index in range(rows)],
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    upload_sha = store_upload_bytes(
        project, frame.to_csv(index=False).encode("utf-8"), filename="fixture.csv"
    )
    write_run_inputs(
        project / "runs" / run_id,
        form={"model_type": "auto", "y": "", "x": ""},
        upload={"sha256": upload_sha, "filename": "fixture.csv"},
        rerun_of=None,
        from_node=None,
        rerun_reason="initial",
        override_hash=None,
        dag_hash="fixture-dag",
    )
    draft = _compile(
        (run_id, artifact_id),
        frame,
        workflow_id="wf-post-estimation",
        steps=[
            {
                "step_id": "estimate_curved_model",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "ols",
                    "covariance": "unadjusted",
                    "branches": [
                        {
                            "branch_id": "curved",
                            "outcome": "response",
                            "predictors": ["exposure"],
                            "categorical": ["segment"],
                            "polynomials": [{"column": "exposure", "degree": 2}],
                        }
                    ],
                },
            },
            {
                "step_id": "test_curved_terms",
                "operation_id": "model.joint_f_test",
                "depends_on": ["estimate_curved_model"],
                "spec": {
                    "branch_id": "curved",
                    "term_selectors": [
                        {"kind": "polynomial", "column": "exposure"},
                        {"kind": "categorical", "column": "segment"},
                    ],
                },
            },
            {
                "step_id": "locate_stationary_point",
                "operation_id": "model.quadratic_stationary_point",
                "depends_on": ["estimate_curved_model"],
                "spec": {"branch_id": "curved", "column": "exposure"},
            },
        ],
    )

    state = WorkflowExecutor(project).execute(
        draft, build_workflow_step_executor(project, draft)
    )

    assert state.status == "completed"
    index = json.loads(
        (project / "runs" / run_id / "artifacts_index.json").read_text(encoding="utf-8")
    )
    records = {record["artifact_id"]: record for record in index["artifacts"]}
    joint_record = records[state.steps["test_curved_terms"].artifact_ids[0]]
    stationary_record = records[state.steps["locate_stationary_point"].artifact_ids[0]]
    assert joint_record["artifact_type"] == "statistical_test"
    assert stationary_record["artifact_type"] == "post_estimation"

    joint = json.loads(
        (project / "runs" / run_id / joint_record["path"]).read_text(encoding="utf-8")
    )["result"]
    stationary = json.loads(
        (project / "runs" / run_id / stationary_record["path"]).read_text(encoding="utf-8")
    )["result"]
    assert joint["test"] == "joint_f_test"
    assert joint["term_selectors"] == [
        {"kind": "polynomial", "column": "exposure"},
        {"kind": "categorical", "column": "segment"},
    ]
    assert joint["f_statistic"] > 0
    assert joint["p_value"] >= 0
    assert stationary["column"] == "exposure"
    assert stationary["curvature"] == "maximum"
    assert stationary["stationary_point"] == pytest.approx(7.5, abs=0.2)
    assert stationary["observed_min"] == -24.0
    assert stationary["observed_max"] == 23.0
    assert stationary["stationary_point_within_observed_range"] is True


def test_report_collection_exports_one_complete_artifact_pack(tmp_path) -> None:
    frame = _frame(6)
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile((run_id, artifact_id), frame, workflow_id="wf-report-runtime")
    previous = {
        step.step_id: WorkflowStepResult(
            artifact_ids=[f"artifact-{step.step_id}"],
            row_counts={"source": len(frame)},
        )
        for step in draft.steps
        if step.operation_id != "report.compose"
    }

    result = _execute_workflow_report(project, draft, previous)

    assert {
        f"workflow_report_{draft.workflow_id}_{suffix}"
        for suffix in ("html", "pdf", "xlsx")
    } <= set(result.artifact_ids)
    assert (project / "runs" / run_id / "reports" / "wf-report-runtime.html").is_file()
    assert (project / "runs" / run_id / "reports" / "wf-report-runtime.pdf").is_file()
    assert (project / "runs" / run_id / "exports" / "wf-report-runtime.xlsx").is_file()


def test_report_collection_uses_the_declared_report_step_id(tmp_path) -> None:
    frame = _frame(6)
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile((run_id, artifact_id), frame, workflow_id="wf-report-renamed")
    report = next(step for step in draft.steps if step.operation_id == "report.compose")
    renamed_report = dataclasses.replace(report, step_id="final_report")
    renamed = dataclasses.replace(
        draft,
        steps=tuple(renamed_report if step.step_id == report.step_id else step for step in draft.steps),
    )
    previous = {
        step.step_id: WorkflowStepResult(
            artifact_ids=[f"artifact-{step.step_id}"],
            row_counts={"source": len(frame)},
        )
        for step in renamed.steps
        if step.operation_id != "report.compose"
    }

    result = _execute_workflow_report(project, renamed, previous, renamed_report)

    assert result.payload["collection_id"]
    collection = json.loads(
        (project / "runs" / run_id / "artifacts" / "statistical_exploration" / "wf-report-renamed.json").read_text()
    )
    assert "final_report" in collection["steps"]
    assert "step-9" not in collection["steps"]


def test_runtime_dispatches_on_operation_identity_not_step_naming(tmp_path):
    """A plan with unfamiliar step ids and ordering must run unchanged.

    The executor used to branch on the literal ids "step-1".."step-9", so any
    plan that was not one exercise's numbering could not execute at all.
    """
    frame = _frame(40)
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile((run_id, artifact_id), frame, workflow_id="wf-renumbered")

    rename = {step.step_id: f"phase_{index:02d}" for index, step in enumerate(draft.steps)}
    renamed = tuple(
        dataclasses.replace(
            step,
            step_id=rename[step.step_id],
            depends_on=tuple(rename[dep] for dep in step.depends_on),
        )
        for step in draft.steps
    )
    # Keep the pre-model steps so the assertion is about dispatch, not about
    # driving a full model run inside a unit test.
    keep = {
        "statistical.explore",
        "statistical.derive_boolean",
        "statistical.derived_group_summarize",
    }
    plan = dataclasses.replace(
        draft, steps=tuple(step for step in renamed if step.operation_id in keep)
    )

    state = WorkflowExecutor(project).execute(
        plan, build_workflow_step_executor(project, plan)
    )

    assert state.status == "completed"
    assert {step.status for step in state.steps.values()} == {"completed"}
    assert all(step_id.startswith("phase_") for step_id in state.steps)


def test_model_custom_requires_an_authorized_gateway_and_can_be_injected(tmp_path) -> None:
    frame = _frame(6)
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile(
        (run_id, artifact_id),
        frame,
        workflow_id="wf-custom-gateway",
        steps=[
            {
                "step_id": "custom_capability",
                "operation_id": "model.custom",
                "spec": {
                    "capability_ref": "capability:example",
                    "binding_ref": "binding:example",
                    "operation": "fit",
                    "parameters": {"family": "count"},
                    "expected_artifacts": ["model_summary"],
                },
            }
        ],
    )
    execute_without_gateway = build_workflow_step_executor(project, draft)
    with pytest.raises(Exception, match="authorized custom capability gateway"):
        execute_without_gateway(draft.steps[0], {})

    calls = []

    def authorized_gateway(*, project_root, draft, step, previous):
        calls.append((project_root, draft.workflow_id, step.step_id, previous))
        return WorkflowStepResult(
            artifact_ids=["custom-result"],
            row_counts={"source": len(frame)},
            result_fingerprint="sha256:custom-result",
            payload={"status": "completed"},
        )

    state = WorkflowExecutor(project).execute(
        draft,
        build_workflow_step_executor(
            project,
            draft,
            custom_step_executor=authorized_gateway,
        ),
    )

    assert state.status == "completed"
    assert state.steps["custom_capability"].artifact_ids == ("custom-result",)
    assert calls and calls[0][1:3] == ("wf-custom-gateway", "custom_capability")
