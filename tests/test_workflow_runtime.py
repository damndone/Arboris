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
    collect_post_estimation_results,
)
from workbench.lineage.run_inputs import write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes


def test_model_family_contracts_declare_existing_ols_and_panel_semantics() -> None:
    """The workflow core declares, rather than infers, each admitted family."""

    from workbench.agent.workflow_contracts import MODEL_FAMILY_CONTRACTS

    assert set(MODEL_FAMILY_CONTRACTS) == {"ols", "panel_ols"}

    ols = MODEL_FAMILY_CONTRACTS["ols"]
    assert ols.family == "ols"
    assert ols.required_spec_fields == ()
    assert set(ols.forbidden_spec_fields) == {"entity_col", "time_col"}
    assert set(ols.expected_artifacts) == {"ols_1", "diagnostic_summary"}
    assert ols.result_shape == "coefficient_intervals"
    assert callable(ols.build_model_params)

    panel = MODEL_FAMILY_CONTRACTS["panel_ols"]
    assert panel.family == "panel_ols"
    assert set(panel.required_spec_fields) == {"entity_col", "time_col"}
    assert panel.forbidden_spec_fields == ()
    assert panel.expected_artifacts == ("panel_ols_1",)
    assert panel.result_shape == "coefficient_intervals"
    assert callable(panel.build_model_params)


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


def _panel_frame() -> pd.DataFrame:
    """A generic balanced panel with within-entity and within-time variation."""

    rows: list[dict[str, float | int | str]] = []
    for entity_index, school in enumerate(("a", "b", "c", "d", "e", "f")):
        for time_index, year in enumerate((2016, 2017, 2018, 2019, 2020)):
            exposure = float((entity_index * 3 + time_index * 2) % 11 + 1)
            rows.append(
                {
                    "school": school,
                    "year": year,
                    "exposure": exposure,
                    "outcome": (
                        40.0
                        + entity_index * 5.0
                        + time_index * 2.0
                        + 1.4 * exposure
                        - 0.08 * exposure**2
                        + (0.25 if (entity_index + time_index) % 2 else -0.15)
                    ),
                }
            )
    return pd.DataFrame(rows)


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


def test_ols_step_preserves_each_declared_branch_covariance(tmp_path) -> None:
    """Sibling OLS branches may differ only in their declared covariance."""

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
    steps = composed_plan()
    model_spec = next(step["spec"] for step in steps if step["operation_id"] == "model.genesis")
    model_spec["branches"][0]["covariance"] = "robust"
    model_spec["branches"][1]["covariance"] = "unadjusted"
    draft = _compile((run_id, artifact_id), frame, workflow_id="wf-ols-covariance", steps=steps)
    model_step = next(step for step in draft.steps if step.operation_id == "model.genesis")

    result = _execute_ols_branches(
        project, draft, {"source_sha256": upload_sha}, frame, model_step
    )

    persisted = {
        branch["branch_id"]: json.loads(
            (project / "runs" / branch["run_id"] / "model_results" / "ols_1.json").read_text(
                encoding="utf-8"
            )
        )
        for branch in result.payload["branches"]
    }
    assert persisted["m1"]["covariance"] == "robust"
    assert persisted["m1"]["covariance_estimator"] == "HC1"
    assert persisted["m2"]["covariance"] == "unadjusted"
    assert persisted["m2"]["covariance_estimator"] == "nonrobust"


