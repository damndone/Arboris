"""Typed provider loop tests with deterministic fake adapters."""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import pytest

from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.agent.notebook.evidence import DataEvidencePackV1, EvidenceRecord, InspectionRequest
from workbench.agent.notebook.planning_agent import (
    NOTEBOOK_TOOLS,
    NotebookPlanningAgent,
    NotebookPlanningContractError,
    NotebookPlanningUnavailable,
)
from workbench.agent.notebook.producer import generate_option_batch
from workbench.agent.context_compiler import compile_notebook_planning_context
from workbench.agent.notebook.proposal import TypedProposal
from tests.test_notebook_support import make_project


def _context(project: Path, *, active_head_run_id: str | None = None):
    return compile_notebook_planning_context(
        project,
        notebook_id="nb_plan",
        run_family_id="family_plan",
        active_head_run_id=active_head_run_id,
        analysis_contract={"revision": 1, "target": "y"},
        available_capabilities=["time_series.ets"],
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
                observations={"candidate_column": "when"},
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
                    "target": {"run_id": run_id, "node_ref": "stage:model"},
                    "preconditions": {},
                    "changes": {"model_options": {"model_type": "ets"}},
                },
                "expected_artifacts": [],
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
    assert len(adapter.requests) == 2


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
