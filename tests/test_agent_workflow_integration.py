from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pandas as pd

from workbench.agent.chains import RerunExecutionResult
from workbench.agent.chains import ChainStore
from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository
from workbench.graph_model import Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore
from workbench.lineage.run_inputs import write_run_inputs
from workbench.lineage.upload_store import store_upload_bytes
from tests.test_data_column_cast import _source_project


class IdleAdapter:
    async def stream(self, request):
        if False:
            yield request


class MultiToolWorkflowAdapter:
    """Drive the first workflow through normalized tool calls deterministically."""

    _inspection_tools = (
        "inspect_node_context",
        "inspect_operation_contract",
        "inspect_diagnostics",
        "inspect_result_summary",
        "inspect_artifact_preview",
    )

    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []
        self.context_fingerprint: str | None = None

    async def stream(self, request: ModelRequest):
        self.requests.append(request)
        request_number = len(self.requests)
        if request_number <= len(self._inspection_tools):
            tool_id = self._inspection_tools[request_number - 1]
            arguments = {
                "request_id": f"inspect-{request_number}",
                "owner_run_id": "run-a",
                "op_node_id": "model:ols_1",
                "active_head_run_id": "run-a",
            }
            if tool_id == "inspect_operation_contract":
                arguments.update({"operation_id": "model.rerun", "operation_version": "v1"})
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": f"call-{request_number}",
                    "tool_id": tool_id,
                    "arguments": arguments,
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return

        if request_number == len(self._inspection_tools) + 1:
            tool_messages = [
                message for message in request.messages if message.get("role") == "tool"
            ]
            assert [message.get("name") for message in tool_messages] == list(
                self._inspection_tools
            )
            node_context_payload = json.loads(tool_messages[0]["content"])
            self.context_fingerprint = node_context_payload["output"]["context_fingerprint"]
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-proposal",
                    "tool_id": "propose_operation",
                    "arguments": {
                        "operation_id": "model.rerun",
                        "operation_version": "v1",
                        "target": {
                            "run_id": "run-a",
                            "node_ref": "model:ols_1",
                            "node_hash": "hash-a",
                            "forest_node_key": "hash-a",
                        },
                        "preconditions": {
                            "context_version": "node-operation-context/v1",
                            "context_fingerprint": self.context_fingerprint,
                            "active_head_run_id": "run-a",
                            "owner_resolution": "active_head_contains_node",
                        },
                        "changes": {
                            "covariance": {"old": "nonrobust", "new": "HC1"}
                        },
                        "evidence_refs": ["diagnostic:MODEL_DIAGNOSTIC_WARNING"],
                        "expected_effect": ["standard errors may change"],
                        "risks": ["small samples may overinflate standard errors"],
                    },
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return

        yield ModelStreamEvent.text_delta(request.request_id, "proposal prepared")
        yield ModelStreamEvent.done(request.request_id)


