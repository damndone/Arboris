from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest


def _requirement(contracts):
    return contracts.DependencyRequirement(
        distribution="safe-library",
        version="1.2.3",
        artifact_digest="a" * 64,
        python_tag="py3",
        platform_tag="macosx_14_0_arm64",
        index_origin="https://packages.example.test/simple",
    )


def test_dependency_lock_is_immutable_and_content_addressed():
    from workbench.capability_factory import dependency_contract as contracts

    requirement = _requirement(contracts)
    lock = contracts.DependencyLock(
        lock_id="lock.alpha",
        revision=1,
        requirements=(requirement,),
        resolver_policy_digest="b" * 64,
        python_version="3.14.6",
        operating_system="darwin",
        architecture="arm64",
    )
    same_lock = contracts.DependencyLock(
        lock_id="lock.alpha",
        revision=1,
        requirements=(requirement,),
        resolver_policy_digest="b" * 64,
        python_version="3.14.6",
        operating_system="darwin",
        architecture="arm64",
    )

    assert lock.content_digest == same_lock.content_digest
    with pytest.raises(FrozenInstanceError):
        lock.revision = 2
    with pytest.raises(FrozenInstanceError):
        lock.requirements += (requirement,)


@pytest.mark.parametrize(
    "changes",
    [
        {"version": "^1.2"},
        {"artifact_digest": "not-a-digest"},
        {"index_origin": "file:///tmp/local"},
        {"distribution": "../../unsafe"},
    ],
)
def test_dependency_requirement_rejects_mutable_or_unsafe_references(changes):
    from workbench.capability_factory import dependency_contract as contracts

    values = {
        "distribution": "safe-library",
        "version": "1.2.3",
        "artifact_digest": "a" * 64,
        "python_tag": "py3",
        "platform_tag": "macosx_14_0_arm64",
        "index_origin": "https://packages.example.test/simple",
    }
    values.update(changes)
    with pytest.raises(contracts.DependencyContractError):
        contracts.DependencyRequirement(**values)


def test_bundle_admission_keeps_validity_and_scope_explicit():
    from workbench.capability_factory import dependency_contract as contracts

    admission = contracts.BundleAdmission(
        bundle_ref="c" * 64,
        status="quarantined",
        scope="project",
        validity_ref="d" * 64,
        reason_code="awaiting_offline_validation",
    )

    assert admission.status == "quarantined"
    assert admission.scope == "project"
    assert admission.content_digest
