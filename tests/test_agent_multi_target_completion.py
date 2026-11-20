"""A question that asks for several estimands binds every one of them, each with its own evidence.

2026-11-06 risk review, finding 10: "estimate both ATT and ATE and compare them" bound two
estimands, but the completion contract held one target and the check required set equality,
so no plan could be saved (omitting target, ATT or ATE alone all refused) and the task stayed
partial however much work was done.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from jsonschema import Draft202012Validator

from tests.test_agent_completion import api, capability_result, checked_question, operation_record, question_contract
from tests.test_data_column_cast import _source_project
from tests.test_read_only_analysis import _Fixture
from workbench.agent.completion import CONTRACT_SCHEMA
from workbench.agent.completion_targets import contract_targets, target_estimands
from workbench.agent.session import JsonlSessionRepository
from workbench.agent.task_requirements import RequirementBinder, enforce, human_revision
from workbench.agent.workflow import WorkflowExecutor, compile_workflow
from workbench.agent.workflow_runtime import build_workflow_step_executor

ATT = {"estimand": "ATT", "outcome": "wage", "treatment": "group"}
ATE = {"estimand": "ATE", "outcome": "wage", "treatment": "group"}
ATC = {"estimand": "ATC", "outcome": "wage", "treatment": "group"}
REGION_ATT = {**ATT, "outcome": "region"}
MULTI_OUTCOME_REQUEST = "Estimate ATT for both wage and region."
SOURCE = {"run_id": "r", "artifact_id": "data", "sha256": "a" * 64}
REQUIRED = {"version": "agent.task-requirements/v1", "status": "verified", "scope": "question",
            "estimands": ["ATE", "ATT"], "sources": [{"kind": "user_message"}],
            "latest_request": {"kind": "user_message"}, "request_chain_sha256": "b" * 64, "cursor": None}


def _contract(**fields):
    return {"scope": "question", "playbooks": [], "source": SOURCE, **fields}


@pytest.mark.parametrize("fields,valid", [
    ({"target": ATT}, True),
    ({"targets": [ATT, ATE]}, True),
    ({"targets": [ATT, ATT]}, False),
    ({"targets": [ATT]}, False),
    ({"target": ATT, "targets": [ATT, ATE]}, False),
])
def test_the_contract_takes_one_target_or_a_list_of_distinct_targets(fields, valid):
    assert Draft202012Validator(CONTRACT_SCHEMA).is_valid(_contract(**fields)) is valid


def test_a_single_target_reads_as_a_list_of_one():
    assert contract_targets(_contract(target=ATT)) == [ATT]
    assert target_estimands(_contract(targets=[ATT, ATE])) == {"ATT", "ATE"}
    assert contract_targets(_contract()) == []


@pytest.mark.parametrize("fields,unbound", [
    ({"targets": [ATT, ATE]}, False),
    ({"targets": [ATE, ATT]}, False),
    ({"target": ATT}, True),
    ({"targets": [ATT, ATC]}, True),
    ({}, True),
])
def test_requirements_need_every_requested_estimand(fields, unbound):
    checked = enforce({"scope": "question", "status": "requirements_met", "missing": [], **fields}, REQUIRED)
    assert ("target:requested_estimand_unbound" in checked["missing"]) is unbound


def test_a_request_naming_two_estimands_is_met_only_by_both():
    request = "Estimate both ATT and ATE and compare them."
    both = api().enforce_request_scope({"status": "requirements_met", "missing": [], "targets": [ATT, ATE]}, request)
    one = api().enforce_request_scope({"status": "requirements_met", "missing": [], "target": ATT}, request)
    assert both["missing"] == [] and "target:requested_estimand_unbound" in one["missing"]


def test_each_target_needs_its_own_bound_result(tmp_path):
    contract = {**question_contract(tmp_path), "targets": [ATT, ATE]}
    operation_record(tmp_path, "s1", outputs={"post_estimation_results": [capability_result(tmp_path)]})
    result = checked_question(tmp_path, contract)[0]
    assert result["status"] == "partial" and "target:computed_estimand_not_bound" in result["missing"]
    assert result["unbound_targets"] == [ATT, ATE] and result["targets"] == [ATT, ATE]


def _plan(tmp_path, completion_fields, request="Estimate both ATT and ATE and compare them."):
    runtime = _Fixture(tmp_path / "project")
    runtime.repository.append("chain-session", "message",
                              {"role": "user", "content": request})
    completion = {"scope": "question", "playbooks": [],
                  "source": {"run_id": runtime.run_id, "artifact_id": runtime.artifact_id}, **completion_fields}
    arguments = {"question": "Estimate both ATT and ATE and compare them.",
                 "steps": [{"step_id": "effects", "title": "Estimate effects", "operation_ids": ["statistical.explore"]}],
                 "completion": completion}
    result = asyncio.run(runtime.orchestrator.tool_registry("chain-a").execute(
        {"tool_call_id": "plan", "tool_id": "update_plan", "arguments": arguments}, session_id="chain-session"))
    return result.output


def test_a_plan_binding_both_requested_estimands_is_saved(tmp_path):
    output = _plan(tmp_path, {"targets": [
        {"estimand": "ATT", "outcome": "wage", "treatment": "group"},
        {"estimand": "ATE", "outcome": "wage", "treatment": "group"}]})
    assert output.get("saved") is not False and "error" not in output


@pytest.mark.parametrize("fields,message", [
    ({"targets": [{"estimand": "ATT", "outcome": "wage", "treatment": "group"},
                  {"estimand": "ATC", "outcome": "wage", "treatment": "group"}]}, "ATC was not requested"),
    ({"target": {"estimand": "ATT", "outcome": "wage", "treatment": "group"}}, "requested_estimand_unbound"),
])
def test_a_plan_narrowing_or_changing_the_requested_estimands_is_refused(tmp_path, fields, message):
    output = _plan(tmp_path, fields)
    assert output.get("saved") is False and message in output["error"]


def test_a_single_outcome_plan_is_refused_for_an_explicit_two_outcome_request(tmp_path):
    output = _plan(tmp_path, {"target": ATT}, request=MULTI_OUTCOME_REQUEST)
    assert output.get("saved") is False and "requested_estimand_unbound" in output["error"]


def test_a_plan_can_bind_the_two_outcomes_for_the_same_estimand(tmp_path):
    output = _plan(tmp_path, {"targets": [ATT, REGION_ATT]}, request=MULTI_OUTCOME_REQUEST)
    assert output.get("saved") is not False and "error" not in output


def test_missing_outcome_cannot_be_completed_by_a_result_for_the_same_estimand(tmp_path):
    rng = np.random.default_rng(7)
    x = rng.normal(size=80)
    group = (rng.uniform(size=80) < 1 / (1 + np.exp(-x))).astype(float)
    frame = pd.DataFrame({"x": x, "group": group, "wage": x + group + rng.normal(size=80),
                          "region": x - group + rng.normal(size=80)})
    project, run, data = _source_project(tmp_path, frame)
    target = {"run_id": run, "artifact_id": data, "node_ref": "stage:source"}
    source = api().source_receipt(project, target)
    steps = [{"step_id": name, "operation_id": "treatment_effects.estimate",
              "spec": {"input_mode": "frame", "column_bindings": {"treatment": "group", "outcome": name, "covariates": ["x"]},
                       "options": {"estimand": "ATT"}}} for name in ("wage", "region")]
    draft = compile_workflow(workflow_id="multi-outcome", target=target,
                             preconditions={"context_fingerprint": "wage-region"},
                             steps=steps, available_columns=list(frame.columns))
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == "completed", state.to_dict()
    refs = [{"run_id": run, "artifact_id": state.steps[step["step_id"]].artifact_ids[0]}
            for step in steps]
    base = {"scope": "question", "playbooks": [], "source": source}
    one = api().evaluate(project, {**base, "target": ATT}, {"results": refs[:1]})
    both_targets = {**base, "targets": [ATT, REGION_ATT]}
    incomplete = api().evaluate(project, both_targets, {"results": refs[:1]})
    both = api().evaluate(project, both_targets, {"results": refs})
    assert incomplete["status"] == "partial" and incomplete["unbound_targets"] == [REGION_ATT]
    assert one["status"] == both["status"] == "requirements_met"

    repository = JsonlSessionRepository(project / "workbench")
    repository.create_session("audit", chain_id="chain", role="chain")
    repository.append("audit", "message", {"role": "user", "content": MULTI_OUTCOME_REQUEST})
    requirement = RequirementBinder(repository).bind("audit", None)
    assert enforce(one, requirement)["status"] == "partial"
    assert enforce(both, requirement)["status"] == "requirements_met"
    assert api().enforce_request_scope(one, MULTI_OUTCOME_REQUEST)["status"] == "partial"
    assert api().enforce_request_scope(both, MULTI_OUTCOME_REQUEST)["status"] == "requirements_met"


def test_migration_recovers_outcomes_from_the_original_user_request(tmp_path):
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    repository.append("s", "message", {"role": "user", "content": MULTI_OUTCOME_REQUEST})
    previous = RequirementBinder(repository).bind("s", None)
    previous.pop("target_bindings", None)  # v1 snapshots written before outcome binding
    repository.append("s", "message", {"role": "user", "content": "Continue."})
    migrated = RequirementBinder(repository).bind("s", previous)

    completed = {"scope": "question", "status": "requirements_met", "missing": [], "target": ATT}
    assert enforce(completed, migrated)["status"] == "partial"


def test_migration_preserves_a_legacy_human_revision(tmp_path):
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    repository.append("s", "message", {"role": "user", "content": MULTI_OUTCOME_REQUEST})
    question = "Estimate ATT for wage."
    previous = human_revision(repository, "s", question, plan_id="plan", version=2,
                              changes={"question": question})
    previous.pop("target_bindings", None)
    repository.append("s", "message", {"role": "user", "content": "Continue."})
    migrated = RequirementBinder(repository).bind("s", previous)

    completed = {"scope": "question", "status": "requirements_met", "missing": [], "target": ATT}
    assert enforce(completed, migrated)["status"] == "requirements_met"


def test_explicit_treatment_controls_which_outcomes_match(tmp_path):
    request = "Estimate ATT for both `wage` and `region` using treatment column `group`."
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("s", chain_id="c", role="chain")
    repository.append("s", "message", {"role": "user", "content": request})
    requirement = RequirementBinder(repository).bind("s", None)
    completed = {"scope": "question", "status": "requirements_met", "missing": [],
                 "targets": [ATT, {**REGION_ATT, "treatment": "other_group"}]}
    assert enforce(completed, requirement)["status"] == "partial"
