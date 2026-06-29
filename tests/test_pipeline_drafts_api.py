from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    compute_context_fingerprint,
)


def _client() -> TestClient:
    return TestClient(app)


def _wait_terminal(client: TestClient, project_root: str, run_id: str, tries: int = 100) -> str:
    terminal = {"completed", "failed", "cancelled", "interrupted", "partial"}
    body: dict = {}
    for _ in range(tries):
        body = client.get(f"/runs/{run_id}", params={"project_root": project_root}).json()
        if body.get("status") in terminal:
            return str(body["status"])
        time.sleep(0.1)
    return str(body.get("status"))


def _create_completed_run(client: TestClient, tmp_path: Path) -> tuple[str, str]:
    csv = tmp_path / "input.csv"
    rows = "\n".join(f"{1 + 2 * i},{i},{i + 1}" for i in range(35))
    csv.write_text("y,x1,x2\n" + rows + "\n", encoding="utf-8")
    with csv.open("rb") as fh:
        response = client.post(
            "/runs",
            data={
                "project_root": str(tmp_path),
                "mode": "auto",
                "model_type": "ols",
                "y": "y",
                "x": "x1",
            },
            files={"file": ("input.csv", fh, "text/csv")},
        )
    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    _wait_terminal(client, str(tmp_path), run_id)
    manifest_path = tmp_path / "runs" / run_id / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["status"] = "completed"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return run_id, str(tmp_path)


def _model_node(graph: dict) -> dict:
    nodes = graph["nodes"]
    if isinstance(nodes, dict):
        return next(n for n in nodes.values() if n.get("stage") == "model")
    return next(n for n in nodes if n.get("stage") == "model")


def _node_hash(project_root: str, run_id: str, node_id: str) -> str:
    path = Path(project_root) / "runs" / run_id / "node_index.json"
    index = json.loads(path.read_text(encoding="utf-8"))
    return str(index[node_id]["node_hash"])


def _context_fingerprint(project_root: str, run_id: str, node_id: str, node_hash: str) -> str:
    request = NodeWriteOperationRequestV1(
        request_id="req_pipeline_draft",
        operation="rerun",
        context_version="node-operation-context/v1",
        context_fingerprint="pending",
        owner_run_id=run_id,
        op_node_id=node_id,
        node_hash=node_hash,
        forest_node_key=node_hash,
        owner_resolution="single_candidate",
        active_head_run_id=run_id,
    )
    return compute_context_fingerprint(Path(project_root) / "runs", request)


def test_from_node_creates_draft_and_get_reads_hash(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = _model_node(graph)
    node_hash = _node_hash(project_root, run_id, model["id"])
    body = {
        "source_run_id": run_id,
        "source_model_node_id": model["id"],
        "source_op_node_id": model["id"],
        "source_node_hash": node_hash,
        "source_context_fingerprint": _context_fingerprint(project_root, run_id, model["id"], node_hash),
    }
    response = client.post("/pipeline-drafts/from-node", params={"project_root": project_root}, json=body)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["draft"]["default_execution_mode"] == "rerun_child"
    assert payload["draft_hash"]
    draft_id = payload["draft"]["draft_id"]
    get_response = client.get(f"/pipeline-drafts/{draft_id}", params={"project_root": project_root})
    assert get_response.status_code == 200
    assert get_response.json()["draft_hash"] == payload["draft_hash"]


def test_patch_requires_base_hash_and_validate_returns_hash(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = _model_node(graph)
    node_hash = _node_hash(project_root, run_id, model["id"])
    create = client.post(
        "/pipeline-drafts/from-node",
        params={"project_root": project_root},
        json={
            "source_run_id": run_id,
            "source_model_node_id": model["id"],
            "source_op_node_id": model["id"],
            "source_node_hash": node_hash,
            "source_context_fingerprint": _context_fingerprint(project_root, run_id, model["id"], node_hash),
        },
    ).json()
    draft_id = create["draft"]["draft_id"]
    stale = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={
            "model_node_id": "model_1",
            "base_draft_hash": "stale",
            "params": {"model_type": "ols", "covariance": "robust"},
        },
    )
    assert stale.status_code == 409
    ok = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={
            "model_node_id": "model_1",
            "base_draft_hash": create["draft_hash"],
            "params": {"model_type": "ols", "covariance": "robust"},
        },
    )
    assert ok.status_code == 200, ok.text
    validate = client.post(
        f"/pipeline-drafts/{draft_id}/validate",
        params={"project_root": project_root},
        json={"execution_mode": "rerun_child"},
    )
    assert validate.status_code == 200
    assert validate.json()["validated_draft_hash"] == ok.json()["draft_hash"]
