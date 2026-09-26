"""v1.8.9 trust round — read-only analyses run at once; everything is recorded.

A workflow that only reads data runs without a confirmation click and hands
the model its results in the same turn. Anything that changes data or a model
still waits for the user. Every executed Agent operation enters the analysis
ledger, whoever authorized it.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from tests.test_agent_workflow_integration import IdleAdapter
from tests.test_data_column_cast import _source_project
from workbench import analysis_ledger
from workbench.agent import read_only_policy
from workbench.agent.chains import ChainStore
from workbench.agent.context_tools import NodeOperationContextProvider
from workbench.agent.core import AgentCore
from workbench.agent.events import AgentEventStream
from workbench.agent.orchestrator import WorkbenchOrchestrator
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

FINGERPRINT = "nocv1:read-only"


def _frame() -> pd.DataFrame:
    rng = np.random.default_rng(5)
    group = np.array(["a", "b"] * 30)
    return pd.DataFrame(
        {
            "wage": np.where(group == "a", 20.0, 23.0) + rng.normal(0, 2, 60).round(3),
            "group": group,
            "region": rng.choice(["north", "south", "west"], 60),
        }
    )


def _explore(step_id: str, column: str) -> dict:
    return {"step_id": step_id, "operation_id": "statistical.explore",
            "spec": {"operation": "tabulate", "selected_columns": [column], "options": {}}}


def _t_test(step_id: str) -> dict:
    return {"step_id": step_id, "operation_id": "test.t_tests",
            "spec": {"input_mode": "frame", "column_bindings": {"columns": ["wage", "group"]}, "options": {}}}


def _recode() -> dict:
    return {"step_id": "recode", "operation_id": "data.recode",
            "spec": {"column": "wage", "output": "high", "rules": [{"from": {"low": 0, "high": 22}, "to": 0}, {"from": "else", "to": 1}]}}


class _Fixture:
    def __init__(self, tmp_path: Path) -> None:
        self.project_root, self.run_id, self.artifact_id = _source_project(tmp_path, _frame())
        workbench_root = self.project_root / "workbench"
        self.repository = JsonlSessionRepository(workbench_root)
        self.repository.create_session("main-session", chain_id="project", role="main")
        self.repository.create_session("chain-session", chain_id="chain-a", role="chain")
        events = AgentEventStream(workbench_root)
        agent = AgentCore(self.repository, events, IdleAdapter(), session_id="chain-session")
        self.orchestrator = WorkbenchOrchestrator(
            self.repository, events, main_session_id="main-session",
            context_provider=NodeOperationContextProvider(self.project_root),
        )
        self.orchestrator.register_chain("chain-a", "chain-session", agent)
        ChainStore(workbench_root).create_root(
            chain_id="chain-a", run_family_id="family", active_head_run_id=self.run_id,
            agent_session_id="chain-session",
        )

        async def runner(proposal):
            record = self.orchestrator.confirm_proposal(
                proposal.proposal_id, revision=proposal.revision, fingerprint=proposal.fingerprint,
                actor_type=read_only_policy.ACTOR, current_context_fingerprint=FINGERPRINT,
                current_active_head_run_id=self.run_id,
            )
            return await self.orchestrator.execute_confirmed_operation(
                record.record_id, project_root=self.project_root,
                current_context_fingerprint=FINGERPRINT, current_active_head_run_id=self.run_id,
            )

        self.orchestrator.read_only_runner = runner

    def propose(self, steps: list[dict]):
        proposal = self.orchestrator.create_proposal(
            chain_id="chain-a",
            operation_id="operation.multi_step",
            target={"run_id": self.run_id, "node_ref": "stage:source", "artifact_id": self.artifact_id},
            preconditions={
                "context_version": "node-operation-context/v1",
                "context_fingerprint": FINGERPRINT,
                "active_head_run_id": self.run_id,
                "owner_resolution": "single_candidate",
            },
            changes={"steps": steps},
            evidence_refs=["profile:fixture"],
            expected_effect=["answer the question"],
            risks=[],
        )
        return asyncio.run(self.orchestrator._run_or_await_confirmation(proposal, session_id="chain-session"))


def test_a_read_only_workflow_runs_at_once_and_returns_its_results(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    receipt = fixture.propose([_explore("tab", "region"), _t_test("tt")])

    assert receipt["executed"] is True, receipt
    assert receipt["authorized_by"] == "read_only_policy"
    assert receipt["operation"]["status"] == "completed"
    by_step = {entry["step_id"]: entry for entry in receipt["results"]}
    [t_test] = by_step["tt"]["artifacts"][0]["result"]["results"]
    assert t_test["test_type"] == "welch_t_test" and t_test["p_value"] < 0.001
    assert t_test["effect"]["difference"] == pytest.approx(2.676, abs=1e-3)
    frequencies = by_step["tab"]["artifacts"][0]["result"]["frequencies"]
    assert sum(item["count"] for item in frequencies) == 60
    assert receipt["inferential_tests_run_this_session"] == 1

    [entry] = analysis_ledger.read(fixture.project_root)
    assert entry["authorized_by"] == "read_only_policy"
    assert entry["actor"] == "agent"
    assert entry["inferential_steps"] == 1
    assert entry["changes_data"] is False
    assert [step["category"] for step in entry["steps"]] == ["descriptive", "inferential"]


def test_a_workflow_that_changes_data_waits_for_the_user(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    receipt = fixture.propose([_recode(), _t_test("tt")])

    assert receipt["requires_confirmation"] is True
    assert "data_change" in receipt["confirmation_reason"]
    assert analysis_ledger.read(fixture.project_root) == []


def test_tests_past_the_session_budget_need_a_confirmation(tmp_path: Path, monkeypatch) -> None:
    fixture = _Fixture(tmp_path)
    monkeypatch.setattr(read_only_policy, "SESSION_INFERENTIAL_BUDGET", 2)
    assert fixture.propose([_t_test("t1"), _t_test("t2")])["executed"] is True

    receipt = fixture.propose([_t_test("t3")])
    assert receipt["requires_confirmation"] is True
    assert "already run 2 inferential tests" in receipt["confirmation_reason"]


def test_a_failed_run_is_reported_to_the_model_not_raised(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)

    async def broken(proposal):
        raise RuntimeError("context changed")

    fixture.orchestrator.read_only_runner = broken
    receipt = fixture.propose([_t_test("tt")])
    assert receipt["executed"] is False
    assert "context changed" in receipt["error"]


def test_without_a_runner_everything_waits_for_the_user(tmp_path: Path) -> None:
    fixture = _Fixture(tmp_path)
    fixture.orchestrator.read_only_runner = None
    assert fixture.propose([_t_test("tt")])["requires_confirmation"] is True


@pytest.mark.parametrize(
    ("operation_id", "category"),
    [
        ("statistical.explore", "descriptive"),
        ("test.t_tests", "inferential"),
        ("nonparametric.mann_whitney", "inferential"),
        ("diagnostics.breusch_pagan", "inferential"),
        ("model.genesis", "model"),
        ("model.joint_f_test", "inferential"),
        ("data.recode", "data_change"),
        ("statistical.derive_numeric", "data_change"),
        ("resample.smote", "data_change"),
        ("report.compose", "report"),
        ("metadata.edit", "metadata_change"),
    ],
)
def test_step_categories(operation_id: str, category: str) -> None:
    assert analysis_ledger.step_category(operation_id) == category


def test_every_registered_step_has_a_category() -> None:
    unclassified = [
        operation_id for operation_id in WORKFLOW_STEP_SPEC_CONTRACTS
        if analysis_ledger.step_category(operation_id) == "unclassified"
    ]
    assert unclassified == [], "classify new steps in workbench/analysis_ledger.py"


def test_a_step_that_produces_a_dataset_is_never_read_only() -> None:
    for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items():
        if contract.produces_dataset:
            assert analysis_ledger.step_category(operation_id) not in read_only_policy.READ_ONLY_CATEGORIES, operation_id



def test_choosing_columns_is_not_a_data_change_but_choosing_rows_is() -> None:
    columns_only = {"step_id": "cols", "operation_id": "data.subset", "spec": {"columns": ["wage", "group"]}}
    rows = {"step_id": "rows", "operation_id": "data.subset",
            "spec": {"columns": ["wage", "group"], "filters": [{"column": "wage", "op": "gt", "value": 20}]}}
    assert read_only_policy.decide("operation.multi_step", {"steps": [columns_only, _t_test("tt")]},
                                   prior_inferential_steps=0).allowed
    decision = read_only_policy.decide("operation.multi_step", {"steps": [rows, _t_test("tt")]}, prior_inferential_steps=0)
    assert not decision.allowed and "data_change" in decision.reason


def test_a_failed_provider_call_leaves_an_explanation_not_an_empty_reply() -> None:
    from workbench.agent.turn_messages import provider_failure_message

    assert "没有执行任何操作" in provider_failure_message("zh", "LLMUpstreamError")
    assert "nothing was run" in provider_failure_message("en", "LLMUpstreamError")


def test_many_workflows_on_one_run_do_not_break_the_next_one(tmp_path: Path) -> None:
    """Found live: after 20 post-estimation results had accumulated on a run,
    every further workflow failed after running, and so did the run detail."""

    from workbench.agent.workflow_runtime import MAX_PROJECTED_POST_ESTIMATION_RESULTS, collect_post_estimation_results

    fixture = _Fixture(tmp_path)
    for index in range(MAX_PROJECTED_POST_ESTIMATION_RESULTS + 2):
        receipt = fixture.propose([_t_test(f"t{index}")])
        assert receipt["executed"] is True and receipt["operation"]["status"] == "completed", (index, receipt)
    latest = collect_post_estimation_results(fixture.project_root, fixture.run_id, keep_latest=True)
    assert len(latest) == MAX_PROJECTED_POST_ESTIMATION_RESULTS


def test_identical_rows_are_kept_as_observations(tmp_path: Path) -> None:
    """Found live: a women-only subset with three columns had 24 distinct
    combinations among 176 respondents; the run dropped 152 of them as
    'duplicates' and refused the logit for too small a sample."""

    import json

    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    rng = np.random.default_rng(9)
    frame = pd.DataFrame({"union": rng.binomial(1, 0.3, 176), "education": rng.integers(9, 21, 176), "female": 1})
    source = tmp_path / "women.csv"
    frame.to_csv(source, index=False)
    root = create_project(tmp_path, "p").root
    outcome = run_workflow(root, [source], mode="auto", model_type="logit", y="union", x=["education"])
    assert outcome["status"] == "completed", outcome
    run_root = root / "runs" / outcome["run_id"]
    [result] = [item for item in analysis_ledger_read_models(run_root)]
    assert result["nobs"] == 176
    issues = json.loads((run_root / "errors.json").read_text())["issues"]
    assert any(issue["code"] == "DUPLICATE_ROWS_KEPT" for issue in issues)


def analysis_ledger_read_models(run_root: Path) -> list[dict]:
    from workbench.services.results_service import read_model_results

    return [item for item in read_model_results(run_root) if not str(item.get("model_id", "")).startswith("diagnostics")]
