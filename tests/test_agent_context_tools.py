from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path

import pytest

from workbench.agent.core import AgentCore
from workbench.agent.chains import ChainStore
from workbench.agent.events import AgentEventStream
from workbench.agent.model import ModelStreamEvent
from workbench.agent.operations import OperationRecordStore
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.proposals import ProposalConfirmation
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.tools import ToolRegistry, ToolVisibleError
from workbench.graph_model import Graph, Node, NodeKind, Stage
from workbench.graph_store import GraphStore


class IdleAdapter:
    async def stream(self, request):
        if False:
            yield request


class CompletedResultAnswerAdapter:
    """Make the Agent consume its own completed-operation evidence before answering."""

    def __init__(self) -> None:
        self.requests = []

    async def stream(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-discover-completed",
                    "tool_id": "inspect_completed_operations",
                    "arguments": {
                        "owner_run_id": "run-a",
                        "op_node_id": "model:ols_1",
                        "active_head_run_id": "run-a",
                    },
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return
        if len(self.requests) == 2:
            tool_message = next(
                message
                for message in request.messages
                if message.get("role") == "tool"
                and message.get("name") == "inspect_completed_operations"
            )
            discovered = json.loads(tool_message["content"])["output"]["completed_operations"][0]
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "call-read-completed-artifact",
                    "tool_id": "inspect_operation_artifact",
                    "arguments": {
                        "owner_run_id": "run-a",
                        "op_node_id": "model:ols_1",
                        "active_head_run_id": "run-a",
                        "operation_record_id": discovered["operation_record_id"],
                        "artifact_id": discovered["artifact_ids"][0],
                    },
                },
            )
            yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")
            return
        tool_message = next(
            message
            for message in request.messages
            if message.get("role") == "tool"
            and message.get("name") == "inspect_operation_artifact"
        )
        evidence = json.loads(tool_message["content"])["output"]["artifact_evidence"]
        mean = evidence["result"]["variables"]["outcome"]["mean"]
        artifact_id = evidence["evidence_ref"]["artifact_id"]
        yield ModelStreamEvent.text_delta(
            request.request_id,
            f"The completed summary reports an outcome mean of {mean} (artifact: {artifact_id}).",
        )
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
        json.dumps({"model:ols_1": {"node_hash": "hash-a"}}),
        encoding="utf-8",
    )
    (run_root / "run_inputs.json").write_text(
        json.dumps({"rerun_of": None, "form": {"model_type": "ols"}}),
        encoding="utf-8",
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
                "run_status": {
                    "report_render_status": "complete",
                    "report_available": True,
                },
                "narrative_contract": {
                    "constraints": {"causal_language_allowed": False}
                },
                "coefficients_summary": {"rows": []},
                "model_quality": {
                    "metrics": {"r_squared": 0.72, "aic": 120.5, "bic": 125.1},
                    "primary_metric_keys": ["r_squared", "aic"],
                },
            }
        ),
        encoding="utf-8",
    )


def _make_orchestrator(
    tmp_path: Path,
    *,
    context_provider=None,
    adapter=None,
) -> WorkbenchOrchestrator:
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("main-session", chain_id="project", role="main")
    repository.create_session("chain-session", chain_id="chain-a", role="chain")
    events = AgentEventStream(tmp_path / "workbench")
    agent = AgentCore(
        repository,
        events,
        adapter or IdleAdapter(),
        session_id="chain-session",
    )
    orchestrator = WorkbenchOrchestrator(
        repository,
        events,
        main_session_id="main-session",
        context_provider=context_provider,
    )
    orchestrator.register_chain("chain-a", "chain-session", agent)
    return orchestrator


