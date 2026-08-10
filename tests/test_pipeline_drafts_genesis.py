"""v1.6.8 Task 2: POST /pipeline-drafts/genesis — parentless genesis draft chain."""
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.api import app
from workbench.contracts.model.linear_mixed_effects import (
    LMM_MODEL_TYPE,
)
from workbench.engine.capabilities import build_capabilities
from workbench.lineage.pipeline_drafts import _validate_graph_shape
from tests.fixtures.models.ets.known_truth import short_stable_series

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


def test_genesis_draft_publishes_initial_server_owned_editor_schema(tmp_path):
    root = _mkproject(tmp_path)
    draft = _genesis(root)["draft"]
    model = next(node for node in draft["graph"]["nodes"] if node["node_id"] == "model_1")
    controls = {item["key"]: item for item in model["editable_schema"]}
    declared_model_types = {
        entry["key"] for entry in build_capabilities()["model_types"]
    }

    assert model["schema_id"] == "genesis.selector@v1"
    assert model["editable_schema_hash"]
    assert controls["model_type"]["options"] == sorted(declared_model_types)
    assert controls["y"]["options"] == ["y", "x"]
    assert controls["x"]["options"] == ["y", "x"]


def test_genesis_model_selector_derives_injected_manifest_entry(monkeypatch):
    """A newly declared model family must appear without a second value list."""
    import workbench.engine.capabilities as capabilities
    from workbench.services.draft_materialization import _genesis_model_editor_schema

    live_manifest = capabilities.build_capabilities()

    def manifest_with_future_family():
        return {
            **live_manifest,
            "model_types": [
                *live_manifest["model_types"],
                {"key": "zz_future_model", "description": "Future model family"},
            ],
        }

    monkeypatch.setattr(capabilities, "build_capabilities", manifest_with_future_family)
    _schema_id, controls = _genesis_model_editor_schema(None, ("y", "x"))

    model_selector = next(control for control in controls if control["key"] == "model_type")
    assert "zz_future_model" in model_selector["options"]


def test_declared_family_editor_never_falls_back_when_contract_lookup_breaks(
    monkeypatch,
):
    """A broken live family contract must stay visible instead of yielding an empty schema."""
    import workbench.agent.workflow_contracts as workflow_contracts
    from workbench.services.draft_materialization import _genesis_model_editor_schema

    def broken_contract_lookup(_model_type):
        raise RuntimeError("contract registry unavailable")

    monkeypatch.setattr(
        workflow_contracts,
        "model_family_contract",
        broken_contract_lookup,
    )

    with pytest.raises(RuntimeError, match="contract registry unavailable"):
        _genesis_model_editor_schema("ols", ("y", "x"))


def test_declared_family_editor_never_discards_a_broken_wire_projection():
    """A family builder failure must not silently erase its projected controls."""
    from workbench.agent.workflow_contracts import model_family_contract
    from workbench.services.draft_materialization import _family_wire_projection

    def broken_builder(*_args, **_kwargs):
        raise ValueError("builder contract changed")

    broken_family = replace(
        model_family_contract("cs_did"),
        build_model_params=broken_builder,
    )

    with pytest.raises(
        ValueError,
        match="MODEL_FAMILY_SCHEMA_PROJECTION_FAILED: cs_did",
    ):
        _family_wire_projection("cs_did", broken_family)


def test_native_family_projection_preserves_non_family_execution_params():
    """Native family projection must not silently discard shared run controls."""
    from workbench.services.draft_service import (
        _project_native_family_params_for_execution,
    )

    projected = _project_native_family_params_for_execution(
        {
            "model_type": "dcdh",
            "editable_schema": [
                {"key": "entity_col"},
                {"key": "time_col"},
                {"key": "treatment_path_col", "satisfied_by": ["did_treatment_path"]},
            ],
        },
        {
            "model_type": "dcdh",
            "y": "outcome",
            "x": [],
            "entity_col": "unit",
            "time_col": "period",
            "treatment_path_col": "path",
            "prediction_model_type": "prediction_ridge",
            "prediction_cv_folds": 3,
        },
    )

    assert projected["prediction_model_type"] == "prediction_ridge"
    assert projected["prediction_cv_folds"] == 3
    assert projected["did_treatment_path"] == "path"
    assert "treatment_path_col" not in projected


def test_genesis_column_kind_follows_the_declared_wire_kind():
    """A newly declared multi-column field must not require a second key list."""
    from workbench.services.draft_materialization import _genesis_column_kind

    assert _genesis_column_kind("future_many", "columns") == "columns"
    assert _genesis_column_kind("future_one", "column") == "column"


