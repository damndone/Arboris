"""2B.3 — POST /rerun incremental wiring + from_node replacement semantics.

With WORKBENCH_INCREMENTAL_CACHE on, a rerun flows through the node-level Merkle cache
(orchestrator `run_pipeline_traced`). The `from_node` is the *replaced* op node: the new
model branch reuses the parent's shared upstream stage-output (same node_hash) and the new
model is a SIBLING of the old one off that shared prefix — never chained after it (spec §3.4).
"""
import io
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project

client = TestClient(app)


def _csv() -> bytes:
    rows = "\n".join(f"{1 + 2 * i},{i}" for i in range(35))
    return ("y,x\n" + rows + "\n").encode()


def _wait_terminal(project_root: Path, run_id: str, tries: int = 120) -> str:
    terminal = {"completed", "failed", "cancelled", "interrupted", "partial"}
    for _ in range(tries):
        body = client.get(f"/runs/{run_id}", params={"project_root": str(project_root)}).json()
        if body.get("status") in terminal:
            return body["status"]
        time.sleep(0.1)
    return body.get("status")


def _create_run(project_root: Path) -> str:
    resp = client.post(
        "/runs",
        data={"project_root": str(project_root), "mode": "auto",
              "model_type": "ols", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    )
    run_id = resp.json()["run_id"]
    _wait_terminal(project_root, run_id)
    return run_id


def _model_node_id(project_root: Path, run_id: str) -> str:
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": str(project_root)}).json()
    return next(n["id"] for n in graph["nodes"].values() if n.get("stage") == "model")


def test_rerun_records_from_node_and_reuses_upstream(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    parent = _create_run(project.root)
    parent_model = _model_node_id(project.root, parent)

    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": parent_model, "op_overrides": {"covariance": "unadjusted"}},
    )
    assert resp.status_code == 200
    child = resp.json()["run_id"]
    _wait_terminal(project.root, child)

    # (1) from_node is recorded as the replaced op node.
    inputs = json.loads((project.root / "runs" / child / "run_inputs.json").read_text())
    assert inputs["from_node"] == parent_model
    assert inputs["rerun_of"] == parent

    # (2) Upstream cleaning stage reuses identity: same node_hash as the parent, status
    #     recomputed_same_hash (not a fresh miss_executed); estimation is the new compute.
    def _trace(run_id: str) -> dict[str, dict]:
        tr = json.loads((project.root / "runs" / run_id / "incremental_trace.json").read_text())
        return {t["stage"]: t for t in tr}

    parent_trace, child_trace = _trace(parent), _trace(child)
    assert child_trace["cleaning"]["node_hash"] == parent_trace["cleaning"]["node_hash"]
    assert child_trace["cleaning"]["status"] in {"hit_reused", "recomputed_same_hash"}
    assert child_trace["estimation"]["status"] == "miss_executed"
    assert child_trace["estimation"]["node_hash"] != parent_trace["estimation"]["node_hash"]


def test_rerun_new_model_is_sibling_not_chained(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("WORKBENCH_INCREMENTAL_CACHE", "1")
    project = create_project(tmp_path, "demo")
    parent = _create_run(project.root)
    parent_model = _model_node_id(project.root, parent)
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": parent_model, "op_overrides": {"covariance": "unadjusted"}},
    )
    child = resp.json()["run_id"]
    _wait_terminal(project.root, child)

    hs = client.get(
        f"/runs/{child}/graph",
        params={"project_root": str(project.root), "view": "headset"},
    ).json()
    stage_of = {key: n.get("producing_stage") for key, n in hs["nodes"].items()}

    # Both estimation (model) nodes hang off the shared cleaning prefix — sibling fork.
    est_keys = {k for k, s in stage_of.items() if s == "estimation"}
    assert len(est_keys) == 2  # M1 and M2
    for key in est_keys:
        parents = [e["source"] for e in hs["edges"] if e["target"] == key]
        assert parents, f"estimation node {key} has no parent edge"
        # Parent of each model is the cleaning output, never another estimation node.
        assert all(stage_of[p] == "cleaning" for p in parents)
    # No estimation -> estimation edge (M1 is NOT chained before M2).
    assert not any(
        stage_of.get(e["source"]) == "estimation" and stage_of.get(e["target"]) == "estimation"
        for e in hs["edges"]
    )
