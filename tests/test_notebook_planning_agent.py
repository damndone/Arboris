"""Typed provider loop tests with deterministic fake adapters."""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from pathlib import Path
from typing import AsyncIterator

import pytest

from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord, InspectionRequest
from workbench.agent.notebook.planning_agent import (
    NOTEBOOK_TOOLS,
    NotebookPlanningAgent,
    NotebookPlanningContractError,
    NotebookPlanningTimeout,
    NotebookPlanningUnavailable,
    _parse_submissions,
    _strict_typed_proposal,
)
from workbench.agent.notebook.producer import generate_option_batch
from workbench.agent.operations import OperationRegistry, OperationValidationError
from workbench.agent.context_compiler import compile_notebook_planning_context
from workbench.agent.context_compiler import freshness_dependency_fingerprint
from workbench.agent.notebook.proposal import TypedProposal
from tests.test_notebook_support import make_project


def _context(
    project: Path,
    *,
    active_head_run_id: str | None = None,
    projection_source: dict | None = None,
):
    return compile_notebook_planning_context(
        project,
        notebook_id="nb_plan",
        run_family_id="family_plan",
        active_head_run_id=active_head_run_id,
        analysis_contract={"revision": 1, "target": "y"},
        available_capabilities=["time_series.ets"],
        projection_source=projection_source,
    )


def _evidence() -> DataEvidencePackV1:
    return DataEvidencePackV1(
        source_id="run:run_001",
        records=(
            EvidenceRecord(
                evidence_id="evidence:time",
                inspection_id="time_index.v1",
                source_refs=("time_index:run_001",),
                protocol_version="time-index/v1",
                status="completed",
                observations={
                    "candidate_column": "when",
                    "columns": [{"name": "outcome"}, {"name": "treatment"}],
                },
                result_hash="sha256:time-result",
            ),
        ),
    )


def _submit_call(*, capability_id: str = "time_series.ets", run_id: str = "notebook:nb_plan") -> dict:
    return {
        "options": [
            {
                "rank": 1,
                "rationale": "The time index supports this registered path.",
                "assumptions": ["time semantics remain unchanged"],
                "capability_id": capability_id,
                "option_id": "opt_ets",
                "proposal": {
                    "proposal_id": "prop_ets",
                    "proposal_revision": 1,
                    "operation_id": "model.rerun",
                    "operation_version": "v1",
                    "target": {
                        "run_id": run_id,
                        "node_ref": "stage:model",
                        "node_hash": "node-hash",
                        "forest_node_key": "forest-node-key",
                    },
                    "preconditions": {
                        "context_version": "node-operation-context/v1",
                        "context_fingerprint": "nocv1:test",
                        "active_head_run_id": run_id,
                        "owner_resolution": "single_candidate",
                    },
                    "changes": {"model_options": {"model_type": "ets"}},
                },
                "expected_artifacts": [
                    {
                        "artifact_id": "ets_1",
                        "artifact_type": "model_result",
                        "required": True,
                        "count": 1,
                        "step": None,
                    }
                ],
                "evidence_refs": [
                    {"evidence_id": "evidence:time", "result_hash": "sha256:time-result", "source_refs": ["time_index:run_001"]}
                ],
                "comparative_claims": ["evidence:time supports the path"],
            }
        ]
    }


class SequencedAdapter:
    def __init__(self, submit_args: dict) -> None:
        self.submit_args = submit_args
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        if len(self.requests) == 1:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {
                    "tool_call_id": "inspect-1",
                    "tool_id": "request_notebook_inspections",
                    "arguments": {
                        "requests": [
                            {"inspection_id": "time_index.v1", "target_ref": "run:active", "arguments": {"max_rows": 10}, "why_needed": "validate index"}
                        ]
                    },
                },
            )
        else:
            yield ModelStreamEvent.tool_call_delta(
                request.request_id,
                {"tool_call_id": "submit-1", "tool_id": "submit_notebook_option_batch", "arguments": self.submit_args},
            )
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