def test_family_context_schema_derives_scalar_or_list_wire_kind():
    """Family context controls must follow the builder's persisted value shape."""
    from workbench.services.draft_materialization import _genesis_model_editor_schema

    _schema_id, panel_controls = _genesis_model_editor_schema(
        "panel_ols", ("outcome", "predictor", "entity", "period")
    )
    panel = {item["key"]: item for item in panel_controls}
    assert panel["entity_col"]["kind"] == "column"
    assert panel["time_col"]["kind"] == "column"

    _schema_id, iv_controls = _genesis_model_editor_schema(
        "iv_2sls", ("outcome", "predictor", "endogenous", "instrument")
    )
    iv = {item["key"]: item for item in iv_controls}
    assert iv["iv_endog"]["kind"] == "columns"
    assert iv["iv_instruments"]["kind"] == "columns"


def test_quantile_model_options_accept_declared_list_values(tmp_path):
    """Family validators, not a false string schema, own quantile option types."""
    root = _mkproject(tmp_path)
    draft = _genesis(root)["draft"]
    draft_id = draft["draft_id"]
    table = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/table_1?project_root={root}",
        json={"params": {"sheet_name": "", "transpose": False}, "columns": ["y", "x"]},
    )
    assert table.status_code == 200, table.text

    response = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={
            "params": {
                "model_type": "quantile_regression",
                "y": "y",
                "x": ["x"],
                "model_options": {
                    "quantiles": [0.25, 0.5, 0.75],
                    "bootstrap_reps": 0,
                    "random_state": 7,
                },
            }
        },
    )

    assert response.status_code == 200, response.text


def test_model_type_patch_refreshes_schema_and_rejects_undeclared_field(tmp_path):
    root = _mkproject(tmp_path)
    draft = _genesis(root)["draft"]
    draft_id = draft["draft_id"]
    table = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/table_1?project_root={root}",
        json={"params": {"sheet_name": "", "transpose": False}, "columns": ["y", "x"]},
    )
    assert table.status_code == 200, table.text

    selected = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={"params": {"model_type": "ols", "y": "y", "x": ["x"]}},
    )
    assert selected.status_code == 200, selected.text
    model = next(node for node in selected.json()["draft"]["graph"]["nodes"] if node["node_id"] == "model_1")
    controls = {item["key"]: item for item in model["editable_schema"]}
    assert model["schema_id"] == "ols@v1"
    assert controls["x"]["options"] == ["y", "x"]
    assert controls["y"]["options"] == ["y", "x"]

    forged = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={
            "params": {
                "model_type": "ols",
                "y": "y",
                "x": ["x"],
                "forged_execution_switch": True,
            }
        },
    )
    assert forged.status_code == 422
    assert "NON_EDITABLE_PARAM" in forged.json()["detail"]


def test_model_type_selection_refreshes_schema_before_family_params_are_complete(tmp_path):
    """Selecting a family is a server round-trip, not a client schema guess."""
    root = _mkproject(tmp_path)
    draft = _genesis(root)["draft"]
    draft_id = draft["draft_id"]
    table = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/table_1?project_root={root}",
        json={"params": {"sheet_name": "", "transpose": False}, "columns": ["y", "x"]},
    )
    assert table.status_code == 200, table.text

    selected = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={"params": {"model_type": "time_series.ets"}},
    )

    assert selected.status_code == 200, selected.text
    model = next(node for node in selected.json()["draft"]["graph"]["nodes"] if node["node_id"] == "model_1")
    assert model["schema_id"] == "time_series.ets@v1"
    assert model["status"] == "pending"
    assert model["params"] == {"model_type": "time_series.ets"}
    model_options = next(item for item in model["editable_schema"] if item["key"] == "model_options")
    assert model_options["schema"]["required"] == [
        "time_column",
        "value_column",
        "error",
        "trend",
        "seasonal",
        "damped_trend",
    ]


