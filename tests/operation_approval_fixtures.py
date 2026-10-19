"""Real shared approval records for isolated capability execution fixtures."""
from dataclasses import replace
from unittest.mock import patch
from workbench.agent.proposals import ProposalStore
from workbench.agent.execution import execution_key
from workbench.operation_approvals import OperationApprovalStore


def with_operation_approval(root, lease):
    proposals = ProposalStore(root / "workbench")
    proposal_id = "fixture_" + lease.authorization_id
    try:
        proposal = proposals.latest_revision(proposal_id)
    except KeyError:
        proposal = proposals.create(session_id="fixture_session", chain_id="fixture_chain",
            operation_id=lease.operation_id, target={"option_id":lease.option_id}, preconditions={},
            changes={"lease_payload":lease._payload()}, evidence_refs=[], expected_effect=[], risks=[], proposal_id=proposal_id)
    with patch("workbench.agent.proposals._now", lambda:lease.issued_at.isoformat()):
        confirmation = proposals.confirm(proposal_id, revision=proposal.revision, fingerprint=proposal.fingerprint,
            actor_type="user", current_context_fingerprint=None, current_active_head_run_id=None)
    approval = OperationApprovalStore(root / "workbench", clock=lambda:lease.issued_at).issue(confirmation)
    return replace(lease, approval_id=approval["approval_id"], approval_proposal_id=proposal_id,
        approval_fingerprint=proposal.fingerprint,
        approval_execution_key=execution_key(proposal_id=proposal_id, revision=proposal.revision, fingerprint=proposal.fingerprint))


def create_approved_operation(store, confirmation):
    from datetime import datetime, timezone
    confirmation = replace(confirmation, confirmed_at=datetime.now(timezone.utc).isoformat())
    record = store.create_pending(confirmation)
    approval = OperationApprovalStore(store.root).issue(confirmation)
    return store.append_status(record.record_id, record.status,
        execution={**record.execution, "approval_id":approval["approval_id"]})
