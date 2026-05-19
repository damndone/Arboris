"""Tests for GET /runs/{id}/graph."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.graph_model import BranchRef, Graph, Node, NodeKind
from workbench.graph_store import GraphStore


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Create a project-like temp directory with a runs/ subdirectory."""
    runs_dir = tmp_path / "runs"
    runs_dir.mkdir()
    return tmp_path


def _seed_run(runs_root: Path, run_id: str, with_graph: bool) -> None:
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    if with_graph:
        store = GraphStore(runs_root=runs_root)
        graph = Graph(
            schema_version=1,
            run_id=run_id,
            nodes={
                "stage:raw": Node(
                    id="stage:raw",
                    kind=NodeKind.DATASET_STAGE,
                    display_label="Raw",
                    created_at="2026-05-13T10:00:00+00:00",
                    parent_stage_id=None,
                    branch_id="main",
                )
            },
            edges={},
            branches={"main": BranchRef(id="main", forked_from_node_id=None, head_node_ids=("stage:raw",))},
        )
        store.write(graph)


def test_get_graph_returns_persisted_graph(project_root: Path):
    runs_root = project_root / "runs"
    _seed_run(runs_root, "run_present", with_graph=True)
    client = TestClient(app)
    response = client.get("/runs/run_present/graph", params={"project_root": str(project_root)})
    assert response.status_code == 200
    data = response.json()
    assert data["run_id"] == "run_present"
    assert data["legacy"] is False
    assert "stage:raw" in data["nodes"]


def test_get_graph_returns_legacy_for_pre_v14_run(project_root: Path):
    runs_root = project_root / "runs"
    _seed_run(runs_root, "run_legacy", with_graph=False)
    client = TestClient(app)
    response = client.get("/runs/run_legacy/graph", params={"project_root": str(project_root)})
    assert response.status_code == 200
    data = response.json()
    assert data["legacy"] is True
    assert data["nodes"] == {}
    assert data["edges"] == {}


def test_get_graph_404_for_unknown_run(project_root: Path):
    client = TestClient(app)
    response = client.get("/runs/does_not_exist/graph", params={"project_root": str(project_root)})
    assert response.status_code == 404


def test_get_graph_422_for_corrupt_json(project_root: Path):
    runs_root = project_root / "runs"
    run_dir = runs_root / "run_corrupt"
    run_dir.mkdir(parents=True)
    (run_dir / "graph.json").write_text("this is not valid json", encoding="utf-8")

    client = TestClient(app)
    response = client.get("/runs/run_corrupt/graph", params={"project_root": str(project_root)})
    assert response.status_code == 422
    data = response.json()
    assert data["error"]["code"] == "GRAPH_CORRUPT"


def test_get_graph_422_for_missing_keys(project_root: Path):
    runs_root = project_root / "runs"
    run_dir = runs_root / "run_bad_keys"
    run_dir.mkdir(parents=True)
    import json
    (run_dir / "graph.json").write_text(
        json.dumps({"wrong_key": "no schema_version or run_id"}), encoding="utf-8",
    )

    client = TestClient(app)
    response = client.get("/runs/run_bad_keys/graph", params={"project_root": str(project_root)})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "GRAPH_CORRUPT"


def test_get_graph_returns_stats_block(project_root: Path):
    runs_root = project_root / "runs"
    _seed_run(runs_root, "run_present", with_graph=True)
    client = TestClient(app)
    response = client.get("/runs/run_present/graph", params={"project_root": str(project_root)})
    assert response.status_code == 200
    body = response.json()
    assert "stats" in body
    stats = body["stats"]
    assert isinstance(stats["node_count"], int)
    assert isinstance(stats["edge_count"], int)
    assert isinstance(stats["leaf_count"], int)
    assert isinstance(stats["has_dp_count"], int)


def test_get_graph_response_has_summary_field_on_nodes(project_root: Path):
    runs_root = project_root / "runs"
    _seed_run(runs_root, "run_present", with_graph=True)
    client = TestClient(app)
    response = client.get("/runs/run_present/graph", params={"project_root": str(project_root)})
    body = response.json()
    for node in body["nodes"].values():
        assert "summary" in node


def test_get_graph_schema_version_is_2(project_root: Path):
    runs_root = project_root / "runs"
    _seed_run(runs_root, "run_present", with_graph=True)
    client = TestClient(app)
    response = client.get("/runs/run_present/graph", params={"project_root": str(project_root)})
    assert response.json()["schema_version"] == 2
