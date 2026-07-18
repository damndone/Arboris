from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd
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


def test_analysis_loop_proposal_route_resolves_persisted_source_without_execution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from test_agent_analysis_loop_resolver import _write_source
    from workbench.http import agent_routes

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_source(project_root)
    result = json.loads(
        (project_root / "runs" / "run-source" / "model_results" / "ols_1.json").read_text()
    )

    class FakeProvider:
        def __init__(self, root: Path) -> None:
            self.project_root = root

        def inspect_node_context(self, request) -> dict[str, object]:
            return {
                "node_hash": "node-hash-source",
                "forest_node_key": "forest:source",
                "context_version": "node-operation-context/v1",
                "context_fingerprint": "ctx:source",
                "active_head_run_id": request.active_head_run_id,
                "owner_resolution": "active_head_contains_node",
            }

        def tool_definitions(self, **_kwargs):
            return []

    monkeypatch.setattr(agent_routes, "NodeOperationContextProvider", FakeProvider)
    with TestClient(app) as client:
        session_id = _create_session(client, project_root)
        response = client.post(
            f"/agent/sessions/{session_id}/analysis-loop/proposals",
            params={"project_root": str(project_root)},
            json={
                "source_run_id": "run-source",
                "source_node_ref": "model:ols_1",
                "active_head_run_id": "run-source",
                "cluster_variable": "company_id",
                "result_id": result["stable_result_ids"][0],
            },
        )

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "pending"
        assert body["proposal"]["status"] == "pending"
        assert body["proposal"]["changes"] == {
            "covariance": "clustered",
            "entity_col": "company_id",
        }
        assert body["plan_diff"]["wire_patch"] == {
            "covariance": "clustered",
            "entity_col": "company_id",
        }
        assert body["proposal"]["preconditions"]["confirmed_payload_hash"]
        assert body["timings_ms"]["node_operation_context_ms"] >= 0
        assert body["timings_ms"]["plan_diff_ms"] >= 0

        proposals = client.get(
            f"/agent/sessions/{session_id}/proposals",
            params={"project_root": str(project_root)},
        )
        assert proposals.status_code == 200
        assert len(proposals.json()["proposals"]) == 1
        assert not (project_root / "workbench" / "operations").exists()