class ScriptedAdapter:
    def __init__(self, calls: list[dict]) -> None:
        self.calls = calls
        self.requests: list[ModelRequest] = []

    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        self.requests.append(request)
        call = self.calls[min(len(self.requests) - 1, len(self.calls) - 1)]
        yield ModelStreamEvent.tool_call_delta(request.request_id, call)
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


class FailingAdapter:
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent.from_error(request.request_id, "provider_unavailable")


class TextOnlyAdapter:
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent.text_delta(request.request_id, "use ETS")
        yield ModelStreamEvent.done(request.request_id)


def test_provider_plan_runs_registered_inspection_then_submits_batch(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    evidence = _evidence()
    adapter = SequencedAdapter(_submit_call())
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=lambda requests, current: evidence,
    )

    result = agent.plan(context=_context(project), initial_evidence=DataEvidencePackV1("run:run_001", ()))

    assert result.inspection_requests[0].inspection_id == "time_index.v1"
    assert len(result.option_drafts) == 1
    assert [tool["tool_id"] for tool in adapter.requests[0].tools] == [tool["tool_id"] for tool in NOTEBOOK_TOOLS]
    planning_payload = json.loads(adapter.requests[0].messages[1]["content"])
    planning_context = planning_payload["context"]
    assert planning_context["generation_context_hash"].startswith("sha256:")
    assert planning_context["freshness_dependency_fingerprint"].startswith("fresh1:")
    assert planning_context["execution_pins"]["rerun_preconditions"]["context_version"] == "node-operation-context/v1"
    assert planning_context["typed_operation_contracts"]["model.genesis"]["changes_allowed_fields"] == [
        "table_params",
        "model_params",
        "model_options",
    ]
    assert "comparative_claim" in adapter.requests[0].messages[0]["content"]
    assert "evidence_id" in adapter.requests[0].messages[0]["content"]
    assert "dataset_source_id" in adapter.requests[0].messages[0]["content"]
    assert "execution_pins" in adapter.requests[0].messages[0]["content"]
    assert len(adapter.requests) == 2


def test_provider_can_request_three_distinct_bounded_inspections_before_submitting(
    tmp_path: Path,
) -> None:
    """Valid sequential inspections must not exhaust a two-turn implementation limit."""

    inspection_ids = ("profile.v1", "quality.v1", "time_index.v1")
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": f"inspect-{inspection_id}",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": inspection_id,
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            }
            for inspection_id in inspection_ids
        ]
        + [
            {
                "tool_call_id": "submit-after-inspections",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            }
        ]
    )

    def inspect(requests: tuple[InspectionRequest, ...], current: DataEvidencePackV1) -> DataEvidencePackV1:
        del current
        inspection_id = requests[0].inspection_id
        if inspection_id == "time_index.v1":
            return _evidence()
        return DataEvidencePackV1(
            source_id="run:run_001",
            records=(
                EvidenceRecord(
                    evidence_id=f"evidence:{inspection_id}",
                    inspection_id=inspection_id,
                    source_refs=(f"{inspection_id}:run_001",),
                    protocol_version=f"{inspection_id}/v1",
                    status="completed",
                    result_hash=f"sha256:{inspection_id}",
                ),
            ),
        )

    result = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=inspect,
    ).plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert [request.inspection_id for request in result.inspection_requests] == list(inspection_ids)
    assert len(result.option_drafts) == 1
    assert len(adapter.requests) == 4


def test_model_custom_planning_contract_exposes_intent_but_rejects_authority_fields(
    tmp_path: Path,
) -> None:
    project = make_project(tmp_path)
    context = _context(
        project,
        projection_source={
            "kind": "dataset",
            "upload_sha256": "a" * 64,
        },
    )
    contracts = NotebookPlanningAgent._typed_operation_contracts(context)
    assert contracts["model.custom"]["changes_allowed_fields"] == [
        "operation",
        "input_handle",
        "parameters",
        "consumer_slots",
    ]

    proposal = {
        "proposal_id": "prop_custom",
        "proposal_revision": 1,
        "operation_id": "model.custom",
        "operation_version": "v1",
        "target": {"dataset_source_id": "a" * 64},
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": "fresh1:test",
            "owner_resolution": "dataset_projection",
        },
        "changes": {
            "operation": "fit",
            "input_handle": "table_1",
            "parameters": {"alpha": 0.1},
            "consumer_slots": ["report_projection"],
        },
    }
    parsed = _strict_typed_proposal(proposal)
    assert parsed.operation_id == "model.custom"
    assert parsed.changes["operation"] == "fit"

    with pytest.raises(NotebookPlanningContractError, match="server-owned"):
        _strict_typed_proposal(
            {
                **proposal,
                "changes": {
                    **proposal["changes"],
                    "binding_ref": "b" * 64,
                },
            }
        )


