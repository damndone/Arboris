"""Persisted workflow ledger counts honor the reported number of groups."""
import pytest
from workbench import analysis_ledger
from workbench.agent.operations import OperationRecord
from workbench.agent.orchestrator import _record_operation_in_ledger
from workbench.projects import create_project


@pytest.mark.parametrize("k", [2, 7, 50])
@pytest.mark.parametrize("state_shape", ["list", "mapping"])
def test_grouped_workflow_increments_persisted_ledger_by_k(tmp_path, k, state_shape):
    project = create_project(tmp_path, "ledger")
    before = analysis_ledger.inferential_count(analysis_ledger.read(project.root))
    step = {"step_id": "s1", "operation_id": "test.t_tests", "row_counts": {"ledger_count": k},
            "result": {"by_group": {"column": "region", "estimated_groups": k}}}
    record = OperationRecord(
        record_id="eval-count", operation_id="operation.multi_step", operation_version="v1",
        proposal_id="p1", proposal_revision=1, proposal_fingerprint="f1", agent_session_id="eval-session",
        chain_id="eval-chain", command_id=None, target={}, preconditions={}, actor_type="read_only_policy",
        status="completed", confirmation={}, changes={"steps": [{"step_id": "s1", "operation_id": "test.t_tests",
                                                                  "spec": {"by_group": "region"}}]},
        outputs={"workflow_state": {"steps": [step] if state_shape == "list" else {"s1": step}}})
    _record_operation_in_ledger(project.root, record)
    entries = analysis_ledger.read(project.root)
    assert analysis_ledger.inferential_count(entries) - before == k
    assert entries[-1]["inferential_steps"] == k
