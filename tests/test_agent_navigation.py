from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from workbench.agent.chains import RerunExecutionResult
from workbench.agent.chains import ChainStore, ForkStore
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.navigation import AgentNavigationProjector
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository


@dataclass(frozen=True)
class NavigationFixture:
    project_root: Path
    repository: JsonlSessionRepository
    chain_session_id: str
    child_session_id: str
    source_run_id: str
    child_run_id: str
    source_node_ref: str
    source_node_hash: str
    source_forest_node_key: str
    child_node_ref: str
    record_id: str
    fork_id: str
    child_chain_id: str


class IdleAdapter:
    async def stream(self, request):
        if False:
            yield request


def _write_run(project_root: Path, run_id: str, node_ref: str, node_hash: str) -> None:
    run_root = project_root / "runs" / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "node_index.json").write_text(
        json.dumps({node_ref: {"node_hash": node_hash}}),
        encoding="utf-8",
    )
    (run_root / "run_manifest.json").write_text(
        json.dumps({"status": "completed"}),
        encoding="utf-8",
    )


def build_confirmed_rerun_fixture(project_root: Path) -> NavigationFixture:
    workbench_root = project_root / "workbench"
    repository = JsonlSessionRepository(workbench_root)
    repository.create_session("main-session", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    source_entry = repository.append(
        "chain-session",
        "message",
        {
            "role": "user",
            "content": "检查模型并准备一个可审计的重跑提议。",
            "command_id": "command-1",
        },
    )
    events = AgentEventStream(workbench_root)
    agent = AgentCore(
        repository,
        events,
        IdleAdapter(),
        session_id="chain-session",
    )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
    )
    orchestrator.register_chain("chain-a", "chain-session", agent)
    proposal = orchestrator.create_proposal(
        chain_id="chain-a",
        operation_id="model.rerun",
        target={
            "run_id": "run-source",
            "node_ref": "model:ols_1",
            "node_hash": "hash-source",
            "forest_node_key": "run-source::model:ols_1",
        },
        preconditions={
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "context-1",
            "active_head_run_id": "run-source",
            "owner_resolution": "active_head_contains_node",
        },
        changes={"covariance": {"old": "robust", "new": "unadjusted"}},
        evidence_refs=["diagnostic:heteroskedasticity"],
        expected_effect=["standard errors may change"],
        risks=["inference assumptions change"],
        command_id="command-1",
        proposal_id="proposal-navigation-1",
    )
    record = orchestrator.confirm_proposal(
        proposal.proposal_id,
        revision=proposal.revision,
        fingerprint=proposal.fingerprint,
        actor_type="user",
        current_context_fingerprint="context-1",
        current_active_head_run_id="run-source",
    )

    async def executor(_request):
        return RerunExecutionResult(
            target_run_id="run-child",
            outputs={"status": "completed"},
            diff_ref={"kind": "canonical", "changed": ["covariance"]},
            verification={"passed": True, "status": "completed"},
        )

    completed = asyncio.run(
        orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint="context-1",
            current_active_head_run_id="run-source",
            executor=executor,
        )
    )
    _write_run(project_root, "run-source", "model:ols_1", "hash-source")
    _write_run(project_root, "run-child", "model:ols_1", "hash-child")

    assert completed.status == "completed"
    return NavigationFixture(
        project_root=project_root,
        repository=repository,
        chain_session_id="chain-session",
        child_session_id=completed.execution["child_session_id"],
        source_run_id="run-source",
        child_run_id="run-child",
        source_node_ref="model:ols_1",
        source_node_hash="hash-source",
        source_forest_node_key="run-source::model:ols_1",
        child_node_ref="model:ols_1",
        record_id=record.record_id,
        fork_id=completed.execution["fork_id"],
        child_chain_id=completed.execution["child_chain_id"],
    )


def link_to(projection, *, kind: str, id: str):
    return next(link for link in projection.links if link.kind == kind and link.id == id)


def hierarchy_child(node, *, kind: str, id: str):
    return next(child for child in node.children if child.ref.kind == kind and child.ref.id == id)