def test_provider_plan_runs_target_model_options_validator_before_accepting_batch(
    tmp_path: Path,
) -> None:
    """A provider proposal is not executable until the target pack accepts it."""

    calls = [_submit_call(), _submit_call()]
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-1",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                            "why_needed": "validate index",
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-1",
                "tool_id": "submit_notebook_option_batch",
                "arguments": calls[0],
            },
            {
                "tool_call_id": "submit-2",
                "tool_id": "submit_notebook_option_batch",
                "arguments": calls[1],
            },
        ]
    )
    seen: list[dict] = []

    def validate_target(_context, submission) -> None:
        seen.append(dict(submission.proposal.changes["model_options"]))
        if len(seen) == 1:
            raise NotebookPlanningContractError(
                "model_options target contract rejected [MODEL_OPTIONS_INVALID_VALUE]"
            )

    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=lambda requests, current: _evidence(),
        proposal_validator=validate_target,
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert len(seen) == 2
    assert any(
        "model_options target contract rejected" in str(message.get("content"))
        for message in adapter.requests[2].messages
        if message.get("role") == "user"
    )


def test_provider_plan_surfaces_a_bounded_timeout(tmp_path: Path) -> None:
    class SlowAdapter:
        async def stream(self, request):
            await asyncio.sleep(0.05)
            yield ModelStreamEvent.done(request.request_id)

    agent = NotebookPlanningAgent(
        adapter=SlowAdapter(),
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        model_timeout_s=0.001,
    )

    with pytest.raises(NotebookPlanningTimeout, match="exceeded"):
        agent.plan(
            context=_context(make_project(tmp_path)),
            initial_evidence=DataEvidencePackV1("run:run_001", ()),
        )


def test_option_parser_rejects_more_than_three_options_at_typed_boundary() -> None:
    payload = _submit_call()
    payload["options"] = payload["options"] * 4

    with pytest.raises(NotebookPlanningContractError, match="at most 3"):
        _parse_submissions(payload)


def test_unregistered_inspection_is_rejected_before_execution_and_corrected(
    tmp_path: Path,
) -> None:
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "forecast-1",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "forecast_rolling_origin.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                            "why_needed": "compare candidates",
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-1",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        available_inspections=("profile.v1", "quality.v1", "time_index.v1", "sample.v1"),
        inspection_executor=lambda requests, current: pytest.fail(
            "an unavailable inspection must not reach the executor"
        ),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=_evidence(),
    )

    assert len(result.option_drafts) == 1
    assert any(
        "inspection is not available" in str(message.get("content"))
        for message in adapter.requests[1].messages
        if message.get("role") == "user"
    )