def _write_completed_workflow_result(
    project_root: Path,
    *,
    proposal_id: str = "proposal-workflow-result",
    session_id: str = "chain-session",
    chain_id: str = "chain-a",
    artifact_id: str = "statistical_exploration_summary",
    artifact_type: str = "statistical_exploration",
    artifact_payload: dict | None = None,
) -> tuple[str, str]:
    """Persist one completed workflow record with a public result artifact."""

    run_root = project_root / "runs" / "run-a"
    artifact_path = run_root / "artifacts" / artifact_type / f"{artifact_id}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(
            artifact_payload
            or {
                "schema_version": "statistical-exploration.v1",
                "source_artifact_id": "cleaned_dataset",
                "source_sha256": "source-sha",
                "spec": {
                    "operation": "summarize",
                    "selected_columns": ["outcome"],
                    "filters": [],
                },
                "result": {
                    "schema_version": "statistical-exploration.v1",
                    "operation": "summarize",
                    "source_row_count": 4,
                    "filtered_row_count": 4,
                    "missing_policy": "variablewise",
                    "variables": {
                        "outcome": {
                            "obs": 4,
                            "mean": 2.5,
                            "std_dev": 1.29,
                            "min": 1.0,
                            "max": 4.0,
                            "raw_rows": [{"outcome": 1.0}],
                        }
                    },
                },
            }
        ),
        encoding="utf-8",
    )
    (run_root / "artifacts_index.json").write_text(
        json.dumps(
            {
                "artifacts": [
                    {
                        "artifact_id": artifact_id,
                        "artifact_type": artifact_type,
                        "path": str(artifact_path.relative_to(run_root)),
                        "sha256": "artifact-sha",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    confirmation = ProposalConfirmation(
        proposal_id=proposal_id,
        operation_id="operation.multi_step",
        operation_version="v1",
        revision=1,
        fingerprint="sha256:proposal-workflow-result",
        session_id=session_id,
        chain_id=chain_id,
        command_id="command-workflow-result",
        target={"run_id": "run-a", "node_ref": "model:ols_1"},
        preconditions={"active_head_run_id": "run-a"},
        actor_type="user",
        confirmed_at="2026-07-28T00:00:00+00:00",
        status="confirmed",
        changes={"steps": []},
    )
    store = OperationRecordStore(project_root / "workbench")
    pending = store.create_pending(confirmation)
    completed = store.append_status(
        pending.record_id,
        "completed",
        outputs={
            "workflow_state": {
                "workflow_id": "workflow-result",
                "status": "completed",
                "steps": {
                    "summary": {
                        "status": "completed",
                        "artifact_ids": [artifact_id],
                        "row_counts": {"source": 4, "filtered": 4},
                    }
                },
            }
        },
    )
    return completed.record_id, artifact_id


def _load_provider_type():
    try:
        module = importlib.import_module("workbench.agent.context_tools")
    except ModuleNotFoundError:
        pytest.fail("provider-backed context module is not registered")
    provider_type = getattr(module, "NodeOperationContextProvider", None)
    assert provider_type is not None, "node context provider is not registered"
    return provider_type


def test_unconfigured_orchestrator_does_not_expose_project_context_tool(
    tmp_path: Path,
) -> None:
    orchestrator = _make_orchestrator(tmp_path)

    tool_ids = {item["tool_id"] for item in orchestrator.tool_registry("chain-a").descriptors()}

    assert "propose_operation" in tool_ids
    assert "inspect_node_context" not in tool_ids
    assert "inspect_operation_contract" not in tool_ids
    assert "inspect_diagnostics" not in tool_ids
    assert "inspect_result_summary" not in tool_ids
    assert "inspect_time_series_summary" not in tool_ids
    assert "inspect_artifact_preview" not in tool_ids


def test_configured_chain_exposes_read_only_node_context_provider(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    registry = orchestrator.tool_registry("chain-a")

    tool_ids = {item["tool_id"] for item in registry.descriptors()}
    assert {
        "propose_operation",
        "inspect_node_context",
        "inspect_operation_contract",
        "inspect_diagnostics",
        "inspect_result_summary",
        "inspect_time_series_summary",
        "inspect_repeated_measures_recipe",
        "inspect_artifact_preview",
    } <= tool_ids
    descriptors = {
        item["tool_id"]: item
        for item in registry.descriptors()
        if item["tool_id"]
        in {
            "inspect_node_context",
            "inspect_operation_contract",
            "inspect_diagnostics",
            "inspect_result_summary",
            "inspect_time_series_summary",
            "inspect_repeated_measures_recipe",
            "inspect_artifact_preview",
        }
    }
    assert set(descriptors) == {
        "inspect_node_context",
        "inspect_operation_contract",
        "inspect_diagnostics",
        "inspect_result_summary",
        "inspect_time_series_summary",
        "inspect_repeated_measures_recipe",
        "inspect_artifact_preview",
    }
    for descriptor in descriptors.values():
        assert descriptor["side_effect"] == "none"
        assert descriptor["scope_requirements"] == ["project", "chain"]
        # The contract tool returns schema rather than rows, so it carries a
        # larger budget than the row-dumping inspectors — see its definition.
        expected = (
            12288
            if descriptor["tool_id"]
            in {"inspect_operation_contract", "inspect_time_series_summary"}
            else 8192
        )
        assert descriptor["max_output_budget"] == expected

    before = {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }
    result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-context-1",
                "tool_id": "inspect_node_context",
                "arguments": {
                    "request_id": "inspect-1",
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    assert result.output["context_version"] == "node-operation-context/v1"
    assert result.output["context_fingerprint"].startswith("nocv1:")
    assert result.output["owner_run_id"] == "run-a"


    assert result.output["op_node_id"] == "model:ols_1"
    assert result.output["node_hash"] == "hash-a"
    assert result.output["forest_node_key"] == "hash-a"
    assert result.output["owner_resolution"] == "active_head_contains_node"
    assert result.output["node"]["id"] == "model:ols_1"
    assert result.output["node"]["stage"] == "model"

    contract_result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-contract-1",
                "tool_id": "inspect_operation_contract",
                "arguments": {
                    "request_id": "inspect-contract-1",
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                    "operation_id": "model.rerun",
                    "operation_version": "v1",
                },
            },
            session_id="chain-session",
        )
    )

    assert contract_result.ok is True
    assert contract_result.output["context_fingerprint"] == result.output["context_fingerprint"]
    assert contract_result.output["target_type"] == "model"
    assert contract_result.output["operation"] == {
        "operation_id": "model.rerun",
        "operation_version": "v1",
        "effect_level": "mutation",
        "scope_requirements": ["chain", "active_head"],
    }
    assert contract_result.output["contract"]["op_type"] == "ols"
    assert contract_result.output["contract"]["schema_id"] == "ols@v1"
    assert {item["key"] for item in contract_result.output["contract"]["editable_schema"]} >= {
        "x",
        "model_type",
    }

    diagnostics_result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-diagnostics-1",
                "tool_id": "inspect_diagnostics",
                "arguments": {
                    "request_id": "inspect-diagnostics-1",
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert diagnostics_result.ok is True
    assert diagnostics_result.output["context_fingerprint"] == result.output["context_fingerprint"]
    diagnostics = diagnostics_result.output["diagnostics"]
    assert diagnostics["available"] is True
    assert diagnostics["preview_status"] == "complete"
    assert diagnostics["run_status"]["report_render_status"] == "complete"
    assert diagnostics["run_status"]["report_available"] is True
    assert diagnostics["trust_label"] == "interpret_with_caution"
    assert diagnostics["trust_counts"] == {
        "blockers": 0,
        "warnings": 1,
        "cautions": 0,
        "info": 0,
    }
    assert diagnostics["primary_reasons"][0]["reason_key"] == "MODEL_DIAGNOSTIC_WARNING"
    assert diagnostics["diagnostic_highlights"][0]["linked_issue_ids"] == ["issue-1"]
    assert diagnostics["interpretation_restrictions"][0]["restriction_type"] == "causal"
    assert diagnostics_result.output["omitted_sections"] == [
        "artifact_manifest",
        "coefficient_risk",
    ]

    result_summary = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-result-summary-1",
                "tool_id": "inspect_result_summary",
                "arguments": {
                    "request_id": "inspect-result-summary-1",
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result_summary.ok is True
    assert result_summary.output["context_fingerprint"] == result.output["context_fingerprint"]
    summary = result_summary.output["result_summary"]
    assert summary["available"] is True
    assert summary["summary_status"] == "complete"
    assert summary["run_lifecycle_status"] == "completed"
    assert summary["trust_label"] == "interpret_with_caution"
    assert summary["model_identity"] == {
        "model_family": "ols",
        "model_label": "OLS regression",
        "y_variable": "y",
        "n_observations": 100,
        "x_variable_count": 1,
    }
    assert summary["metrics"] == {"r_squared": 0.72, "aic": 120.5, "bic": 125.1}
    assert summary["primary_metric_keys"] == ["r_squared", "aic"]
    assert summary["coefficient_rows"] == []
    assert summary["full_table_ref"] is None
    assert result_summary.output["omitted_sections"] == ["raw_model_results"]

    artifact_result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-artifact-preview-1",
                "tool_id": "inspect_artifact_preview",
                "arguments": {
                    "request_id": "inspect-artifact-preview-1",
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert artifact_result.ok is True
    assert artifact_result.output["context_fingerprint"] == result.output["context_fingerprint"]
    artifact_preview = artifact_result.output["artifact_preview"]
    assert artifact_preview["available"] is True
    assert artifact_preview["preview_status"] == "complete"
    assert artifact_preview["run_lifecycle_status"] == "completed"
    assert artifact_preview["artifact_manifest"]["diagnostic_summary_json"] == {
        "expected": True,
        "available": True,
        "readable": True,
        "artifact_id": "diagnostic_summary",
        "filename": "diagnostic_summary.json",
        "schema_valid": True,
    }
    assert artifact_preview["artifact_manifest"]["primary_model_results"] == {
        "expected": True,
        "available": True,
        "readable": True,
        "model_id": "ols_1",
    }
    assert artifact_result.output["omitted_sections"] == ["raw_artifact_payloads"]
    assert before == {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }


def test_completed_workflow_result_is_discoverable_as_bounded_evidence(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    operation_record_id, artifact_id = _write_completed_workflow_result(project_root)
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    registry = orchestrator.tool_registry("chain-a")

    tool_ids = {item["tool_id"] for item in registry.descriptors()}
    assert "inspect_completed_operations" in tool_ids
    assert "inspect_operation_artifact" in tool_ids

    discovery = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-completed-operations",
                "tool_id": "inspect_completed_operations",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert discovery.ok is True
    assert discovery.output["completed_operations"][0] == {
        "operation_record_id": operation_record_id,
        "operation_id": "operation.multi_step",
        "operation_version": "v1",
        "status": "completed",
        "artifact_ids": [artifact_id],
        "workflow": {
            "workflow_id": "workflow-result",
            "status": "completed",
            "steps": [
                {
                    "step_id": "summary",
                    "status": "completed",
                    "artifact_ids": [artifact_id],
                    "row_counts": {"source": 4, "filtered": 4},
                }
            ],
        },
    }

    result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-operation-artifact",
                "tool_id": "inspect_operation_artifact",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                    "operation_record_id": operation_record_id,
                    "artifact_id": artifact_id,
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    evidence = result.output["artifact_evidence"]
    assert evidence["evidence_ref"] == {
        "operation_record_id": operation_record_id,
        "artifact_id": artifact_id,
        "artifact_type": "statistical_exploration",
        "sha256": "artifact-sha",
    }
    assert evidence["result"]["variables"]["outcome"] == {
        "obs": 4,
        "mean": 2.5,
        "std_dev": 1.29,
        "min": 1.0,
        "max": 4.0,
    }
    assert "raw_rows" not in json.dumps(evidence["result"])
    assert "raw_rows" in result.output["omitted_sections"]


def test_rerun_precheck_rejects_non_option_fields_before_confirmation(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)

    with pytest.raises(ToolVisibleError, match="OLS_MODEL_OPTIONS_UNKNOWN_FIELD"):
        orchestrator._precheck_model_options(
            owner_run_id="run-a",
            changes={"model_options": {"x": ["x1", "x2"]}},
        )


def test_operation_artifact_rejects_a_record_from_another_chain(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    _write_completed_workflow_result(project_root)
    foreign_record_id, artifact_id = _write_completed_workflow_result(
        project_root,
        proposal_id="proposal-workflow-result-foreign",
        session_id="other-session",
        chain_id="chain-b",
    )
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)

    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-foreign-operation-artifact",
                "tool_id": "inspect_operation_artifact",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                    "operation_record_id": foreign_record_id,
                    "artifact_id": artifact_id,
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is False
    assert result.error == "ToolVisibleError"
    assert "OPERATION_RESULT_NOT_IN_SCOPE" in result.error_details[0]["message"]


def test_operation_artifact_refuses_an_unregistered_figure_payload(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    operation_record_id, artifact_id = _write_completed_workflow_result(
        project_root,
        artifact_id="plot-packet",
        artifact_type="figure_packet",
        artifact_payload={
            "series": [{"x": 1, "y": 2}],
            "rendered_path": "artifacts/figures/plot.png",
        },
    )
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)

    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-unregistered-figure",
                "tool_id": "inspect_operation_artifact",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                    "operation_record_id": operation_record_id,
                    "artifact_id": artifact_id,
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    evidence = result.output["artifact_evidence"]
    assert evidence["available"] is False
    assert evidence["status"] == "public_result_not_available"
    assert evidence["result"] is None
    assert "registered public Agent result view" in evidence["reason"]
    assert "series" not in json.dumps(result.output)
    assert "raw_artifact_payloads" in result.output["omitted_sections"]


@pytest.mark.parametrize("artifact_type", ["statistical_test", "post_estimation"])
def test_operation_artifact_projects_declared_model_post_estimation_results(
    tmp_path: Path,
    artifact_type: str,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    operation_record_id, artifact_id = _write_completed_workflow_result(
        project_root,
        artifact_id=f"declared_{artifact_type}",
        artifact_type=artifact_type,
        artifact_payload={
            "result": {
                "branch_id": "curved",
                "f_statistic": 12.4,
                "p_value": 0.003,
                "raw_rows": [{"response": 1.0}],
            }
        },
    )
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)

    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-declared-post-estimation",
                "tool_id": "inspect_operation_artifact",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                    "operation_record_id": operation_record_id,
                    "artifact_id": artifact_id,
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    evidence = result.output["artifact_evidence"]
    assert evidence["available"] is True
    assert evidence["evidence_ref"]["artifact_type"] == artifact_type
    assert evidence["result"] == {
        "branch_id": "curved",
        "f_statistic": 12.4,
        "p_value": 0.003,
    }
    assert "raw_rows" not in json.dumps(evidence["result"])


def test_operation_artifact_enforces_a_total_public_result_budget(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    operation_record_id, artifact_id = _write_completed_workflow_result(
        project_root,
        artifact_payload={
            "result": {
                "variables": {
                    f"variable_{index}_{'x' * 120}": {"note": "y" * 400}
                    for index in range(24)
                }
            }
        },
    )
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)

    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-large-public-result",
                "tool_id": "inspect_operation_artifact",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                    "operation_record_id": operation_record_id,
                    "artifact_id": artifact_id,
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    public_result = result.output["artifact_evidence"]["result"]
    assert len(json.dumps(public_result)) <= 7_000
    assert public_result["variables"]["_omitted_item_count"] > 0


def test_operation_artifact_reserves_its_omission_marker(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    operation_record_id, artifact_id = _write_completed_workflow_result(
        project_root,
        artifact_payload={
            "result": {
                "_omitted_item_count": 999,
                "variables": {"outcome": {"mean": 2.5}},
            }
        },
    )
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)

    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-reserved-omission-marker",
                "tool_id": "inspect_operation_artifact",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                    "operation_record_id": operation_record_id,
                    "artifact_id": artifact_id,
                },
            },
            session_id="chain-session",
        )
    )

    public_result = result.output["artifact_evidence"]["result"]
    assert "_omitted_item_count" not in public_result
    assert public_result["variables"]["outcome"]["mean"] == 2.5


def test_agent_uses_completed_operation_evidence_before_answering(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    _write_completed_workflow_result(project_root)
    provider = _load_provider_type()(project_root)
    adapter = CompletedResultAnswerAdapter()
    orchestrator = _make_orchestrator(
        tmp_path,
        context_provider=provider,
        adapter=adapter,
    )

    command = orchestrator.dispatch_to_chain(
        "chain-a",
        objective="Read the completed summary and answer with its mean.",
        allowed_operations=["inspect"],
        budget={"max_steps": 4, "timeout_s": 30},
        context_fingerprint="nocv1:test",
    )
    answer = asyncio.run(orchestrator.execute(command.command_id))

    assert answer == (
        "The completed summary reports an outcome mean of 2.5 "
        "(artifact: statistical_exploration_summary)."
    )
    assert len(adapter.requests) == 3


def test_managed_chain_context_tool_rejects_a_forged_active_head(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    ChainStore(project_root / "workbench").create_root(
        chain_id="chain-a",
        run_family_id="legacy-family:run-b",
        active_head_run_id="run-b",
        agent_session_id="chain-session",
    )

    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-forged-head",
                "tool_id": "inspect_node_context",
                "arguments": {
                    "request_id": "inspect-forged-head",
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is False
    assert result.error == "ChainHeadConflict"


def test_invalid_node_probe_returns_one_visible_error_with_valid_targets(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)

    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-invalid-node",
                "tool_id": "inspect_node_context",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:does-not-exist",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is False
    assert result.error == "ToolVisibleError"
    message = result.error_details[0]["message"]
    assert "INVALID_OPERATION_TARGET" in message
    assert "model:ols_1" in message


def test_result_summary_bounds_coefficient_rows_and_preserves_artifact_ref(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    summary_path = project_root / "runs" / "run-a" / "diagnostic_summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["coefficients_summary"] = {
        "interpretation_mode": "associational",
        "full_table_ref": "model_results/ols_1.json",
        "rows": [
            {
                "variable": f"x{index}",
                "estimate": index,
                "std_error": 0.1,
                "p_value": 0.05,
                "ci_lower": index - 0.2,
                "ci_upper": index + 0.2,
                "significance_label": "not reported",
                "raw_payload": {"should_not": "leak"},
            }
            for index in range(10)
        ],
    }
    summary_path.write_text(json.dumps(summary), encoding="utf-8")
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-result-summary-bounded",
                "tool_id": "inspect_result_summary",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    summary_output = result.output["result_summary"]
    assert summary_output["coefficient_row_count"] == 10
    assert summary_output["coefficient_rows_omitted"] == 2
    assert len(summary_output["coefficient_rows"]) == 8
    assert summary_output["coefficient_rows"][0]["ci_lower"] == -0.2
    assert summary_output["coefficient_rows"][0]["ci_upper"] == 0.2
    assert all("raw_payload" not in row for row in summary_output["coefficient_rows"])
    assert summary_output["full_table_ref"] == "model_results/ols_1.json"
    assert summary_output["interpretation_mode"] == "associational"
    assert "raw_model_results" in result.output["omitted_sections"]
    assert "coefficient_rows" in result.output["omitted_sections"]


def test_global_coefficient_inspector_returns_requested_persisted_intervals(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    result_path = project_root / "runs" / "run-a" / "model_results" / "ols_1.json"
    result_path.write_text(
        json.dumps(
            {
                "model_id": "ols_1",
                "model_type": "ols_robust",
                "nobs": 100,
                "y_column": "outcome",
                "x_columns": ["share", "control"],
                "covariance": "robust",
                "covariance_estimator": "HC1",
                "covariance_evidence": {
                    "confidence_level": 0.95,
                    "confidence_interval_method": "normal_z",
                },
                "coefficients": {
                    "share": {
                        "estimate": 1.2,
                        "std_error": 0.3,
                        "p_value": 0.001,
                        "ci_lower": 0.61,
                        "ci_upper": 1.79,
                        "source_id": "model_results.ols_1.coefficients.share",
                    },
                    "control": {"estimate": 0.4},
                },
                "raw_rows": [{"outcome": 99}],
            }
        ),
        encoding="utf-8",
    )
    provider = _load_provider_type()(project_root)
    registry = ToolRegistry()
    for definition in provider.global_tool_definitions(session_id="main-session"):
        registry.register(definition)

    result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-global-coefficients",
                "tool_id": "inspect_project_model_coefficients",
                "arguments": {"run_ids": ["run-a"], "terms": ["share"]},
            },
            session_id="main-session",
        )
    )

    assert result.ok is True
    assert result.output == {
        "models": [
            {
                "run_id": "run-a",
                "model_id": "ols_1",
                "model_type": "ols_robust",
                "nobs": 100,
                "outcome": "outcome",
                "predictors": ["share", "control"],
                "predictors_omitted": 0,
                "covariance": "robust",
                "covariance_estimator": "HC1",
                "confidence_interval": {"level": 0.95, "method": "normal_z"},
                "coefficients": [
                    {
                        "term": "share",
                        "estimate": 1.2,
                        "std_error": 0.3,
                        "p_value": 0.001,
                        "ci_lower": 0.61,
                        "ci_upper": 1.79,
                        "source_id": "model_results.ols_1.coefficients.share",
                    }
                ],
                "missing_terms": [],
                "evidence_ref": {
                    "run_id": "run-a",
                    "model_id": "ols_1",
                    "result_ref": "model_results:ols_1",
                },
            }
        ],
        "omitted_sections": ["raw_model_results", "raw_rows"],
    }
    assert "99" not in json.dumps(result.output)


def test_time_series_summary_reads_only_bounded_public_artifacts(
    tmp_path: Path,
) -> None:
    from tests.agent.test_arma_garch_agent_compare import _artifacts

    project_root = tmp_path / "project"
    _write_project_run(project_root)
    run_root = project_root / "runs" / "run-a"
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["model_routing"] = {
        "requested_model_type": "time_series.arma_garch",
        "effective_model_type": "time_series.arma_garch",
    }
    (run_root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    artifact_root = run_root / "artifacts" / "time_series"
    artifact_root.mkdir(parents=True)
    for artifact_id, payload in _artifacts().items():
        (artifact_root / f"{artifact_id}.json").write_text(
            json.dumps(
                {
                    "artifact_id": artifact_id,
                    "metadata": {
                        "run_id": "run-a",
                        "source_run_id": None,
                        "node_id": "model:ols_1",
                    },
                    "payload": payload,
                }
            ),
            encoding="utf-8",
        )

    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    before = {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }
    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-time-series-summary",
                "tool_id": "inspect_time_series_summary",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    summary = result.output["time_series_summary"]
    assert summary["available"] is True
    assert summary["candidate_counts"] == {"mean": 10, "volatility": 1}
    assert len(summary["mean_candidates"]) == 8
    assert summary["conditional_series"] == {
        "available": True,
        "observation_count": 120,
    }
    assert "raw_rows" in result.output["omitted_sections"]
    assert before == {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }


def test_time_series_summary_reads_blocked_manifest_and_frozen_run_input(
    tmp_path: Path,
) -> None:
    from tests.agent.test_arma_garch_agent_compare import _contract

    project_root = tmp_path / "project"
    _write_project_run(project_root)
    run_root = project_root / "runs" / "run-a"
    run_inputs = json.loads((run_root / "run_inputs.json").read_text(encoding="utf-8"))
    run_inputs["executed_payload"] = {
        "model_type": "time_series.arma_garch",
        "model_options": _contract(),
    }
    (run_root / "run_inputs.json").write_text(json.dumps(run_inputs), encoding="utf-8")
    artifact_root = run_root / "artifacts" / "time_series"
    artifact_root.mkdir(parents=True)
    diagnostic = {
        "severity": "blocking",
        "code": "LOG_REQUIRES_POSITIVE_VALUES",
        "message": "Log transforms require positive values.",
        "evidence": {"nonpositive_count": 1},
        "impact": "The confirmed transform cannot run.",
        "recommended_actions": [
            {
                "operation": "model.rerun",
                "patch": {"transform": "level", "transform_confirmed": True},
            }
        ],
    }
    (artifact_root / "ts.artifact_manifest.json").write_text(
        json.dumps(
            {
                "artifact_id": "ts.artifact_manifest",
                "metadata": {"run_id": "run-a", "node_id": "stage:ts-analysis-view"},
                "payload": {
                    "status": "blocked",
                    "terminal_code": diagnostic["code"],
                    "complete": False,
                    "diagnostic": diagnostic,
                },
            }
        ),
        encoding="utf-8",
    )

    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-blocked-time-series-summary",
                "tool_id": "inspect_time_series_summary",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    summary = result.output["time_series_summary"]
    assert summary["available"] is True
    assert summary["terminal_code"] == "LOG_REQUIRES_POSITIVE_VALUES"
    assert summary["recommended_actions"][0]["changes"] == {
        "model_options": {"transform": "level", "transform_confirmed": True}
    }


def test_operation_contract_rejects_unregistered_operation_without_writes(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    registry = orchestrator.tool_registry("chain-a")

    before = {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }
    result = asyncio.run(
        registry.execute(
            {
                "tool_call_id": "call-contract-unknown",
                "tool_id": "inspect_operation_contract",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                    "operation_id": "graph.unknown",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is False
    # The operation_id schema now enumerates registered operations (live smoke
    # showed the model guessing "rerun"/"run"/"ols"), so an unregistered id is
    # rejected at the schema boundary — earlier than the handler's
    # UnknownOperationError, still fail-closed, still write-free.
    assert result.error == "invalid_tool_arguments"
    # P6-1: the rejection must also say why, or the model can only guess (the
    # live smoke showed it retrying blind). The enum is the whole point here —
    # name it, and list what is actually registered.
    assert result.error_details
    detail = next(d for d in result.error_details if d["path"] == "operation_id")
    assert detail["constraint"] == "enum"
    assert "data.columns.cast" in detail["message"]
    assert "error_details" in result.to_payload()
    assert before == {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }


def test_diagnostics_preserves_malformed_summary_as_read_only_preview_state(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    (project_root / "runs" / "run-a" / "diagnostic_summary.json").write_text(
        "not json",
        encoding="utf-8",
    )
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-diagnostics-malformed",
                "tool_id": "inspect_diagnostics",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    assert result.output["diagnostics"]["preview_status"] == "malformed"
    assert result.output["diagnostics"]["trust_label"] == "contract_unavailable"


def test_result_summary_preserves_malformed_summary_state_without_raw_results(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    (project_root / "runs" / "run-a" / "diagnostic_summary.json").write_text(
        "not json",
        encoding="utf-8",
    )
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-result-summary-malformed",
                "tool_id": "inspect_result_summary",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    summary = result.output["result_summary"]
    assert summary["available"] is False
    assert summary["summary_status"] == "malformed"
    assert summary["trust_label"] == "contract_unavailable"
    assert result.output["omitted_sections"] == ["raw_model_results"]


def test_artifact_preview_reports_running_lifecycle_without_writes(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_project_run(project_root)
    (project_root / "runs" / "run-a" / "run_manifest.json").write_text(
        json.dumps({"status": "running"}),
        encoding="utf-8",
    )
    provider = _load_provider_type()(project_root)
    orchestrator = _make_orchestrator(tmp_path, context_provider=provider)
    before = {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }
    result = asyncio.run(
        orchestrator.tool_registry("chain-a").execute(
            {
                "tool_call_id": "call-artifact-preview-running",
                "tool_id": "inspect_artifact_preview",
                "arguments": {
                    "owner_run_id": "run-a",
                    "op_node_id": "model:ols_1",
                    "active_head_run_id": "run-a",
                },
            },
            session_id="chain-session",
        )
    )

    assert result.ok is True
    artifact_preview = result.output["artifact_preview"]
    assert artifact_preview["available"] is False
    assert artifact_preview["preview_status"] == "pending"
    assert artifact_preview["run_lifecycle_status"] == "running"
    assert artifact_preview["artifact_manifest"]["primary_model_results"]["available"] is True
    assert result.output["omitted_sections"] == ["raw_artifact_payloads"]
    assert before == {
        path.relative_to(project_root): path.read_bytes()
        for path in project_root.rglob("*")
        if path.is_file()
    }


def _inspect_contract(project_root: Path, provider_type) -> dict:
    from workbench.agent.context_tools import InspectOperationContractRequest
    from workbench.agent.operations import OperationRegistry

    return provider_type(project_root).inspect_operation_contract(
        InspectOperationContractRequest(
            request_id="r1",
            owner_run_id="run-a",
            op_node_id="model:ols_1",
            active_head_run_id="run-a",
            operation_id="model.rerun",
        ),
        operation_registry=OperationRegistry(),
    )


def test_arma_garch_contract_publishes_its_option_vocabulary(tmp_path: Path) -> None:
    """The pack's editable schema is one opaque `model_options` JSON control.

    Without a vocabulary the Agent has to guess field names, closed value sets,
    and server caps, so it writes patches confirmation rejects. The vocabulary
    is what makes a natural-language request into a legal typed patch.
    """

    project_root = tmp_path / "project"
    _write_project_run(project_root)
    run_root = project_root / "runs" / "run-a"
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["model_routing"] = {
        "requested_model_type": "time_series.arma_garch",
        "effective_model_type": "time_series.arma_garch",
    }
    (run_root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    contract = _inspect_contract(project_root, _load_provider_type())["contract"]

    assert contract["op_type"] == "time_series.arma_garch"
    vocabulary = contract["option_vocabulary"]
    paths = {field["path"] for field in vocabulary["fields"]}
    assert {"arma.p", "variance.model", "missing_value_policy"} <= paths
    assert vocabulary["cross_field_rules"]


def test_ols_contract_publishes_its_bounded_option_vocabulary(tmp_path: Path) -> None:
    # OLS now owns a small Agent envelope; publishing it prevents the Agent
    # from guessing the nested covariance field or its closed value set.
    project_root = tmp_path / "project"
    _write_project_run(project_root)

    contract = _inspect_contract(project_root, _load_provider_type())["contract"]

    assert contract["op_type"] == "ols"
    vocabulary = contract["option_vocabulary"]
    assert vocabulary["version"] == "ols-model-options/v1"
    assert vocabulary["fields"]["covariance"]["allowed_values"] == [
        "robust",
        "clustered",
        "unadjusted",
    ]


def test_the_arma_garch_contract_payload_fits_the_tool_output_budget(
    tmp_path: Path,
) -> None:
    """Found by a live DeepSeek turn, not by the deterministic suite.

    The vocabulary made `inspect_operation_contract` exceed the tool's output
    budget, so the tool returned `tool_output_budget_exceeded`, the model
    retried the identical call, and the turn died on the repetition limit. The
    Agent could not read the contract at all -- the opposite of what publishing
    a vocabulary was for. Asserting the vocabulary is *present* was not enough;
    it has to fit in the response the model actually receives.
    """

    from workbench.agent.operations import OperationRegistry

    project_root = tmp_path / "project"
    _write_project_run(project_root)
    run_root = project_root / "runs" / "run-a"
    manifest = json.loads((run_root / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["model_routing"] = {
        "requested_model_type": "time_series.arma_garch",
        "effective_model_type": "time_series.arma_garch",
    }
    (run_root / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    payload = _inspect_contract(project_root, _load_provider_type())
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    budget = next(
        definition.max_output_budget
        for definition in _load_provider_type()(project_root).tool_definitions(
            chain_id="chain-a",
            session_id="chain-session",
            operation_registry=OperationRegistry(),
        )
        if definition.tool_id == "inspect_operation_contract"
    )
    assert budget is not None
    assert len(serialized) <= budget, (
        f"contract payload is {len(serialized)} chars against a {budget} budget; "
        "the Agent would receive tool_output_budget_exceeded instead of the contract"
    )
