"""Typed, deterministic option planning producer."""

from __future__ import annotations

import pytest

from workbench.agent.context_compiler import compile_notebook_planning_context
from workbench.agent.notebook import OptionDraft, TypedProposal, generate_option_batch
from workbench.agent.notebook.evidence import DataEvidencePackV1
from workbench.agent.notebook.planning_agent import (
    NotebookPlanningContractError,
    NotebookPlanningUnavailable,
)
from tests.test_notebook_support import make_project, model_rerun_proposal


def test_option_producer_requires_typed_agent_context_and_evidence() -> None:
    with pytest.raises(NotebookPlanningUnavailable):
        generate_option_batch(notebook_id="nb_producer_test", count=3)


def test_option_producer_rejects_counts_outside_typed_batch_limit(tmp_path) -> None:
    context = compile_notebook_planning_context(
        make_project(tmp_path),
        notebook_id="nb_producer_test",
        run_family_id="family_producer_test",
        active_head_run_id=None,
        analysis_contract={"revision": 1},
        available_capabilities=["time_series.ets"],
    )
    with pytest.raises(NotebookPlanningContractError, match="between 1 and 3"):
        generate_option_batch(
            notebook_id="nb_producer_test",
            count=4,
            planner=object(),
            context=context,
            initial_evidence=DataEvidencePackV1("run:run_001", ()),
        )


def test_option_producer_delegates_to_injected_planner_without_rewriting_drafts(tmp_path) -> None:
    context = compile_notebook_planning_context(
        make_project(tmp_path),
        notebook_id="nb_producer_test",
        run_family_id="family_producer_test",
        active_head_run_id=None,
        analysis_contract={"revision": 1},
        available_capabilities=["time_series.ets"],
    )
    evidence = DataEvidencePackV1("run:run_001", ())
    draft = OptionDraft(
        rank=1,
        rationale="evidence-backed option",
        proposal=TypedProposal.from_dict(model_rerun_proposal("prop_producer")),
        option_id="opt_producer",
        capability_id="time_series.ets",
    )

    class Planner:
        def __init__(self) -> None:
            self.calls = []

        def plan(self, *, context, initial_evidence):
            self.calls.append((context, initial_evidence))
            return type("Result", (), {"option_drafts": (draft,)})()

    planner = Planner()
    result = generate_option_batch(
        notebook_id="nb_producer_test",
        count=3,
        planner=planner,
        context=context,
        initial_evidence=evidence,
    )

    assert result == (draft,)
    assert planner.calls == [(context, evidence)]