def test_provider_plan_keeps_evidence_from_multiple_inspection_rounds(tmp_path: Path) -> None:
    profile = EvidenceRecord(
        evidence_id="evidence:profile",
        inspection_id="profile.v1",
        source_refs=("profile:run_001",),
        protocol_version="profile/v1",
        status="completed",
        observations={"row_count": 10},
        result_hash="sha256:profile-result",
    )
    calls = [
        {
            "tool_call_id": "inspect-time",
            "tool_id": "request_notebook_inspections",
            "arguments": {
                "requests": [
                    {
                        "inspection_id": "time_index.v1",
                        "target_ref": "run:active",
                        "arguments": {},
                        "why_needed": "validate index",
                    }
                ]
            },
        },
        {
            "tool_call_id": "inspect-profile",
            "tool_id": "request_notebook_inspections",
            "arguments": {
                "requests": [
                    {
                        "inspection_id": "profile.v1",
                        "target_ref": "run:active",
                        "arguments": {},
                        "why_needed": "validate sample size",
                    }
                ]
            },
        },
        {
            "tool_call_id": "submit-both",
            "tool_id": "submit_notebook_option_batch",
            "arguments": {
                **_submit_call(),
                "options": [
                    {
                        **_submit_call()["options"][0],
                        "evidence_refs": [
                            {
                                "evidence_id": "evidence:time",
                                "result_hash": "sha256:time-result",
                                "source_refs": ["time_index:run_001"],
                            },
                            {
                                "evidence_id": "evidence:profile",
                                "result_hash": "sha256:profile-result",
                                "source_refs": ["profile:run_001"],
                            },
                        ],
                    }
                ],
            },
        },
    ]
    adapter = ScriptedAdapter(calls)

    def inspect(requests, current):
        del current
        if requests[0].inspection_id == "time_index.v1":
            return _evidence()
        return DataEvidencePackV1(source_id="run:run_001", records=(profile,))

    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        inspection_executor=inspect,
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert {record.evidence_id for record in result.evidence_pack.records} == {
        "evidence:time",
        "evidence:profile",
    }
    assert result.option_drafts[0].evidence_refs[-1].evidence_id == "evidence:profile"
    assert "evidence:time" in adapter.requests[2].messages[-1]["content"]
    assert "evidence:profile" in adapter.requests[2].messages[-1]["content"]


def test_provider_gets_bounded_correction_for_invalid_inspection_id(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-invalid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "inspect_head",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    executor_calls: list[tuple[InspectionRequest, ...]] = []
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: (executor_calls.append(requests) or _evidence()),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert result.inspection_requests[0].inspection_id == "time_index.v1"
    assert len(executor_calls) == 1
    assert len(adapter.requests) == 3
    correction_messages = adapter.requests[1].messages
    assert any(message.get("role") == "tool" and "rejected" in message["content"] for message in correction_messages)
    assert "inspect_head" in correction_messages[-1]["content"]
    assert "time_index.v1" in correction_messages[-1]["content"]


def test_provider_gets_projection_target_correction_for_failed_inspection(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-wrong-target",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "inspect-right-target",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    failed = DataEvidencePackV1(
        "run:run_001",
        (
            EvidenceRecord(
                evidence_id="evidence:target-failed",
                inspection_id="profile.v1",
                source_refs=("inspection_failure:run:run_001",),
                protocol_version="inspection-error/v1",
                status="failed",
                failure_code="TARGET_REF_INVALID",
                result_hash="sha256:target-failed",
            ),
        ),
    )
    calls = 0

    def execute(requests, current):
        nonlocal calls
        calls += 1
        if calls == 1:
            return failed
        return DataEvidencePackV1(
            "run:run_001",
            (
                *_evidence().records,
                EvidenceRecord(
                    evidence_id="evidence:profile-recovered",
                    inspection_id="profile.v1",
                    source_refs=("dataset_profile:run_001",),
                    protocol_version="profile/v1",
                    status="completed",
                    observations={"row_count": 35},
                    result_hash="sha256:profile-recovered",
                ),
            ),
        )

    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=execute,
    )
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "run", "run_id": "run_001"},
    )

    result = agent.plan(context=context, initial_evidence=DataEvidencePackV1("run:run_001", ()))

    assert len(result.option_drafts) == 1
    assert result.decision.outcome == "recommended"
    assert any("TARGET_REF_INVALID" in str(message) for message in adapter.requests[1].messages)
    assert any(
        "target_ref exactly 'run:active'" in str(message)
        for message in adapter.requests[1].messages
    )


