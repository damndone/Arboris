"""One persistent approval authority for public operation entry points."""

from tests.operation_request_fixtures import admit_proposal
from datetime import datetime, timedelta, timezone
import pytest
from tests.test_agent_proposal_operations import make_orchestrator, proposal_kwargs


def _confirmed(tmp_path):
    orchestrator = make_orchestrator(tmp_path)
    proposal = admit_proposal(orchestrator, **proposal_kwargs())
    record = orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
        fingerprint=proposal.fingerprint, actor_type="user",
        current_context_fingerprint="ctx-1", current_active_head_run_id="run-1")
    return orchestrator, proposal, record


def test_common_confirmation_issues_one_approval_and_restart_keeps_it(tmp_path):
    from workbench.operation_approvals import OperationApprovalStore
    orchestrator, proposal, record = _confirmed(tmp_path)
    store = OperationApprovalStore(orchestrator.repository.root)
    approval = store.read(record.execution["approval_id"])
    assert approval["proposal_id"] == proposal.proposal_id
    assert approval["fingerprint"] == proposal.fingerprint
    key = orchestrator._operation_execution_key(record)
    claimed = store.claim(approval["approval_id"], execution_key=key)
    restarted = OperationApprovalStore(orchestrator.repository.root)
    assert restarted.claim(approval["approval_id"], execution_key=key) == claimed
    with pytest.raises(ValueError, match="execution"):
        restarted.claim(approval["approval_id"], execution_key="different")


def test_unclaimed_approval_expires_and_confirmation_retry_cannot_extend_it(tmp_path):
    from workbench.operation_approvals import OperationApprovalStore
    orchestrator, proposal, record = _confirmed(tmp_path)
    initial = OperationApprovalStore(orchestrator.repository.root).read(record.execution["approval_id"])
    after = datetime.fromisoformat(initial["expires_at"]) + timedelta(seconds=1)
    store = OperationApprovalStore(orchestrator.repository.root, clock=lambda:after)
    with pytest.raises(ValueError, match="expired"):
        store.claim(initial["approval_id"], execution_key="first")
    retry = orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
        fingerprint=proposal.fingerprint, actor_type="user",
        current_context_fingerprint="ctx-1", current_active_head_run_id="run-1")
    assert retry.execution["approval_id"] == initial["approval_id"]
    assert store.read(initial["approval_id"])["expires_at"] == initial["expires_at"]


@pytest.mark.parametrize("claimed", [False, True])
def test_revocation_survives_restart_and_blocks_new_dispatch(tmp_path, claimed):
    from workbench.operation_approvals import OperationApprovalStore
    orchestrator, _, record = _confirmed(tmp_path)
    store = OperationApprovalStore(orchestrator.repository.root)
    approval_id = record.execution["approval_id"]
    if claimed:
        store.claim(approval_id, execution_key="one")
    store.revoke(approval_id, actor_type="user")
    restarted = OperationApprovalStore(orchestrator.repository.root)
    with pytest.raises(ValueError, match="revoked"):
        restarted.claim(approval_id, execution_key="one")


def test_confirmation_obeys_current_project_deny_rule(tmp_path):
    import json
    orchestrator = make_orchestrator(tmp_path)
    root = orchestrator.repository.root
    (root / "agent-permissions.json").write_text(json.dumps({"deny":[{"class":"derive"}]}))
    proposal = admit_proposal(orchestrator, **proposal_kwargs())
    with pytest.raises(PermissionError, match="denies"):
        orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
            fingerprint=proposal.fingerprint, actor_type="user",
            current_context_fingerprint="ctx-1", current_active_head_run_id="run-1")
    assert orchestrator.proposal_store.latest_status(proposal.proposal_id) == "pending"


def test_capability_lease_without_common_approval_cannot_dispatch(tmp_path):
    from datetime import datetime, timezone
    from tests.test_capability_execution_authorization import _authorization
    from workbench.capability_factory.execution_authorization import OptionExecutionAuthorizationStore
    now = datetime.now(timezone.utc)
    lease = _authorization(now=now)
    store = OptionExecutionAuthorizationStore(tmp_path, clock=lambda:now)
    store.issue(lease)
    with pytest.raises(ValueError, match="approval"):
        store.claim(lease.authorization_id, idempotency_key=lease.idempotency_key,
            current_binding_ref=lease.capability_resolution_binding_ref,
            current_freshness_cursor_ref=lease.freshness_cursor_ref, owner_id="executor", lease_seconds=30)


