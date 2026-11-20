"""Real generic and fork adapters share typed proposal admission."""
from __future__ import annotations

from tests.operation_request_fixtures import admit_proposal

import asyncio
import importlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.operations import UnknownOperationError
from workbench.app import app
from tests.test_agent_proposal_operations import make_orchestrator, proposal_kwargs
from tests.test_agent_routes import _write_inspectable_run


def request_module():
    path = Path(__file__).parents[1] / "backend/workbench/agent/operation_requests.py"
    assert path.is_file(), "typed operation request admission is not implemented"
    return importlib.import_module("workbench.agent.operation_requests")


def test_legacy_arguments_normalize_to_one_typed_request_without_wire_changes() -> None:
    module = request_module()
    arguments = {key: value for key, value in proposal_kwargs().items() if key not in {"chain_id", "command_id"}}
    request = module.OperationRequest.from_arguments(arguments)
    assert request.operation_id == "model.rerun"
    assert request.operation_version == "v1"
    assert request.target == arguments["target"]
    assert request.preconditions == arguments["preconditions"]
    assert request.changes == arguments["changes"]
    assert list(request.evidence_refs) == arguments["evidence_refs"]
    assert list(request.expected_effect) == arguments["expected_effect"]
    assert list(request.risks) == arguments["risks"]


def test_generic_tool_reaches_shared_admission_without_legacy_create_proposal(tmp_path: Path, monkeypatch) -> None:
    module = request_module()
    orchestrator = make_orchestrator(tmp_path)
    admitted = []
    original = module.admit

    def observe(request, **kwargs):
        receipt = original(request, **kwargs)
        admitted.append((request, kwargs, receipt))
        return receipt

    monkeypatch.setattr(module, "admit", observe)
    assert not hasattr(orchestrator, "create_proposal")
    arguments = {key: value for key, value in proposal_kwargs().items() if key not in {"chain_id", "command_id"}}
    result = asyncio.run(orchestrator.tool_registry("chain-a").execute(
        {"tool_call_id": "typed-generic", "tool_id": "run_operation", "arguments": arguments},
        session_id="chain-session",
        metadata={"command_id": "cmd-typed", "allowed_operations": ["model.rerun"], "context_fingerprint": "ctx-1"},
    ))
    assert result.ok, result.error
    assert result.output["requires_confirmation"] is True
    assert len(admitted) == 1
    request, scope, receipt = admitted[0]
    assert isinstance(request, module.OperationRequest)
    assert isinstance(receipt, module.OperationReceipt)
    assert receipt.status == "pending"
    assert receipt.proposal.to_dict() == result.output["proposal"]
    assert scope["chain_id"] == "chain-a"
    assert scope["session_id"] == "chain-session"
    assert receipt.proposal.command_id == "cmd-typed"
    assert orchestrator.operation_store.list_records() == []


def test_fork_route_reaches_shared_admission_after_server_source_resolution(tmp_path: Path, monkeypatch) -> None:
    module = request_module()
    project = tmp_path / "project"
    project.mkdir()
    _write_inspectable_run(project)
    admitted = []
    original = module.admit

    def observe(request, **kwargs):
        receipt = original(request, **kwargs)
        admitted.append((request, kwargs, receipt))
        return receipt

    monkeypatch.setattr(module, "admit", observe)
    assert not hasattr(WorkbenchOrchestrator, "create_proposal")
    with TestClient(app) as client:
        response = client.post("/agent/fork-proposals", params={"project_root": str(project)}, json={
            "source_run_id": "run-a", "source_node_ref": "model:ols_1", "active_head_run_id": "run-a",
            "reason": "Typed fork admission.",
        })
    assert response.status_code == 200, response.text
    assert len(admitted) == 1
    request, scope, receipt = admitted[0]
    assert isinstance(request, module.OperationRequest)
    assert isinstance(receipt, module.OperationReceipt)
    body = response.json()
    assert request.operation_id == "graph.fork"
    assert request.target["source_session_entry_id"] == body["source_session_entry_id"]
    assert request.target["node_hash"] == body["proposal"]["target"]["node_hash"]
    assert request.preconditions["active_head_run_id"] == "run-a"
    assert scope["session_id"] == body["session_id"]
    assert receipt.proposal.proposal_id == body["proposal"]["proposal_id"]
    assert not (project / "workbench/operations").exists()
    assert sorted(p.name for p in (project / "runs").iterdir()) == ["run-a"]


def test_shared_admission_keeps_scope_and_unknown_operation_refusals_before_writes(tmp_path: Path) -> None:
    module = request_module()
    orchestrator = make_orchestrator(tmp_path)
    arguments = {key: value for key, value in proposal_kwargs().items() if key not in {"chain_id", "command_id"}}
    request = module.OperationRequest.from_arguments({**arguments, "operation_id": "arbitrary.file_write"})
    with pytest.raises(ValueError, match="proposal session must be a matching chain session"):
        orchestrator.admit_operation_request(request, chain_id="chain-a", session_id="main-session")
    with pytest.raises(UnknownOperationError):
        orchestrator.admit_operation_request(request, chain_id="chain-a")
    assert orchestrator.repository.get_branch("chain-session") == []
    assert orchestrator.operation_store.list_records() == []


def test_typed_admission_persists_the_original_proposal_shape(tmp_path: Path, monkeypatch) -> None:
    module = request_module()
    orchestrator = make_orchestrator(tmp_path)
    admitted = []
    original = module.admit

    def observe(request, **kwargs):
        receipt = original(request, **kwargs)
        admitted.append(receipt)
        return receipt

    monkeypatch.setattr(module, "admit", observe)
    proposal = admit_proposal(orchestrator, **proposal_kwargs(), proposal_id="proposal_typed")
    assert len(admitted) == 1
    assert admitted[0].proposal is proposal
    stored = orchestrator.proposal_store.latest_revision(proposal.proposal_id)
    assert stored.to_dict() == proposal.to_dict()
    assert set(stored.to_dict()) == {
        "record_type", "proposal_id", "operation_id", "operation_version", "revision", "session_id", "chain_id",
        "command_id", "target", "preconditions", "changes", "evidence_refs", "expected_effect", "risks", "created_at", "fingerprint", "status",
    }
