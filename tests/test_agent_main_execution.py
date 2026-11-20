"""Project research sessions use the common source-bound execution lifecycle."""
import asyncio
import json
from workbench.artifacts import sha256_file
import pytest
from fastapi.testclient import TestClient

from tests.test_read_only_analysis import _Fixture, _explore, _recode
from tests.test_agent_workflow_integration import IdleAdapter
from workbench.agent.core import AgentCore
from workbench.agent.operation_requests import OperationRequest
from workbench.agent.chains import ChainStore
from workbench.app import app


def _main(fixture):
    source = fixture.project_root / "runs" / fixture.run_id
    digest = sha256_file(source / "data.csv")
    (source / "node_index.json").write_text(json.dumps({"stage:source":{
        "node_hash":digest, "producing_stage":"ingestion",
        "cas_ref":{"node_hash":digest, "artifact":"data.csv"}}}))
    core = AgentCore(fixture.repository, fixture.orchestrator.events, IdleAdapter(), session_id="main-session")
    fixture.orchestrator.register_main("main-session", core)
    fixture.orchestrator.execution_policy = "proposal_only"
    return fixture.orchestrator.tool_registry("project")


def _request(fixture, steps):
    return {"operation_id":"operation.multi_step", "target":{
        "run_id":fixture.run_id, "node_ref":"stage:source", "artifact_id":fixture.artifact_id},
        "preconditions":{"context_version":"node-operation-context/v1", "context_fingerprint":"client-preview",
                         "active_head_run_id":fixture.run_id, "owner_resolution":"single_candidate"},
        "changes":{"steps":steps}, "evidence_refs":[], "expected_effect":["Analyze the source."], "risks":[]}


def test_main_proposal_keeps_project_identity_and_confirms_through_common_http(tmp_path):
    fixture = _Fixture(tmp_path)
    registry = _main(fixture)
    result = asyncio.run(registry.execute({"tool_id":"run_operation", "tool_call_id":"run",
        "arguments":_request(fixture, [_explore("tab", "region")])}, session_id="main-session"))
    assert result.ok, result
    proposal = result.output["proposal"]
    assert proposal["session_id"] == "main-session"
    assert proposal["chain_id"] != "project"
    assert fixture.repository.get_metadata("main-session")["role"] == "main"
    assert ChainStore(fixture.repository.root).get(proposal["chain_id"])["agent_session_id"] == "main-session"
    assert fixture.orchestrator.operation_store.list_records() == []
    with TestClient(app) as client:
        params = {"project_root":str(fixture.project_root)}
        response = client.post(f"/agent/sessions/main-session/proposals/{proposal['proposal_id']}/confirm",
            params=params, json={"revision":proposal["revision"], "fingerprint":proposal["fingerprint"],
                                 "active_head_run_id":fixture.run_id})
        assert response.status_code == 200, response.text
        record = response.json()["operation"]
        assert record["status"] == "completed", record
        projection = client.get(f"/agent/sessions/main-session/operations/{record['record_id']}", params=params)
        assert projection.status_code == 200, projection.text
        forbidden = client.get(f"/agent/sessions/chain-session/operations/{record['record_id']}", params=params)
        assert forbidden.status_code == 404


def test_main_cannot_admit_under_another_sessions_chain(tmp_path):
    fixture = _Fixture(tmp_path)
    _main(fixture)
    with pytest.raises(ValueError, match="scope|matching"):
        fixture.orchestrator.admit_operation_request(OperationRequest.from_arguments(
            _request(fixture, [_recode()])), chain_id="chain-a", session_id="main-session")
    assert fixture.orchestrator.operation_store.list_records() == []


def test_main_proposal_context_is_bounded_while_full_proposal_is_retained(tmp_path):
    fixture = _Fixture(tmp_path)
    registry = _main(fixture)
    arguments = _request(fixture, [_recode()])
    arguments["expected_effect"] = ["E" * 30000]
    result = asyncio.run(registry.execute({"tool_id":"run_operation", "tool_call_id":"large",
        "arguments":arguments}, session_id="main-session"))
    assert result.ok
    messages = [e.payload for e in fixture.repository.get_branch("main-session")
                if e.entry_type == "custom_message" and e.payload.get("message_type") == "operation_proposal"]
    assert len(messages) == 1
    assert len(messages[0]["content"]) <= 24000
    assert messages[0]["proposal"]["expected_effect"] == arguments["expected_effect"]