def test_recipe_schema_projects_declared_dotted_paths_and_server_owned_fields(tmp_path):
    """The Recipe vocabulary's nested wire shape is preserved in the Draft schema."""
    root = _mkproject(tmp_path)
    draft = _genesis(
        root,
        data=b"when,value\n2020-01-01,1\n2020-01-02,2\n",
        columns=["when", "value"],
    )["draft"]
    selected = client.patch(
        f"/pipeline-drafts/{draft['draft_id']}/nodes/model_1?project_root={root}",
        json={"params": {"model_type": "time_series.arma_garch"}},
    )

    assert selected.status_code == 200, selected.text
    model = next(node for node in selected.json()["draft"]["graph"]["nodes"] if node["node_id"] == "model_1")
    control = next(item for item in model["editable_schema"] if item["key"] == "model_options")
    schema = control["schema"]

    assert "arma" in schema["properties"]
    assert "p" in schema["properties"]["arma"]["properties"]
    assert "arma.p" not in schema["properties"]
    assert schema["properties"]["dataset_ref"]["server_owned"] is True
    assert "dataset_ref" in schema["required"]


def test_recipe_server_owned_source_binding_is_derived_and_forgery_is_rejected(tmp_path):
    """Recipe source identity is bound from the upload, never accepted as a free client field."""
    root = _mkproject(tmp_path)
    uploaded = _upload(
        root,
        name="series.csv",
        data=b"when,value\n2020-01-01,1\n2020-01-02,2\n",
    )
    draft = _genesis(root, data=b"when,value\n2020-01-01,1\n2020-01-02,2\n", columns=["when", "value"])["draft"]
    draft_id = draft["draft_id"]
    assert uploaded["sha256"] == draft["created_from"]["source_input_fingerprint"]
    client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/table_1?project_root={root}",
        json={"params": {"sheet_name": "", "transpose": False}, "columns": ["when", "value"]},
    )
    options = {
        "time_column": "when",
        "value_column": "value",
        "time_index_semantics": "observation_order",
        "transform": "level",
        "transform_confirmed": True,
    }
    selected = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={"params": {"model_type": "time_series.arma_garch", "model_options": options}},
    )
    assert selected.status_code == 200, selected.text
    model = next(node for node in selected.json()["draft"]["graph"]["nodes"] if node["node_id"] == "model_1")
    assert model["params"]["model_options"]["dataset_ref"] == f"upload:{uploaded['sha256']}"

    forged = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={
            "params": {
                "model_type": "time_series.arma_garch",
                "model_options": {**options, "dataset_ref": "upload:attacker.csv"},
            }
        },
    )
    assert forged.status_code == 422
    assert "RECIPE_SERVER_OWNED_OPTION_MISMATCH" in forged.json()["detail"]


def test_table_patch_refreshes_model_column_options_and_hash_atomically(tmp_path):
    root = _mkproject(tmp_path)
    draft = _genesis(root)["draft"]
    draft_id = draft["draft_id"]
    first = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/table_1?project_root={root}",
        json={"params": {"sheet_name": "", "transpose": False}, "columns": ["y", "x"]},
    )
    assert first.status_code == 200, first.text
    first_model = next(node for node in first.json()["draft"]["graph"]["nodes"] if node["node_id"] == "model_1")

    second = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/table_1?project_root={root}",
        json={"params": {"sheet_name": "", "transpose": False}, "columns": ["y", "z"]},
    )
    assert second.status_code == 200, second.text
    second_model = next(node for node in second.json()["draft"]["graph"]["nodes"] if node["node_id"] == "model_1")
    controls = {item["key"]: item for item in second_model["editable_schema"]}

    assert controls["x"]["options"] == ["y", "z"]
    assert controls["y"]["options"] == ["y", "z"]
    assert second_model["editable_schema_hash"] != first_model["editable_schema_hash"]
    assert second_model["editable_schema_hash"]


def test_model_patch_rejects_column_not_in_bound_table(tmp_path):
    root = _mkproject(tmp_path)
    draft = _genesis(root)["draft"]
    draft_id = draft["draft_id"]
    table = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/table_1?project_root={root}",
        json={"params": {"sheet_name": "", "transpose": False}, "columns": ["y", "x"]},
    )
    assert table.status_code == 200, table.text

    forged = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={"params": {"model_type": "ols", "y": "y", "x": ["not_a_column"]}},
    )
    assert forged.status_code == 422
    assert "INVALID_PARAM_OPTION" in forged.json()["detail"]


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


def test_validate_graph_shape_rejects_non_canonical_node_ids():
    """R2: execute resolves the chain by source_1/table_1/model_1 — the
    validator must enforce those exact ids, not just distinct types."""
    draft = _genesis_draft_dict()
    draft["graph"]["nodes"][1]["node_id"] = "tbl_custom"
    draft["graph"]["edges"] = [
        {"from": "source_1", "to": "tbl_custom"},
        {"from": "tbl_custom", "to": "model_1"},
    ]
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


