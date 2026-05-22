"""Tests for GET /runs/{id}/graph."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.graph_model import BranchRef, DecisionPoint, Edge, Graph, Node, NodeKind
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


def test_get_graph_stats_counts_leaves_and_dp_nodes(project_root: Path):
    runs_root = project_root / "runs"
    run_dir = runs_root / "run_stats"
    run_dir.mkdir(parents=True)
    raw = Node(
        id="stage:raw",
        kind=NodeKind.DATASET_STAGE,
        display_label="Raw",
        created_at="2026-05-13T10:00:00+00:00",
        parent_stage_id=None,
        branch_id="main",
    )
    cleaned = Node(
        id="stage:cleaned",
        kind=NodeKind.DATASET_STAGE,
        display_label="Cleaned",
        created_at="2026-05-13T10:01:00+00:00",
        parent_stage_id=None,
        branch_id="main",
        decision_points=(DecisionPoint(decision_id="handle_missing_values"),),
    )
    report = Node(
        id="report:html",
        kind=NodeKind.REPORT,
        display_label="HTML report",
        created_at="2026-05-13T10:02:00+00:00",
        parent_stage_id=None,
        branch_id="main",
    )
    graph = Graph(
        schema_version=2,
        run_id="run_stats",
        nodes={node.id: node for node in (raw, cleaned, report)},
        edges={
            "e_raw_cleaned": Edge(
                id="e_raw_cleaned",
                source_id="stage:raw",
                target_id="stage:cleaned",
                op="clean",
            )
        },
        branches={
            "main": BranchRef(
                id="main",
                forked_from_node_id=None,
                head_node_ids=("stage:cleaned", "report:html"),
            )
        },
    )
    GraphStore(runs_root=runs_root).write(graph)

    client = TestClient(app)
    response = client.get("/runs/run_stats/graph", params={"project_root": str(project_root)})

    assert response.status_code == 200
    assert response.json()["stats"] == {
        "node_count": 3,
        "edge_count": 1,
        "leaf_count": 2,
        "has_dp_count": 1,
    }


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


def test_get_graph_upcasts_v1_file_on_disk(project_root: Path):
    """A V1.4.0-era graph.json (schema_version=1, decision_point singular) sitting
    on disk must be read by the endpoint, upcast to schema_version=2, and
    returned with legacy=False — the file IS lineage data, just an older shape.

    Regression guard: bypasses GraphStore.write() (which stamps v2) by writing
    raw v1 JSON directly, so this exercises the real on-disk legacy path that
    real V1.4.0 users would hit after upgrading to V1.4.1.
    """
    import json as _json
    runs_root = project_root / "runs"
    run_dir = runs_root / "run_v1_legacy"
    run_dir.mkdir(parents=True)
    v1_payload = {
        "schema_version": 1,
        "run_id": "run_v1_legacy",
        "nodes": {
            "stage:raw": {
                "id": "stage:raw",
                "kind": "dataset_stage",
                "display_label": "Raw",
                "created_at": "2026-05-13T10:00:00+00:00",
                "parent_stage_id": None,
                "branch_id": "main",
                "trust": "ok",
                "trust_reason": None,
                "archived": False,
                "payload_ref": None,
            },
            "model:ols_1": {
                "id": "model:ols_1",
                "kind": "model",
                "display_label": "OLS",
                "created_at": "2026-05-13T10:01:00+00:00",
                "parent_stage_id": None,
                "branch_id": "main",
                "trust": "ok",
                "trust_reason": None,
                "archived": False,
                "payload_ref": None,
                # V1.4.0 singular field shape — must round-trip via list.
                "decision_point": {
                    "decision_id": "model_type_auto_select",
                    "decision_id_alias": [],
                    "selected": "continuous",
                    "candidates": [],
                    "source": "data_driven_default",
                    "contestability": {
                        "is_contestable": True,
                        "assumption_checks_needed": [],
                        "warnings": [],
                        "review_status": "needed",
                    },
                    "reason": None,
                },
            },
        },
        "edges": {},
        "branches": {},
    }
    (run_dir / "graph.json").write_text(_json.dumps(v1_payload), encoding="utf-8")

    client = TestClient(app)
    response = client.get(
        "/runs/run_v1_legacy/graph", params={"project_root": str(project_root)}
    )
    assert response.status_code == 200
    body = response.json()
    # The endpoint must upcast to v2 in the response shape ...
    assert body["schema_version"] == 2
    # ... while NOT marking the run as legacy (a v1 file IS data, it has
    # nodes — legacy=True is reserved for completely-missing graph.json).
    assert body["legacy"] is False
    # ... and the singular decision_point must be promoted to a list.
    assert "decision_points" in body["nodes"]["model:ols_1"]
    dps = body["nodes"]["model:ols_1"]["decision_points"]
    assert len(dps) == 1
    assert dps[0]["decision_id"] == "model_type_auto_select"
