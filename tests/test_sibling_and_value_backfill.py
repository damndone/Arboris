"""2B.4 — head-set sibling semantics + editable_schema.value backfill.

After forking A→B (covariance override), the two model nodes are siblings off the shared
upstream prefix, and the head-set edit schema shows each run's REAL current value
(run_inputs.form) rather than the capabilities default. Runs whose form leaves a param
unset keep the capabilities default (missing-key fallback).
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
    run_id = client.post(
        "/runs",
        data={"project_root": str(project_root), "mode": "auto",
              "model_type": "ols", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    ).json()["run_id"]
    _wait_terminal(project_root, run_id)
    return run_id


def _model_node_id(project_root: Path, run_id: str) -> str:
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": str(project_root)}).json()
    return next(n["id"] for n in graph["nodes"].values() if n.get("stage") == "model")


def _covariance_value(node: dict) -> str | None:
    for param in node.get("editable_schema") or []:
        if param.get("key") == "covariance":
            return param.get("value")
    return None


def test_sibling_models_and_value_backfill(monkeypatch, tmp_path: Path) -> None:
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

    hs = client.get(
        f"/runs/{child}/graph",
        params={"project_root": str(project.root), "view": "headset"},
    ).json()

    est_nodes = [n for n in hs["nodes"].values() if n.get("producing_stage") == "estimation"]
    assert len(est_nodes) == 2

    by_run = {n["runs"][0]: n for n in est_nodes}
    child_model = by_run[child]
    parent_model_view = by_run[parent]

    # Siblings: both estimation nodes share the same cleaning parent hash.
    def _parent_hashes(key: str) -> set[str]:
        return {e["source"] for e in hs["edges"] if e["target"] == key}
    child_key = next(k for k, n in hs["nodes"].items() if n is child_model)
    parent_key = next(k for k, n in hs["nodes"].items() if n is parent_model_view)
    assert _parent_hashes(child_key) == _parent_hashes(parent_key)
    assert _parent_hashes(child_key)  # non-empty shared parent

    # Value backfill: child shows the overridden covariance; parent keeps the default.
    child_inputs = json.loads((project.root / "runs" / child / "run_inputs.json").read_text())
    assert child_inputs["form"]["covariance"] == "unadjusted"
    assert child_model["editable_schema_source"] == "run_inputs"
    assert _covariance_value(child_model) == "unadjusted"
    # Parent run never set covariance (auto) -> capabilities default preserved.
    assert _covariance_value(parent_model_view) == "robust"


def test_legacy_per_run_graph_schema_unchanged(tmp_path: Path) -> None:
    # The non-headset path must stay byte-compatible: capabilities source, no backfill.
    project = create_project(tmp_path, "demo")
    run_id = _create_run(project.root)
    graph = client.get(
        f"/runs/{run_id}/graph", params={"project_root": str(project.root)}
    ).json()
    model = next(n for n in graph["nodes"].values() if n.get("stage") == "model")
    assert model["editable_schema_source"] == "capabilities"
