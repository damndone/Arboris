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


def test_headset_uses_newest_presentation_for_one_shared_result_node(
    monkeypatch, tmp_path: Path
) -> None:
    """A corrected later label must not be masked by an old merged Graph node."""

    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    parent = _create_run(project.root)
    node_id = _model_node_id(project.root, parent)
    response = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": node_id, "op_overrides": {}},
    )
    assert response.status_code == 200
    child = response.json()["run_id"]
    _wait_terminal(project.root, child)

    for run_id, label, summary, created_at in (
        (parent, "legacy presentation", "legacy summary", "2026-01-01T00:00:00+00:00"),
        (child, "canonical presentation", "canonical summary", "2026-01-02T00:00:00+00:00"),
    ):
        graph_path = project.root / "runs" / run_id / "graph.json"
        graph = json.loads(graph_path.read_text(encoding="utf-8"))
        graph["nodes"][node_id].update(
            {
                "display_label": label,
                "summary": summary,
                "created_at": created_at,
            }
        )
        graph_path.write_text(json.dumps(graph), encoding="utf-8")

    parent_index_path = project.root / "runs" / parent / "node_index.json"
    child_index_path = project.root / "runs" / child / "node_index.json"
    parent_index = json.loads(parent_index_path.read_text(encoding="utf-8"))
    child_index = json.loads(child_index_path.read_text(encoding="utf-8"))
    child_index[node_id]["node_hash"] = parent_index[node_id]["node_hash"]
    child_index_path.write_text(json.dumps(child_index), encoding="utf-8")

    body = client.get(
        f"/runs/{parent}/graph",
        params={"project_root": str(project.root), "view": "headset"},
    ).json()
    shared_model = next(
        node
        for node in body["nodes"].values()
        if node.get("id") == node_id
        and set(node.get("runs", [])) == {parent, child}
    )

    assert shared_model["display_label"] == "canonical presentation"
    assert shared_model["summary"] == "canonical summary"


def test_headset_exposes_run_level_rerun_from_on_child_head(tmp_path: Path):
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
    run_inputs_path = project.root / "runs" / child / "run_inputs.json"
    run_inputs = json.loads(run_inputs_path.read_text(encoding="utf-8"))
    run_inputs.update(
        {
            "rerun_of": parent,
            "from_node": "model:ols_1",
            "rerun_from": {
                "owner_run_id": parent,
                "op_node_id": "model:ols_1",
                "node_hash": "hash_parent_model",
                "context_fingerprint": "nocv1:parent",
                "rerun_request_id": "req_headset",
            },
        }
    )
    run_inputs_path.write_text(
        json.dumps(run_inputs),
        encoding="utf-8",
    )
    body = client.get(
        f"/runs/{child}/graph",
        params={"project_root": str(project.root), "view": "headset"},
    ).json()
    child_head = next(head for head in body["heads"] if head["run_id"] == child)
    assert child_head["rerun_from"]["rerun_request_id"] == "req_headset"
    child_model = next(
        node
        for node in body["nodes"].values()
        if node.get("id") == "model:ols_1" and node.get("runs") == [child]
    )
    assert child_model["produced_by_rerun_request_id"] == "req_headset"


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