def test_public_revocation_checks_session_and_rejects_execution(tmp_path):
    from fastapi.testclient import TestClient
    from workbench.app import app
    orchestrator, _, record = _confirmed(tmp_path)
    project = orchestrator.repository.root.parent
    with TestClient(app) as client:
        url = f"/agent/sessions/chain-session/operations/{record.record_id}/revoke-approval"
        response = client.post(url, params={"project_root":str(project)})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "revoked"
        forbidden = client.post(url.replace("chain-session", "main-session"), params={"project_root":str(project)})
        assert forbidden.status_code == 404
    from workbench.operation_approvals import OperationApprovalStore
    with pytest.raises(ValueError, match="revoked"):
        OperationApprovalStore(orchestrator.repository.root).claim(record.execution["approval_id"], execution_key="run")


@pytest.mark.parametrize("mutation", ["none", "revoked", "expired", "different_credential"])
def test_capability_credentials_share_common_approval_state_after_restart(tmp_path, mutation):
    from dataclasses import replace
    from tests.test_capability_execution_authorization import _authorization
    from tests.operation_approval_fixtures import with_operation_approval
    from workbench.capability_factory.execution_authorization import OptionExecutionAuthorizationStore
    from workbench.operation_approvals import OperationApprovalStore
    now = datetime.now(timezone.utc)
    lease = with_operation_approval(tmp_path, _authorization(now=now))
    store = OptionExecutionAuthorizationStore(tmp_path, clock=lambda:now)
    store.issue(lease)
    if mutation == "revoked":
        OperationApprovalStore(tmp_path / "workbench").revoke(lease.approval_id, actor_type="user")
    if mutation == "expired":
        now += timedelta(minutes=6)
        store = OptionExecutionAuthorizationStore(tmp_path, clock=lambda:now)
    if mutation in {"revoked", "expired"}:
        with pytest.raises(ValueError, match="revoked|expired"):
            store.require_operation_approval(lease)
        return
    store.require_operation_approval(lease)
    restarted = OptionExecutionAuthorizationStore(tmp_path, clock=lambda:now)
    if mutation == "different_credential":
        with pytest.raises(ValueError, match="credential"):
            restarted.require_operation_approval(replace(lease, draft_hash="sha256:" + "f"*64))
    else:
        restarted.require_operation_approval(lease)
        assert len(OperationApprovalStore(tmp_path / "workbench").read(lease.approval_id)["credential_digest"]) == 64


def test_auto_plan_and_project_allow_cannot_approve_high_risk(tmp_path):
    import json
    from workbench.agent.operations import OperationDefinition
    orchestrator = make_orchestrator(tmp_path)
    orchestrator.operation_registry.register(OperationDefinition(operation_id="test.high", risk_level="high"))
    arguments = {**proposal_kwargs(), "operation_id":"test.high"}
    proposal = admit_proposal(orchestrator, **arguments)
    orchestrator.execution_mode = "auto"
    orchestrator.plan_scope = {"in_plan":True, "named":True, "allowed_classes":["high"]}
    (orchestrator.repository.root / "agent-permissions.json").write_text(json.dumps({"allow":[{"class":"high"}]}))
    with pytest.raises(PermissionError, match="always needs"):
        orchestrator.confirm_proposal(proposal.proposal_id, revision=proposal.revision,
            fingerprint=proposal.fingerprint, actor_type="approved_plan",
            current_context_fingerprint="ctx-1", current_active_head_run_id="run-1")
    assert orchestrator.proposal_store.latest_status(proposal.proposal_id) == "pending"
    assert orchestrator.operation_store.list_records() == []


def test_proposal_revision_and_confirmation_bound_context_without_losing_audit(tmp_path):
    import json
    from workbench.agent.operations import OperationDefinition
    orchestrator = make_orchestrator(tmp_path)
    arguments = proposal_kwargs()
    full_text = "Full audit evidence. " * 4000
    orchestrator.operation_registry.register(OperationDefinition(operation_id="test.large"))
    proposal = admit_proposal(orchestrator, **{**arguments, "operation_id":"test.large",
        "changes":{"parameters":full_text}, "expected_effect":[full_text]})
    revised = orchestrator.revise_proposal(proposal.proposal_id, base_revision=proposal.revision,
        changes=proposal.changes, expected_effect=[full_text + " Revised."])
    orchestrator.confirm_proposal(revised.proposal_id, revision=revised.revision,
        fingerprint=revised.fingerprint, actor_type="user",
        current_context_fingerprint="ctx-1", current_active_head_run_id="run-1")
    entries = orchestrator.repository.get_branch("chain-session")
    assert len(entries) == 3
    for entry in entries:
        assert len(entry.payload["content"]) <= 24_000
        summary = json.loads(entry.payload["content"])
        assert summary["proposal_id"] == proposal.proposal_id
        assert "details_omitted" in summary
    assert entries[0].payload["proposal"]["expected_effect"] == [full_text]
    assert entries[1].payload["proposal"]["expected_effect"] == [full_text + " Revised."]
    assert entries[2].payload["confirmation"]["changes"]["parameters"] == full_text
