"""Offline public-entry parity and exact CF4 receipt recovery."""
from types import SimpleNamespace
import json
import pytest

from tests.test_notebook_capability_binding import _service_with_catalog, _server_decision
from tests.test_capability_notebook_binding import _exploration_draft
from tests.test_notebook_routes import make_project
from workbench.agent.notebook.errors import OptionExecutionGatewayUnavailable
from workbench.agent.notebook.capability_adapter import prepare_operation
from workbench.capability_factory.notebook_bridge import NotebookExecutionDispatch
from workbench.agent.operations import OperationRecordStore
from workbench.operation_approvals import OperationApprovalStore


def _case(tmp_path, monkeypatch):
    project = make_project(tmp_path, name="project.alpha")
    service, notebook, binding, _ = _service_with_catalog(project)
    context = service.compile_context(notebook.notebook_id)
    decision = _server_decision(service, notebook, context, option_id="opt_exploration",
        decision_id="rec_exploration", batch_id="batch_exploration")
    (revision,) = service.propose_batch(notebook.notebook_id, context=context,
        drafts=[_exploration_draft(capability_id="capability.registered")],
        batch_id=decision.batch_id, recommendation_decision=decision)
    service.record_decision(notebook.notebook_id, revision.option_id, decision="selected", actor="user")
    materialization = SimpleNamespace(materialization_id="mat", option_id=revision.option_id,
        option_revision=revision.option_revision, capability_resolution_binding_ref=binding.content_digest,
        draft_id="draft", draft_hash="sha256:" + "d"*64)
    draft = SimpleNamespace(draft={"draft_id":"draft", "graph":{"nodes":[]}}, draft_hash=materialization.draft_hash)
    monkeypatch.setattr(service.store, "read_materialization", lambda *args:materialization)
    def materialize(*args, **kwargs):
        view = service.store.read_option(notebook.notebook_id, revision.option_id)
        if view.lifecycle_status == "selected":
            service._transition(notebook.notebook_id, view, to_status="materialized", actor="system", reason="test")
        return SimpleNamespace(materialization=materialization, draft=draft)
    monkeypatch.setattr(service, "materialize_option", materialize)
    calls = []
    class Gateway:
        def dispatch(self, **kwargs):
            lease = kwargs["authorization"]
            approval = OperationApprovalStore(project / "workbench").read(lease.approval_id)
            assert approval["fingerprint"] == lease.approval_fingerprint
            assert approval["status"] == "claimed"
            calls.append(lease)
            return NotebookExecutionDispatch(authorization_id=lease.authorization_id,
                run_intent_id=lease.run_intent_id, status="running", run_id="run_fixture",
                attempt_id="attempt_fixture", receipt_ref="a"*64)
    service.execution_gateway = Gateway()
    return service, notebook, revision, context, calls


@pytest.mark.parametrize("entry", ["notebook", "agent"])
def test_entry_points_share_project_deny_before_materialization(tmp_path, monkeypatch, entry):
    service, notebook, revision, context, calls = _case(tmp_path, monkeypatch)
    root = service.project_root / "workbench"
    root.mkdir(exist_ok=True)
    (root / "agent-permissions.json").write_text(json.dumps({"deny":[{"class":"analyze"}]}))
    with pytest.raises(PermissionError, match="denies"):
        if entry == "notebook":
            service.confirm_and_execute(notebook.notebook_id, revision.option_id, context=context)
        else:
            from workbench.agent.session import JsonlSessionRepository
            from workbench.agent.events import AgentEventStream
            from workbench.agent.orchestrator import WorkbenchOrchestrator
            from workbench.agent.notebook.agent_bridge import publish_option
            repository = JsonlSessionRepository(root)
            repository.create_session("main", chain_id="project", role="main")
            orchestrator = WorkbenchOrchestrator(repository, AgentEventStream(root), main_session_id="main",
                operation_registry=service.registry)
            proposal = publish_option(service, orchestrator, session_id="main",
                notebook_id=notebook.notebook_id, revision=revision)
            orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
                fingerprint=proposal.fingerprint, actor_type="user",
                current_context_fingerprint=proposal.preconditions.get("context_fingerprint"),
                current_active_head_run_id=proposal.preconditions.get("active_head_run_id"))
    assert not calls
    assert service.store.read_option(notebook.notebook_id, revision.option_id).lifecycle_status == "selected"


@pytest.mark.parametrize("revoke_after_dispatch", [False, True])
def test_capability_dispatch_uses_one_approval_and_restart_reads_original_receipt(tmp_path, monkeypatch, revoke_after_dispatch):
    service, notebook, revision, context, calls = _case(tmp_path, monkeypatch)
    orchestrator, record = prepare_operation(service, notebook.notebook_id, revision.option_id)
    approval_id = record.execution["approval_id"]
    dispatch = service.confirm_and_execute(notebook.notebook_id, revision.option_id,
        context=context, operation_record=record)
    assert len(calls) == 1 and calls[0].approval_id == approval_id
    assert dispatch.status == "running"
    current = OperationRecordStore(service.project_root / "workbench").get(record.record_id)
    assert current.outputs["capability_dispatch"] == dispatch.to_dict()
    if revoke_after_dispatch:
        OperationApprovalStore(service.project_root / "workbench").revoke(approval_id, actor_type="user")
    # A fresh controller recovers the actual persisted reply, without calling the gateway.
    import asyncio
    from workbench.agent.orchestrator import WorkbenchOrchestrator
    restarted = WorkbenchOrchestrator(orchestrator.repository, orchestrator.events,
        main_session_id=record.agent_session_id, operation_registry=service.registry)
    recovered = asyncio.run(restarted.execute_confirmed_operation(record.record_id,
        project_root=service.project_root, current_context_fingerprint=current.preconditions.get("context_fingerprint"),
        current_active_head_run_id=current.preconditions.get("active_head_run_id"),
        notebook_service=service, allow_recovery=True))
    assert recovered.outputs["capability_dispatch"] == dispatch.to_dict()
    assert recovered.execution["approval_id"] == approval_id
    assert len(calls) == 1


def test_revoked_capability_approval_does_not_materialize_or_dispatch(tmp_path, monkeypatch):
    service, notebook, revision, context, calls = _case(tmp_path, monkeypatch)
    _, record = prepare_operation(service, notebook.notebook_id, revision.option_id)
    OperationApprovalStore(service.project_root / "workbench").revoke(record.execution["approval_id"], actor_type="user")
    with pytest.raises(ValueError, match="revoked"):
        service.confirm_and_execute(notebook.notebook_id, revision.option_id, context=context, operation_record=record)
    assert not calls
    assert service.store.read_option(notebook.notebook_id, revision.option_id).lifecycle_status == "selected"


def test_expired_approval_does_not_start_capability_after_restart(tmp_path, monkeypatch):
    from datetime import datetime, timedelta
    import workbench.operation_approvals as approvals
    service, notebook, revision, context, calls = _case(tmp_path, monkeypatch)
    _, record = prepare_operation(service, notebook.notebook_id, revision.option_id)
    approval = OperationApprovalStore(service.project_root / "workbench").read(record.execution["approval_id"])
    after = datetime.fromisoformat(approval["expires_at"]) + timedelta(seconds=1)
    class Later(datetime):
        @classmethod
        def now(cls, tz=None):
            return after
    monkeypatch.setattr(approvals, "datetime", Later)
    with pytest.raises(ValueError, match="expired"):
        service.confirm_and_execute(notebook.notebook_id, revision.option_id, context=context, operation_record=record)
    assert not calls
    assert service.store.read_option(notebook.notebook_id, revision.option_id).lifecycle_status == "selected"
