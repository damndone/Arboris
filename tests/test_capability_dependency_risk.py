from __future__ import annotations

import pytest


def _lock():
    from workbench.capability_factory.dependency_contract import (
        DependencyLock,
        DependencyRequirement,
    )

    return DependencyLock(
        lock_id="lock.alpha",
        revision=1,
        requirements=(
            DependencyRequirement(
                distribution="safe-library",
                version="1.2.3",
                artifact_digest="a" * 64,
                python_tag="py3",
                platform_tag="macosx_14_0_arm64",
                index_origin="https://packages.example.test/simple",
            ),
        ),
        resolver_policy_digest="b" * 64,
        python_version="3.14.6",
        operating_system="darwin",
        architecture="arm64",
    )


def test_dependency_acquisition_is_a_high_risk_confirmation_binding_without_execution():
    from workbench.agent.dependency_control import DependencyAcquisitionControl

    proposal = DependencyAcquisitionControl().create_proposal(
        lock=_lock(),
        index_snapshot_ref="c" * 64,
        proposal_id="proposal_dependency_1",
    )

    assert proposal.status == "pending_confirmation"
    assert proposal.operation_id == "capability.dependency.acquire"
    assert proposal.risk_level == "high"
    assert proposal.confirmation_policy == "required"
    assert proposal.risk_authorization_policy == "explicit_single_use"
    assert proposal.user_data_access is False
    assert proposal.execution_allowed is False
    confirmed = DependencyAcquisitionControl().confirm(
        proposal,
        confirmation_ref="d" * 64,
    )
    binding = confirmed.risk_binding()
    assert binding["proposal_digest"] == proposal.content_digest
    assert binding["lock_ref"] == _lock().content_digest


def test_dependency_acquisition_requires_confirmation_before_risk_binding():
    from workbench.agent.dependency_control import (
        DependencyAcquisitionControl,
        DependencyControlError,
    )

    proposal = DependencyAcquisitionControl().create_proposal(
        lock=_lock(),
        index_snapshot_ref="c" * 64,
        proposal_id="proposal_dependency_2",
    )
    with pytest.raises(DependencyControlError):
        proposal.risk_binding()

    confirmed = DependencyAcquisitionControl().confirm(
        proposal,
        confirmation_ref="d" * 64,
    )
    assert confirmed.status == "confirmed"
    assert confirmed.confirmation_ref == "d" * 64
    assert confirmed.execution_allowed is False
    assert confirmed.risk_binding()["risk_level"] == "high"


def test_dependency_acquisition_cannot_skip_confirmation_or_change_lock_binding():
    from workbench.agent.dependency_control import (
        DependencyAcquisitionControl,
        DependencyControlError,
    )

    control = DependencyAcquisitionControl()
    with pytest.raises(DependencyControlError):
        control.confirm(
            control.create_proposal(
                lock=_lock(),
                index_snapshot_ref="c" * 64,
                proposal_id="proposal_dependency_3",
            ),
            confirmation_ref="not-a-digest",
        )


def test_dependency_lifecycle_uses_existing_proposal_and_risk_stores_without_execution(
    tmp_path,
):
    from workbench.agent.dependency_control import DependencyAcquisitionControl
    from workbench.agent.proposals import ProposalStore
    from workbench.agent.risk import RiskAuthorizationStore

    control = DependencyAcquisitionControl()
    proposal = control.create_proposal(
        lock=_lock(),
        index_snapshot_ref="c" * 64,
        proposal_id="proposal_dependency_durable",
    )
    revision = control.persist_proposal(
        proposal,
        root=tmp_path,
        session_id="session-dependency",
        chain_id="chain-dependency",
        active_head_run_id="run-1",
    )
    receipt = control.authorize_persisted_proposal(
        proposal,
        root=tmp_path,
        revision=revision.revision,
        fingerprint=revision.fingerprint,
        actor_type="human_ui",
        current_context_fingerprint=proposal.content_digest,
        current_active_head_run_id="run-1",
    )
    confirmation = receipt.confirmation
    grant = receipt.risk_authorization

    assert confirmation.status == "confirmed"
    assert grant.status == "issued"
    assert grant.operation_id == proposal.operation_id
    assert grant.proposal_id == proposal.proposal_id
    assert grant.fingerprint == revision.fingerprint
    assert receipt.proposal.status == "confirmed"
    assert receipt.execution_allowed is False
    assert RiskAuthorizationStore(tmp_path, create=False).read(grant.authorization_id)["status"] == "issued"
    assert ProposalStore(tmp_path, create=False).latest_status(proposal.proposal_id) == "confirmed"
    assert proposal.execution_allowed is False


def test_dependency_lifecycle_rejects_stale_confirmation_and_unregistered_execution_surface(
    tmp_path,
):
    from workbench.agent.dependency_control import DependencyAcquisitionControl
    from workbench.agent.operations import OperationRegistry, UnknownOperationError
    from workbench.agent.proposals import ProposalStaleError

    control = DependencyAcquisitionControl()
    proposal = control.create_proposal(
        lock=_lock(),
        index_snapshot_ref="c" * 64,
        proposal_id="proposal_dependency_stale",
    )
    revision = control.persist_proposal(
        proposal,
        root=tmp_path,
        session_id="session-dependency",
        chain_id="chain-dependency",
        active_head_run_id="run-1",
    )
    with pytest.raises(ProposalStaleError):
        control.confirm_persisted_proposal(
            proposal,
            root=tmp_path,
            revision=revision.revision,
            fingerprint=revision.fingerprint,
            actor_type="human_ui",
            current_context_fingerprint=proposal.content_digest,
            current_active_head_run_id="run-2",
        )

    with pytest.raises(UnknownOperationError):
        OperationRegistry().require("capability.dependency.acquire", "v1")


def test_dependency_risk_grant_requires_the_durable_confirmation_record(tmp_path):
    from dataclasses import replace

    from workbench.agent.dependency_control import (
        DependencyAcquisitionControl,
        DependencyControlError,
    )

    control = DependencyAcquisitionControl()
    proposal = control.create_proposal(
        lock=_lock(),
        index_snapshot_ref="c" * 64,
        proposal_id="proposal_dependency_forged_confirmation",
    )
    revision = control.persist_proposal(
        proposal,
        root=tmp_path,
        session_id="session-dependency",
        chain_id="chain-dependency",
        active_head_run_id="run-1",
    )
    confirmation = control.confirm_persisted_proposal(
        proposal,
        root=tmp_path,
        revision=revision.revision,
        fingerprint=revision.fingerprint,
        actor_type="human_ui",
        current_context_fingerprint=proposal.content_digest,
        current_active_head_run_id="run-1",
    )
    forged = replace(confirmation, fingerprint="e" * 64)

    with pytest.raises(DependencyControlError):
        control.issue_risk_authorization(
            forged,
            root=tmp_path,
            current_active_head_run_id="run-1",
            actor_type="human_ui",
        )
