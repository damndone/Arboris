"""v1.8.10 step 2d: post-estimation steps run on completed model nodes.

A `postestimation.*` step reads the model's kernel through the workflow
runtime, persists a post-estimation artifact on the run, is classified as an
inferential, read-only step, and refuses with the property that is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workbench.contracts.common.errors import OperationValidationError
from workbench.agent.read_only_policy import decide
from workbench.agent.workflow import WorkflowExecutionError, compile_workflow
from workbench.agent.workflow_runtime import build_workflow_step_executor, collect_post_estimation_results
from workbench.analysis_ledger import step_category
from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.postestimation import wald_test
from workbench.projects import create_project

DATA = Path(__file__).parent / "fixtures" / "postestimation" / "data.csv"


def _run(root: Path, name: str, **kwargs) -> tuple[Path, str]:
    project = create_project(root, name)
    outcome = run_workflow(project.root, [DATA], mode="auto", **kwargs)
    assert outcome["status"] == "completed", outcome
    return project.root, outcome["run_id"]


@pytest.fixture(scope="module")
def logit_run(tmp_path_factory) -> tuple[Path, str]:
    return _run(tmp_path_factory.mktemp("pe-steps"), "logit", model_type="logit", y="yb", x=["x1", "x2", "x3"])


def _execute(project: Path, run_id: str, steps: list[dict]):
    draft = compile_workflow(
        workflow_id=f"wf-{steps[0]['step_id']}",
        target={"run_id": run_id, "node_ref": "stage:cleaned", "artifact_id": "cleaned_dataset"},
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "sha256:postestimation",
            "active_head_run_id": run_id,
            "owner_resolution": "single_candidate",
        },
        steps=steps,
        available_columns=["y", "yb", "yc", "ynb", "x1", "x2", "x3", "yo", "ym"],
    )
    execute = build_workflow_step_executor(project, draft)
    return [execute(step, {}) for step in draft.steps]


JOINT = [{"terms": {"x1": 1}, "value": 0}, {"terms": {"x2": 1}, "value": 0}]


def test_a_wald_step_reads_the_selected_models_kernel(logit_run) -> None:
    project, run_id = logit_run
    [result] = _execute(project, run_id, [{
        "step_id": "joint", "operation_id": "postestimation.wald",
        "spec": {"model_ref": "model:logit_1", "constraints": JOINT},
    }])
    kernel = read_json(project / "runs" / run_id / kernel_relative_path("logit_1"))
    expected = wald_test(kernel, JOINT)
    produced = result.payload["result"]
    assert produced["statistic"] == expected["statistic"]
    assert produced["distribution"] == "chi2" and produced["df_num"] == 2
    assert produced["model_id"] == "logit_1"

    persisted = collect_post_estimation_results(project, run_id, keep_latest=True)
    assert any(item["result"].get("operation") == "wald" for item in persisted), persisted


def test_a_forest_key_names_the_same_model(logit_run) -> None:
    project, run_id = logit_run
    [result] = _execute(project, run_id, [{
        "step_id": "lincom", "operation_id": "postestimation.lincom",
        "spec": {"model_ref": "a" * 64 + "::model:logit_1", "terms": {"x1": 1, "x2": 2}},
    }])
    assert result.payload["result"]["operation"] == "lincom"


def test_margins_read_the_estimation_sample_from_lineage(logit_run) -> None:
    project, run_id = logit_run
    [result] = _execute(project, run_id, [{
        "step_id": "ame", "operation_id": "postestimation.margins",
        "spec": {"model_ref": "model:logit_1", "variables": ["x1"]},
    }])
    stored = read_json(project / "runs" / run_id / "model_results" / "logit_1.json")["marginal_effects"]
    [effect] = result.payload["result"]["effects"]
    assert effect["estimate"] == pytest.approx(next(r["dy/dx"] for r in stored if r["term"] == "x1"), rel=1e-9)


def test_lr_compares_models_in_two_runs(tmp_path, logit_run) -> None:
    project, run_id = logit_run
    restricted = run_workflow(project, [DATA], mode="auto", model_type="logit", y="yb", x=["x1"])
    [result] = _execute(project, run_id, [{
        "step_id": "lr", "operation_id": "postestimation.lr",
        "spec": {
            "model_ref": "model:logit_1", "restricted_model_ref": "model:logit_1",
            "restricted_model_run_id": restricted["run_id"],
        },
    }])
    assert result.payload["result"]["df"] == 2


def test_a_refusal_reaches_the_agent_with_its_reason(logit_run) -> None:
    project, run_id = logit_run
    restricted = run_workflow(project, [DATA], mode="auto", model_type="logit", y="yb", x=["x1"])
    with pytest.raises(WorkflowExecutionError, match="strict subset"):
        _execute(project, run_id, [{
            "step_id": "reversed", "operation_id": "postestimation.lr",
            "spec": {
                "model_ref": "model:logit_1", "model_run_id": restricted["run_id"],
                "restricted_model_ref": "model:logit_1", "restricted_model_run_id": run_id,
            },
        }])
    with pytest.raises(WorkflowExecutionError, match="does not exist"):
        _execute(project, run_id, [{
            "step_id": "missing", "operation_id": "postestimation.wald",
            "spec": {"model_ref": "model:logit_1", "constraints": JOINT,
                     "model_run_id": "20990101_000000_000000_deadbeef"},
        }])


def test_a_model_ref_that_is_not_a_model_is_refused_at_plan_time(logit_run) -> None:
    project, run_id = logit_run
    with pytest.raises(OperationValidationError, match="model node"):
        _execute(project, run_id, [{
            "step_id": "bad", "operation_id": "postestimation.wald",
            "spec": {"model_ref": "stage:cleaned", "constraints": JOINT},
        }])


def test_post_estimation_is_inferential_and_runs_without_confirmation() -> None:
    assert step_category("postestimation.wald") == "inferential"
    decision = decide(
        "operation.multi_step",
        {"steps": [{"operation_id": "postestimation.wald", "spec": {}}]},
        prior_inferential_steps=0,
    )
    assert decision.allowed and decision.inferential_steps == 1
