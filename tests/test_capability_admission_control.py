from __future__ import annotations

import pytest

from test_capability_admission_contract import _adapter, _bundle


def _admission():
    from workbench.capability_factory.admission_contract import CapabilityAdmissionController

    adapter = _adapter()
    bundle = _bundle(adapter, independent=True, case_count=2)
    controller = CapabilityAdmissionController()
    assessment = controller.assess(
        adapter=adapter,
        validation_bundle=bundle,
        assessment_id="assessment.agent",
        assessment_rule_ref="c" * 64,
    )
    record = controller.propose(
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission_id="admission.agent",
        runtime_policy_ref="d" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=("report_projection",),
    )
    return controller, adapter, bundle, assessment, record


def test_agent_admission_is_high_risk_proposal_data_without_execution():
    from workbench.agent.admission_control import CapabilityAdmissionProposalControl

    _, adapter, bundle, assessment, record = _admission()
    proposal = CapabilityAdmissionProposalControl().create_proposal(record)

    assert proposal.status == "pending_confirmation"
    assert proposal.operation_id == "capability.admission.propose"
    assert proposal.risk_level == "high"
    assert proposal.execution_allowed is False
    assert proposal.source_eligible is False
    with pytest.raises(ValueError, match="confirmation"):
        proposal.risk_binding()

    confirmed = CapabilityAdmissionProposalControl().confirm(
        proposal,
        confirmation_ref="e" * 64,
    )
    assert confirmed.execution_allowed is False
    assert confirmed.risk_binding()["admission_ref"] == record.content_digest
    assert confirmed.risk_binding()["assessment_ref"] == assessment.content_digest
    assert confirmed.risk_binding()["adapter_ref"] == adapter.content_digest
    assert confirmed.risk_binding()["validation_bundle_ref"] == bundle.content_digest


def test_agent_admission_lifecycle_reuses_existing_stores_and_is_not_registered(tmp_path):
    from workbench.agent.admission_control import CapabilityAdmissionProposalControl
    from workbench.agent.operations import OperationRegistry, UnknownOperationError

    control = CapabilityAdmissionProposalControl()
    controller, _, _, _, record = _admission()
    proposal = control.create_proposal(record)
    stale_root = tmp_path / "stale"
    revision = control.persist_proposal(
        proposal,
        root=stale_root,
        session_id="session-admission",
        chain_id="chain-admission",
        active_head_run_id="run-1",
    )
    receipt = control.authorize_persisted_proposal(
        proposal,
        root=stale_root,
        revision=revision.revision,
        fingerprint=revision.fingerprint,
        actor_type="human_ui",
        current_context_fingerprint=proposal.content_digest,
        current_active_head_run_id="run-1",
    )
    assert receipt.confirmation.status == "confirmed"
    assert receipt.risk_authorization.status == "issued"
    assert receipt.execution_allowed is False
    admitted = control.complete_admission(
        admission_controller=controller,
        proposal=proposal,
        receipt=receipt,
        approver_ref="human_ui",
    )
    assert admitted.status == "admitted"
    assert receipt.risk_authorization.status == "issued"
    with pytest.raises(UnknownOperationError):
        OperationRegistry().require("capability.admission.propose", "v1")


def test_agent_admission_rejects_a_forged_or_stale_proposal(tmp_path):
    from dataclasses import replace

    from workbench.agent.admission_control import (
        CapabilityAdmissionProposalControl,
        CapabilityAdmissionControlError,
    )
    from workbench.agent.proposals import ProposalStaleError

    control = CapabilityAdmissionProposalControl()
    _, _, _, _, record = _admission()
    proposal = control.create_proposal(record)
    stale_root = tmp_path / "stale"
    revision = control.persist_proposal(
        proposal,
        root=stale_root,
        session_id="session-admission",
        chain_id="chain-admission",
        active_head_run_id="run-1",
    )
    with pytest.raises(ProposalStaleError):
        control.confirm_persisted_proposal(
            proposal,
            root=stale_root,
            revision=revision.revision,
            fingerprint=revision.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=proposal.content_digest,
            current_active_head_run_id="run-2",
        )
    forged_root = tmp_path / "forged"
    revision = control.persist_proposal(
        proposal,
        root=forged_root,
        session_id="session-admission",
        chain_id="chain-admission",
        active_head_run_id="run-1",
    )
    confirmation = control.confirm_persisted_proposal(
        proposal,
        root=forged_root,
        revision=revision.revision,
        fingerprint=revision.fingerprint,
        actor_type="human_ui",
        current_context_fingerprint=proposal.content_digest,
        current_active_head_run_id="run-1",
    )
    forged = replace(confirmation, fingerprint="f" * 64)
    with pytest.raises(CapabilityAdmissionControlError, match="risk grant"):
        control.issue_risk_authorization(
            forged,
            root=forged_root,
            current_active_head_run_id="run-1",
            actor_type="human_ui",
        )


def test_agent_completion_rejects_a_proposal_after_admission_record_changes(tmp_path):
    from workbench.agent.admission_control import CapabilityAdmissionProposalControl

    control = CapabilityAdmissionProposalControl()
    controller, _, _, _, record = _admission()
    proposal = control.create_proposal(record)
    root = tmp_path / "changed-record"
    revision = control.persist_proposal(
        proposal,
        root=root,
        session_id="session-admission",
        chain_id="chain-admission",
        active_head_run_id="run-1",
    )
    receipt = control.authorize_persisted_proposal(
        proposal,
        root=root,
        revision=revision.revision,
        fingerprint=revision.fingerprint,
        actor_type="human_ui",
        current_context_fingerprint=proposal.content_digest,
        current_active_head_run_id="run-1",
    )
    controller.admit(record.admission_id, approver_ref="another_approver", approval_ref="f" * 64)
    with pytest.raises(ValueError, match="current admission record"):
        control.complete_admission(
            admission_controller=controller,
            proposal=proposal,
            receipt=receipt,
            approver_ref="human_ui",
        )