def test_analysis_loop_confirmation_rejects_tampered_canonical_payload(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from test_agent_analysis_loop_resolver import _write_source
    from workbench.http import agent_routes

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_source(project_root)
    result = json.loads(
        (project_root / "runs" / "run-source" / "model_results" / "ols_1.json").read_text()
    )

    class FakeProvider:
        def __init__(self, root: Path) -> None:
            self.project_root = root

        def inspect_node_context(self, request) -> dict[str, object]:
            return {
                "node_hash": "node-hash-source",
                "forest_node_key": "forest:source",
                "context_version": "node-operation-context/v1",
                "context_fingerprint": "ctx:source",
                "active_head_run_id": request.active_head_run_id,
                "owner_resolution": "active_head_contains_node",
            }

        def tool_definitions(self, **_kwargs):
            return []

    monkeypatch.setattr(agent_routes, "NodeOperationContextProvider", FakeProvider)
    with TestClient(app) as client:
        session_id = _create_session(client, project_root)
        created = client.post(
            f"/agent/sessions/{session_id}/analysis-loop/proposals",
            params={"project_root": str(project_root)},
            json={
                "source_run_id": "run-source",
                "source_node_ref": "model:ols_1",
                "active_head_run_id": "run-source",
                "cluster_variable": "company_id",
                "result_id": result["stable_result_ids"][0],
            },
        )
        assert created.status_code == 200
        proposal = created.json()["proposal"]
        confirmed = client.post(
            f"/agent/sessions/{session_id}/proposals/{proposal['proposal_id']}/confirm",
            params={"project_root": str(project_root)},
            json={
                "revision": proposal["revision"],
                "fingerprint": proposal["fingerprint"],
                "active_head_run_id": "run-source",
                "confirmed_payload_hash": "tampered",
            },
        )

    assert confirmed.status_code == 409
    assert confirmed.json()["error"]["code"] == "CONFIRMED_PAYLOAD_MISMATCH"


def test_analysis_loop_packet_route_returns_bounded_source_facts_without_building_packets(
    tmp_path: Path,
) -> None:
    from test_agent_analysis_loop_resolver import _write_source

    project_root = tmp_path / "project"
    project_root.mkdir()
    _write_source(project_root)

    with TestClient(app) as client:
        response = client.get(
            "/analysis-loop/packets/run-source",
            params={"project_root": str(project_root)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "absent"
    assert body["run"]["run_id"] == "run-source"
    assert body["run"]["model"] == "ols"
    assert body["run"]["contract_version"] == "ols_result_contract_v1"
    assert body["run"]["covariance"] == "unadjusted"
    assert body["packet"] is None
    assert body["children"] == []
    assert not (project_root / "workbench" / "analysis-packets").exists()


def test_analysis_loop_packet_route_fails_closed_for_missing_run(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    with TestClient(app) as client:
        response = client.get(
            "/analysis-loop/packets/missing-run",
            params={"project_root": str(project_root)},
        )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_LOOP_RUN_NOT_FOUND"


def test_analysis_loop_packet_route_reads_immutable_child_packets_and_source_facts(
    tmp_path: Path,
) -> None:
    from test_agent_analysis_loop_observation import _write_run
    from workbench.analysis_loop.observation import build_and_store_analysis_loop_packets
    from workbench.analysis_loop.plan import build_plan_diff
    from workbench.analysis_loop.resolver import (
        resolve_analysis_loop_inputs,
        resolve_analysis_loop_run,
    )
    from workbench.analysis_loop.storage import (
        ComparePacketStore,
        PlanDiffStore,
        ValidationPacketStore,
    )

    project_root = tmp_path / "project"
    project_root.mkdir()
    frame = pd.DataFrame(
        {
            "y": [1.0, 2.0, 1.5, 3.0, 2.5, 4.0],
            "x": [0.0, 1.0, 0.5, 2.0, 1.5, 3.0],
            "company_id": ["a", "a", "b", "b", "c", "c"],
        }
    )
    source_result = _write_run(project_root, "run-source", frame, covariance="unadjusted")
    _write_run(
        project_root,
        "run-child",
        frame,
        covariance="clustered",
        rerun_of="run-source",
        workbench_context={
            "confirmed_payload_hash": "payload-hash-1",
        },
    )
    resolved = resolve_analysis_loop_inputs(
        project_root,
        run_id="run-source",
        cluster_variable="company_id",
    )
    plan = build_plan_diff(
        source=resolved.source,
        intent={
            "action_id": "ols.use_clustered_covariance_v1",
            "patch": {"covariance": "clustered", "cluster_variable": "company_id"},
        },
        requested_result_id=source_result["stable_result_ids"][0],
        cluster_values=resolved.cluster_values,
        model_row_ids=resolved.model_row_ids,
        source_context_fingerprint="ctx:source-v1",
        source_identity={"run_id": "run-source"},
    )
    PlanDiffStore(project_root / "workbench").persist_terminal_plan(plan)
    build_and_store_analysis_loop_packets(
        source=resolved.source,
        source_run=resolve_analysis_loop_run(project_root, run_id="run-source", require_result=True),
        child_run=resolve_analysis_loop_run(project_root, run_id="run-child"),
        plan=plan,
        execution_evidence={
            "confirmed_payload_hash": "payload-hash-1",
            "executed_payload_hash": "payload-hash-1",
            "executed_plan_hash": plan.plan_hash,
            "executed_canonical_patch_hash": plan.canonical_patch_hash,
            "effect_status": "committed",
            "projection_status": "complete",
            "child_terminal": True,
        },
        validation_store=ValidationPacketStore(project_root / "workbench"),
        compare_store=ComparePacketStore(project_root / "workbench"),
    )

    with TestClient(app) as client:
        response = client.get(
            "/analysis-loop/packets/run-child",
            params={"project_root": str(project_root)},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "complete"
    assert body["run"]["run_id"] == "run-child"
    assert body["source_run"]["run_id"] == "run-source"
    assert body["packet"]["validation_packet"]["status"] == "complete"
    assert body["packet"]["compare_packet"]["source_run_id"] == "run-source"
    assert body["packet"]["plan_diff"]["plan_hash"] == plan.plan_hash