def test_panel_genesis_step_runs_two_way_fixed_effects_with_entity_clusters(tmp_path) -> None:
    """A registered panel model family is executable through typed workflow composition."""

    pytest.importorskip("linearmodels")
    frame = _panel_frame()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    upload_sha = store_upload_bytes(
        project, frame.to_csv(index=False).encode("utf-8"), filename="panel_fixture.csv"
    )
    write_run_inputs(
        project / "runs" / run_id,
        form={"model_type": "auto", "y": "", "x": ""},
        upload={"sha256": upload_sha, "filename": "panel_fixture.csv"},
        rerun_of=None,
        from_node=None,
        rerun_reason="initial",
        override_hash=None,
        dag_hash="panel-fixture-dag",
    )
    draft = _compile(
        (run_id, artifact_id),
        frame,
        workflow_id="wf-panel-runtime",
        steps=[
            {
                "step_id": "estimate_panel",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "panel_ols",
                    "covariance": "clustered",
                    "entity_col": "school",
                    "time_col": "year",
                    "branches": [
                        {
                            "branch_id": "two_way_fe",
                            "outcome": "outcome",
                            "predictors": ["exposure"],
                            "polynomials": [{"column": "exposure", "degree": 2}],
                        }
                    ],
                },
            }
        ],
    )

    state = WorkflowExecutor(project).execute(
        draft, build_workflow_step_executor(project, draft)
    )

    assert state.status == "completed"
    model_ref = next(
        artifact
        for artifact in state.steps["estimate_panel"].artifact_ids
        if artifact.endswith(":panel_ols_1")
    )
    run_id = model_ref.split(":", 1)[0]
    result = json.loads(
        (project / "runs" / run_id / "model_results" / "panel_ols_1.json").read_text(
            encoding="utf-8"
        )
    )
    assert result["model_type"] == "panel_ols"
    assert result["covariance"] == "clustered"
    assert result["entity_col"] == "school"
    assert result["time_col"] == "year"
    assert result["covariance_evidence"]["cluster_variable"] == "school"
    assert result["coefficients"]["exposure"]["ci_lower"] is not None
    assert result["coefficients"]["exposure_pow2"]["ci_upper"] is not None


def test_composed_panel_and_dummy_fixed_effects_branches_share_point_estimate(tmp_path) -> None:
    """One typed workflow may compare equivalent panel and dummy-FE branches.

    This is deliberately a runtime-level oracle: both branches are compiled,
    admitted, and executed by ``operation.multi_step`` before their persisted
    public model results are compared.  It therefore catches accidental
    fallback of a panel branch to the generic OLS artifact path.
    """

    pytest.importorskip("linearmodels")
    frame = _panel_frame()
    project, source_run_id, artifact_id = _source_project(tmp_path, frame)
    upload_sha = store_upload_bytes(
        project, frame.to_csv(index=False).encode("utf-8"), filename="panel_fixture.csv"
    )
    write_run_inputs(
        project / "runs" / source_run_id,
        form={"model_type": "auto", "y": "", "x": ""},
        upload={"sha256": upload_sha, "filename": "panel_fixture.csv"},
        rerun_of=None,
        from_node=None,
        rerun_reason="initial",
        override_hash=None,
        dag_hash="panel-comparison-fixture-dag",
    )
    draft = _compile(
        (source_run_id, artifact_id),
        frame,
        workflow_id="wf-panel-dummy-equivalence",
        steps=[
            {
                "step_id": "estimate_panel",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "panel_ols",
                    "covariance": "robust",
                    "entity_col": "school",
                    "time_col": "year",
                    "branches": [
                        {
                            "branch_id": "panel_two_way",
                            "outcome": "outcome",
                            "predictors": ["exposure"],
                        }
                    ],
                },
            },
            {
                "step_id": "estimate_dummy_fe",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "ols",
                    "covariance": "robust",
                    "branches": [
                        {
                            "branch_id": "dummy_two_way",
                            "outcome": "outcome",
                            "predictors": ["exposure"],
                            "categorical": ["school", "year"],
                        }
                    ],
                },
            },
        ],
    )

    state = WorkflowExecutor(project).execute(
        draft, build_workflow_step_executor(project, draft)
    )

    assert state.status == "completed"
    panel_ref = next(
        artifact
        for artifact in state.steps["estimate_panel"].artifact_ids
        if artifact.endswith(":panel_ols_1")
    )
    dummy_ref = next(
        artifact
        for artifact in state.steps["estimate_dummy_fe"].artifact_ids
        if artifact.endswith(":ols_1")
    )
    panel_run_id = panel_ref.split(":", 1)[0]
    dummy_run_id = dummy_ref.split(":", 1)[0]
    panel = json.loads(
        (project / "runs" / panel_run_id / "model_results" / "panel_ols_1.json").read_text(
            encoding="utf-8"
        )
    )
    dummy = json.loads(
        (project / "runs" / dummy_run_id / "model_results" / "ols_1.json").read_text(
            encoding="utf-8"
        )
    )

    assert panel["model_type"] == "panel_ols"
    # The generic OLS family persists its robust covariance variant under the
    # explicit ``ols_robust`` result type; it must not be a panel artifact.
    assert dummy["model_type"] == "ols_robust"
    assert dummy["covariance"] == "robust"
    assert panel["coefficients"]["exposure"]["estimate"] == pytest.approx(
        dummy["coefficients"]["exposure"]["estimate"], abs=1e-8
    )


