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
