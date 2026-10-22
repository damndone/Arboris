"""A workflow runs on a dataset node, whichever node the Agent was looking at (free-route round, 2026-10-22).

leverage.goal (Ask, no thinking): six operation.multi_step proposals targeted
``model:ols_1``. Each was admitted, then its confirmation raised inside
workflow compilation -- HTTP 500, the record left pending, and the Agent told it
had run. The report it composed three times never existed.
"""
import asyncio
from dataclasses import replace

import pandas as pd
import pytest

from tests.operation_request_fixtures import admit_proposal
from tests.test_agent_workflow_integration import IdleAdapter
from tests.test_data_column_cast import _source_project
from workbench.agent import tools
from workbench.agent.chains import ChainStore
from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.operation_handlers.proposal_arguments import _canonicalize_workflow_arguments
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tools import ToolVisibleError
from workbench.graph_model import Edge, Node, NodeKind, Stage
from workbench.graph_store import GraphStore


def _project(tmp_path, *, extra_input=False):
    project, run_id, artifact_id = _source_project(tmp_path, pd.DataFrame({"y": [1.0, 2.0, 3.5], "x": [0.0, 1.0, 2.0]}))
    store = GraphStore(project / "runs")
    graph = store.read(run_id)
    nodes = dict(graph.nodes)
    edges = dict(graph.edges)
    nodes["model:ols_1"] = Node(id="model:ols_1", kind=NodeKind.MODEL, display_label="OLS", created_at="2026-10-22T00:00:00+00:00",
                                parent_stage_id=None, branch_id="main", stage=Stage.MODEL)
    nodes["report:html"] = Node(id="report:html", kind=NodeKind.REPORT, display_label="Report", created_at="2026-10-22T00:00:00+00:00",
                                parent_stage_id=None, branch_id="main")
    edges["e:source-model"] = Edge("e:source-model", "stage:source", "model:ols_1", "ols.fit")
    if extra_input:
        nodes["stage:other"] = replace(graph.nodes["stage:source"], id="stage:other")
        edges["e:other-model"] = Edge("e:other-model", "stage:other", "model:ols_1", "ols.fit")
    store.write(replace(graph, nodes=nodes, edges=edges))
    return project, run_id, artifact_id


def _canonical(project, run_id, node_ref):
    notes = []
    token = tools._TOOL_NOTES.set(notes)
    try:
        arguments = {"operation_id": "operation.multi_step", "target": {"run_id": run_id, "node_ref": node_ref}}
        return _canonicalize_workflow_arguments(arguments, project_root=project)["target"], notes
    finally:
        tools._TOOL_NOTES.reset(token)


def test_a_model_node_is_bound_to_the_dataset_it_was_fitted_on(tmp_path):
    project, run_id, artifact_id = _project(tmp_path)
    target, notes = _canonical(project, run_id, "model:ols_1")
    assert target == {"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id}
    assert notes and "stage:source" in notes[0] and "model:ols_1" in notes[0]
    unchanged, notes = _canonical(project, run_id, "stage:source")
    assert unchanged["node_ref"] == "stage:source" and not notes


@pytest.mark.parametrize("node_ref,extra", [("report:html", False), ("model:ols_1", True)])
def test_a_node_without_one_input_dataset_is_refused_naming_the_dataset_nodes(tmp_path, node_ref, extra):
    project, run_id, _ = _project(tmp_path, extra_input=extra)
    with pytest.raises(ToolVisibleError, match="WORKFLOW_SOURCE_NOT_DATASET") as raised:
        _canonical(project, run_id, node_ref)
    assert "stage:source" in str(raised.value)


def test_a_confirmed_workflow_whose_source_does_not_resolve_fails_instead_of_raising(tmp_path):
    async def scenario():
        project, run_id, artifact_id = _project(tmp_path)
        workbench_root = tmp_path / "workbench"
        repository = JsonlSessionRepository(workbench_root)
        repository.create_session("main-session", chain_id="project", role="main")
        repository.create_session("chain-session", chain_id="chain-a", role="chain")
        events = AgentEventStream(workbench_root)
        orchestrator = WorkbenchOrchestrator(repository, events, main_session_id="main-session",
                                             context_provider=NodeOperationContextProvider(project))
        orchestrator.register_chain("chain-a", "chain-session", AgentCore(repository, events, IdleAdapter(), session_id="chain-session"))
        ChainStore(workbench_root).create_root(chain_id="chain-a", run_family_id="family-source",
                                               active_head_run_id=run_id, agent_session_id="chain-session")
        fingerprint = "nocv1:source"
        # Admitted as recorded before this fix: the model node, with the dataset's artifact.
        proposal = admit_proposal(orchestrator, chain_id="chain-a", operation_id="operation.multi_step",
            target={"run_id": run_id, "node_ref": "model:ols_1", "artifact_id": artifact_id},
            preconditions={"context_version": "node-operation-context/v1", "context_fingerprint": fingerprint,
                           "active_head_run_id": run_id, "owner_resolution": "single_candidate"},
            changes={"steps": [{"step_id": "explore", "operation_id": "statistical.explore",
                                "spec": {"operation": "summarize", "selected_columns": ["y", "x"]}}]},
            evidence_refs=["fixture"], expected_effect=["summary"], risks=["none"])
        record = orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
            fingerprint=proposal.fingerprint, actor_type="user", current_context_fingerprint=fingerprint,
            current_active_head_run_id=run_id)
        terminal = await orchestrator.execute_confirmed_operation(record.record_id, project_root=project,
            current_context_fingerprint=fingerprint, current_active_head_run_id=run_id)
        assert terminal.status == "failed"
        assert terminal.error["code"] == "WORKFLOW_SOURCE_INVALID"
        told = [entry.payload for entry in repository.get_branch("chain-session")
                if entry.entry_type == "custom_message" and entry.payload.get("message_type") == "operation_result"]
        assert told and '"status": "failed"' in told[-1]["content"]
    asyncio.run(scenario())
