"""P7 must travel through one generic compiled-workflow execution seam."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pandas as pd

from workbench.lineage.run_inputs import write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes
from tests.test_p7_adoption_calls import _cases, _hurdle_negative_binomial_success_case
from tests.test_data_column_cast import _source_project
from workbench.agent.workflow import WorkflowExecutor, compile_workflow
from workbench.agent.workflow_runtime import (
    build_workflow_step_executor,
    collect_post_estimation_results,
)
from workbench.artifacts import sha256_file


def _compile_p7(
    project_run: tuple[str, str],
    frame: pd.DataFrame,
    *,
    workflow_id: str = "wf-p7-generic-runtime",
):
    run_id, artifact_id = project_run
    return compile_workflow(
        workflow_id=workflow_id,
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
                    "options": {"correction": False},
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


def test_p7_failed_result_fails_workflow_instead_of_false_success(
    tmp_path, monkeypatch
) -> None:
    """A typed P7 failure must not be rendered as a successful workflow."""

    import workbench.agent.p7_pack_registry as registry_module

    operation_id = "categorical.cramers_v"
    real_operation = registry_module.p7_pack_registry.get(operation_id)
    failed_result = {
        "contract": "categorical_count.result",
        "contract_version": "1.0",
        "operation_id": operation_id,
        "result": {
            "status": "failed",
            "reason_code": "CATEGORICAL_FAILED",
            "error_code": "CATEGORICAL_FAILED",
            "message": "CATEGORICAL_FAILED: fixture failure",
        },
    }
    fake_operation = SimpleNamespace(
        operation_id=operation_id,
        pack_family=real_operation.pack_family,
        validate=lambda request: request,
        preflight=lambda _frame, request: request,
        extract_columns=real_operation.extract_columns,
        execute=lambda _frame, _request: failed_result,
        validate_result=lambda _result: None,
    )
    monkeypatch.setattr(
        registry_module.p7_pack_registry,
        "get",
        lambda requested_operation_id: fake_operation,
    )

    frame = pd.DataFrame(
        {
            "row": ["a"] * 12 + ["b"] * 12,
            "column": ["x"] * 10 + ["y"] * 2 + ["x"] * 3 + ["y"] * 9,
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = _compile_p7((run_id, artifact_id), frame, workflow_id="wf-p7-failed-result")

    state = WorkflowExecutor(project).execute(
        draft,
        build_workflow_step_executor(project, draft),
    )

    assert state.status == "failed"
    step_state = state.steps["categorical_association"]
    assert step_state.status == "failed"
    assert "status 'failed'" in (step_state.error or "")
    assert "CATEGORICAL_FAILED: fixture failure" in (step_state.error or "")
    assert "CATEGORICAL_FAILED: CATEGORICAL_FAILED" not in (step_state.error or "")
    assert collect_post_estimation_results(project, run_id) == []


def test_runtime_preflight_refuses_an_impossible_p7_request_before_execution(
    tmp_path, monkeypatch
) -> None:
    """The runtime independently rechecks frame-dependent declarations."""

    import workbench.agent.p7_pack_registry as registry_module

    operation_id = "synthetic_control.fit"
    real_operation = registry_module.p7_pack_registry.get(operation_id)
    execute_calls: list[str] = []

    def execute(frame, request):
        execute_calls.append(operation_id)
        return real_operation.execute(frame, request)

    guarded_operation = SimpleNamespace(
        operation_id=operation_id,
        pack_family=real_operation.pack_family,
        validate=real_operation.validate,
        preflight=real_operation.preflight,
        extract_columns=real_operation.extract_columns,
        execute=execute,
        validate_result=real_operation.validate_result,
    )
    monkeypatch.setattr(
        registry_module.p7_pack_registry,
        "get",
        lambda requested_operation_id: guarded_operation,
    )
    frame = pd.DataFrame(
        {
            "treated_sc": [1.0 + index / 10 for index in range(10)],
            "d1": [1.1 + index / 10 for index in range(10)],
            "d2": [0.9 + index / 10 for index in range(10)],
            "d3": [1.2 + index / 10 for index in range(10)],
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    step_id = "fit_counterfactual"
    draft = compile_workflow(
        workflow_id="wf-p7-runtime-preflight",
        target={
            "run_id": run_id,
            "node_ref": "stage:source",
            "artifact_id": artifact_id,
        },
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:p7-runtime-preflight",
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        steps=[
            {
                "step_id": step_id,
                "operation_id": operation_id,
                "spec": {
                    "input_mode": "typed",
                    "column_bindings": {
                        "outcomes": ["treated_sc", "d1", "d2", "d3"]
                    },
                    "options": {
                        "treated_unit": "treated_sc",
                        "donor_pool": ["d1", "d2", "d3"],
                        "periods": [0, 1, 2, 3, 4, 5],
                        "pre_periods": [0, 1, 2],
                        "post_periods": [3, 4, 5],
                    },
                },
            }
        ],
        available_columns=list(frame.columns),
    )

    state = WorkflowExecutor(project).execute(
        draft,
        build_workflow_step_executor(project, draft),
    )

    assert state.status == "failed"
    assert "SYNTHETIC_CONTROL_PERIOD_COUNT_MISMATCH" in (
        state.steps[step_id].error or ""
    )
    assert execute_calls == []
    assert collect_post_estimation_results(project, run_id) == []


def test_repeating_a_p7_step_on_one_source_run_creates_distinct_artifacts(tmp_path) -> None:
    """A second confirmed workflow must not collide with the first result path."""

    frame = pd.DataFrame(
        {
            "row": ["a"] * 12 + ["b"] * 12,
            "column": ["x"] * 10 + ["y"] * 2 + ["x"] * 3 + ["y"] * 9,
        }
    )
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    first_draft = _compile_p7(
        (run_id, artifact_id), frame, workflow_id="wf-p7-repeat-1"
    )
    first = WorkflowExecutor(project).execute(
        first_draft,
        build_workflow_step_executor(project, first_draft),
    )
    second_draft = _compile_p7(
        (run_id, artifact_id), frame, workflow_id="wf-p7-repeat-2"
    )
    second = WorkflowExecutor(project).execute(
        second_draft,
        build_workflow_step_executor(project, second_draft),
    )

    assert first.status == "completed", first.steps["categorical_association"].error
    assert second.status == "completed", second.steps["categorical_association"].error
    first_artifact = first.steps["categorical_association"].artifact_ids[0]
    second_artifact = second.steps["categorical_association"].artifact_ids[0]
    assert first_artifact != second_artifact
    assert len(collect_post_estimation_results(project, run_id)) == 2


def test_every_registered_p7_operation_completes_through_compiled_workflow(tmp_path) -> None:
    """Every registered operation reaches the runtime without false success.

    The Hurdle negative-binomial fixture is intentionally non-convergent.  Its
    expected outcome is a failed workflow with no committed P7 artifact; the
    matrix treats that explicit failure as a successful safety result.
    """

    from workbench.agent.p7_pack_registry import p7_pack_registry

    cases = _cases()
    operation_ids = set(p7_pack_registry.operation_ids())
    assert {key for key in cases if ":" not in key} == operation_ids
    expected_fixture_failures = {
        "glm.hurdle_negative_binomial": "GLM_NONCONVERGENCE",
    }
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
            expected_reason = expected_fixture_failures.get(operation_id)
            if expected_reason is not None:
                assert state.status == "failed", step_state.error
                assert step_state.status == "failed"
                assert expected_reason in (step_state.error or "")
                assert not step_state.artifact_ids
                assert collect_post_estimation_results(project, run_id) == []
                continue
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


def test_hurdle_negative_binomial_success_fixture_completes_generic_workflow(
    tmp_path,
) -> None:
    """The Hurdle NB operation has a verified success path as well as its failure fixture."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    frame, request = _hurdle_negative_binomial_success_case()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    operation_id = request["operation_id"]
    step_id = "hurdle_negative_binomial_success"
    draft = compile_workflow(
        workflow_id="wf-p7-hurdle-negative-binomial-success",
        target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:p7-hurdle-negative-binomial-success",
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
        available_columns=list(frame.columns),
    )

    state = WorkflowExecutor(project).execute(
        draft,
        build_workflow_step_executor(project, draft),
    )

    assert state.status == "completed", state.steps[step_id].error
    assert state.steps[step_id].artifact_ids
    operation = p7_pack_registry.get(operation_id)
    operation.validate(request)
    result = operation.execute(frame, request)
    operation.validate_result(result)
    assert result["result"]["status"] == "completed"
    assert result["result"]["inference"]["positive_count"] == {
        "standard_error_method": "bfgs_inverse_hessian_approximation",
        "p_value_method": "normal_wald_approximation",
        "p_value_status": "approximate",
    }


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
                    "options": {"correction": False},
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