def _write_project_run(project_root: Path) -> None:
    runs_root = project_root / "runs"
    run_root = runs_root / "run-a"
    run_root.mkdir(parents=True)
    GraphStore(runs_root).write(
        Graph(
            schema_version=3,
            run_id="run-a",
            nodes={
                "model:ols_1": Node(
                    id="model:ols_1",
                    kind=NodeKind.MODEL,
                    display_label="OLS",
                    created_at="2026-07-14T00:00:00+00:00",
                    parent_stage_id=None,
                    branch_id="main",
                    stage=Stage.MODEL,
                )
            },
            edges={},
            branches={},
        )
    )
    (run_root / "node_index.json").write_text(
        json.dumps({"model:ols_1": {"node_hash": "hash-a"}}), encoding="utf-8"
    )
    (run_root / "run_inputs.json").write_text(
        json.dumps({"rerun_of": None, "form": {"model_type": "ols"}}), encoding="utf-8"
    )
    (run_root / "run_manifest.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "started_at": "2026-07-14T00:00:00+00:00",
                "model_routing": {
                    "requested_model_type": "ols",
                    "effective_model_type": "ols",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_root / "model_results").mkdir()
    (run_root / "model_results" / "ols_1.json").write_text(
        json.dumps(
            {
                "model_id": "ols_1",
                "model_type": "ols",
                "nobs": 100,
                "coefficients": {"x1": {"estimate": 1.2}},
            }
        ),
        encoding="utf-8",
    )
    (run_root / "diagnostic_summary.json").write_text(
        json.dumps(
            {
                "model_identity": {
                    "model_label": "OLS regression",
                    "model_family": "ols",
                    "y_variable": "y",
                    "x_variables": ["x1"],
                    "n_observations": 100,
                },
                "diagnostics": {
                    "blockers": [],
                    "warnings": [
                        {
                            "issue_id": "issue-1",
                            "severity": "WARNING",
                            "code": "MODEL_DIAGNOSTIC_WARNING",
                            "message": "Review residual variance before interpretation.",
                            "variables": ["x1"],
                            "is_user_action_required": True,
                        }
                    ],
                    "cautions": [],
                    "info": [],
                },
                "narrative_contract": {"constraints": {"causal_language_allowed": False}},
                "coefficients_summary": {"rows": []},
                "model_quality": {
                    "metrics": {"r_squared": 0.72, "aic": 120.5, "bic": 125.1},
                    "primary_metric_keys": ["r_squared", "aic"],
                },
            }
        ),
        encoding="utf-8",
    )


def _project_files(project_root: Path) -> dict[Path, bytes]:
    return {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }


def test_main_to_chain_multi_tool_workflow_stops_at_confirmation_then_completes(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        project_root = tmp_path / "project"
        _write_project_run(project_root)
        before_confirmation = _project_files(project_root)

        workbench_root = tmp_path / "workbench"
        repository = JsonlSessionRepository(workbench_root)
        repository.create_session("main-session", chain_id="project", role="main")
        repository.create_session("chain-session", chain_id="chain-a", role="chain")
        events = AgentEventStream(workbench_root)
        adapter = MultiToolWorkflowAdapter()
        chain_agent = AgentCore(
            repository,
            events,
            adapter,
            session_id="chain-session",
        )
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id="main-session",
            context_provider=NodeOperationContextProvider(project_root),
        )
        orchestrator.register_chain("chain-a", "chain-session", chain_agent)

        command = orchestrator.dispatch_to_chain(
            "chain-a",
            objective="检查当前模型，如果有问题提出修改",
            allowed_operations=["inspect", "propose", "model.rerun"],
            budget={"max_steps": 8, "timeout_s": 30},
            command_id="command-workflow-1",
        )
        assert await orchestrator.execute(command.command_id) == "proposal prepared"
        assert len(adapter.requests) == 7
        assert adapter.context_fingerprint is not None
        assert _project_files(project_root) == before_confirmation

        ready_events = [
            event for event in events.replay("chain-session") if event.event_type == "proposal_ready"
        ]
        assert len(ready_events) == 1
        proposal = orchestrator.proposal_store.latest_revision(
            ready_events[0].payload["proposal_id"]
        )
        assert proposal.operation_id == "model.rerun"
        assert orchestrator.proposal_store.latest_status(proposal.proposal_id) == "pending"

        record = orchestrator.confirm_proposal(
            proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="user",
            current_context_fingerprint=adapter.context_fingerprint,
            current_active_head_run_id="run-a",
        )

        executed_requests = []

        async def executor(request):
            executed_requests.append(request)
            return RerunExecutionResult(
                target_run_id="run-b",
                outputs={"status": "completed"},
                diff_ref={"kind": "canonical", "changed": ["covariance"]},
                verification={"passed": True, "status": "completed"},
            )

        completed = await orchestrator.execute_confirmed_proposal(
            record.record_id,
            current_context_fingerprint=adapter.context_fingerprint,
            current_active_head_run_id="run-a",
            executor=executor,
        )

        assert completed.status == "completed"
        assert len(executed_requests) == 1
        assert executed_requests[0].source_node_ref == "model:ols_1"
        assert executed_requests[0].changes["covariance"]["new"] == "HC1"
        assert completed.diff_ref == {"kind": "canonical", "changed": ["covariance"]}
        assert completed.verification["passed"] is True
        child_chain = orchestrator.chain_store.get(completed.execution["child_chain_id"])
        assert child_chain["status"] == "active"
        assert child_chain["active_head_run_id"] == "run-b"
        fork = orchestrator.fork_store.get(completed.execution["fork_id"])
        assert fork["status"] == "active"
        assert fork["graph_fork_node_id"] == f"fork:{completed.execution['fork_id']}"
        assert any(
            entry.payload.get("message_type") == "operation_result"
            for entry in repository.get_branch(completed.execution["child_session_id"])
        )
        event_types = [event.event_type for event in events.replay("chain-session")]
        assert event_types.index("proposal_ready") < event_types.index("proposal_confirmed")
        assert "operation_completed" in event_types

    asyncio.run(scenario())


def test_confirmed_workflow_runs_declared_model_terms_and_post_estimation(
    tmp_path: Path,
) -> None:
    """The normal Agent confirmation path, not a test-only executor, owns the run."""

    async def scenario() -> None:
        rows = 44
        exposure = [float(index - 22) for index in range(rows)]
        frame = pd.DataFrame(
            {
                "response": [
                    15.0
                    + 1.4 * value
                    - 0.1 * value**2
                    + (1.0 if index % 2 else -1.0)
                    for index, value in enumerate(exposure)
                ],
                "exposure": exposure,
                "segment": ["lower" if index % 2 else "upper" for index in range(rows)],
            }
        )
        project_root, run_id, artifact_id = _source_project(tmp_path, frame)
        upload_sha = store_upload_bytes(
            project_root,
            frame.to_csv(index=False).encode("utf-8"),
            filename="fixture.csv",
        )
        write_run_inputs(
            project_root / "runs" / run_id,
            form={"model_type": "auto", "y": "", "x": ""},
            upload={"sha256": upload_sha, "filename": "fixture.csv"},
            rerun_of=None,
            from_node=None,
            rerun_reason="initial",
            override_hash=None,
            dag_hash="fixture-dag",
        )
        workbench_root = tmp_path / "workbench"
        repository = JsonlSessionRepository(workbench_root)
        repository.create_session("main-session", chain_id="project", role="main")
        repository.create_session("chain-session", chain_id="chain-a", role="chain")
        events = AgentEventStream(workbench_root)
        agent = AgentCore(repository, events, IdleAdapter(), session_id="chain-session")
        orchestrator = WorkbenchOrchestrator(
            repository,
            events,
            main_session_id="main-session",
            context_provider=NodeOperationContextProvider(project_root),
        )
        orchestrator.register_chain("chain-a", "chain-session", agent)
        ChainStore(workbench_root).create_root(
            chain_id="chain-a",
            run_family_id="family-source",
            active_head_run_id=run_id,
            agent_session_id="chain-session",
        )
        context_fingerprint = "nocv1:declared-model-terms"
        proposal = orchestrator.create_proposal(
            chain_id="chain-a",
            operation_id="operation.multi_step",
            target={
                "run_id": run_id,
                "node_ref": "stage:source",
                "artifact_id": artifact_id,
            },
            preconditions={
                "context_version": "node-operation-context/v1",
                "context_fingerprint": context_fingerprint,
                "active_head_run_id": run_id,
                "owner_resolution": "single_candidate",
            },
            changes={
                "steps": [
                    {
                        "step_id": "estimate",
                        "operation_id": "model.genesis",
                        "spec": {
                            "model_family": "ols",
                            "covariance": "unadjusted",
                            "branches": [
                                {
                                    "branch_id": "curved",
                                    "outcome": "response",
                                    "predictors": ["exposure"],
                                    "categorical": ["segment"],
                                    "polynomials": [
                                        {"column": "exposure", "degree": 2}
                                    ],
                                }
                            ],
                        },
                    },
                    {
                        "step_id": "test_terms",
                        "operation_id": "model.joint_f_test",
                        "depends_on": ["estimate"],
                        "spec": {
                            "branch_id": "curved",
                            "term_selectors": [
                                {"kind": "polynomial", "column": "exposure"},
                                {"kind": "categorical", "column": "segment"},
                            ],
                        },
                    },
                    {
                        "step_id": "stationary_point",
                        "operation_id": "model.quadratic_stationary_point",
                        "depends_on": ["estimate"],
                        "spec": {"branch_id": "curved", "column": "exposure"},
                    },
                ]
            },
            evidence_refs=["profile:fixture"],
            expected_effect=["estimate declared OLS branch and post-estimation evidence"],
            risks=["model semantics require user confirmation"],
        )
        before_confirmation = list(orchestrator.operation_store.list_records())
        assert before_confirmation == []

        record = orchestrator.confirm_proposal(
            proposal.proposal_id,
            revision=proposal.revision,
            fingerprint=proposal.fingerprint,
            actor_type="user",
            current_context_fingerprint=context_fingerprint,
            current_active_head_run_id=run_id,
        )
        completed = await orchestrator.execute_confirmed_operation(
            record.record_id,
            project_root=project_root,
            current_context_fingerprint=context_fingerprint,
            current_active_head_run_id=run_id,
            allow_recovery=True,
        )

        assert completed.status == "completed"
        state = completed.outputs["workflow_state"]
        assert state["status"] == "completed"
        assert state["steps"]["test_terms"]["artifact_ids"]
        assert state["steps"]["stationary_point"]["artifact_ids"]
        child_operations = [
            item
            for item in orchestrator.operation_store.list_records()
            if item.record_id != record.record_id
        ]
        assert {item.operation_id for item in child_operations} == {
            "model.genesis",
            "model.joint_f_test",
            "model.quadratic_stationary_point",
        }
        assert {item.status for item in child_operations} == {"completed"}

    asyncio.run(scenario())
