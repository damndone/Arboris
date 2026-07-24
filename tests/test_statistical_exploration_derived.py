from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

from tests.test_data_column_cast import _source_project
from workbench.app import app
from workbench.graph_store import GraphStore
from workbench.statistical_exploration import ExplorationSpec, execute_exploration


def test_percentile_derived_boolean_returns_threshold_and_bounded_preview() -> None:
    frame = pd.DataFrame({"totreg": [10, 20, 30, 40], "pfl": [1.0, 2.0, 3.0, 4.0]})
    result = execute_exploration(
        frame,
        ExplorationSpec(
            operation="derive_boolean",
            selected_columns=("totreg",),
            options={
                "source_column": "totreg",
                "percentile": 25,
                "comparison": "lte",
                "output_name": "small_school",
            },
        ),
    )

    assert result["derived"]["source_column"] == "totreg"
    assert result["derived"]["threshold"] == 17.5
    assert result["derived"]["comparison"] == "lte"
    assert result["derived"]["output_name"] == "small_school"
    assert result["derived"]["counts"] == {"true": 1, "false": 3, "missing": 0}
    assert len(result["derived"]["preview"]) <= 20


def test_derived_boolean_confirm_creates_one_child_artifact_recipe_and_graph_node(
    tmp_path: Path,
) -> None:
    project, run_id, artifact_id = _source_project(
        tmp_path,
        pd.DataFrame({"totreg": [10, 20, 30, 40], "pfl": [1.0, 2.0, 3.0, 4.0]}),
    )
    request = {
        "source_run_id": run_id,
        "source_node_id": "stage:source",
        "source_artifact_id": artifact_id,
        "operation": "derive_boolean",
        "selected_columns": ["totreg"],
        "filters": [],
        "options": {
            "source_column": "totreg",
            "percentile": 25,
            "comparison": "lte",
            "output_name": "small_school",
        },
    }

    with TestClient(app) as client:
        preview = client.post(
            "/statistical-explorations/preview",
            params={"project_root": str(project)},
            json=request,
        ).json()["preview"]
        body = {**request, "preview_fingerprint": preview["fingerprint"]}
        first = client.post(
            "/statistical-explorations/confirm",
            params={"project_root": str(project)},
            json=body,
        )
        second = client.post(
            "/statistical-explorations/confirm",
            params={"project_root": str(project)},
            json=body,
        )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["derived"] == second.json()["derived"]
    derived = first.json()["derived"]
    assert derived["child_node_id"].startswith("data-derive:")
    assert derived["threshold"] == 17.5
    frame = pd.read_csv(project / "runs" / run_id / derived["artifact_path"])
    assert frame["small_school"].tolist() == [True, False, False, False]
    recipe = json.loads((project / "runs" / run_id / derived["recipe_path"]).read_text())
    assert recipe["source"]["artifact_id"] == artifact_id
    assert recipe["definition"]["threshold"] == 17.5
    graph = GraphStore(project / "runs").read(run_id)
    assert derived["child_node_id"] in graph.nodes
    assert any(
        edge.source_id == "stage:source"
        and edge.target_id == derived["child_node_id"]
        and edge.op == "data.derive.boolean"
        for edge in graph.edges.values()
    )
