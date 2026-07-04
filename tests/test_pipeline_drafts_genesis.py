"""v1.6.8 Task 2: POST /pipeline-drafts/genesis — parentless genesis draft chain."""
import json
import time
from pathlib import Path

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


def _genesis(root, sheet_names=None, **kw):
    up = _upload(root, **({"name": kw.pop("name")} if "name" in kw else {}))
    return client.post(
        f"/pipeline-drafts/genesis?project_root={root}",
        json={
            "upload_sha256": up["sha256"],
            "filename": up["filename"],
            "sheet_names": sheet_names or [],
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
    assert r.json()["detail"].startswith("DRAFT_NODE_PATCH_CONFLICT:")  # R5: class code prefix


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


# --- Task 4: genesis branch of validate_draft_for_execution ---


def _configure_chain(root, did, model_params=None, table_params=None):
    client.patch(
        f"/pipeline-drafts/{did}/nodes/table_1?project_root={root}",
        json={
            "params": table_params or {"sheet_name": "", "transpose": False},
            "columns": ["y", "x"],
        },
    )
    client.patch(
        f"/pipeline-drafts/{did}/nodes/model_1?project_root={root}",
        json={"params": model_params or {"model_type": "ols", "y": "y", "x": ["x"]}},
    )


def _validate(root, did, body=None):
    return client.post(
        f"/pipeline-drafts/{did}/validate?project_root={root}",
        json=body if body is not None else {"execution_mode": "genesis"},
    )


def test_validate_genesis_ok(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    r = _validate(root, did)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["executable"] is True
    assert body["ok"] is True
    assert body["status"] == "valid"
    assert body["validated_execution_mode"] == "genesis"
    assert body["resolved_execution"]["genesis"] is True
    assert body["resolved_execution"]["execution_mode"] == "genesis"
    # hash pins the draft content the way execute (Task 5) will check it
    current = client.get(f"/pipeline-drafts/{did}?project_root={root}").json()
    assert body["validated_draft_hash"] == current["draft_hash"]


def test_validate_genesis_defaults_to_draft_mode(tmp_path):
    """No execution_mode in body -> default_execution_mode ('genesis') is used."""
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    r = _validate(root, did, body={})
    assert r.status_code == 200, r.text
    assert r.json()["executable"] is True
    assert r.json()["validated_execution_mode"] == "genesis"


def test_validate_genesis_missing_xy_blocks(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did, model_params={"model_type": "ols"})  # no y/x
    body = _validate(root, did).json()
    assert body["executable"] is False
    assert any(c["code"] == "GENESIS_MODEL_INCOMPLETE" for c in body["checks"])
    assert "validated_draft_hash" not in body


def test_validate_genesis_multisheet_requires_sheet_choice(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root, sheet_names=["A", "B"], name="d.xlsx")
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)  # empty sheet_name
    body = _validate(root, did).json()
    assert body["executable"] is False
    assert any(c["code"] == "GENESIS_SHEET_REQUIRED" for c in body["checks"])
    # choosing a sheet unblocks
    _configure_chain(root, did, table_params={"sheet_name": "B", "transpose": False})
    body2 = _validate(root, did).json()
    assert body2["executable"] is True
    assert not any(c["code"] == "GENESIS_SHEET_REQUIRED" for c in body2["checks"])


def test_validate_genesis_wrong_mode_blocks(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    body = _validate(root, did, body={"execution_mode": "rerun_child"}).json()
    assert body["executable"] is False
    assert any(c["code"] == "GENESIS_MODE_REQUIRED" for c in body["checks"])
    assert "validated_execution_mode" not in body


def test_validate_genesis_unbound_source(tmp_path):
    """Store-level: an upload binding without sha256 blocks with GENESIS_SOURCE_UNBOUND."""
    from workbench.lineage.pipeline_drafts import (
        DRAFT_SCHEMA_VERSION,
        PipelineDraftStore,
        validate_draft_for_execution,
    )

    draft = {
        "draft_id": "draft_genesisunbound1",
        "schema_version": DRAFT_SCHEMA_VERSION,
        "created_at": "2026-07-03T00:00:00Z",
        "updated_at": "2026-07-03T00:00:00Z",
        "status": "draft",
        "created_from": {
            "source_type": "genesis",
            "source_input_fingerprint": "0" * 64,
        },
        "graph": {
            "nodes": [
                {
                    "node_id": "source_1",
                    "node_type": "input.upload",
                    "upload": {"filename": "d.csv"},  # sha256 missing
                    "sheet_names": [],
                    "status": "bound",
                },
                {
                    "node_id": "table_1",
                    "node_type": "table",
                    "params": {"sheet_name": "", "transpose": False},
                    "columns": ["y", "x"],
                    "status": "configured",
                },
                {
                    "node_id": "model_1",
                    "node_type": "model",
                    "model_family": "regression",
                    "model_type": "ols",
                    "params": {"model_type": "ols", "y": "y", "x": ["x"]},
                    "status": "configured",
                },
            ],
            "edges": [
                {"from": "source_1", "to": "table_1"},
                {"from": "table_1", "to": "model_1"},
            ],
        },
        "default_execution_mode": "genesis",
    }
    store = PipelineDraftStore(tmp_path)
    stored = store.create(draft)
    result = validate_draft_for_execution(stored.draft, execution_mode="genesis")
    assert result["executable"] is False
    assert any(c["code"] == "GENESIS_SOURCE_UNBOUND" for c in result["checks"])


def test_validate_genesis_has_no_from_node_noise(tmp_path):
    """Genesis validate must NOT emit from-node checks (schema-hash / created_from / mode)."""
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    body = _validate(root, did).json()
    codes = {c["code"] for c in body["checks"]}
    assert "EDITABLE_SCHEMA_HASH_MISMATCH" not in codes
    assert "INVALID_EXECUTION_MODE" not in codes
    assert "CREATED_FROM_REQUIRED_FOR_RERUN_CHILD" not in codes


# --- Task 5: genesis branch of POST /pipeline-drafts/{draft_id}/execute ---


def _wait_terminal(root, run_id, tries=100):
    terminal = {"completed", "failed", "cancelled", "interrupted", "partial"}
    body = {}
    for _ in range(tries):
        body = client.get(f"/runs/{run_id}", params={"project_root": root}).json()
        if body.get("status") in terminal:
            return str(body["status"])
        time.sleep(0.1)
    return str(body.get("status"))


def _upload_rich(root):
    """Upload with enough rows for the OLS engine to actually run."""
    rows = "\n".join(f"{1 + 2 * i},{i}" for i in range(35))
    return client.post(
        "/uploads",
        data={"project_root": root},
        files={"file": ("d.csv", ("y,x\n" + rows + "\n").encode(), "text/csv")},
    ).json()


def _genesis_rich(root):
    up = _upload_rich(root)
    return client.post(
        f"/pipeline-drafts/genesis?project_root={root}",
        json={
            "upload_sha256": up["sha256"],
            "filename": up["filename"],
            "sheet_names": [],
            "columns": ["y", "x"],
        },
    ).json()


def test_execute_genesis_produces_first_run(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis_rich(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    v = _validate(root, did).json()
    r = client.post(
        f"/pipeline-drafts/{did}/execute?project_root={root}",
        json={
            "execution_mode": "genesis",
            "validated_draft_hash": v["validated_draft_hash"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    run_id = body["run_id"]
    assert body["ok"] is True
    assert body["execution_mode"] == "genesis"
    assert body["produced_lineage"] == {"genesis": True}
    detail = client.get(f"/runs/{run_id}", params={"project_root": root}).json()
    assert detail["run_id"] == run_id
    inputs = json.loads(
        (Path(root) / "runs" / run_id / "run_inputs.json").read_text(encoding="utf-8")
    )
    assert not inputs.get("rerun_of")
    assert inputs.get("rerun_reason") == "initial"
    assert not inputs.get("from_node")
    assert inputs["form"]["y"] == "y" and inputs["form"]["x"] == "x"
    _wait_terminal(root, run_id)


def test_execute_genesis_idempotent(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis_rich(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    v = _validate(root, did).json()
    body = {
        "execution_mode": "genesis",
        "validated_draft_hash": v["validated_draft_hash"],
        "idempotency_key": "k1",
    }
    r1 = client.post(f"/pipeline-drafts/{did}/execute?project_root={root}", json=body).json()
    _wait_terminal(root, r1["run_id"])
    r2 = client.post(f"/pipeline-drafts/{did}/execute?project_root={root}", json=body).json()
    assert r2["deduped"] is True and r2["run_id"] == r1["run_id"]
    assert r2["execution_mode"] == "genesis"


def test_execute_genesis_wrong_mode_409(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis_rich(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    current = client.get(f"/pipeline-drafts/{did}?project_root={root}").json()
    r = client.post(
        f"/pipeline-drafts/{did}/execute?project_root={root}",
        json={
            "execution_mode": "rerun_child",
            "validated_draft_hash": current["draft_hash"],
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "GENESIS_MODE_REQUIRED"
    assert not list((Path(root) / "runs").glob("*/executed_pipeline_draft.json"))


def test_execute_genesis_mode_on_from_node_draft_409(tmp_path):
    """A non-genesis draft may not execute with execution_mode='genesis'."""
    from workbench.lineage.pipeline_drafts import (
        DRAFT_SCHEMA_VERSION,
        PipelineDraftStore,
        schema_hash,
    )

    editable_schema = [{"key": "x", "kind": "columns", "label": "X"}]
    draft = {
        "draft_id": "draft_fromnode2",
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
    stored = PipelineDraftStore(tmp_path).create(draft)
    r = client.post(
        f"/pipeline-drafts/{draft['draft_id']}/execute?project_root={tmp_path}",
        json={
            "execution_mode": "genesis",
            "validated_draft_hash": stored.draft_hash,
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "GENESIS_ONLY_FOR_GENESIS_DRAFTS"


def test_execute_genesis_stale_hash_409(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis_rich(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    v = _validate(root, did).json()
    old_hash = v["validated_draft_hash"]
    # draft changes after validate -> the validated hash is stale
    client.patch(
        f"/pipeline-drafts/{did}/nodes/model_1?project_root={root}",
        json={"params": {"model_type": "ols", "y": "x", "x": ["y"]}},
    )
    r = client.post(
        f"/pipeline-drafts/{did}/execute?project_root={root}",
        json={"execution_mode": "genesis", "validated_draft_hash": old_hash},
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "VALIDATED_DRAFT_HASH_MISMATCH"
    assert not list((Path(root) / "runs").glob("*/executed_pipeline_draft.json"))


def test_execute_genesis_unvalidatable_chain_409(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis_rich(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did, model_params={"model_type": "ols"})  # no y/x
    v = _validate(root, did).json()
    assert v["executable"] is False
    current = client.get(f"/pipeline-drafts/{did}?project_root={root}").json()
    r = client.post(
        f"/pipeline-drafts/{did}/execute?project_root={root}",
        json={
            "execution_mode": "genesis",
            "validated_draft_hash": current["draft_hash"],
        },
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "VALIDATION_REQUIRED"
    assert not list((Path(root) / "runs").glob("*/executed_pipeline_draft.json"))


def test_execute_genesis_writes_snapshot(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis_rich(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    v = _validate(root, did).json()
    r = client.post(
        f"/pipeline-drafts/{did}/execute?project_root={root}",
        json={
            "execution_mode": "genesis",
            "validated_draft_hash": v["validated_draft_hash"],
        },
    ).json()
    snap_path = Path(root) / "runs" / r["run_id"] / "executed_pipeline_draft.json"
    assert snap_path.is_file()
    snap = json.loads(snap_path.read_text(encoding="utf-8"))
    assert snap["source_draft_id"] == did
    assert snap["executed_draft_hash"] == r["executed_draft_hash"]
    assert snap["execution_request"]["execution_mode"] == "genesis"
    assert snap["draft"]["created_from"]["source_type"] == "genesis"
    _wait_terminal(root, r["run_id"])


def test_list_summary_shows_genesis_model_type(tmp_path):
    """R2: configuring the model node mirrors model_type into the list summary."""
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    listed = client.get(f"/pipeline-drafts?project_root={root}").json()["drafts"]
    mine = next(item for item in listed if item["draft_id"] == did)
    assert mine["model_type"] == "ols"
