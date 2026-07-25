from __future__ import annotations

import pandas as pd

from tests.test_data_column_cast import _source_project
from workbench.agent.workflow_runtime import _execute_ols_branches
from workbench.agent.workflow import (
    WorkflowExecutor,
    WorkflowStepResult,
    compile_class3_workflow,
)
from workbench.agent.workflow_runtime import _execute_class3_report, build_class3_step_executor
from workbench.lineage.run_inputs import write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes


def test_class3_native_exploration_steps_materialize_without_code_execution(tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "year": [1998, 1998, 2002, 2002, 2006, 2006, 2010, 2010, 2014, 2014, 2016, 2016],
            "adj_dppupil_comp": [10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21],
            "pblack": [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
            "pfl": [10, 20, 30, 40, 50, 60, 70, 80, 90, 80, 70, 60],
            "totreg": [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000, 1100, 1200],
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    bindings = {
        "year_column": "year",
        "spending_column": "adj_dppupil_comp",
        "black_column": "pblack",
        "poverty_column": "pfl",
        "enrollment_column": "totreg",
        "all_numeric_columns": list(frame.columns),
        "group_values": [1998, 2002, 2006, 2010, 2014, 2016],
    }
    draft = compile_class3_workflow(
        workflow_id="wf-runtime",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:runtime-source",
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        bindings=bindings,
        available_columns=list(frame.columns),
    )
    execute = build_class3_step_executor(project, draft)
    previous = {}
    for step in draft.steps[:7]:
        result = execute(step, previous)
        assert result.artifact_ids
        previous[step.step_id] = result

    assert set(previous["step-5"].row_counts) == {
        "small_school",
        "large_school",
        "poor_school",
        "least_poor_school",
    }
    assert previous["step-4"].result_fingerprint
    assert previous["step-5"].payload["threshold_source"] == {
        "step_id": "step-4",
        "artifact_role": "result",
        "result_fingerprint": previous["step-4"].result_fingerprint,
    }
    assert all(value > 0 for value in previous["step-6"].row_counts.values())
    assert len(previous["step-7"].artifact_ids) >= 2
    assert not list(project.glob("**/code-execute*"))


def test_class3_ols_step_uses_native_genesis_and_persists_two_model_runs(tmp_path) -> None:
    rows = 60
    frame = pd.DataFrame(
        {
            "year": [1998 + 4 * (index // 10) for index in range(rows)],
            "adj_dppupil_comp": [100 + index * 1.5 for index in range(rows)],
            "pblack": [10 + index % 20 for index in range(rows)],
            "pfl": [20 + (index * 3) % 60 for index in range(rows)],
            "totreg": [200 + index * 10 for index in range(rows)],
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    upload_bytes = frame.to_csv(index=False).encode("utf-8")
    upload_sha = store_upload_bytes(project, upload_bytes, filename="fixture.csv")
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
    bindings = {
        "year_column": "year",
        "spending_column": "adj_dppupil_comp",
        "black_column": "pblack",
        "poverty_column": "pfl",
        "enrollment_column": "totreg",
        "all_numeric_columns": list(frame.columns),
        "group_values": [1998, 2002, 2006, 2010, 2014, 2016],
    }
    draft = compile_class3_workflow(
        workflow_id="wf-ols-runtime",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:runtime-source",
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        bindings=bindings,
        available_columns=list(frame.columns),
    )
    context = {"source_sha256": upload_sha}

    result = _execute_ols_branches(project, draft, context, frame)

    assert len(result.payload["branches"]) == 2
    assert all(branch["run_id"] for branch in result.payload["branches"])
    assert all("ols_1" in branch["artifact_ids"] for branch in result.payload["branches"])


def test_class3_report_collection_exports_one_complete_artifact_pack(tmp_path) -> None:
    frame = pd.DataFrame(
        {
            "year": [1998, 2002],
            "adj_dppupil_comp": [10, 11],
            "pblack": [1, 2],
            "pfl": [20, 30],
            "totreg": [100, 200],
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = compile_class3_workflow(
        workflow_id="wf-report-runtime",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:runtime-source",
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        bindings={
            "year_column": "year",
            "spending_column": "adj_dppupil_comp",
            "black_column": "pblack",
            "poverty_column": "pfl",
            "enrollment_column": "totreg",
            "all_numeric_columns": list(frame.columns),
            "group_values": [1998, 2002, 2006, 2010, 2014, 2016],
        },
        available_columns=list(frame.columns),
    )
    previous = {
        f"step-{index}": WorkflowStepResult(
            artifact_ids=[f"artifact-step-{index}"],
            row_counts={"source": len(frame)},
        )
        for index in range(1, 9)
    }

    result = _execute_class3_report(project, draft, previous)

    assert {
        f"class3_report_{draft.workflow_id}_{suffix}"
        for suffix in ("html", "pdf", "xlsx")
    } <= set(result.artifact_ids)
    assert (project / "runs" / run_id / "reports" / "wf-report-runtime.html").is_file()
    assert (project / "runs" / run_id / "reports" / "wf-report-runtime.pdf").is_file()
    assert (project / "runs" / run_id / "exports" / "wf-report-runtime.xlsx").is_file()


def test_runtime_dispatches_on_operation_identity_not_step_numbering(tmp_path):
    """A plan with different step ids and ordering must run unchanged.

    The executor used to branch on the literal ids "step-1".."step-9", so any
    plan that was not this one exercise's numbering could not execute at all.
    """
    import dataclasses

    frame = pd.DataFrame(
        {
            "wave": [2019, 2021] * 20,
            "cost_pc": [100.0 + index for index in range(40)],
            "pct_minority": [float(index % 17) for index in range(40)],
            "pct_lowinc": [float(index % 23) for index in range(40)],
            "headcount": [200 + index * 3 for index in range(40)],
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = compile_class3_workflow(
        workflow_id="wf-renumbered",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "fp"},
        bindings={
            "year_column": "wave",
            "spending_column": "cost_pc",
            "black_column": "pct_minority",
            "poverty_column": "pct_lowinc",
            "enrollment_column": "headcount",
            "all_numeric_columns": ["cost_pc", "pct_minority", "pct_lowinc", "headcount"],
            "group_values": [2019, 2021],
        },
        available_columns=list(frame.columns),
        group_value_witness=[2019, 2021],
    )

    # Rename every step to an id the old executor had never heard of.
    rename = {step.step_id: f"phase_{index:02d}" for index, step in enumerate(draft.steps)}
    renamed = tuple(
        dataclasses.replace(
            step,
            step_id=rename[step.step_id],
            depends_on=tuple(rename[dep] for dep in step.depends_on),
        )
        for step in draft.steps
    )
    # Keep only the pre-model exploration steps so the assertion is about
    # dispatch, not about driving a full model run in a unit test.
    keep = {"statistical.explore", "statistical.derive_boolean", "statistical.derived_group_summarize"}
    renamed = tuple(step for step in renamed if step.operation_id in keep)
    plan = dataclasses.replace(draft, steps=renamed)

    state = WorkflowExecutor(project).execute(plan, build_class3_step_executor(project, plan))

    assert state.status == "completed"
    assert {step.status for step in state.steps.values()} == {"completed"}
    assert all(step_id.startswith("phase_") for step_id in state.steps)