def _genesis(root, sheet_names=None, columns=None, **kw):
    upload_kwargs = {
        key: kw.pop(key)
        for key in ("name", "data")
        if key in kw
    }
    up = _upload(root, **upload_kwargs)
    return client.post(
        f"/pipeline-drafts/genesis?project_root={root}",
        json={
            "upload_sha256": up["sha256"],
            "filename": up["filename"],
            "sheet_names": sheet_names or [],
            "columns": columns or ["y", "x"],
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


def _configure_chain(root, did, model_params=None, table_params=None, columns=None):
    client.patch(
        f"/pipeline-drafts/{did}/nodes/table_1?project_root={root}",
        json={
            "params": table_params or {"sheet_name": "", "transpose": False},
            "columns": columns or ["y", "x"],
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


def test_validate_genesis_rejects_nonobject_model_options_before_execution(tmp_path):
    root = _mkproject(tmp_path)
    draft = _genesis(root)
    draft_id = draft["draft"]["draft_id"]
    table = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/table_1?project_root={root}",
        json={"params": {"sheet_name": "", "transpose": False}, "columns": ["y", "x"]},
    )
    assert table.status_code == 200, table.text
    response = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={
            "params": {
                "model_type": "ols",
                "y": "y",
                "x": ["x"],
                "model_options": ["not", "an", "object"],
            }
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "INVALID_PARAM_TYPE"
    current = client.get(f"/pipeline-drafts/{draft_id}?project_root={root}").json()
    model = next(node for node in current["draft"]["graph"]["nodes"] if node["node_id"] == "model_1")
    assert model["params"] == {}


def test_genesis_draft_rejects_client_owned_model_options_binding(tmp_path):
    root = _mkproject(tmp_path)
    draft = _genesis(root)
    draft_id = draft["draft"]["draft_id"]
    _configure_chain(root, draft_id)

    response = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={
            "params": {
                "model_options_binding": {
                    "owner_model_type": "forged",
                    "owner_model_id": "forged",
                    "producer_version": "forged",
                    "input_contract_version": "0",
                    "normalized_options_hash": "0" * 64,
                }
            }
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "MODEL_OPTIONS_BINDING_CLIENT_MANAGED"
    current = client.get(f"/pipeline-drafts/{draft_id}?project_root={root}").json()
    model = next(
        node
        for node in current["draft"]["graph"]["nodes"]
        if node["node_id"] == "model_1"
    )
    assert "model_options_binding" not in model["params"]


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


def test_validate_genesis_accepts_univariate_arma_garch_recipe_without_regression_fields(tmp_path):
    root = _mkproject(tmp_path)
    draft = _genesis(
        root,
        data=b"when,value\n2020-01-01,1\n2020-01-02,2\n",
        columns=["when", "value"],
    )
    draft_id = draft["draft"]["draft_id"]
    _configure_chain(
        root,
        draft_id,
        model_params={
            "model_type": "time_series.arma_garch",
            "model_options": {
                "time_column": "when",
                "value_column": "value",
                "time_index_semantics": "observation_order",
                "transform": "level",
                "transform_confirmed": True,
            },
        },
        columns=["when", "value"],
    )

    body = _validate(root, draft_id).json()

    assert body["executable"] is True
    assert not any(c["code"] == "GENESIS_MODEL_INCOMPLETE" for c in body["checks"])


def test_execute_genesis_ets_recipe_maps_value_column_to_runtime_outcome(tmp_path):
    """A Recipe keeps y/x out of its public Draft yet remains executable.

    The generic workflow still needs one outcome column for early column
    checks.  A RecipeContract, not a UI-specific branch, owns the mapping from
    its value input to that internal runtime field.
    """
    root = _mkproject(tmp_path)
    series = short_stable_series().frame(time_column="when", value_column="value")
    draft = _genesis(
        root,
        data=series.to_csv(index=False).encode(),
        columns=["when", "value"],
    )
    draft_id = draft["draft"]["draft_id"]
    _configure_chain(
        root,
        draft_id,
        model_params={
            "model_type": "time_series.ets",
            "model_options": {
                "time_column": "when",
                "value_column": "value",
                "error": "add",
                "trend": "add",
                "seasonal": None,
                "damped_trend": False,
            },
        },
        columns=["when", "value"],
    )

    validation = _validate(root, draft_id).json()
    assert validation["executable"] is True
    response = client.post(
        f"/pipeline-drafts/{draft_id}/execute?project_root={root}",
        json={
            "execution_mode": "genesis",
            "validated_draft_hash": validation["validated_draft_hash"],
        },
    )

    assert response.status_code == 200, response.text
    run_id = response.json()["run_id"]
    inputs = json.loads(
        (Path(root) / "runs" / run_id / "run_inputs.json").read_text(encoding="utf-8")
    )
    assert inputs["form"]["y"] == "value"
    assert inputs["form"]["x"] == ""
    assert _wait_terminal(root, run_id) == "completed"
    graph = json.loads(
        (Path(root) / "runs" / run_id / "graph.json").read_text(encoding="utf-8")
    )
    model_node = graph["nodes"]["model:ets_1"]
    assert model_node["display_label"] == "time_series.ets (primary)"
    assert model_node["summary"] == f"time_series.ets (n={len(series)})"


def test_validate_genesis_rejects_regression_shaped_arma_garch_recipe(tmp_path):
    root = _mkproject(tmp_path)
    draft = _genesis(root)
    draft_id = draft["draft"]["draft_id"]
    table = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/table_1?project_root={root}",
        json={"params": {"sheet_name": "", "transpose": False}, "columns": ["y", "x"]},
    )
    assert table.status_code == 200, table.text
    response = client.patch(
        f"/pipeline-drafts/{draft_id}/nodes/model_1?project_root={root}",
        json={
            "params": {
                "model_type": "time_series.arma_garch",
                "y": "y",
                "x": [],
                "model_options": {},
            }
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "NON_EDITABLE_PARAM, MISSING_EDITABLE_PARAM"
    current = client.get(f"/pipeline-drafts/{draft_id}?project_root={root}").json()
    model = next(node for node in current["draft"]["graph"]["nodes"] if node["node_id"] == "model_1")
    assert model["params"] == {}


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
    raise AssertionError(
        f"run {run_id} not terminal after {tries} tries, last status={body.get('status')!r}"
    )


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


def test_execute_genesis_normalizes_legacy_ols_covariance_model_options(tmp_path):
    """A materialized OLS Draft keeps its bound options and legacy projection."""
    root = _mkproject(tmp_path)
    d = _genesis_rich(root)
    did = d["draft"]["draft_id"]
    _configure_chain(
        root,
        did,
        model_params={
            "model_type": "ols",
            "y": "y",
            "x": ["x"],
            "model_options": {"covariance": "robust"},
        },
    )
    v = _validate(root, did).json()
    response = client.post(
        f"/pipeline-drafts/{did}/execute?project_root={root}",
        json={
            "execution_mode": "genesis",
            "validated_draft_hash": v["validated_draft_hash"],
        },
    )
    assert response.status_code == 200, response.text
    inputs = json.loads(
        (Path(root) / "runs" / response.json()["run_id"] / "run_inputs.json").read_text(
            encoding="utf-8"
        )
    )
    assert inputs["form"]["covariance"] == "robust"
    assert inputs["form"]["model_options"] == {"covariance": "robust"}
    _wait_terminal(root, response.json()["run_id"])


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


def test_execute_genesis_marks_draft_executed_for_reload_hydration(tmp_path):
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
    _wait_terminal(root, r["run_id"])

    summaries = client.get(f"/pipeline-drafts?project_root={root}").json()["drafts"]
    summary = next(item for item in summaries if item["draft_id"] == did)
    assert summary["status"] == "executed"


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


def test_execute_genesis_snapshot_carries_server_owned_model_options_binding(
    tmp_path,
):
    root = _mkproject(tmp_path)
    draft = _genesis_rich(root)
    draft_id = draft["draft"]["draft_id"]
    _configure_chain(
        root,
        draft_id,
        model_params={
            "model_type": LMM_MODEL_TYPE,
            "y": "y",
            "x": ["x"],
            "model_options": {
                "subject_id": "participant_id",
                "time": "week",
                "group": "arm",
                "fit_method": "reml",
                "random_slope": True,
            },
        },
        columns=["y", "x", "participant_id", "week", "arm"],
    )
    validated = _validate(root, draft_id).json()
    response = client.post(
        f"/pipeline-drafts/{draft_id}/execute?project_root={root}",
        json={
            "execution_mode": "genesis",
            "validated_draft_hash": validated["validated_draft_hash"],
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "LMM_FROZEN_CONTAINMENT_REQUIRED"
    # C1 validates and binds LMM inputs, but C2 has not yet admitted a real
    # OS-contained evaluator.  Refusal is before draft snapshots, uploads,
    # or runs are materialized, so no ordinary executor can bypass C2.
    assert not list((Path(root) / "runs").iterdir())


# --- Task 7 (F6): reclaim unreferenced upload on genesis draft discard ---


def _blob_path(root, sha):
    # resolve_upload raises UploadBlobMissing when absent, so tests check the
    # content-addressed path directly (layout: <root>/data/uploads/<sha256>).
    return Path(root) / "data" / "uploads" / sha


def _genesis_sha(d):
    return next(
        n for n in d["draft"]["graph"]["nodes"] if n["node_id"] == "source_1"
    )["upload"]["sha256"]


def test_discard_genesis_reclaims_unreferenced_upload(tmp_path):
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    sha = _genesis_sha(d)
    assert _blob_path(root, sha).is_file()
    r = client.delete(f"/pipeline-drafts/{did}?project_root={root}")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and body["draft_id"] == did
    assert body["upload_reclaimed"] is True
    assert not _blob_path(root, sha).exists()


def test_discard_keeps_upload_referenced_by_run(tmp_path):
    """After a genesis chain EXECUTES, run_inputs.json references the sha —
    discarding the draft must NOT reclaim the blob."""
    root = _mkproject(tmp_path)
    d = _genesis_rich(root)
    did = d["draft"]["draft_id"]
    sha = _genesis_sha(d)
    _configure_chain(root, did)
    v = _validate(root, did).json()
    r = client.post(
        f"/pipeline-drafts/{did}/execute?project_root={root}",
        json={
            "execution_mode": "genesis",
            "validated_draft_hash": v["validated_draft_hash"],
        },
    ).json()
    _wait_terminal(root, r["run_id"])
    dr = client.delete(f"/pipeline-drafts/{did}?project_root={root}")
    assert dr.status_code == 200
    assert dr.json()["upload_reclaimed"] is False
    assert _blob_path(root, sha).is_file()


def test_discard_keeps_upload_referenced_by_other_draft(tmp_path):
    """Two genesis drafts over the same bytes share one blob (content-addressed).
    Discarding one keeps the blob; discarding the last reclaims it."""
    root = _mkproject(tmp_path)
    d1 = _genesis(root)
    d2 = _genesis(root)  # same default bytes -> same sha, dedup'd store
    sha = _genesis_sha(d1)
    assert _genesis_sha(d2) == sha
    r1 = client.delete(
        f"/pipeline-drafts/{d1['draft']['draft_id']}?project_root={root}"
    )
    assert r1.status_code == 200
    assert r1.json()["upload_reclaimed"] is False
    assert _blob_path(root, sha).is_file()
    r2 = client.delete(
        f"/pipeline-drafts/{d2['draft']['draft_id']}?project_root={root}"
    )
    assert r2.status_code == 200
    assert r2.json()["upload_reclaimed"] is True
    assert not _blob_path(root, sha).exists()


def test_discard_from_node_draft_never_touches_blobs(tmp_path):
    """Regression: discarding a FROM-NODE draft performs no blob GC at all —
    an unrelated blob in the store must survive."""
    from workbench.lineage.pipeline_drafts import (
        DRAFT_SCHEMA_VERSION,
        PipelineDraftStore,
        schema_hash,
    )

    root = _mkproject(tmp_path)
    up = _upload(root)  # unrelated blob sitting in the store
    sha = up["sha256"]
    assert _blob_path(root, sha).is_file()

    editable_schema = [{"key": "x", "kind": "columns", "label": "X"}]
    draft = {
        "draft_id": "draft_fromnode7",
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
    PipelineDraftStore(Path(root)).create(draft)
    r = client.delete(f"/pipeline-drafts/draft_fromnode7?project_root={root}")
    assert r.status_code == 200
    assert r.json()["upload_reclaimed"] is False
    assert _blob_path(root, sha).is_file()


def test_delete_upload_if_unreferenced_missing_blob_is_noop(tmp_path):
    """Unit: no references and no blob -> False, no crash."""
    from workbench.lineage.upload_store import delete_upload_if_unreferenced

    assert delete_upload_if_unreferenced(tmp_path, "0" * 64) is False


def test_list_summary_shows_genesis_model_type(tmp_path):
    """R2: configuring the model node mirrors model_type into the list summary."""
    root = _mkproject(tmp_path)
    d = _genesis(root)
    did = d["draft"]["draft_id"]
    _configure_chain(root, did)
    listed = client.get(f"/pipeline-drafts?project_root={root}").json()["drafts"]
    mine = next(item for item in listed if item["draft_id"] == did)
    assert mine["model_type"] == "ols"
