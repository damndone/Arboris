"""v1.6.8 Task 2: POST /pipeline-drafts/genesis — parentless genesis draft chain."""
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.lineage.pipeline_drafts import _validate_graph_shape

client = TestClient(app)


def _mkproject(tmp_path):
    return client.post(
        "/projects", json={"parent": str(tmp_path), "name": "p1"}
    ).json()["project_root"]


def _upload(root, name="d.csv", data=b"y,x\n1,2\n3,4\n"):
    return client.post(
        "/uploads",
        data={"project_root": root},
        files={"file": (name, data, "text/csv")},
    ).json()


def test_genesis_draft_created_and_persisted(tmp_path):
    root = _mkproject(tmp_path)
    up = _upload(root)
    r = client.post(
        f"/pipeline-drafts/genesis?project_root={root}",
        json={
            "upload_sha256": up["sha256"],
            "filename": up["filename"],
            "sheet_names": [],
            "columns": ["y", "x"],
        },
    )
    assert r.status_code == 200
    body = r.json()
    draft = body["draft"]
    assert body["draft_hash"]
    assert draft["created_from"]["source_type"] == "genesis"
    assert draft["created_from"]["source_input_fingerprint"] == up["sha256"]
    types = [n["node_type"] for n in draft["graph"]["nodes"]]
    assert types == ["input.upload", "table", "model"]
    source = draft["graph"]["nodes"][0]
    assert source["upload"] == {"sha256": up["sha256"], "filename": up["filename"]}
    table = draft["graph"]["nodes"][1]
    assert table["columns"] == ["y", "x"]
    assert draft["graph"]["edges"] == [
        {"from": "source_1", "to": "table_1"},
        {"from": "table_1", "to": "model_1"},
    ]
    assert draft["default_execution_mode"] == "genesis"
    listed = client.get(f"/pipeline-drafts?project_root={root}").json()["drafts"]
    assert any(d["draft_id"] == draft["draft_id"] for d in listed)


def test_genesis_rejects_unknown_upload(tmp_path):
    root = _mkproject(tmp_path)
    r = client.post(
        f"/pipeline-drafts/genesis?project_root={root}",
        json={
            "upload_sha256": "0" * 64,
            "filename": "x.csv",
            "sheet_names": [],
            "columns": [],
        },
    )
    assert r.status_code == 422
    assert "UPLOAD_NOT_FOUND" in r.json()["detail"]


def test_genesis_rejects_unknown_project(tmp_path):
    r = client.post(
        f"/pipeline-drafts/genesis?project_root={tmp_path}/nope",
        json={
            "upload_sha256": "0" * 64,
            "filename": "x.csv",
            "sheet_names": [],
            "columns": [],
        },
    )
    assert r.status_code == 404


def _genesis_draft_dict():
    return {
        "created_from": {"source_type": "genesis", "source_input_fingerprint": "0" * 64},
        "graph": {
            "nodes": [
                {"node_id": "source_1", "node_type": "input.upload"},
                {"node_id": "table_1", "node_type": "table"},
                {"node_id": "model_1", "node_type": "model"},
            ],
            "edges": [
                {"from": "source_1", "to": "table_1"},
                {"from": "table_1", "to": "model_1"},
            ],
        },
    }


def test_validate_graph_shape_accepts_genesis_chain():
    assert _validate_graph_shape(_genesis_draft_dict()) == []


def test_validate_graph_shape_rejects_broken_genesis_chain():
    draft = _genesis_draft_dict()
    draft["graph"]["nodes"] = draft["graph"]["nodes"][::-1]
    codes = [c["code"] for c in _validate_graph_shape(draft)]
    assert "GENESIS_CHAIN_SHAPE" in codes


def test_validate_graph_shape_rejects_bad_genesis_edges():
    draft = _genesis_draft_dict()
    draft["graph"]["edges"] = [{"from": "source_1", "to": "model_1"}]
    codes = [c["code"] for c in _validate_graph_shape(draft)]
    assert "GENESIS_CHAIN_EDGES" in codes


def test_validate_graph_shape_rejects_duplicate_node_ids():
    draft = _genesis_draft_dict()
    for node in draft["graph"]["nodes"]:
        node["node_id"] = "dup_1"
    codes = [c["code"] for c in _validate_graph_shape(draft)]
    assert "GENESIS_CHAIN_SHAPE" in codes


def test_validate_graph_shape_from_node_path_untouched():
    draft = {
        "created_from": {"source_type": "run"},
        "graph": {
            "nodes": [
                {"node_id": "input_1", "node_type": "input.dataset"},
                {"node_id": "model_1", "node_type": "model"},
            ],
            "edges": [{"from": "input_1", "to": "model_1"}],
        },
    }
    assert _validate_graph_shape(draft) == []


# --- Task 3: wizard step endpoint PATCH /pipeline-drafts/{id}/nodes/{node_id} ---