def test_projection_links_chain_message_operation_child_run_and_fork(tmp_path: Path):
    fixture = build_confirmed_rerun_fixture(tmp_path)

    projection = AgentNavigationProjector(fixture.project_root).session(
        fixture.chain_session_id
    )

    assert projection.subject.kind == "agent_session"
    assert link_to(
        projection,
        kind="graph_node",
        id=fixture.source_forest_node_key,
    ).available
    assert link_to(projection, kind="operation", id=fixture.record_id).available
    assert link_to(projection, kind="run", id=fixture.child_run_id).available
    assert link_to(projection, kind="fork", id=fixture.fork_id).available
    assert link_to(
        projection,
        kind="agent_session",
        id=fixture.child_session_id,
    ).available


def test_session_projection_contains_backend_owned_main_chain_hierarchy(tmp_path: Path):
    fixture = build_confirmed_rerun_fixture(tmp_path)

    projection = AgentNavigationProjector(fixture.project_root).session(
        fixture.chain_session_id
    )

    assert projection.hierarchy is not None
    assert projection.hierarchy.ref.kind == "agent_session"
    assert projection.hierarchy.ref.id == "main-session"

    source_chain = hierarchy_child(
        projection.hierarchy,
        kind="chain",
        id="chain-a",
    )
    assert source_chain.status == "idle"
    hierarchy_child(source_chain, kind="agent_session", id=fixture.chain_session_id)

    operation = hierarchy_child(source_chain, kind="operation", id=fixture.record_id)
    assert operation.status == "completed"
    hierarchy_child(operation, kind="fork", id=fixture.fork_id)
    hierarchy_child(operation, kind="run", id=fixture.child_run_id)

    child_chain = hierarchy_child(source_chain, kind="chain", id=fixture.child_chain_id)
    assert child_chain.status == "active"
    hierarchy_child(child_chain, kind="agent_session", id=fixture.child_session_id)


def test_activity_projection_contains_main_chain_operation_diff_and_links(tmp_path: Path):
    fixture = build_confirmed_rerun_fixture(tmp_path)

    activities = AgentNavigationProjector(fixture.project_root).activity()

    assert len(activities) == 1
    activity = activities[0]
    assert activity.operation.id == fixture.record_id
    assert activity.operation.label == "model.rerun · completed"
    assert activity.main.id == "main-session"
    assert activity.chain.id == "chain-a"
    assert activity.diff_ref == {"kind": "canonical", "changed": ["covariance"]}
    assert activity.verification["passed"] is True
    assert activity.effect_status == "committed"
    assert activity.projection_status == "complete"
    assert {link.kind for link in activity.links} >= {
        "proposal",
        "graph_node",
        "run",
        "fork",
        "chain",
        "agent_session",
        "diff",
    }
    diff = next(link for link in activity.links if link.kind == "diff")
    assert diff.href["operation_record_id"] == fixture.record_id
    assert diff.href["diff"] == "1"


def test_activity_hierarchy_contains_operation_diff_and_child_links(tmp_path: Path):
    fixture = build_confirmed_rerun_fixture(tmp_path)

    hierarchy = AgentNavigationProjector(fixture.project_root).activity_hierarchy()

    assert hierarchy is not None
    operation = next(
        child for child in hierarchy.children[0].children
        if child.ref.kind == "operation"
    )
    diff = next(child for child in operation.children if child.ref.kind == "diff")
    assert diff.ref.href["operation_record_id"] == fixture.record_id
    assert diff.status == "available"


def test_activity_events_project_durable_lifecycle_and_typed_links(tmp_path: Path):
    fixture = build_confirmed_rerun_fixture(tmp_path)

    events = AgentNavigationProjector(fixture.project_root).activity_events()

    event_types = {event.event_type for event in events}
    assert {
        "proposal_ready",
        "needs_confirmation",
        "proposal_confirmed",
        "operation_submitted",
        "operation_completed",
    } <= event_types
    completed = next(event for event in events if event.event_type == "operation_completed")
    assert completed.session.id == fixture.chain_session_id
    assert completed.chain.id == "chain-a"
    assert completed.details["record_id"] == fixture.record_id
    assert {link.kind for link in completed.links} >= {
        "operation",
        "fork",
        "run",
        "chain",
        "agent_session",
    }


