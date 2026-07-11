from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi.testclient import TestClient

from workbench.api import app
from workbench.lineage.pipeline_drafts import PipelineDraftStore
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
    # POST /runs now requires a valid project root (v1.6.9 PROJECT_NOT_FOUND
    # symmetry); create_project guarantees runs/ at birth, so mirror that here.
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
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


def _context_fingerprint(
    project_root: str,
    run_id: str,
    node_id: str,
    node_hash: str,
    *,
    forest_node_key: str | None = None,
) -> str:
    request = NodeWriteOperationRequestV1(
        request_id="req_pipeline_draft",
        operation="rerun",
        context_version="node-operation-context/v1",
        context_fingerprint="pending",
        owner_run_id=run_id,
        op_node_id=node_id,
        node_hash=node_hash,
        forest_node_key=forest_node_key or node_hash,
        owner_resolution="single_candidate",
        active_head_run_id=run_id,
    )
    return compute_context_fingerprint(Path(project_root) / "runs", request)


def _create_draft_from_first_model_node(client: TestClient, project_root: str, run_id: str) -> dict:
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = _model_node(graph)
    node_hash = _node_hash(project_root, run_id, model["id"])
    response = client.post(
        "/pipeline-drafts/from-node",
        params={"project_root": project_root},
        json={
            "source_run_id": run_id,
            "source_model_node_id": model["id"],
            "source_op_node_id": model["id"],
            "source_node_hash": node_hash,
            "source_context_fingerprint": _context_fingerprint(project_root, run_id, model["id"], node_hash),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


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


def test_from_node_accepts_headset_forest_node_key_context(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = _model_node(graph)
    node_hash = _node_hash(project_root, run_id, model["id"])
    forest_node_key = f"{node_hash}::{model['id']}"

    response = client.post(
        "/pipeline-drafts/from-node",
        params={"project_root": project_root},
        json={
            "source_run_id": run_id,
            "source_model_node_id": model["id"],
            "source_op_node_id": model["id"],
            "source_node_hash": node_hash,
            "source_forest_node_key": forest_node_key,
            "source_context_fingerprint": _context_fingerprint(
                project_root,
                run_id,
                model["id"],
                node_hash,
                forest_node_key=forest_node_key,
            ),
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["draft"]["created_from"]["source_op_node_id"] == model["id"]


def test_from_node_hash_mismatch_fails_closed(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    graph = client.get(f"/runs/{run_id}/graph", params={"project_root": project_root}).json()
    model = _model_node(graph)
    node_hash = _node_hash(project_root, run_id, model["id"])

    response = client.post(
        "/pipeline-drafts/from-node",
        params={"project_root": project_root},
        json={
            "source_run_id": run_id,
            "source_model_node_id": model["id"],
            "source_op_node_id": model["id"],
            "source_node_hash": "wrong_hash",
            "source_context_fingerprint": _context_fingerprint(project_root, run_id, model["id"], node_hash),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "SOURCE_NODE_HASH_MISMATCH"
    assert not (tmp_path / "data" / "pipeline_drafts").exists()


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
            "params": {"model_type": "ols", "covariance": "robust", "focal_x": []},
        },
    )
    assert stale.status_code == 409
    ok = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={
            "model_node_id": "model_1",
            "base_draft_hash": create["draft_hash"],
            "params": {"model_type": "ols", "covariance": "robust", "focal_x": []},
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


def test_patch_rejects_params_outside_editable_schema_options(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    create = _create_draft_from_first_model_node(client, project_root, run_id)
    draft_id = create["draft"]["draft_id"]
    model = next(node for node in create["draft"]["graph"]["nodes"] if node["node_type"] == "model")

    response = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={
            "model_node_id": "model_1",
            "base_draft_hash": create["draft_hash"],
            "params": {**model["params"], "covariance": "not_allowed"},
        },
    )

    assert response.status_code == 422
    assert "INVALID_PARAM_OPTION" in response.json()["detail"]


def test_patch_auto_mode_draft_edits_without_touching_model_type(tmp_path: Path) -> None:
    """P1 (v1.6.10): a draft forked from an auto-mode run carries
    params.model_type='auto', which is absent from the editable_schema's
    concrete-family options. A full-params PATCH that leaves model_type as the
    inherited 'auto' (e.g. editing only covariance) must succeed — it used to
    422 with INVALID_PARAM_OPTION on the untouched 'auto', making EVERY draft
    forked from an auto-mode run un-editable."""
    client = _client()
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    csv = tmp_path / "input.csv"
    rows = "\n".join(f"{1 + 2 * i},{i},{i + 1}" for i in range(35))
    csv.write_text("y,x1,x2\n" + rows + "\n", encoding="utf-8")
    with csv.open("rb") as fh:
        resp = client.post(
            "/runs",
            data={"project_root": str(tmp_path), "mode": "auto",
                  "model_type": "auto", "y": "y", "x": "x1"},
            files={"file": ("input.csv", fh, "text/csv")},
        )
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    _wait_terminal(client, str(tmp_path), run_id)
    project_root = str(tmp_path)

    create = _create_draft_from_first_model_node(client, project_root, run_id)
    draft_id = create["draft"]["draft_id"]
    model = next(n for n in create["draft"]["graph"]["nodes"] if n["node_type"] == "model")
    # P1 precondition: the inherited model_type is the auto sentinel, and it is
    # NOT among the model_type control's options.
    assert model["params"].get("model_type") == "auto"
    controls = {c["key"]: c for c in model["editable_schema"]}
    mt_opts = [o.get("value") if isinstance(o, dict) else o
               for o in controls.get("model_type", {}).get("options", [])]
    assert "auto" not in mt_opts

    # Edit a real, in-options covariance value; leave model_type as inherited 'auto'.
    cov = controls.get("covariance", {})
    cov_opts = [o.get("value") if isinstance(o, dict) else o for o in cov.get("options", [])]
    new_cov = next((o for o in cov_opts if o != model["params"].get("covariance")),
                   model["params"].get("covariance"))
    ok = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={
            "model_node_id": "model_1",
            "base_draft_hash": create["draft_hash"],
            "params": {**model["params"], "covariance": new_cov},
        },
    )
    assert ok.status_code == 200, ok.text

    # Guard: actually CHANGING model_type to a bogus family is still rejected.
    bad = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={
            "model_node_id": "model_1",
            "base_draft_hash": ok.json()["draft_hash"],
            "params": {**model["params"], "model_type": "bogus_family"},
        },
    )
    assert bad.status_code == 422


def test_validate_does_not_create_run_or_snapshot(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    create = _create_draft_from_first_model_node(client, project_root, run_id)
    draft_id = create["draft"]["draft_id"]
    runs_before = {path.name for path in (tmp_path / "runs").iterdir() if path.is_dir()}

    validate = client.post(
        f"/pipeline-drafts/{draft_id}/validate",
        params={"project_root": project_root},
        json={"execution_mode": "rerun_child"},
    )

    assert validate.status_code == 200, validate.text
    assert validate.json()["executable"] is True
    runs_after = {path.name for path in (tmp_path / "runs").iterdir() if path.is_dir()}
    assert runs_after == runs_before
    assert not list((tmp_path / "runs").glob("*/executed_pipeline_draft.json"))


def test_execute_rejects_new_run_and_stale_hash(tmp_path: Path) -> None:
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
    new_run = client.post(
        f"/pipeline-drafts/{draft_id}/execute",
        params={"project_root": project_root},
        json={"validated_draft_hash": create["draft_hash"], "execution_mode": "new_run"},
    )
    assert new_run.status_code == 409
    assert new_run.json()["detail"] == "NEW_RUN_EXECUTION_NOT_ENABLED"
    stale = client.post(
        f"/pipeline-drafts/{draft_id}/execute",
        params={"project_root": project_root},
        json={"validated_draft_hash": "stale", "execution_mode": "rerun_child"},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == "VALIDATED_DRAFT_HASH_MISMATCH"


def test_execute_revalidates_current_draft_after_lock(tmp_path: Path) -> None:
    client = _client()
    run_id, project_root = _create_completed_run(client, tmp_path)
    create = _create_draft_from_first_model_node(client, project_root, run_id)
    draft_id = create["draft"]["draft_id"]
    validation = client.post(
        f"/pipeline-drafts/{draft_id}/validate",
        params={"project_root": project_root},
        json={"execution_mode": "rerun_child"},
    ).json()
    model = next(node for node in create["draft"]["graph"]["nodes"] if node["node_type"] == "model")
    next_covariance = "clustered" if model["params"].get("covariance") != "clustered" else "robust"
    patch = client.patch(
        f"/pipeline-drafts/{draft_id}",
        params={"project_root": project_root},
        json={
            "model_node_id": "model_1",
            "base_draft_hash": validation["validated_draft_hash"],
            "params": {**model["params"], "covariance": next_covariance},
        },
    )
    assert patch.status_code == 200, patch.text

    execute = client.post(
        f"/pipeline-drafts/{draft_id}/execute",
        params={"project_root": project_root},
        json={
            "validated_draft_hash": validation["validated_draft_hash"],
            "execution_mode": "rerun_child",
        },
    )

    assert execute.status_code == 409
    assert execute.json()["detail"] == "VALIDATED_DRAFT_HASH_MISMATCH"
    assert not list((tmp_path / "runs").glob("*/executed_pipeline_draft.json"))


def test_execute_writes_snapshot_and_returns_deduped_on_retry(tmp_path: Path) -> None:
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
    validation = client.post(
        f"/pipeline-drafts/{draft_id}/validate",
        params={"project_root": project_root},
        json={"execution_mode": "rerun_child"},
    ).json()
    request = {
        "validated_draft_hash": validation["validated_draft_hash"],
        "execution_mode": "rerun_child",
    }
    first = client.post(
        f"/pipeline-drafts/{draft_id}/execute",
        params={"project_root": project_root},
        json=request,
    )
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["execution_mode"] == "rerun_child"
    assert body["produced_lineage"]["rerun_from_run_id"] == run_id
    assert (tmp_path / "runs" / body["run_id"] / "executed_pipeline_draft.json").is_file()
    _wait_terminal(client, project_root, body["run_id"])
    second = client.post(
        f"/pipeline-drafts/{draft_id}/execute",
        params={"project_root": project_root},
        json=request,
    )
    assert second.status_code == 200
    assert second.json()["run_id"] == body["run_id"]
    assert second.json()["deduped"] is True


def _make_draft(draft_id: str, status: str = "draft", model_type: str = "ols") -> dict:
    return {
        "draft_id": draft_id,
        "schema_version": "pipeline_draft.v1",
        "created_at": "2026-07-02T00:00:00Z",
        "updated_at": "2026-07-02T00:00:00Z",
        "status": status,
        "created_from": {
            "source_type": "run",
            "source_run_id": "run_a",
            "source_model_node_id": "model#0",
            "source_op_node_id": "model#0",
            "source_node_hash": "hash_a",
            "source_context_fingerprint": "ctx_a",
            "source_input_fingerprint": "in_a",
        },
        "graph": {
            "nodes": [
                {"node_type": "model", "node_id": "model#0", "model_type": model_type,
                 "editable_schema": []},
            ],
            "edges": [],
        },
        "default_execution_mode": "rerun_child",
    }


def test_list_pipeline_drafts_endpoint(tmp_path: Path):
    client = _client()
    PipelineDraftStore(tmp_path).create(_make_draft("draft_aaaaaaaa"))
    resp = client.get("/pipeline-drafts", params={"project_root": str(tmp_path)})
    assert resp.status_code == 200, resp.text
    assert [d["draft_id"] for d in resp.json()["drafts"]] == ["draft_aaaaaaaa"]


def test_delete_pipeline_draft_endpoint(tmp_path: Path):
    client = _client()
    store = PipelineDraftStore(tmp_path)
    store.create(_make_draft("draft_aaaaaaaa"))
    resp = client.delete("/pipeline-drafts/draft_aaaaaaaa", params={"project_root": str(tmp_path)})
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "ok": True,
        "draft_id": "draft_aaaaaaaa",
        "upload_reclaimed": False,  # v1.6.8 F6: non-genesis draft -> no blob GC
    }
    assert not store._path("draft_aaaaaaaa").exists()


def test_delete_missing_draft_is_ok(tmp_path: Path):
    client = _client()
    resp = client.delete("/pipeline-drafts/draft_missing0", params={"project_root": str(tmp_path)})
    assert resp.status_code == 200, resp.text
    assert resp.json()["ok"] is True
