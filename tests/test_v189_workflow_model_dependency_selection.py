"""P0 guards for selecting model dependencies in mixed workflow inputs."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from workbench.agent.workflow import WorkflowExecutionError, WorkflowStepResult
from workbench.agent.workflow_runtime import _dependent_model_branch


def _canonical_branch() -> dict[str, object]:
    return {
        "branch_id": "m1",
        "branch_spec": {
            "model_family": "ols",
            "covariance": "unadjusted",
            "outcome": "outcome",
            "predictors": ["rate_a"],
        },
        "term_groups": {
            "linear": {"rate_a": ["rate_a"]},
            "polynomial": {},
            "categorical": {},
        },
    }


def _post_estimation_step(*dependencies: str) -> SimpleNamespace:
    return SimpleNamespace(
        step_id="white",
        depends_on=dependencies,
        operation_id="model.white_test",
        spec={"branch_id": "m1", "output_id": "result"},
    )


def test_model_branch_selection_skips_separate_source_dependency() -> None:
    branch = _canonical_branch()
    model = WorkflowStepResult(
        output_bindings={
            "model_branches": {
                "binding_type": "model_branches",
                "branches": [branch],
            }
        }
    )
    source = WorkflowStepResult(
        payload={"produced_dataset": {"artifact_id": "derived-data"}}
    )

    resolved = _dependent_model_branch(
        _post_estimation_step("model", "source"),
        {"model": model, "source": source},
    )

    assert resolved == branch


def test_malformed_selected_model_binding_still_fails_closed() -> None:
    model = WorkflowStepResult(
        output_bindings={
            "model_branches": {
                "binding_type": "model_branches",
                "branches": "not-a-list",
            }
        }
    )
    source = WorkflowStepResult(
        payload={"produced_dataset": {"artifact_id": "derived-data"}}
    )

    with pytest.raises(WorkflowExecutionError, match="canonical model branch"):
        _dependent_model_branch(
            _post_estimation_step("model", "source"),
            {"model": model, "source": source},
        )