def test_projection_marks_missing_relationship_unavailable(tmp_path: Path):
    fixture = build_confirmed_rerun_fixture(tmp_path)
    (fixture.project_root / "runs" / fixture.child_run_id).rename(
        fixture.project_root / "runs" / "run-child-removed"
    )

    projection = AgentNavigationProjector(fixture.project_root).operation(
        fixture.record_id
    )

    assert projection.subject.available is True
    assert link_to(projection, kind="run", id=fixture.child_run_id).available is False
    assert link_to(projection, kind="fork", id=fixture.fork_id).available is True


@pytest.mark.parametrize("selector", ["run-source", "run-child"])
def test_graph_projection_requires_a_real_run(tmp_path: Path, selector: str):
    fixture = build_confirmed_rerun_fixture(tmp_path)

    projection = AgentNavigationProjector(fixture.project_root).graph(
        run_id=selector,
        node_ref=fixture.source_node_ref,
        forest_node_key=(
            fixture.source_forest_node_key
            if selector == fixture.source_run_id
            else "run-child::model:ols_1"
        ),
    )

    assert projection.subject.kind == "graph_node"
    assert projection.subject.available is True


def test_child_graph_projection_links_back_to_child_agent_and_operation(tmp_path: Path):
    fixture = build_confirmed_rerun_fixture(tmp_path)

    projection = AgentNavigationProjector(fixture.project_root).graph(
        run_id=fixture.child_run_id,
        node_ref=fixture.child_node_ref,
        forest_node_key=f"{fixture.child_run_id}::{fixture.child_node_ref}",
    )

    assert link_to(projection, kind="operation", id=fixture.record_id).available
    assert link_to(
        projection,
        kind="agent_session",
        id=fixture.child_session_id,
    ).available


def test_graph_projection_includes_source_fork_without_operation_record(tmp_path: Path):
    fixture = build_confirmed_rerun_fixture(tmp_path)
    repository = fixture.repository
    repository.create_session("agent-orphan-child", chain_id="chain-orphan", role="chain")
    ChainStore(fixture.project_root / "workbench").create_child(
        child_chain_id="chain-orphan",
        source_chain_id="chain-a",
        run_family_id="family-a",
        source_run_id=fixture.source_run_id,
        source_node_ref=fixture.source_node_ref,
        fork_id="fork-source-only",
        child_session_id="agent-orphan-child",
    )
    ForkStore(fixture.project_root / "workbench").create(
        fork_id="fork-source-only",
        source_chain_id="chain-a",
        source_node_ref=fixture.source_node_ref,
        source_session_id=fixture.chain_session_id,
        source_session_entry_id="entry-source-only",
        inherited_context_fingerprint="context-1",
        child_chain_id="chain-orphan",
        child_session_id="agent-orphan-child",
    )

    projection = AgentNavigationProjector(fixture.project_root).graph(
        run_id=fixture.source_run_id,
        node_ref=fixture.source_node_ref,
        forest_node_key=fixture.source_forest_node_key,
    )

    assert link_to(projection, kind="fork", id="fork-source-only").available
    assert link_to(projection, kind="chain", id="chain-orphan").available
    assert link_to(projection, kind="agent_session", id="agent-orphan-child").available


def test_graph_projection_rejects_inconsistent_forest_key_without_links(tmp_path: Path):
    fixture = build_confirmed_rerun_fixture(tmp_path)

    projection = AgentNavigationProjector(fixture.project_root).graph(
        run_id=fixture.source_run_id,
        node_ref=fixture.source_node_ref,
        forest_node_key="run-child::model:ols_1",
    )

    assert projection.subject.available is False
    assert projection.links == ()


def test_read_only_graph_projection_does_not_create_agent_storage(tmp_path: Path):
    project_root = tmp_path / "empty-project"
    project_root.mkdir()

    projection = AgentNavigationProjector(project_root).graph(
        run_id="unknown-run",
        node_ref="model:ols_1",
        forest_node_key=None,
    )

    assert projection.subject.available is False
    assert not (project_root / "workbench").exists()
