"""2B.2 — head-set graph response behind WORKBENCH_GRAPH_HEADSET / ?view=headset.

Flag-off (default) must keep the legacy per-run graph shape byte-for-byte (existing FE
contract). Flag-on / ?view=headset returns the family head-set: a union DAG keyed by
node_hash (shared-prefix nodes appear once), a `heads` list (one per family member), a
bumped schema_version, and a `legacy` degrade flag.
"""
import io
import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project

client = TestClient(app)


def _csv() -> bytes:
    rows = "\n".join(f"{1 + 2 * i},{i}" for i in range(35))
    return ("y,x\n" + rows + "\n").encode()


def _wait_terminal(project_root: Path, run_id: str, tries: int = 100) -> str:
    terminal = {"completed", "failed", "cancelled", "interrupted", "partial"}
    for _ in range(tries):
        body = client.get(f"/runs/{run_id}", params={"project_root": str(project_root)}).json()
        if body.get("status") in terminal:
            return body["status"]
        time.sleep(0.1)
    return body.get("status")


def _create_run(project_root: Path, model_type: str = "ols") -> str:
    resp = client.post(
        "/runs",
        data={"project_root": str(project_root), "mode": "auto",
              "model_type": model_type, "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    )
    run_id = resp.json()["run_id"]
    _wait_terminal(project_root, run_id)
    return run_id


def _model_node_id(project_root: Path, run_id: str) -> str:
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": str(project_root)}).json()
    model = next(n for n in graph["nodes"].values() if n.get("stage") == "model")
    return model["id"]


def test_graph_flag_off_is_legacy_shape(tmp_path: Path) -> None:
    project = create_project(tmp_path, "demo")
    run_id = _create_run(project.root)
    body = client.get(
        f"/runs/{run_id}/graph", params={"project_root": str(project.root)}
    ).json()
    # Legacy contract: nodes is a dict keyed by node_id, no `heads` key.
    assert "model:ols_1" in body["nodes"]
    assert "heads" not in body
    assert "stats" in body


def test_headset_view_shape(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    run_id = _create_run(project.root)
    body = client.get(
        f"/runs/{run_id}/graph",
        params={"project_root": str(project.root), "view": "headset"},
    ).json()
    assert body["legacy"] is False
    assert "heads" in body and len(body["heads"]) == 1
    head = body["heads"][0]
    assert head["run_id"] == run_id
    assert head["head_node_hash"]
    # nodes keyed by node_hash for cacheable stages.
    hashes = {n.get("node_hash") for n in body["nodes"].values()}
    assert head["head_node_hash"] in hashes
    assert "schema_version" in body


def test_headset_dedups_shared_prefix_across_family(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    parent = _create_run(project.root)
    node_id = _model_node_id(project.root, parent)
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": node_id, "op_overrides": {"covariance": "unadjusted"}},
    )
    assert resp.status_code == 200
    child = resp.json()["run_id"]
    _wait_terminal(project.root, child)

    body = client.get(
        f"/runs/{child}/graph",
        params={"project_root": str(project.root), "view": "headset"},
    ).json()
    # Two family heads (parent + child).
    assert len(body["heads"]) == 2
    run_ids = {h["run_id"] for h in body["heads"]}
    assert run_ids == {parent, child}
    # Shared cleaned-dataset node appears exactly once across the family (deduped by
    # node_id + node_hash); its per-variable nodes are kept distinct (so variables stay
    # visible) but each still dedups across the two runs to a single node.
    cleaned_nodes = [n for n in body["nodes"].values() if n.get("id") == "stage:cleaned"]
    assert len(cleaned_nodes) == 1
    assert set(cleaned_nodes[0]["runs"]) == {parent, child}
    var_ids = [n.get("id") for n in body["nodes"].values()
               if str(n.get("id", "")).startswith("var:")]
    assert var_ids and len(var_ids) == len(set(var_ids))  # each variable once, not per-run
    # Two distinct model nodes (M1 / M2) — sibling branches off the shared prefix.
    model_hashes = {h for n in body["nodes"].values()
                    if n.get("producing_stage") == "estimation"
                    for h in [n.get("node_hash")]}
    assert len(model_hashes) == 2


def test_headset_legacy_run_degrades(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKBENCH_GRAPH_HEADSET", "1")
    project = create_project(tmp_path, "demo")
    run_id = _create_run(project.root)
    # v1.6.1: node_index is now ALWAYS written. A *legacy* run is one that predates the
    # lineage index — simulate by removing it, then the head-set degrades to old shape.
    (project.root / "runs" / run_id / "node_index.json").unlink()
    body = client.get(
        f"/runs/{run_id}/graph", params={"project_root": str(project.root)}
    ).json()
    # Legacy target (no node_index): degrade to old shape with legacy marker.
    assert body.get("legacy") is True
    assert "model:ols_1" in body["nodes"]