def _genesis(root, **kw):
    up = _upload(root, **({"name": kw.pop("name")} if "name" in kw else {}))
    return client.post(
        f"/pipeline-drafts/genesis?project_root={root}",
        json={
            "upload_sha256": up["sha256"],
            "filename": up["filename"],
            "sheet_names": [],
            "columns": ["y", "x"],
        },
    ).json()


def test_wizard_step_updates_table_then_model(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    r = client.patch(
        f"/pipeline-drafts/{did}/nodes/table_1?project_root={root}",
        json={
            "params": {"sheet_name": "Sheet1", "transpose": False},
            "columns": ["y", "x"],
        },
    )
    assert r.status_code == 200
    assert r.json()["draft_hash"] != d["draft_hash"]  # hash advances with content
    table = next(
        n for n in r.json()["draft"]["graph"]["nodes"] if n["node_id"] == "table_1"
    )
    assert table["params"]["sheet_name"] == "Sheet1"
    assert table["status"] == "configured"
    r2 = client.patch(
        f"/pipeline-drafts/{did}/nodes/model_1?project_root={root}",
        json={"params": {"model_type": "ols", "y": "y", "x": ["x"]}},
    )
    assert r2.status_code == 200
    model = next(
        n for n in r2.json()["draft"]["graph"]["nodes"] if n["node_id"] == "model_1"
    )
    assert model["params"]["y"] == "y" and model["status"] == "configured"


def test_node_patch_rejects_nongenesis_source_node(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root)
    r = client.patch(
        f"/pipeline-drafts/{d['draft']['draft_id']}/nodes/source_1?project_root={root}",
        json={"params": {"anything": 1}},
    )
    assert r.status_code == 409  # source immutable once bound (change file = discard & restart)


def test_node_patch_unknown_node_is_404(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root)
    r = client.patch(
        f"/pipeline-drafts/{d['draft']['draft_id']}/nodes/nope_1?project_root={root}",
        json={"params": {"a": 1}},
    )
    assert r.status_code == 404


def test_node_patch_unknown_draft_is_404(tmp_path):
    root = _mkproject(tmp_path)
    _genesis(root)  # store dir exists
    r = client.patch(
        f"/pipeline-drafts/draft_{'0' * 32}/nodes/table_1?project_root={root}",
        json={"params": {"a": 1}},
    )
    assert r.status_code == 404


def test_node_patch_rejects_from_node_draft_store_level(tmp_path):
    """update_node_params is genesis-only: a from-node draft raises the 409 error."""
    from workbench.lineage.pipeline_drafts import (
        DRAFT_SCHEMA_VERSION,
        DraftNodePatchConflict,
        PipelineDraftStore,
        schema_hash,
    )
    import pytest

    editable_schema = [{"key": "x", "kind": "columns", "label": "X"}]
    draft = {
        "draft_id": "draft_fromnode1",
        "schema_version": DRAFT_SCHEMA_VERSION,
        "created_at": "2026-07-03T00:00:00Z",
        "updated_at": "2026-07-03T00:00:00Z",
        "status": "draft",
        "created_from": {
            "source_type": "run",
            "source_run_id": "run_source",
            "source_model_node_id": "model_node",
            "source_op_node_id": "model_op",
            "source_node_hash": "h_source",
            "source_context_fingerprint": "ctx_source",
            "source_input_fingerprint": "input_source",
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "input_1",
                    "node_type": "input.dataset",
                    "source_type": "run_input",
                    "run_input_id": "run_source",
                    "schema_fingerprint": "schema_1",
                    "input_fingerprint": "input_source",
                    "columns_summary": [{"name": "y"}, {"name": "x1"}],
                    "status": "bound",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": "ols",
                    "schema_id": "ols@v1",
                    "editable_schema": editable_schema,
                    "editable_schema_hash": schema_hash(editable_schema),
                    "source_ref": {
                        "source_run_id": "run_source",
                        "source_model_node_id": "model_node",
                        "source_op_node_id": "model_op",
                        "source_node_hash": "h_source",
                        "source_context_fingerprint": "ctx_source",
                    },
                    "source_params": {"x": ["x1"]},
                    "params": {"x": ["x1"]},
                },
            ],
            "edges": [{"from": "input_1", "to": "model_1"}],
        },
        "default_execution_mode": "rerun_child",
    }
    store = PipelineDraftStore(tmp_path)
    store.create(draft)
    with pytest.raises(DraftNodePatchConflict):
        store.update_node_params("draft_fromnode1", "model_1", {"x": ["x1"]})


def test_genesis_rejects_malformed_sha256(tmp_path):
    root = _mkproject(tmp_path)
    r = client.post(
        f"/pipeline-drafts/genesis?project_root={root}",
        json={
            "upload_sha256": "../../etc/passwd",
            "filename": "x.csv",
            "sheet_names": [],
            "columns": [],
        },
    )
    assert r.status_code == 422
    detail = r.json()["detail"]
    assert "UPLOAD_NOT_FOUND" in detail
    assert "passwd" not in detail  # no reflection / no file-system leakage
