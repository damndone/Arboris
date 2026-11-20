"""A completion source named by its dataset node binds that node's registered dataset.

2026-11-08 NVIDIA positions (binary_logit open.r3, specific.r1): update_plan named the source
"stage:cleaned"; it was refused as "not a registered dataset; name the cleaned dataset (for
example artifact_id cleaned_dataset)" and resent, one request each time. The graph node owns the
payload reference, so the binding is exact; a name that is no dataset node is still refused.
"""
from __future__ import annotations

import asyncio

from tests.test_read_only_analysis import _Fixture
from workbench.data_operations.casts import dataset_node_artifact_id

QUESTION = "Please run a full analysis of the outcome."


def _plan(runtime, artifact_id):
    arguments = {"question": QUESTION, "steps": [{"step_id": "explore", "title": "Explore",
                                                  "operation_ids": ["statistical.explore"]}],
                 "completion": {"scope": "question", "playbooks": [],
                                "source": {"run_id": runtime.run_id, "artifact_id": artifact_id}}}
    return asyncio.run(runtime.orchestrator.tool_registry("chain-a").execute(
        {"tool_call_id": "plan", "tool_id": "update_plan", "arguments": arguments}, session_id="chain-session"))


def test_the_node_resolves_to_its_registered_artifact_without_reading_data(tmp_path):
    runtime = _Fixture(tmp_path / "project")
    assert dataset_node_artifact_id(runtime.project_root, runtime.run_id, "stage:source") == runtime.artifact_id
    assert dataset_node_artifact_id(runtime.project_root, runtime.run_id, "stage:missing") is None
    assert dataset_node_artifact_id(runtime.project_root, "../outside", "stage:source") is None


def test_update_plan_binds_a_source_named_by_its_node(tmp_path):
    runtime = _Fixture(tmp_path / "project")
    runtime.repository.append("chain-session", "message", {"role": "user", "content": "What is the mean outcome?"})
    result = _plan(runtime, "stage:source")
    assert result.ok and result.output.get("saved") is not False, result.output
    plan = runtime.orchestrator.plan_store.current("chain-session")
    assert plan.completion["source"]["artifact_id"] == runtime.artifact_id
    assert len(plan.completion["source"]["sha256"]) == 64


def test_a_name_that_is_no_dataset_node_is_still_refused(tmp_path):
    runtime = _Fixture(tmp_path / "project")
    runtime.repository.append("chain-session", "message", {"role": "user", "content": "What is the mean outcome?"})
    result = _plan(runtime, "stage:cleaned")
    assert result.output.get("saved") is False and "not a registered dataset" in result.output["error"]
