from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from workbench.agent.chains import RerunExecutionResult
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