def _post_estimation_results(project, run_id, state, step_ids):
    """Read each declared post-estimation step's persisted result."""

    index = json.loads(
        (project / "runs" / run_id / "artifacts_index.json").read_text(encoding="utf-8")
    )
    records = {record["artifact_id"]: record for record in index["artifacts"]}
    out = {}
    for step_id in step_ids:
        record = records[state.steps[step_id].artifact_ids[0]]
        out[step_id] = json.loads(
            (project / "runs" / run_id / record["path"]).read_text(encoding="utf-8")
        )["result"]
    return out


def _curved_post_estimation_state(tmp_path, covariance: str):
    """Run the same curved design under one declared covariance."""

    rows = 48
    exposure = [float(index - 24) for index in range(rows)]
    frame = pd.DataFrame(
        {
            "response": [
                20.0
                + 1.8 * value
                - 0.12 * value**2
                # Deliberate heteroskedasticity: the robust and unadjusted
                # covariances must not agree, or the assertion below is vacuous.
                + ((index % 7) - 3) * (1.0 + abs(value) * 0.6)
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
        workflow_id=f"wf-cov-{covariance}",
        steps=[
            {
                "step_id": "estimate",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "ols",
                    "covariance": covariance,
                    "branches": [
                        {
                            "branch_id": "curved",
                            "outcome": "response",
                            "predictors": ["exposure"],
                            "polynomials": [{"column": "exposure", "degree": 2}],
                        }
                    ],
                },
            },
            {
                "step_id": "joint",
                "operation_id": "model.joint_f_test",
                "depends_on": ["estimate"],
                "spec": {
                    "branch_id": "curved",
                    "term_selectors": [{"kind": "polynomial", "column": "exposure"}],
                },
            },
            {
                "step_id": "stationary",
                "operation_id": "model.quadratic_stationary_point",
                "depends_on": ["estimate"],
                "spec": {"branch_id": "curved", "column": "exposure"},
            },
        ],
    )
    state = WorkflowExecutor(project).execute(
        draft, build_workflow_step_executor(project, draft)
    )
    assert state.status == "completed", {
        step_id: step.error for step_id, step in state.steps.items() if step.error
    }
    return _post_estimation_results(
        project, run_id, state, ["joint", "stationary"]
    )


def test_post_estimation_inference_uses_the_model_declared_covariance(tmp_path) -> None:
    """A joint test must answer for the model the user actually fitted.

    The F statistic depends on the covariance estimator, so refitting a robust
    branch under an unadjusted vcov reports a p-value that belongs to a model
    nobody estimated -- and labels it with the model's own provenance. The
    label and the arithmetic have to move together.
    """

    robust = _curved_post_estimation_state(tmp_path / "robust", "robust")
    unadjusted = _curved_post_estimation_state(tmp_path / "plain", "unadjusted")

    assert robust["joint"]["covariance"] == "robust"
    assert unadjusted["joint"]["covariance"] == "unadjusted"
    # Not just a relabelling: the inference itself differs under the two
    # estimators on a deliberately heteroskedastic design.
    assert robust["joint"]["f_statistic"] != pytest.approx(
        unadjusted["joint"]["f_statistic"], rel=1e-6
    )

    # The stationary point is a ratio of coefficients, so it is invariant to the
    # covariance choice; only its reported provenance changes.
    assert robust["stationary"]["covariance"] == "robust"
    assert robust["stationary"]["stationary_point"] == pytest.approx(
        unadjusted["stationary"]["stationary_point"], rel=1e-9
    )


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
            {
                "step_id": "test_white_heteroskedasticity",
                "operation_id": "model.white_test",
                "depends_on": ["estimate_curved_model"],
                "spec": {"branch_id": "curved"},
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
    white_record = records[state.steps["test_white_heteroskedasticity"].artifact_ids[0]]
    assert joint_record["artifact_type"] == "statistical_test"
    assert stationary_record["artifact_type"] == "post_estimation"
    assert white_record["artifact_type"] == "statistical_test"

    joint = json.loads(
        (project / "runs" / run_id / joint_record["path"]).read_text(encoding="utf-8")
    )["result"]
    stationary = json.loads(
        (project / "runs" / run_id / stationary_record["path"]).read_text(encoding="utf-8")
    )["result"]
    white = json.loads(
        (project / "runs" / run_id / white_record["path"]).read_text(encoding="utf-8")
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
    assert white["test"] == "white_test"
    assert white["branch_id"] == "curved"
    assert white["nobs"] == 48
    assert white["lm_statistic"] >= 0
    assert 0 <= white["lm_p_value"] <= 1
    assert white["f_statistic"] >= 0
    assert 0 <= white["f_p_value"] <= 1

    # The result is only evidence a user can act on if a product surface can
    # find it. The workflow persists on the *source* run, but the reader who
    # asked the question opens the child model run, so the projection has to
    # be reachable from both identities.
    from_source = collect_post_estimation_results(project, run_id)
    assert {entry["operation_id"] for entry in from_source} == {
        "model.joint_f_test",
        "model.quadratic_stationary_point",
        "model.white_test",
    }
    stationary_entry = next(
        entry
        for entry in from_source
        if entry["operation_id"] == "model.quadratic_stationary_point"
    )
    assert stationary_entry["run_id"] == run_id
    assert stationary_entry["workflow_step_id"] == "locate_stationary_point"
    assert stationary_entry["result"]["stationary_point"] == pytest.approx(7.5, abs=0.2)

    model_run_id = stationary_entry["model_run_id"]
    assert model_run_id and model_run_id != run_id
    from_model_run = collect_post_estimation_results(project, model_run_id)
    assert [entry["artifact_id"] for entry in from_model_run] == [
        entry["artifact_id"] for entry in from_source
    ]


def test_post_estimation_projection_is_bounded_and_ignores_unregistered_files(
    tmp_path,
) -> None:
    """The projection reads the artifacts index, never the directory listing.

    An unregistered file dropped next to real evidence must not become a
    result: the index is the admission record, and honouring loose files on
    disk would let anything that can write to the run directory publish a
    finding through the product surface.
    """

    frame = _frame()
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    run_root = project / "runs" / run_id
    stray = run_root / "artifacts" / "post_estimation" / "stray.json"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text(
        json.dumps({"result": {"schema_version": "forged", "value": 1}}),
        encoding="utf-8",
    )

    assert collect_post_estimation_results(project, run_id) == []
    assert collect_post_estimation_results(project, run_id, limit=0) == []


def test_white_test_handles_a_high_scale_polynomial_categorical_design(tmp_path) -> None:
    """White's auxiliary regression uses one stable rank policy for valid designs."""

    rows = 420
    position = pd.Series(range(rows), dtype="float64")
    scale = 250.0 + 31.0 * position
    frame = pd.DataFrame(
        {
            "outcome": 40.0 + 0.03 * scale + 0.00001 * scale**2 + (position % 7) / 10.0,
            "scale": scale,
            **{
                f"ratio_{index}": ((position * (index + 3)) % (29 + index)) / (29 + index)
                for index in range(8)
            },
            "wave": [f"wave_{index % 6}" for index in range(rows)],
            "group": [f"group_{index % 2}" for index in range(rows)],
            "region": [f"region_{index % 5}" for index in range(rows)],
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
        workflow_id="wf-white-stable-rank",
        steps=[
            {
                "step_id": "estimate_main",
                "operation_id": "model.genesis",
                "spec": {
                    "model_family": "ols",
                    "covariance": "unadjusted",
                    "branches": [
                        {
                            "branch_id": "main",
                            "outcome": "outcome",
                            "predictors": [
                                "scale",
                                *[f"ratio_{index}" for index in range(8)],
                            ],
                            "categorical": ["wave", "group", "region"],
                            "polynomials": [{"column": "scale", "degree": 2}],
                        }
                    ],
                },
            },
            {
                "step_id": "test_white",
                "operation_id": "model.white_test",
                "depends_on": ["estimate_main"],
                "spec": {"branch_id": "main"},
            },
        ],
    )

    state = WorkflowExecutor(project).execute(
        draft, build_workflow_step_executor(project, draft)
    )

    assert state.status == "completed"
    assert state.steps["test_white"].artifact_ids


def test_numeric_transform_reaches_model_and_declared_joint_test(tmp_path) -> None:
    """A later model may use a declared product without a formula/code escape."""

    rows = 60
    left = [1.0 + (index % 13) for index in range(rows)]
    right = [2.0 + ((index * 5) % 17) for index in range(rows)]
    product = [first * second for first, second in zip(left, right)]
    frame = pd.DataFrame(
        {
            "response": [
                8.0 + 0.7 * first + 0.25 * second + 0.08 * combined
                + (0.2 if index % 2 else -0.2)
                for index, (first, second, combined) in enumerate(
                    zip(left, right, product)
                )
            ],
            "left_exposure": left,
            "right_exposure": right,
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
        workflow_id="wf-numeric-model-post-estimation",
        steps=[
            {
                "step_id": "derive_product",
                "operation_id": "statistical.derive_numeric",
                "spec": {
                    "recipes": [
                        {
                            "operator": "multiply",
                            "input_columns": ["left_exposure", "right_exposure"],
                            "output_name": "exposure_product",
                        }
                    ]
                },
            },
            {
                "step_id": "estimate_interaction",
                "operation_id": "model.genesis",
                "depends_on": ["derive_product"],
                "spec": {
                    "model_family": "ols",
                    "covariance": "unadjusted",
                    "branches": [
                        {
                            "branch_id": "interaction",
                            "outcome": "response",
                            "predictors": [
                                "left_exposure",
                                "right_exposure",
                                "exposure_product",
                            ],
                        }
                    ],
                },
            },
            {
                "step_id": "test_interaction",
                "operation_id": "model.joint_f_test",
                "depends_on": ["estimate_interaction"],
                "spec": {
                    "branch_id": "interaction",
                    "term_selectors": [
                        {"kind": "linear", "column": "exposure_product"}
                    ],
                },
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
    joint_record = records[state.steps["test_interaction"].artifact_ids[0]]
    joint = json.loads(
        (project / "runs" / run_id / joint_record["path"]).read_text(encoding="utf-8")
    )["result"]
    assert joint["term_selectors"] == [
        {"kind": "linear", "column": "exposure_product"}
    ]
    assert joint["f_statistic"] > 0


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
