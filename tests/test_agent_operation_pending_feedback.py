"""Recorded rerun reads stay closed while their parent receipt is nonterminal."""
from __future__ import annotations

from dataclasses import replace
import json

import pytest

from tests.test_agent_context_tools import _load_provider_type, _write_project_run
from workbench.agent.context_tools_support.requests import InspectOperationArtifactRequest
from workbench.agent import operation_records
from workbench.agent.tools import ToolVisibleError


# Public request/record metadata from the two v6-r30 leverage Auto refusals;
# no task text, observation data, model answers or scoring material is used.
RUN = "20261029_210515_767950_7a54c524"
SESSION = "agent_chain_9a9b324c5fcb4cc38cf857c9d442178a"
CHAIN = "run:" + RUN
RECORDED = [
    ("oprec_d0673fbca42463ad046a0d42", "20261029_210823_279799_fee47759"),
    ("oprec_e2ac94c4fe8255a87f0ce25f", "20261029_211034_240688_8996d47e"),
]
GENERIC = ("OPERATION_RESULT_NOT_IN_SCOPE: the completed operation is not "
           "available in this Chain and node scope.")


def _recorded_read(tmp_path, recorded, *, change=None):
    root = tmp_path / "project"
    record_id, child_run = recorded
    _write_project_run(root, run_id=RUN)
    _write_project_run(root, run_id=child_run)
    record = operation_records.OperationRecord(
        record_id=record_id, operation_id="model.rerun", operation_version="v1",
        proposal_id="recorded-proposal", proposal_revision=1, proposal_fingerprint="recorded-fingerprint",
        agent_session_id=SESSION, chain_id=CHAIN, command_id="recorded-command",
        target={"run_id": RUN, "node_ref": "model:ols_1"}, preconditions={},
        actor_type="agent", status="running", confirmation={},
        execution={"bindings": {"child_run_id": child_run}},
        outputs={"status": "running", "target_run_id": child_run},
        created_at="2026-10-29T21:08:23+00:00", updated_at="2026-10-29T21:08:24+00:00",
    )
    if change:
        record = replace(record, **change)
    store = operation_records.OperationRecordStore(root / "workbench")
    path = store.records_dir / (record_id + ".jsonl")
    path.write_text(json.dumps(record.to_dict()) + "\n")
    request = InspectOperationArtifactRequest(
        request_id="recorded-read", owner_run_id=RUN, op_node_id="model:ols_1",
        active_head_run_id=RUN, operation_record_id=record_id, artifact_id="ols_1",
    )
    return root, path, request


@pytest.mark.parametrize("recorded", RECORDED, ids=[row[0] for row in RECORDED])
def test_recorded_running_parent_reports_persisted_state_without_reading_artifact(tmp_path, monkeypatch, recorded):
    root, path, request = _recorded_read(tmp_path, recorded)
    before = path.read_bytes()
    from workbench.agent.context_tools_support import workflow_results
    def forbidden(*args):
        pytest.fail("an unfinished parent receipt cannot authorize artifact reading")
    monkeypatch.setattr(workflow_results, "_resolve_operation_artifact", forbidden)
    with pytest.raises(ToolVisibleError, match="OPERATION_RESULT_NOT_COMPLETED") as caught:
        _load_provider_type()(root).inspect_operation_artifact(request, chain_id=CHAIN, session_id=SESSION)
    message = str(caught.value)
    assert "last persisted status: running" in message
    assert "no completed operation receipt" in message
    assert "does not prove a process is running" in message
    assert "Do not automatically rerun" in message
    assert "reconcile" in message and "human" in message
    assert path.read_bytes() == before


@pytest.mark.parametrize("change", [
    {"agent_session_id": "private-session"},
    {"chain_id": "private-chain"},
    {"target": {"run_id": "private-run", "node_ref": "model:ols_1"}},
    {"target": {"run_id": RUN, "node_ref": "model:private"}},
    {"workflow_step_id": "private-child-step"},
])
def test_nonterminal_status_is_not_disclosed_outside_existing_record_scope(tmp_path, change):
    root, path, request = _recorded_read(tmp_path, RECORDED[0], change=change)
    before = path.read_bytes()
    with pytest.raises(ToolVisibleError) as caught:
        _load_provider_type()(root).inspect_operation_artifact(request, chain_id=CHAIN, session_id=SESSION)
    assert str(caught.value) == GENERIC
    assert path.read_bytes() == before


def test_failed_parent_keeps_the_existing_unavailable_result_refusal(tmp_path):
    root, path, request = _recorded_read(tmp_path, RECORDED[0], change={"status": "failed"})
    before = path.read_bytes()
    with pytest.raises(ToolVisibleError) as caught:
        _load_provider_type()(root).inspect_operation_artifact(request, chain_id=CHAIN, session_id=SESSION)
    assert str(caught.value) == GENERIC
    assert path.read_bytes() == before


@pytest.mark.parametrize("target", [
    {"run_id": "other-owned-run", "node_ref": "model:ols_1"},
    {"run_id": RUN, "node_ref": "stage:cleaned"},
])
def test_completed_owned_parent_keeps_its_existing_exact_scope_correction(tmp_path, target):
    root, path, request = _recorded_read(tmp_path, RECORDED[0], change={
        "status": "completed", "target": target,
        "outputs": {"status": "completed", "target_run_id": RECORDED[0][1]},
    })
    before = path.read_bytes()
    with pytest.raises(ToolVisibleError) as caught:
        _load_provider_type()(root).inspect_operation_artifact(request, chain_id=CHAIN, session_id=SESSION)
    message = str(caught.value)
    assert message.startswith(GENERIC)
    assert (f"call again with owner_run_id {target['run_id']}, op_node_id {target['node_ref']} "
            f"and operation_record_id {request.operation_record_id}.") in message
    assert "NOT_COMPLETED" not in message and "last persisted status" not in message
    assert path.read_bytes() == before
