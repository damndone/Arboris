import io
import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.lineage.node_write_validation import (
    NodeWriteOperationRequestV1,
    compute_context_fingerprint,
)
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


def _write_node_index(project_root: Path, run_id: str, node_id: str, node_hash: str) -> None:
    path = project_root / "runs" / run_id / "node_index.json"
    path.write_text(json.dumps({node_id: {"node_hash": node_hash}}), encoding="utf-8")


def _run_ids(project_root: Path) -> set[str]:
    return {entry.name for entry in (project_root / "runs").iterdir() if entry.is_dir()}


def _context_fingerprint(project_root: Path, **overrides) -> str:
    data = {
        "request_id": "req_context_rerun",
        "operation": "rerun",
        "context_version": "node-operation-context/v1",
        "context_fingerprint": "pending",
        "owner_run_id": overrides["owner_run_id"],
        "op_node_id": overrides["op_node_id"],
        "node_hash": overrides["node_hash"],
        "forest_node_key": overrides["forest_node_key"],
        "owner_resolution": overrides["owner_resolution"],
        "active_head_run_id": overrides.get("active_head_run_id"),
    }
    request = NodeWriteOperationRequestV1(**data)
    return compute_context_fingerprint(project_root / "runs", request)


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


def test_context_driven_rerun_uses_owner_run_not_url_run(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    owner = _create_terminal_run(project.root)
    active_head = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, owner)
    _write_node_index(project.root, owner, node_id, "hash_owner_model")
    context_fingerprint = _context_fingerprint(
        project.root,
        owner_run_id=owner,
        op_node_id=node_id,
        node_hash="hash_owner_model",
        forest_node_key="hash_owner_model",
        owner_resolution="manual_candidate_selection",
        active_head_run_id=active_head,
    )

    resp = client.post(
        f"/runs/{active_head}/rerun",
        params={"project_root": str(project.root)},
        json={
            "request_id": "req_context_rerun",
            "operation": "rerun",
            "context_version": "node-operation-context/v1",
            "context_fingerprint": context_fingerprint,
            "owner_run_id": owner,
            "op_node_id": node_id,
            "node_hash": "hash_owner_model",
            "forest_node_key": "hash_owner_model",
            "owner_resolution": "manual_candidate_selection",
            "active_head_run_id": active_head,
            "op_overrides": {"covariance": "unadjusted"},
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    child = body["run_id"]
    assert body["new_run_id"] == child
    assert body["new_active_head_id"] == child
    assert body["focus"] is None
    assert body["rerun_from"] == {
        "owner_run_id": owner,
        "op_node_id": node_id,
        "node_hash": "hash_owner_model",
        "forest_node_key": "hash_owner_model",
    }
    assert body["accepted_context"]["owner_run_id"] == owner
    assert body["accepted_context"]["op_node_id"] == node_id
    _wait_terminal(project.root, child)
    inputs = json.loads((project.root / "runs" / child / "run_inputs.json").read_text())
    assert inputs["rerun_of"] == owner
    assert inputs["from_node"] == node_id


def test_context_rerun_persists_run_level_rerun_from_and_returns_pending_lineage(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    owner = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, owner)
    _write_node_index(project.root, owner, node_id, "hash_owner_model")
    fingerprint = _context_fingerprint(
        project.root,
        owner_run_id=owner,
        op_node_id=node_id,
        node_hash="hash_owner_model",
        forest_node_key="hash_owner_model",
        owner_resolution="active_head_contains_node",
        active_head_run_id=owner,
    )

    resp = client.post(
        f"/runs/{owner}/rerun",
        params={"project_root": str(project.root)},
        json={
            "request_id": "req_provenance",
            "operation": "rerun",
            "context_version": "node-operation-context/v1",
            "context_fingerprint": fingerprint,
            "owner_run_id": owner,
            "op_node_id": node_id,
            "node_hash": "hash_owner_model",
            "forest_node_key": "hash_owner_model",
            "owner_resolution": "active_head_contains_node",
            "active_head_run_id": owner,
            "op_overrides": {"covariance": "unadjusted"},
        },
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["produced_lineage"] == {
        "produced_owner_run_id": body["run_id"],
        "produced_op_node_id": None,
        "produced_node_hash": None,
        "rerun_request_id": "req_provenance",
        "status": "pending_index",
        "rerun_from": {
            "owner_run_id": owner,
            "op_node_id": node_id,
            "node_hash": "hash_owner_model",
            "context_fingerprint": fingerprint,
            "rerun_request_id": "req_provenance",
        },
    }
    stored = json.loads((project.root / "runs" / body["run_id"] / "run_inputs.json").read_text())
    assert stored["rerun_from"]["owner_run_id"] == owner
    assert stored["rerun_from"]["op_node_id"] == node_id
    _wait_terminal(project.root, body["run_id"])


def test_manual_patch_idempotency_reuses_existing_child(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    url_run = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)
    _write_node_index(project.root, parent, node_id, "hash_parent_model")
    fingerprint = _context_fingerprint(
        project.root,
        owner_run_id=parent,
        op_node_id=node_id,
        node_hash="hash_parent_model",
        forest_node_key="hash_parent_model",
        owner_resolution="active_head_contains_node",
        active_head_run_id=parent,
    )
    payload = {
        "request_id": "req_patch_1",
        "operation": "rerun",
        "context_version": "node-operation-context/v1",
        "context_fingerprint": fingerprint,
        "owner_run_id": parent,
        "op_node_id": node_id,
        "node_hash": "hash_parent_model",
        "forest_node_key": "hash_parent_model",
        "owner_resolution": "active_head_contains_node",
        "active_head_run_id": parent,
        "manual_patch": {
            "patch_id": "patch_same",
            "patch_source": "MANUAL_EDIT",
            "source_context_fingerprint": fingerprint,
            "editable_schema_version": "run_inputs",
            "target": {
                "owner_run_id": parent,
                "op_node_id": node_id,
                "node_hash": "hash_parent_model",
            },
            "changes": [
                {
                    "field_id": "covariance",
                    "old_value": "robust",
                    "new_value": "unadjusted",
                }
            ],
        },
    }
    first = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json=payload,
    )
    second = client.post(
        f"/runs/{url_run}/rerun",
        params={"project_root": str(project.root)},
        json=payload,
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["run_id"] == first.json()["run_id"]
    inputs = json.loads(
        (project.root / "runs" / first.json()["run_id"] / "run_inputs.json").read_text()
    )
    assert inputs["rerun_of"] == parent
    assert inputs["rerun_from"]["patch_id"] == "patch_same"
    _wait_terminal(project.root, first.json()["run_id"])


def test_manual_patch_requires_context_version(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)

    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={
            "from_node": node_id,
            "manual_patch": {
                "patch_id": "patch_without_context",
                "patch_source": "MANUAL_EDIT",
                "source_context_fingerprint": "nocv1:missing",
                "editable_schema_version": "run_inputs",
                "target": {
                    "owner_run_id": parent,
                    "op_node_id": node_id,
                    "node_hash": "hash_parent_model",
                },
                "changes": [
                    {
                        "field_id": "covariance",
                        "old_value": "robust",
                        "new_value": "unadjusted",
                    }
                ],
            },
        },
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "context_version is required for context target fields."


def test_manual_patch_rejects_mixed_op_overrides(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)
    _write_node_index(project.root, parent, node_id, "hash_parent_model")
    fingerprint = _context_fingerprint(
        project.root,
        owner_run_id=parent,
        op_node_id=node_id,
        node_hash="hash_parent_model",
        forest_node_key="hash_parent_model",
        owner_resolution="active_head_contains_node",
        active_head_run_id=parent,
    )

    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={
            "request_id": "req_patch_mixed",
            "operation": "rerun",
            "context_version": "node-operation-context/v1",
            "context_fingerprint": fingerprint,
            "owner_run_id": parent,
            "op_node_id": node_id,
            "node_hash": "hash_parent_model",
            "forest_node_key": "hash_parent_model",
            "owner_resolution": "active_head_contains_node",
            "active_head_run_id": parent,
            "op_overrides": {"covariance": "clustered"},
            "manual_patch": {
                "patch_id": "patch_mixed",
                "patch_source": "MANUAL_EDIT",
                "source_context_fingerprint": fingerprint,
                "editable_schema_version": "run_inputs",
                "target": {
                    "owner_run_id": parent,
                    "op_node_id": node_id,
                    "node_hash": "hash_parent_model",
                },
                "changes": [
                    {
                        "field_id": "covariance",
                        "old_value": "robust",
                        "new_value": "unadjusted",
                    }
                ],
            },
        },
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "MANUAL_PATCH_WITH_OP_OVERRIDES"


def test_partial_context_without_context_version_does_not_rerun_from_owner(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    url_run = _create_terminal_run(project.root)
    owner = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, owner)
    before = _run_ids(project.root)

    resp = client.post(
        f"/runs/{url_run}/rerun",
        params={"project_root": str(project.root)},
        json={
            "owner_run_id": owner,
            "op_node_id": node_id,
            "op_overrides": {"covariance": "unadjusted"},
        },
    )

    assert resp.status_code in {400, 422}
    assert _run_ids(project.root) == before


def test_context_driven_rerun_rejects_unsupported_context_version_400(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)

    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={
            "request_id": "req_context_rerun",
            "operation": "rerun",
            "context_version": "node-operation-context/v9",
            "context_fingerprint": "fingerprint_owner",
            "owner_run_id": parent,
            "op_node_id": node_id,
            "node_hash": "hash_owner_model",
            "forest_node_key": "hash_owner_model",
            "owner_resolution": "active_head_contains_node",
            "active_head_run_id": parent,
            "op_overrides": {"covariance": "unadjusted"},
        },
    )

    assert resp.status_code == 400
    assert resp.json()["detail"] == "unsupported_context_version"


def test_context_driven_rerun_rejects_node_hash_mismatch_409(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)
    _write_node_index(project.root, parent, node_id, "hash_persisted")

    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={
            "request_id": "req_context_rerun",
            "operation": "rerun",
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "fingerprint_owner",
            "owner_run_id": parent,
            "op_node_id": node_id,
            "node_hash": "hash_submitted",
            "forest_node_key": "hash_submitted",
            "owner_resolution": "active_head_contains_node",
            "active_head_run_id": parent,
            "op_overrides": {"covariance": "unadjusted"},
        },
    )

    assert resp.status_code == 409
    assert resp.json()["detail"] == "context_mismatch: node_hash"


def test_rerun_missing_run_inputs_422_not_500(tmp_path: Path):
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)
    # Simulate a legacy / pre-v1.6.0 run with no run_inputs.json.
    (project.root / "runs" / parent / "run_inputs.json").unlink()
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": node_id, "op_overrides": {"covariance": "robust"}},
    )
    assert resp.status_code == 422


def test_rerun_list_override_is_json_encoded(tmp_path: Path):
    # Switching to IV via rerun with native-array role overrides must dispatch
    # (the JSON-array gets encoded for the pipeline, not str()-mangled into "['x']").
    project = create_project(tmp_path, "demo")
    parent = _create_terminal_run(project.root)
    node_id = _model_node_id(project.root, parent)
    resp = client.post(
        f"/runs/{parent}/rerun",
        params={"project_root": str(project.root)},
        json={"from_node": node_id, "op_overrides": {
            "model_type": "iv_2sls", "iv_endog": ["x"], "iv_instruments": ["x"]}},
    )
    assert resp.status_code == 200  # dispatches; estimability is the pipeline's call
    child = resp.json()["run_id"]
    _wait_terminal(project.root, child)
    inputs = json.loads((project.root / "runs" / child / "run_inputs.json").read_text())
    assert inputs["form"]["iv_endog"] == '["x"]'  # JSON-encoded, not "['x']"


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
