"""Manual discovery stays in sync with the executable declarations."""

from dataclasses import replace

from fastapi import FastAPI
from fastapi.testclient import TestClient


def _client():
    from workbench.http.operation_routes import router

    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_catalog_covers_live_registry_without_creating_project_records(tmp_path):
    from workbench.agent.operations import OperationRegistry

    response = _client().get("/operations", params={"project_root": str(tmp_path)})
    assert response.status_code == 200
    payload = response.json()
    entries = {item["id"]: item for item in payload["operations"]}
    assert set(OperationRegistry().operation_ids()) <= set(entries)
    assert payload["total"] == len(entries)
    assert list(entries) == sorted(entries)
    assert not list(tmp_path.iterdir())
    assert entries["data.aggregate"]["availability"]["status"] == "needs_target"
    assert entries["data.aggregate"]["execution"]["path"] == "/operations/run"
    assert entries["model.custom"]["availability"]["status"] == "unavailable"


def test_catalog_preserves_nested_form_contracts_and_dedicated_schema():
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    entries = {item["id"]: item for item in _client().get("/operations").json()["operations"]}
    aggregate = entries["data.aggregate"]
    assert aggregate["spec_schema"] == WORKFLOW_STEP_SPEC_CONTRACTS["data.aggregate"].to_schema()
    assert aggregate["spec_schema"]["properties"]["aggregations"]["items"]["properties"]["func"]["enum"]
    assert aggregate["field_hints"]["group_by"]["control"] == "list"
    assert entries["code.execute"]["execution"]["path"] == "/data-operations/code-execute/preview"
    assert entries["code.execute"]["execution"]["confirmation_path"] == "/data-operations/code-execute/confirm"
    assert entries["operation.multi_step"]["execution"]["kind"] == "dedicated"
    assert entries["operation.multi_step"]["execution"]["path"] == "/operations/run"
    assert entries["operation.multi_step"]["availability"]["status"] == "needs_parameters"
    custom = entries["model.custom"]
    assert custom["execution"]["kind"] == "dedicated"
    assert custom["execution"]["path"] == "/notebooks/{notebook_id}/options/{option_id}/confirm-and-execute"
    assert "body" in custom["execution"]["request_schema"]["properties"]
    assert "admitted_capability_binding" in custom["target_requirements"]
    assert custom["availability"]["reason_code"] == "AUTHORIZED_GATEWAY_REQUIRED"


def test_new_declaration_appears_with_defaults_without_catalog_changes(monkeypatch):
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    contract = replace(
        WORKFLOW_STEP_SPEC_CONTRACTS["data.aggregate"],
        summary="A newly registered operation.",
        fields={"limit": "Maximum rows."},
        required=(),
        field_types={"limit": "integer"},
        field_schemas={"limit": {"type": "integer", "minimum": 1, "default": 4}},
        field_enums={},
    )
    monkeypatch.setitem(WORKFLOW_STEP_SPEC_CONTRACTS, "data.catalog_probe", contract)
    entries = {item["id"]: item for item in _client().get("/operations").json()["operations"]}
    item = entries["data.catalog_probe"]
    assert item["spec_schema"]["properties"]["limit"]["default"] == 4
    assert item["spec_schema"]["properties"]["limit"]["minimum"] == 1
    assert item["field_hints"]["limit"]["control"] == "number"
    assert item["execution"]["kind"] == "workflow"


def test_unresolvable_target_is_reported_without_any_writes(tmp_path):
    response = _client().get("/operations", params={
        "project_root": str(tmp_path), "source_run_id": "absent",
        "source_node_id": "stage:raw", "source_artifact_id": "raw_data",
    })
    assert response.status_code == 200
    entries = {item["id"]: item for item in response.json()["operations"]}
    assert entries["data.aggregate"]["availability"]["status"] == "unavailable"
    assert entries["data.aggregate"]["availability"]["reason_code"] == "TARGET_INVALID"
    assert not list(tmp_path.iterdir())
