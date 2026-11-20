"""Saved column roles are usable without widening server-owned rerun options."""
from __future__ import annotations

from copy import deepcopy
import json
from types import SimpleNamespace

import pytest

from workbench.http import _deps
from workbench.services import draft_materialization


@pytest.fixture(params=["http", "service"])
def backfill(request):
    return (_deps._backfill_schema_values if request.param == "http"
            else draft_materialization._backfill_schema_values)


@pytest.mark.parametrize("key,columns", [("iv_endog", ["d1", "d2"]),
                                         ("iv_instruments", ["z1", "z2", "z3"])])
@pytest.mark.parametrize("encoding", ["json", "list", "csv"])
@pytest.mark.parametrize("options", [None, []])
def test_saved_iv_roles_decode_and_fill_only_current_options(backfill, key, columns, encoding, options):
    schema = [{"key": key, "kind": "columns", "options": options}]
    before = deepcopy(schema)
    raw = json.dumps(columns) if encoding == "json" else columns if encoding == "list" else ", ".join(columns)
    control = backfill(schema, {key: raw})[0]
    assert control["value"] == columns
    assert control["options"] == columns
    assert schema == before


def test_missing_options_are_filled_without_exposing_dataset_columns(backfill):
    result = backfill([{"key": "iv_endog", "kind": "columns"}], {"iv_endog": '["d1"]'})
    assert result[0]["value"] == ["d1"]
    assert result[0]["options"] == ["d1"]


@pytest.mark.parametrize("key", ["iv_endog", "focal_x"])
def test_existing_server_candidates_are_preserved(backfill, key):
    schema = [{"key": key, "kind": "columns", "options": ["current", "authorized_other"]}]
    before = deepcopy(schema)
    result = backfill(schema, {key: '["current"]'})
    assert result[0]["value"] == ["current"]
    assert result[0]["options"] == ["current", "authorized_other"]
    assert schema == before


def test_x_still_restricts_reruns_to_dropping_current_columns(backfill):
    schema = [{"key": "x", "kind": "columns", "options": ["w1", "w2", "not_current"]}]
    result = backfill(schema, {"x": '["w1", "w2"]'})
    assert result[0]["value"] == result[0]["options"] == ["w1", "w2"]
    assert schema[0]["options"] == ["w1", "w2", "not_current"]


def test_missing_values_and_noncolumn_controls_keep_existing_defaults(backfill):
    schema = [{"key": "iv_endog", "kind": "columns", "value": ["saved"], "options": ["saved"]},
              {"key": "covariance", "kind": "select", "value": "robust", "options": ["robust", "unadjusted"]}]
    assert backfill(schema, {"iv_endog": "", "covariance": None}) == schema
    assert backfill(schema, {"covariance": "unadjusted"})[1]["value"] == "unadjusted"


def test_http_backfill_delegates_to_the_same_service_helper(monkeypatch):
    called = []
    expected = [{"same": "shared implementation"}]

    def shared(schema, form):
        called.append((schema, form))
        return expected

    monkeypatch.setattr(draft_materialization, "_backfill_schema_values", shared)
    schema, form = [], {}
    assert _deps._backfill_schema_values(schema, form) is expected
    assert called == [(schema, form)]


def test_http_graph_annotation_exposes_saved_iv_role_choices():
    from workbench.http.graph_routes import _annotate_editable_node

    node = {"stage": "model"}
    _annotate_editable_node(node, {"requested_model_type": "iv_2sls"},
                            {"model_type": "iv_2sls", "x": '["w"]',
                             "iv_endog": '["d1", "d2"]', "iv_instruments": '["z1", "z2", "z3"]'})
    controls = {control["key"]: control for control in node["editable_schema"]}
    assert controls["iv_endog"]["value"] == controls["iv_endog"]["options"] == ["d1", "d2"]
    assert controls["iv_instruments"]["value"] == controls["iv_instruments"]["options"] == ["z1", "z2", "z3"]


def test_from_run_draft_materialization_keeps_decoded_iv_roles(tmp_path, monkeypatch):
    """Exercise the real source-form projection; identity validation has separate coverage."""
    from workbench.projects import create_project

    project = create_project(tmp_path, "saved_iv")
    run_id = "20261104_000000_saved_iv"
    run = project.root / "runs" / run_id
    run.mkdir()
    node_hash = "b" * 64
    (run / "run_manifest.json").write_text(json.dumps({"status": "completed", "requested_model_type": "iv_2sls"}))
    (run / "node_index.json").write_text(json.dumps({"model_1": {"node_hash": node_hash}}))
    (run / "run_inputs.json").write_text(json.dumps({
        "upload": {"sha256": "a" * 64, "filename": "iv.csv"},
        "form": {"model_type": "iv_2sls", "x": '["w"]', "iv_endog": '["d1", "d2"]',
                 "iv_instruments": '["z1", "z2", "z3"]', "estimation_engine": "fast"},
    }))
    node = SimpleNamespace(stage=SimpleNamespace(value="model"))
    monkeypatch.setattr(draft_materialization.GraphStore, "read", lambda self, source: SimpleNamespace(nodes={"model_1": node}))
    monkeypatch.setattr(draft_materialization, "validate_rerun_operation_target", lambda *args: None)
    stored = draft_materialization.create_rerun_draft_from_node(
        project.root, source_run_id=run_id, source_model_node_id="model_1", source_op_node_id="model_1",
        source_node_hash=node_hash, source_forest_node_key=None, source_context_fingerprint="context", persist=False)
    model = next(item for item in stored.draft["graph"]["nodes"] if item["node_type"] == "model")
    controls = {control["key"]: control for control in model["editable_schema"]}
    for key, expected in (("iv_endog", ["d1", "d2"]), ("iv_instruments", ["z1", "z2", "z3"])):
        assert model["params"][key] == model["source_params"][key] == expected
        assert controls[key]["value"] == controls[key]["options"] == expected
