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


def _wait_terminal(project_root: Path, run_id: str, tries: int = 100) -> str:
    terminal = {"completed", "failed", "cancelled", "interrupted", "partial"}
    for _ in range(tries):
        body = client.get(f"/runs/{run_id}", params={"project_root": str(project_root)}).json()
        if body.get("status") in terminal:
            return body["status"]
        time.sleep(0.1)
    return body.get("status")


def _create_terminal_run(project_root: Path) -> str:
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
    model = next(n for n in graph["nodes"].values() if n.get("stage") == "model")
    return model["id"]


def test_rerun_unknown_from_node_422(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": "does:not:exist", "op_overrides": {"covariance": "robust"}},
    )
    assert resp.status_code == 422


def test_rerun_unknown_override_key_422(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": node_id, "op_overrides": {"bogus": "x"}},
    )
    assert resp.status_code == 422


def test_rerun_creates_child_with_rerun_of(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": node_id, "op_overrides": {"covariance": "unadjusted"}},
    )
    assert resp.status_code == 200
    child = resp.json()["run_id"]
    assert child != parent
    _wait_terminal(project.root, child)
    inputs = json.loads((project.root / "runs" / child / "run_inputs.json").read_text())
    assert inputs["rerun_of"] == parent
    assert inputs["from_node"] == node_id
    assert inputs["form"]["covariance"] == "unadjusted"
    assert inputs["override_hash"] is not None
    parent_inputs = json.loads((project.root / "runs" / parent / "run_inputs.json").read_text())
    assert inputs["upload"]["sha256"] == parent_inputs["upload"]["sha256"]


def test_rerun_on_running_parent_409(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)
    mpath = project.root / "runs" / parent / "run_manifest.json"
    m = json.loads(mpath.read_text())
    m["status"] = "running"
    mpath.write_text(json.dumps(m))
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": node_id, "op_overrides": {"covariance": "robust"}},
    )
    assert resp.status_code == 409
