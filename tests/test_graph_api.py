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
