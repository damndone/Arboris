"""Input-bound identities for workflow dataset-producing steps."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from tests.test_data_column_cast import _source_project as _legacy_source_project
from workbench.agent.workflow import compile_workflow
from workbench.agent.workflow_runtime import (
    _admit_workflow_host_endpoint_from_supervisor,
    build_workflow_step_executor,
    issue_server_evidence_port,
)
from workbench.artifacts import initialize_artifact_index, register_artifact
from workbench.graph_model import BranchRef, Graph, Node, NodeKind, Stage, Trust
from workbench.graph_store import GraphStore
import workbench.agent.workflow_runtime as workflow_runtime


def _source_project(tmp_path: Path, frame: pd.DataFrame) -> tuple[Path, str, str]:
    project, run_id, artifact_id = _legacy_source_project(tmp_path, frame)
    run_root = project / "runs" / run_id
    initialize_artifact_index(run_root)
    register_artifact(
        run_root,
        artifact_id,
        run_root / "data.csv",
        "raw_data",
        "fixture",
        [],
    )
    return project, run_id, artifact_id


def _add_same_bytes_source(
    project: Path, run_id: str, source_artifact_id: str = "alternate_source"
) -> str:
    run_root = project / "runs" / run_id
    alternate_path = run_root / "alternate.csv"
    alternate_path.write_bytes((run_root / "data.csv").read_bytes())
    register_artifact(
        run_root,
        source_artifact_id,
        alternate_path,
        "raw_data",
        "fixture",
        [],
    )

    def add_source(graph: Graph) -> Graph:
        node_id = "stage:alternate"
        node = Node(
            id=node_id,
            kind=NodeKind.DATASET_STAGE,
            display_label="Alternate source data",
            created_at="2026-08-21T00:00:00+00:00",
            parent_stage_id=None,
            branch_id="alternate",
            trust=Trust.OK,
            payload_ref="alternate.csv",
            summary="Alternate source with the same bytes and a different binding",
            stage=Stage.SOURCE,
        )
        return Graph(
            schema_version=graph.schema_version,
            run_id=graph.run_id,
            nodes={**graph.nodes, node_id: node},
            edges=dict(graph.edges),
            branches={
                **graph.branches,
                "alternate": BranchRef(
                    id="alternate",
                    forked_from_node_id="stage:source",
                    head_node_ids=(node_id,),
                ),
            },
            legacy=graph.legacy,
        )

    GraphStore(project / "runs").mutate(run_id, add_source)
    return source_artifact_id


def _numeric_step() -> dict[str, object]:
    return {
        "step_id": "derive",
        "operation_id": "statistical.derive_numeric",
        "spec": {
            "recipes": [
                {
                    "operator": "multiply",
                    "input_columns": ["size", "weight"],
                    "output_name": "weighted_size",
                }
            ]
        },
    }


def _compile(
    *,
    project: Path,
    run_id: str,
    artifact_id: str,
    node_ref: str,
    workflow_id: str,
    frame: pd.DataFrame,
    steps: list[dict[str, object]] | None = None,
):
    return compile_workflow(
        workflow_id=workflow_id,
        target={"run_id": run_id, "node_ref": node_ref, "artifact_id": artifact_id},
        preconditions={
            "context_fingerprint": "sha256:fixed-workflow-source-context",
            "source_artifact_fingerprint": "sha256:fixed-workflow-source-context",
            "active_head_run_id": run_id,
        },
        steps=steps if steps is not None else [_numeric_step()],
        available_columns=list(frame.columns),
    )


def _admitted_executor(project: Path, draft):
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
            evidence_port = issue_server_evidence_port(project)
    finally:
        os.close(endpoint_fd)
    return evidence_port, build_workflow_step_executor(
        project,
        draft,
        evidence_port=evidence_port,
    )


def _execute_one(evidence_port, executor, draft):
    step = draft.steps[0]
    receipt = evidence_port.admit(draft, step)
    if receipt.completed_result is not None:
        return receipt.completed_result
    try:
        result = executor(step, {}, admission_receipt=receipt)
        evidence_port.complete(receipt, result)
        return result
    except Exception as exc:
        evidence_port.abort(receipt, str(exc))
        raise


def test_same_numeric_transform_on_different_source_bindings_has_distinct_identity(
    tmp_path: Path,
) -> None:
    """A source-bound transform cannot reuse one child/node-index identity."""

    frame = pd.DataFrame(
        {
            "size": [1.0, 2.0, 3.0, 4.0],
            "weight": [3.0, 3.0, 3.0, 3.0],
        }
    )
    project, run_id, source_artifact_id = _source_project(tmp_path, frame)
    alternate_artifact_id = _add_same_bytes_source(project, run_id)
    source_draft = _compile(
        project=project,
        run_id=run_id,
        artifact_id=source_artifact_id,
        node_ref="stage:source",
        workflow_id="workflow_identity_source",
        frame=frame,
    )
    alternate_draft = _compile(
        project=project,
        run_id=run_id,
        artifact_id=alternate_artifact_id,
        node_ref="stage:alternate",
        workflow_id="workflow_identity_alternate",
        frame=frame,
    )

    assert source_draft.steps[0].fingerprint == alternate_draft.steps[0].fingerprint

    source_port, source_executor = _admitted_executor(project, source_draft)
    alternate_port, alternate_executor = _admitted_executor(project, alternate_draft)
    try:
        source_result = _execute_one(source_port, source_executor, source_draft)
        alternate_result = _execute_one(
            alternate_port, alternate_executor, alternate_draft
        )
    finally:
        source_port.close()
        alternate_port.close()

    source_binding = source_result.payload["produced_dataset"]
    alternate_binding = alternate_result.payload["produced_dataset"]
    assert source_binding["node_ref"] != alternate_binding["node_ref"]
    assert source_binding["artifact_id"] != alternate_binding["artifact_id"]


def test_same_numeric_input_replay_reuses_identity_and_node_index_entry(
    tmp_path: Path,
) -> None:
    """A completed input replay is idempotent at the child and index layers."""

    frame = pd.DataFrame(
        {
            "size": [1.0, 2.0, 3.0, 4.0],
            "weight": [3.0, 3.0, 3.0, 3.0],
        }
    )
    project, run_id, source_artifact_id = _source_project(tmp_path, frame)
    draft = _compile(
        project=project,
        run_id=run_id,
        artifact_id=source_artifact_id,
        node_ref="stage:source",
        workflow_id="workflow_identity_replay",
        frame=frame,
    )
    evidence_port, executor = _admitted_executor(project, draft)
    try:
        first = _execute_one(evidence_port, executor, draft)
        replay = _execute_one(evidence_port, executor, draft)
    finally:
        evidence_port.close()

    first_binding = first.payload["produced_dataset"]
    replay_binding = replay.payload["produced_dataset"]
    assert replay_binding == first_binding
    node_index = json.loads(
        (project / "runs" / run_id / "node_index.json").read_text(encoding="utf-8")
    )
    assert list(node_index) == [first_binding["node_ref"]]


def test_capability_dataset_on_different_source_bindings_has_distinct_identity(
    tmp_path: Path,
) -> None:
    """The generic dataset capability uses the same source-bound identity rule."""

    frame = pd.DataFrame(
        {
            "wave": [0, 0, 0, 0, 1, 1],
            "size": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "rate_a": [1.0, 1.5, 2.0, 2.5, 3.0, 3.5],
        }
    )
    project, run_id, source_artifact_id = _source_project(tmp_path, frame)
    alternate_artifact_id = _add_same_bytes_source(project, run_id)
    step = {
        "step_id": "resample",
        "operation_id": "imputation.mice",
        "spec": {
            "input_mode": "frame",
            "column_bindings": {"columns": ["wave", "size", "rate_a"]},
            "options": {},
        },
    }
    source_draft = _compile(
        project=project,
        run_id=run_id,
        artifact_id=source_artifact_id,
        node_ref="stage:source",
        workflow_id="workflow_capability_source",
        frame=frame,
        steps=[step],
    )
    alternate_draft = _compile(
        project=project,
        run_id=run_id,
        artifact_id=alternate_artifact_id,
        node_ref="stage:alternate",
        workflow_id="workflow_capability_alternate",
        frame=frame,
        steps=[step],
    )
    assert source_draft.steps[0].fingerprint == alternate_draft.steps[0].fingerprint

    source_port, source_executor = _admitted_executor(project, source_draft)
    alternate_port, alternate_executor = _admitted_executor(project, alternate_draft)
    try:
        source_result = _execute_one(source_port, source_executor, source_draft)
        alternate_result = _execute_one(
            alternate_port, alternate_executor, alternate_draft
        )
    finally:
        source_port.close()
        alternate_port.close()

    source_binding = source_result.payload["produced_dataset"]
    alternate_binding = alternate_result.payload["produced_dataset"]
    assert source_binding["node_ref"] != alternate_binding["node_ref"]
    assert source_binding["artifact_id"] != alternate_binding["artifact_id"]
