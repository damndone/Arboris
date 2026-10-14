"""After a confirmed proposal runs, the Agent is told what it produced."""
from __future__ import annotations

import json

from workbench.agent.operation_outcome import identical_runs, outcome, outcome_text, produced_run
from workbench.agent.session import JsonlSessionRepository


def run(root, run_id, node_hash, covariance):
    path = root / "runs" / run_id
    (path / "model_results").mkdir(parents=True)
    (path / "node_index.json").write_text(json.dumps({"stage:raw": {"node_hash": "raw"}, "model:ols_1": {"node_hash": node_hash}}))
    (path / "model_results" / "ols_1.json").write_text(json.dumps({"covariance": covariance, "covariance_estimator": {"robust": "HC1", "unadjusted": "nonrobust"}[covariance]}))


RECORD = {
    "record_id": "oprec_1", "operation_id": "model.rerun", "proposal_id": "proposal_1", "status": "completed",
    "outputs": {"status": "completed", "target_run_id": "r3"},
    "execution": {"bindings": {"child_run_id": "r3"}},
}


def test_the_produced_run_and_an_identical_earlier_run_are_named(tmp_path):
    run(tmp_path, "r1", "h-robust", "robust")
    run(tmp_path, "r2", "h-unadjusted", "unadjusted")
    run(tmp_path, "r3", "h-unadjusted", "unadjusted")
    assert produced_run(RECORD) == "r3"
    assert identical_runs(tmp_path, "r3") == {"model:ols_1": ["r2"]}
    text = outcome_text(outcome(tmp_path, RECORD))
    assert "executed it: status completed" in text and "It produced run r3" in text
    assert "covariance unadjusted (nonrobust)" in text
    assert "already existed in run(s) r2" in text and "result is not new" in text
    assert "inspect_project_model_coefficients using run_ids [r3]" in text
    assert "Do not say you could not execute it" in text


def test_a_new_result_is_not_called_a_duplicate_and_a_failure_says_so(tmp_path):
    run(tmp_path, "r1", "h-robust", "robust")
    run(tmp_path, "r3", "h-hc3", "robust")
    assert "already existed" not in outcome_text(outcome(tmp_path, RECORD))
    failed = outcome_text(outcome(tmp_path, {**RECORD, "status": "failed", "outputs": {}, "execution": {},
                                             "error": {"code": "FIT_FAILED"}}))
    assert "status failed" in failed and "FIT_FAILED" in failed and "produced run" not in failed


def test_the_confirm_route_leaves_the_outcome_in_the_conversation(tmp_path):
    from workbench.http.agent_routes import _tell_agent_the_outcome

    run(tmp_path, "r3", "h-unadjusted", "unadjusted")
    repository = JsonlSessionRepository(tmp_path / "workbench")
    repository.create_session("agent_chain_s", chain_id="chain:r1", role="chain")
    _tell_agent_the_outcome(tmp_path, "agent_chain_s", RECORD)
    entry = repository.get_branch("agent_chain_s")[-1]
    assert entry.payload["name"] == "workbench_operation_result" and entry.payload["audience"] == "model"
    assert "It produced run r3" in entry.payload["content"] and entry.payload["metadata"]["produced_run_id"] == "r3"