def test_provider_gets_bounded_correction_for_invalid_submission(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["comparative_claims"] = ["The time index supports the path."]
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert len(adapter.requests) == 3
    correction_messages = adapter.requests[2].messages
    assert any(message.get("role") == "tool" and "rejected" in message["content"] for message in correction_messages)
    assert "comparative claim has no evidence ref" in correction_messages[-1]["content"]
    assert "evidence:time" in correction_messages[-1]["content"]


def test_provider_gets_server_owned_dataset_pin_after_invalid_submission(tmp_path: Path) -> None:
    upload_sha256 = "sha256:upload-123"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    genesis_preconditions = {
        "context_version": "node-operation-context/v1",
        "context_fingerprint": freshness_dependency_fingerprint(context),
        "owner_resolution": "single_candidate",
    }
    invalid = _submit_call()
    invalid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": "sha256:not-the-upload"},
        "preconditions": genesis_preconditions,
        "changes": {"model_params": {"model_type": "ols", "y": "outcome", "x": ["treatment"]}},
    }
    valid = _submit_call()
    valid["options"][0]["proposal"] = {
        **valid["options"][0]["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": upload_sha256},
        "preconditions": genesis_preconditions,
        "changes": {"model_params": {"model_type": "ols", "y": "outcome", "x": ["treatment"]}},
    }
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": valid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=context,
        initial_evidence=DataEvidencePackV1("dataset", ()),
    )

    assert len(result.option_drafts) == 1
    correction_messages = adapter.requests[2].messages
    assert "dataset-source proposal is not pinned to the source upload" in correction_messages[-1]["content"]
    assert upload_sha256 in correction_messages[-1]["content"]


def test_provider_gets_correction_for_incomplete_genesis_preconditions(tmp_path: Path) -> None:
    upload_sha256 = "sha256:upload-preconditions"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    invalid = _submit_call()
    invalid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": upload_sha256},
        "preconditions": {},
        "changes": {"model_params": {"model_type": "ols", "y": "outcome", "x": ["treatment"]}},
    }
    valid = invalid.copy()
    valid["options"] = [dict(invalid["options"][0])]
    valid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": freshness_dependency_fingerprint(context),
            "owner_resolution": "single_candidate",
        },
    }
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": valid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(context=context, initial_evidence=DataEvidencePackV1("dataset", ()))

    assert len(result.option_drafts) == 1
    correction_messages = adapter.requests[2].messages
    assert "model.genesis preconditions missing" in correction_messages[-1]["content"]
    assert freshness_dependency_fingerprint(context) in correction_messages[-1]["content"]


def test_provider_rejects_genesis_without_evidence_backed_target(tmp_path: Path) -> None:
    upload_sha256 = "a" * 64
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    invalid = _submit_call(capability_id="time_series.ets")
    invalid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": upload_sha256},
        "preconditions": {
            "context_version": "node-operation-context/v1",
            "context_fingerprint": freshness_dependency_fingerprint(context),
            "owner_resolution": "single_candidate",
        },
        "changes": {"model_params": {"model_type": "ols", "x": ["treatment"]}},
    }
    valid = json.loads(json.dumps(invalid))
    valid["options"][0]["proposal"]["changes"]["model_params"]["y"] = "outcome"
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-profile",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-missing-y",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-with-y",
                "tool_id": "submit_notebook_option_batch",
                "arguments": valid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=context,
        initial_evidence=DataEvidencePackV1("dataset", ()),
    )

    assert len(result.option_drafts) == 1
    assert "model.genesis model_params must include evidence-backed y" in adapter.requests[2].messages[-1]["content"]


def test_provider_gets_exact_genesis_changes_envelope_after_invalid_fields(tmp_path: Path) -> None:
    upload_sha256 = "sha256:upload-changes"
    context = _context(
        make_project(tmp_path),
        projection_source={"kind": "dataset", "upload_sha256": upload_sha256},
    )
    genesis_preconditions = {
        "context_version": "node-operation-context/v1",
        "context_fingerprint": freshness_dependency_fingerprint(context),
        "owner_resolution": "single_candidate",
    }
    invalid = _submit_call()
    invalid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "operation_id": "model.genesis",
        "target": {"dataset_source_id": upload_sha256},
        "preconditions": genesis_preconditions,
        "changes": {"capability_id": "ols", "params": {"model_type": "ols"}},
    }
    valid = {"options": [dict(invalid["options"][0])]}
    valid["options"][0]["proposal"] = {
        **invalid["options"][0]["proposal"],
        "changes": {"model_params": {"model_type": "ols", "y": "outcome", "x": ["treatment"]}},
    }
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "profile.v1",
                            "target_ref": "dataset:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": valid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(context=context, initial_evidence=DataEvidencePackV1("dataset", ()))

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "model.genesis changes contain unknown field(s)" in correction
    assert "table_params" in correction
    assert "model_params" in correction
    assert "model_options" in correction


