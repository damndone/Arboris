import io
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.projects import create_project

client = TestClient(app)

_TERMINAL = {"completed", "failed", "cancelled", "interrupted", "partial", "blocked"}


def _csv() -> bytes:
    rows = "\n".join(f"{1 + 2 * i},{i}" for i in range(35))
    return ("y,x\n" + rows + "\n").encode()


def _wait_terminal(project_root: Path, run_id: str) -> None:
    for _ in range(100):
        b = client.get(f"/runs/{run_id}", params={"project_root": str(project_root)}).json()
        if b.get("status") in _TERMINAL:
            return
        time.sleep(0.1)


def _terminal(project_root: Path) -> str:
    rid = client.post(
        "/runs",
        data={"project_root": str(project_root), "mode": "auto",
              "model_type": "ols", "y": "y", "x": "x"},
        files={"file": ("d.csv", io.BytesIO(_csv()), "text/csv")},
    ).json()["run_id"]
    _wait_terminal(project_root, rid)
    return rid


def _model_node_id(project_root: Path, run_id: str) -> str:
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": str(project_root)}).json()
    return next(n for n in graph["nodes"].values() if n.get("stage") == "model")["id"]


def test_rerun_appends_immutable_child_without_mutating_parent(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _terminal(project.root)
    parent_graph_before = (project.root / "runs" / parent / "graph.json").read_text()
    node_id = _model_node_id(project.root, parent)

    child = client.post(
        f"/runs/{parent}/rerun", params={"project_root": str(project.root)},
        json={"from_node": node_id, "op_overrides": {"covariance": "unadjusted"}},
    ).json()["run_id"]
    _wait_terminal(project.root, child)

    # Invariant 1: parent graph.json unchanged by the rerun.
    assert (project.root / "runs" / parent / "graph.json").read_text() == parent_graph_before

    child_inputs = json.loads((project.root / "runs" / child / "run_inputs.json").read_text())
    # Invariants 2-3: exactly one parent, recorded as rerun_of; distinct run.
    assert child_inputs["rerun_of"] == parent
    assert child != parent

    # Invariant 5: child recomputed its own derived artifacts (did not inherit the
    # parent's graph.json — its content embeds the child's own run_id).
    child_graph = (project.root / "runs" / child / "graph.json").read_text()
    assert child_graph != parent_graph_before
    assert child in child_graph and parent not in child_graph
