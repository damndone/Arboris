"""Post-estimation evidence reaches the run surface a user actually opens.

A declared post-estimation step already persisted a provenance-carrying
artifact, but no product surface read it, so the question that prompted the
workflow went unanswered on screen. These tests pin the serve-layer half of
that projection.

The workflow's own source fixture is not a materialized run, so the HTTP
assertions run against the child run Genesis creates -- which is also the run
a user opens to read the model, and therefore the one that matters here.
"""
from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from tests.test_workflow_runtime import _compile
from workbench.agent.workflow import WorkflowExecutor
from workbench.agent.workflow_runtime import (
    build_workflow_step_executor,
    collect_post_estimation_results,
)
from workbench.api import app
from workbench.events import get_event_manager
from workbench.lineage.run_inputs import write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes


@pytest.fixture(autouse=True)
def _reset_event_manager():
    """Claim a clean single-worker run slot.

    These tests execute real runs, and the event manager is a process-wide
    singleton: a slot leaked by an earlier test makes Genesis fail with
    "429: A run is already in progress." Declaring the requirement is the
    repository's existing convention for tests that actually submit runs.
    """

    get_event_manager()._reset_for_testing()


def _curved_frame() -> pd.DataFrame:
    exposure = [float(index - 24) for index in range(48)]
    return pd.DataFrame(
        {
            "response": [
                20.0 + 1.8 * value - 0.12 * value**2 + (2.0 if index % 2 else -1.0)
                for index, value in enumerate(exposure)
            ],
            "exposure": exposure,
        }
    )


def _run_workflow(tmp_path, *, with_stationary_point: bool):
    """Execute a curved-model workflow and return (project, source, model run)."""

    frame = _curved_frame()
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
    steps = [
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
                        "polynomials": [{"column": "exposure", "degree": 2}],
                    }
                ],
            },
        }
    ]
    if with_stationary_point:
        steps.append(
            {
                "step_id": "locate_stationary_point",
                "operation_id": "model.quadratic_stationary_point",
                "depends_on": ["estimate_curved_model"],
                "spec": {"branch_id": "curved", "column": "exposure"},
            }
        )
    draft = _compile(
        (run_id, artifact_id), frame, workflow_id="wf-projection", steps=steps
    )
    state = WorkflowExecutor(project).execute(
        draft, build_workflow_step_executor(project, draft)
    )
    assert state.status == "completed", {
        step_id: step.error for step_id, step in state.steps.items() if step.error
    }

    if with_stationary_point:
        entry = next(
            item
            for item in collect_post_estimation_results(project, run_id)
            if item["operation_id"] == "model.quadratic_stationary_point"
        )
        return project, run_id, entry["model_run_id"]

    assert state.steps["estimate_curved_model"].status == "completed"
    return project, run_id, _model_run_from_project(project, run_id)


def _model_run_from_project(project, source_run_id: str) -> str:
    """The one run Genesis created for this workflow."""

    created = sorted(
        item.name
        for item in (project / "runs").iterdir()
        if item.is_dir() and item.name != source_run_id
    )
    assert len(created) == 1, created
    return created[0]


def _stationary_entries(payload):
    return [
        entry
        for entry in payload["post_estimation_results"]
        if entry["operation_id"] == "model.quadratic_stationary_point"
    ]


def test_run_detail_projects_post_estimation_results_on_the_model_run(tmp_path) -> None:
    """The child run the user opens carries the evidence about its own model."""

    project, source_run_id, model_run_id = _run_workflow(
        tmp_path, with_stationary_point=True
    )
    assert model_run_id != source_run_id
    api = TestClient(app)

    response = api.get(f"/runs/{model_run_id}", params={"project_root": str(project)})
    assert response.status_code == 200, response.text
    entries = _stationary_entries(response.json())
    assert len(entries) == 1
    entry = entries[0]
    # Persisted on the source run, but reachable from the model it describes.
    assert entry["run_id"] == source_run_id
    assert entry["model_run_id"] == model_run_id
    assert entry["workflow_id"] == "wf-projection"
    assert entry["workflow_step_id"] == "locate_stationary_point"
    assert entry["artifact_type"] == "post_estimation"
    assert entry["result"]["column"] == "exposure"
    assert entry["result"]["stationary_point_within_observed_range"] is True


def test_run_detail_omits_post_estimation_results_when_none_were_declared(
    tmp_path,
) -> None:
    """A model run with no declared post-estimation step projects nothing."""

    project, _source_run_id, model_run_id = _run_workflow(
        tmp_path, with_stationary_point=False
    )
    api = TestClient(app)

    response = api.get(f"/runs/{model_run_id}", params={"project_root": str(project)})
    assert response.status_code == 200, response.text
    assert response.json()["post_estimation_results"] == []


def test_run_detail_ignores_an_unregistered_artifact_file(tmp_path) -> None:
    """Only indexed evidence is published; a loose file is not a finding.

    The artifacts index is the admission record. Reading the directory instead
    would let anything able to write into a run directory publish a result
    through the product surface.
    """

    project, _source_run_id, model_run_id = _run_workflow(
        tmp_path, with_stationary_point=False
    )
    stray = (
        project / "runs" / model_run_id / "artifacts" / "post_estimation" / "stray.json"
    )
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text(
        json.dumps(
            {
                "source": {"run_id": model_run_id, "model_run_id": model_run_id},
                "result": {"stationary_point": 1.0},
            }
        ),
        encoding="utf-8",
    )
    api = TestClient(app)

    response = api.get(f"/runs/{model_run_id}", params={"project_root": str(project)})
    assert response.status_code == 200, response.text
    assert response.json()["post_estimation_results"] == []
