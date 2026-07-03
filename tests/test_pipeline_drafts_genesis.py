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
