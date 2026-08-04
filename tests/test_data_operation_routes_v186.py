"""HTTP contract tests for the user-reachable v1.8.6 data operations."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.app import app
from workbench.artifacts import sha256_file, write_json
from workbench.graph_model import BranchRef, Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore


def _secondary_source(
    project: Path,
    run_id: str,
    frame: pd.DataFrame,
    artifact_id: str,
) -> None:
    root = project / "runs" / run_id
    root.mkdir()
    path = root / "data.csv"
    frame.to_csv(path, index=False)
    write_json(
        root / "artifacts_index.json",
        {
            "schema_version": 1,
            "artifacts": [
                {
                    "artifact_id": artifact_id,
                    "path": "data.csv",
                    "artifact_type": "raw_data",
                    "step": "fixture",
                    "sha256": sha256_file(path),
                    "inputs": [],
                }
            ],
        },
    )
    node = Node(
        id="stage:source",
        kind=NodeKind.DATASET_STAGE,
        display_label="Secondary source",
        created_at="2026-07-15T00:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        payload_ref="data.csv",
        summary="secondary source",
        stage=Stage.SOURCE,
    )
    GraphStore(project / "runs").write(
        Graph(
            schema_version=3,
            run_id=run_id,
            nodes={node.id: node},
            edges={},
            branches={"main": BranchRef("main", None, (node.id,))},
        )
    )


def test_transform_route_enforces_nested_merge_growth_policy(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "value": [10, 20]}),
    )
    _secondary_source(
        project,
        "run_merge_right",
        pd.DataFrame({"id": [2, 3], "extra": [30, 40]}),
        "merge_right_data",
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json={
                "source_run_id": run_id,
                "source_node_id": "stage:source",
                "source_artifact_id": artifact_id,
                "operation": "merge",
                "parameters": {
                    "keys": ["id"],
                    "how": "inner",
                    "growth_policy": {"max_rows": 0},
                },
                "secondary_run_id": "run_merge_right",
                "secondary_node_id": "stage:source",
                "secondary_artifact_id": "merge_right_data",
            },
        )

    assert response.status_code == 422, response.text
    assert "DATA_MERGE_ROW_EXPANSION_BLOCKED" in json.dumps(response.json())


def test_transform_route_rejects_append_schema_mismatch_before_artifact(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "value": [10, 20]}),
    )
    _secondary_source(
        project,
        "run_append_right",
        pd.DataFrame({"id": [3], "other": [30]}),
        "append_right_data",
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json={
                "source_run_id": run_id,
                "source_node_id": "stage:source",
                "source_artifact_id": artifact_id,
                "operation": "append",
                "parameters": {
                    "schema_policy": "exact",
                    "row_growth_policy": {"max_rows": 10},
                },
                "secondary_run_id": "run_append_right",
                "secondary_node_id": "stage:source",
                "secondary_artifact_id": "append_right_data",
            },
        )

    assert response.status_code == 422, response.text
    assert "DATA_APPEND_SCHEMA_INCOMPATIBLE" in json.dumps(response.json())


def test_transform_route_transfers_complete_long_to_wide_payload(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame(
            {
                "id": [1, 1, 2, 2],
                "metric": ["score", "cost", "score", "cost"],
                "value": [10.0, 4.0, 20.0, 5.0],
            }
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json={
                "source_run_id": run_id,
                "source_node_id": "stage:source",
                "source_artifact_id": artifact_id,
                "operation": "reshape",
                "parameters": {
                    "direction": "long_to_wide",
                    "index": ["id"],
                    "columns": "metric",
                    "values": "value",
                },
            },
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["spec"]["parameters"] == {
        "direction": "long_to_wide",
        "index": ["id"],
        "columns": "metric",
        "values": "value",
    }
    assert payload["preview"]["output_columns"] == ["id", "cost", "score"]


def test_transform_route_rejects_out_of_range_subset_range_stably(tmp_path: Path) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"id": [1, 2], "value": [10, 20]}),
    )

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/data-operations/transform/preview",
            params={"project_root": str(project)},
            json={
                "source_run_id": run_id,
                "source_node_id": "stage:source",
                "source_artifact_id": artifact_id,
                "operation": "subset",
                "parameters": {
                    "columns": ["id", "value"],
                    "row_index_range": {"start": 1, "stop": 10},
                },
            },
        )

    assert response.status_code == 422, response.text
    assert "DATA_SUBSET_ROW_INDEX_INVALID" in json.dumps(response.json())
