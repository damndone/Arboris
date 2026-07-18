from __future__ import annotations

from pathlib import Path
import asyncio

from fastapi.testclient import TestClient

from workbench.analysis_loop.validation import ValidationCheck, ValidationPacket
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.agent.session import JsonlSessionRepository
from workbench.app import app


def _create_session(client: TestClient, project_root: Path) -> str:
    response = client.post(
        "/agent/sessions",
        params={"project_root": str(project_root)},
        json={
            "role": "chain",
            "chain_id": "analysis-loop-chain",
            "run_id": "run-source",
            "context_packet": {
                "packet_version": "analysis-loop-context/v1",
                "context_fingerprint": "ctx-source",
            },
        },
    )
    assert response.status_code == 200
    return response.json()["session_id"]


def _source_context() -> dict[str, object]:
    return {
        "run_id": "run-source",
        "status": "completed",
        "model": "ols",
        "covariance": "conventional",
        "primary_target": "coef:treatment",
        "diagnostics": {"recommended_action": "ols.use_clustered_covariance_v1"},
    }


def _validation_packet() -> dict[str, object]:
    check = ValidationCheck(
        check_id="execution_integrity",
        status="pass",
        severity="info",
        expected=True,
        observed=True,
    )
    packet = ValidationPacket(
        status="complete",
        overall_status="passed",
        terminal=True,
        checks=(check,),
        logical_key="validation:test",
        child_run_id="run-child",
        source_run_id="run-source",
        plan_hash="plan:test",
        executed_payload_hash="payload:test",
        artifact_manifest_hash="artifact:test",
        validation_policy_version="validation_policy_v1",
        schema_version="validation_packet_v1",
    )
    return packet.to_dict()


def test_analysis_loop_context_route_is_scoped_and_packet_typed(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        session_id = _create_session(client, project_root)
        response = client.post(
            f"/agent/sessions/{session_id}/analysis-loop/context",
            params={"project_root": str(project_root)},
            json={
                "scope": "validation",
                "source_context": _source_context(),
                "validation_packet": _validation_packet(),
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["context"]["scope"] == "validation"
    assert body["context"]["status"] == "complete"
    assert body["context"]["packet"]["logical_key"] == "validation:test"
    assert body["registered_actions"][0]["action_id"] == "ols.use_clustered_covariance_v1"


def test_analysis_loop_intent_route_forwards_exact_intent_without_proposal_or_execution(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        session_id = _create_session(client, project_root)
        response = client.post(
            f"/agent/sessions/{session_id}/analysis-loop/intents",
            params={"project_root": str(project_root)},
            json={
                "intent": {
                    "intent": "rerun",
                    "action_id": "ols.use_clustered_covariance_v1",
                    "cluster_variable": "company_id",
                    "result_id": "coef:treatment",
                },
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "accepted"
        assert body["decision"]["intent"] == {
            "kind": "rerun",
            "action_id": "ols.use_clustered_covariance_v1",
            "cluster_variable": "company_id",
            "result_id": "coef:treatment",
        }
        assert "proposal" not in body
        assert "operation" not in body

        proposals = client.get(
            f"/agent/sessions/{session_id}/proposals",
            params={"project_root": str(project_root)},
        )
        assert proposals.status_code == 200
        assert proposals.json()["proposals"] == []


def test_analysis_loop_routes_fail_closed_with_stable_codes(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        session_id = _create_session(client, project_root)
        unsupported_intent = client.post(
            f"/agent/sessions/{session_id}/analysis-loop/intents",
            params={"project_root": str(project_root)},
            json={
                "intent": {
                    "intent": "rerun",
                    "action_id": "invented.action",
                    "cluster_variable": "company_id",
                },
            },
        )
        assert unsupported_intent.status_code == 200
        assert unsupported_intent.json()["status"] == "rejected"
        assert unsupported_intent.json()["decision"]["rejection"]["code"] == (
            "UNSUPPORTED_ACTION"
        )

        scope_violation = client.post(
            f"/agent/sessions/{session_id}/analysis-loop/context",
            params={"project_root": str(project_root)},
            json={
                "scope": "inspect",
                "source_context": {**_source_context(), "api_key": "secret"},
            },
        )
        assert scope_violation.status_code == 422
        assert scope_violation.json()["error"]["code"] == (
            "SOURCE_CONTEXT_SCOPE_VIOLATION"
        )

        unsupported_scope = client.post(
            f"/agent/sessions/{session_id}/analysis-loop/context",
            params={"project_root": str(project_root)},
            json={"scope": "execute", "source_context": _source_context()},
        )
        assert unsupported_scope.status_code == 422
        assert unsupported_scope.json()["error"]["code"] == "CONTEXT_SCOPE_UNSUPPORTED"


def test_chain_tool_registry_exposes_typed_analysis_loop_tools_without_mutation(
    tmp_path: Path,
) -> None:
    repository = JsonlSessionRepository(tmp_path)
    events = AgentEventStream(tmp_path)
    repository.create_session("main", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    agent = AgentCore(repository, events, object(), session_id="chain-session")
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main",
        context_provider=NodeOperationContextProvider(tmp_path),
    )
    orchestrator.register_chain("chain-a", "chain-session", agent)
    registry = orchestrator.tool_registry("chain-a")
    descriptors = {item["tool_id"]: item for item in registry.descriptors()}

    assert descriptors["inspect_analysis_loop_context"]["side_effect"] == "none"
    assert descriptors["submit_analysis_loop_intent"]["side_effect"] == "none"

    result = asyncio.run(
        registry.execute(
            {
                "tool_id": "submit_analysis_loop_intent",
                "tool_call_id": "call-1",
                "arguments": {
                    "intent": {
                        "intent": "rerun",
                        "action_id": "ols.use_clustered_covariance_v1",
                        "cluster_variable": "company_id",
                    }
                },
            },
            session_id="chain-session",
        )
    )
    assert result.ok is True
    assert result.output["status"] == "accepted"
    assert not (tmp_path / "workbench" / "analysis-packets").exists()