def test_provider_gets_correction_for_duplicate_executable_options(tmp_path: Path) -> None:
    duplicate = _submit_call()
    duplicate["options"].append(
        {
            **duplicate["options"][0],
            "rank": 2,
            "option_id": "opt_ets_duplicate",
        }
    )
    valid = _submit_call()
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": duplicate,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": valid,
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "duplicate executable proposals" in correction
    assert "fewer options" in correction


def test_provider_gets_correction_for_undeclarable_required_artifact(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["expected_artifacts"] = [
        {
            "artifact_id": "regression_summary",
            "artifact_type": "json",
            "required": True,
            "count": 1,
            "step": None,
        }
    ]
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "published artifact vocabulary" in correction
    assert "do not invent" in correction


def test_provider_gets_correction_for_missing_capability_result_artifact(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["expected_artifacts"] = []
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "capability required artifact(s) missing" in correction
    assert "ets_1" in correction


def test_provider_gets_bounded_correction_for_malformed_typed_fields(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["expected_artifacts"] = [{"artifact_id": "ts.parameters"}]
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "typed fields are invalid" in correction
    assert "not executed" in correction


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("assumptions", 7),
        ("comparative_claims", 7),
        ("rank", []),
        ("capability_id", []),
    ],
)
def test_provider_scalar_shape_errors_enter_bounded_correction(
    tmp_path: Path, field: str, value: object
) -> None:
    invalid = _submit_call()
    invalid["options"][0][field] = value
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert "not executed" in adapter.requests[2].messages[-1]["content"]


def test_provider_inspection_shape_errors_enter_bounded_correction(tmp_path: Path) -> None:
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-invalid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": 7,
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert "inspection target_ref" in adapter.requests[1].messages[-1]["content"]


def test_provider_rejects_unknown_nested_proposal_fields_with_correction(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["proposal"]["unexpected"] = "do not ignore"
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    assert "typed proposal fields" in adapter.requests[2].messages[-1]["content"]


def test_provider_contract_error_names_missing_and_unknown_proposal_fields(tmp_path: Path) -> None:
    invalid = _submit_call()
    invalid["options"][0]["proposal"].pop("proposal_revision")
    invalid["options"][0]["proposal"]["unexpected"] = "do not ignore"
    adapter = ScriptedAdapter(
        [
            {
                "tool_call_id": "inspect-valid",
                "tool_id": "request_notebook_inspections",
                "arguments": {
                    "requests": [
                        {
                            "inspection_id": "time_index.v1",
                            "target_ref": "run:active",
                            "arguments": {},
                        }
                    ]
                },
            },
            {
                "tool_call_id": "submit-invalid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": invalid,
            },
            {
                "tool_call_id": "submit-valid",
                "tool_id": "submit_notebook_option_batch",
                "arguments": _submit_call(),
            },
        ]
    )
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )

    result = agent.plan(
        context=_context(make_project(tmp_path)),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert len(result.option_drafts) == 1
    correction = adapter.requests[2].messages[-1]["content"]
    assert "missing proposal_revision" in correction
    assert "unknown unexpected" in correction


def test_run_execution_pins_include_the_registry_context_fingerprint(tmp_path: Path) -> None:
    context = replace(
        _context(make_project(tmp_path), active_head_run_id="run_001"),
        bounded_lineage=[
            {
                "node_id": "stage:model",
                "kind": "model",
                "node_hash": "node-hash",
                "forest_node_key": "forest-node-key",
                "context_fingerprint": "nocv1:active-model",
            }
        ],
    )

    pins = NotebookPlanningAgent._execution_pins(context)["rerun_preconditions"]

    assert pins["context_fingerprint"] == "nocv1:active-model"
    assert pins["context_fingerprint_by_node"] == {
        "stage:model": "nocv1:active-model"
    }


def test_model_rerun_registry_rejects_unknown_change_fields() -> None:
    definition = OperationRegistry().require("model.rerun", "v1")

    changes_schema = definition.proposal_schema["properties"]["changes"]
    assert all(branch["additionalProperties"] is False for branch in changes_schema["oneOf"])

    with pytest.raises(OperationValidationError, match="unknown field"):
        definition.validate(
            target={
                "run_id": "run_001",
                "node_ref": "stage:model",
                "node_hash": "node-hash",
                "forest_node_key": "forest-node-key",
            },
            preconditions={
                "context_version": "node-operation-context/v1",
                "context_fingerprint": "nocv1:active-model",
                "active_head_run_id": "run_001",
                "owner_resolution": "single_candidate",
            },
            changes={"capability": "ols"},
        )


def test_notebook_provider_tools_describe_typed_payloads() -> None:
    inspection_tool = NOTEBOOK_TOOLS[0]
    inspection_item = inspection_tool["input_schema"]["properties"]["requests"]["items"]

    assert inspection_item["additionalProperties"] is False
    assert set(inspection_item["required"]) == {
        "inspection_id",
        "target_ref",
        "arguments",
    }
    assert set(inspection_item["properties"]) == {
        "inspection_id",
        "target_ref",
        "arguments",
        "why_needed",
    }
    assert set(inspection_item["properties"]["inspection_id"]["enum"]) == {
        "profile.v1",
        "quality.v1",
        "time_index.v1",
        "sample.v1",
        "forecast_rolling_origin.v1",
    }

    submission_tool = NOTEBOOK_TOOLS[1]
    submission_item = submission_tool["input_schema"]["properties"]["options"]["items"]
    assert submission_item["additionalProperties"] is False
    assert {
        "rank",
        "rationale",
        "proposal",
        "evidence_refs",
        "comparative_claims",
        "capability_id",
        "option_id",
    }.issubset(submission_item["required"])
    assert submission_item["properties"]["proposal"]["properties"]["changes"]["additionalProperties"] is False
    assert "proposal_revision" in submission_item["properties"]["proposal"]["required"]


def test_provider_failure_is_not_replaced_by_fixed_model_paths(tmp_path: Path) -> None:
    with pytest.raises(NotebookPlanningUnavailable):
        NotebookPlanningAgent(adapter=FailingAdapter()).plan(
            context=_context(make_project(tmp_path)), initial_evidence=_evidence()
        )

    with pytest.raises(NotebookPlanningUnavailable, match="configured NotebookPlanningAgent"):
        generate_option_batch(notebook_id="nb_plan")


def test_text_only_completion_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(NotebookPlanningContractError, match="text-only"):
        NotebookPlanningAgent(adapter=TextOnlyAdapter()).plan(
            context=_context(make_project(tmp_path)), initial_evidence=_evidence()
        )


def test_unregistered_capability_is_rejected(tmp_path: Path) -> None:
    adapter = SequencedAdapter(_submit_call(capability_id="not_registered"))
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )
    with pytest.raises(NotebookPlanningUnavailable, match="not registered"):
        agent.plan(context=_context(make_project(tmp_path)), initial_evidence=DataEvidencePackV1("run:run_001", ()))


def test_run_source_proposal_must_be_rerun_child_of_active_head(tmp_path: Path) -> None:
    adapter = SequencedAdapter(_submit_call(run_id="other_run"))
    agent = NotebookPlanningAgent(
        adapter=adapter,
        capability_catalog={"time_series.ets": {}},
        inspection_executor=lambda requests, current: _evidence(),
    )
    with pytest.raises(NotebookPlanningContractError, match="rerun-child"):
        agent.plan(context=_context(make_project(tmp_path), active_head_run_id="run_001"), initial_evidence=DataEvidencePackV1("run:run_001", ()))
