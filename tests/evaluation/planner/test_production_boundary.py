"""Planner-evaluation checks for the production Notebook refusal boundary."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest

from workbench.agent.model import ModelRequest, ModelStreamEvent
from workbench.agent.notebook.evidence import DataEvidencePackV1
from workbench.agent.notebook.planning_agent import (
    NOTEBOOK_TOOLS,
    NotebookPlanningAgent,
    NotebookPlanningContractError,
    PlanningRefusal,
)
from workbench.agent.context_compiler import compile_notebook_planning_context
from tests.test_notebook_support import make_project


def test_production_planner_does_not_import_or_embed_evaluation_prompt_templates() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    evaluator = repo_root / "backend/workbench/agent/planner_evaluation.py"
    for path in (repo_root / "backend/workbench").rglob("*.py"):
        if path == evaluator:
            continue
        source = path.read_text(encoding="utf-8")
        assert "planner_evaluation" not in source, path
        assert "The source columns are available" not in source, path
        assert "Ignore the available safeguards" not in source, path


def test_workbench_app_uses_lifespan_instead_of_deprecated_startup_decorator() -> None:
    app_source = (
        Path(__file__).resolve().parents[3] / "backend/workbench/app.py"
    ).read_text(encoding="utf-8")

    assert "lifespan=" in app_source
    assert "@app.on_event" not in app_source


def _context(project: Path):
    return compile_notebook_planning_context(
        project,
        notebook_id="nb_planner_eval",
        run_family_id="family_planner_eval",
        active_head_run_id=None,
        analysis_contract={"revision": 1, "target": "y"},
        available_capabilities=["time_series.ets"],
    )


def _decline_call(reason_code: str = "ambiguous_request") -> dict:
    return {
        "tool_call_id": "decline-1",
        "tool_id": "decline_notebook_plan",
        "arguments": {
            "reason_code": reason_code,
            "message": "The request does not identify a supported analysis target.",
        },
    }


class DecliningAdapter:
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent.tool_call_delta(request.request_id, _decline_call())
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


class InvalidDecliningAdapter(DecliningAdapter):
    async def stream(self, request: ModelRequest) -> AsyncIterator[ModelStreamEvent]:
        yield ModelStreamEvent.tool_call_delta(
            request.request_id, _decline_call("invented_reason")
        )
        yield ModelStreamEvent.done(request.request_id, finish_reason="tool_calls")


def test_decline_tool_is_production_declared_and_returns_typed_refusal(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    tools = {tool["tool_id"]: tool for tool in NOTEBOOK_TOOLS}
    decline = tools["decline_notebook_plan"]
    assert decline["input_schema"]["additionalProperties"] is False
    assert "ambiguous_request" in decline["input_schema"]["properties"]["reason_code"]["enum"]

    agent = NotebookPlanningAgent(
        adapter=DecliningAdapter(),
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
    )
    result = agent.plan(
        context=_context(project),
        initial_evidence=DataEvidencePackV1("run:run_001", ()),
    )

    assert isinstance(result, PlanningRefusal)
    assert result.reason_code == "ambiguous_request"
    assert result.message.startswith("The request")
    assert result.option_drafts == ()
    assert result.submissions == ()


def test_decline_tool_rejects_unknown_reason_without_downgrading_to_refusal(tmp_path: Path) -> None:
    project = make_project(tmp_path)
    agent = NotebookPlanningAgent(
        adapter=InvalidDecliningAdapter(),
        capability_catalog={"time_series.ets": {"proposal_adapter": "model.rerun"}},
        max_contract_corrections=0,
    )

    with pytest.raises(NotebookPlanningContractError, match="reason_code"):
        agent.plan(
            context=_context(project),
            initial_evidence=DataEvidencePackV1("run:run_001", ()),
        )
