from __future__ import annotations

import pytest


def _budget():
    from workbench.native_containment.contracts import ResourceBudget

    return ResourceBudget(10_000, 8_000, 64 * 1024 * 1024, 8, 1_000_000, 100_000)


def test_strict_policy_is_deny_by_default():
    from workbench.native_containment.policy import ContainmentPolicy

    policy = ContainmentPolicy(
        profile_id="strict-readonly-v1",
        filesystem_mode="sealed_readonly",
        network_mode="disabled",
        process_mode="isolated",
        inherited_descriptors=False,
        dependency_tree_writable=False,
        environment_allowlist={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        locale="C.UTF-8",
        thread_count=1,
        budget=_budget(),
        allow_weaker_fallback=False,
    )
    assert policy.content_digest


def test_policy_rejects_weaker_fallback_and_writable_dependency_tree():
    from workbench.native_containment.policy import ContainmentPolicy, ContainmentPolicyError

    with pytest.raises(ContainmentPolicyError, match="read-only"):
        ContainmentPolicy(
            profile_id="strict-readonly-v1",
            filesystem_mode="sealed_readonly",
            network_mode="disabled",
            process_mode="isolated",
            inherited_descriptors=False,
            dependency_tree_writable=True,
            environment_allowlist={"LANG": "C.UTF-8"},
            locale="C.UTF-8",
            thread_count=1,
            budget=_budget(),
            allow_weaker_fallback=True,
        )


def _experimental_policy(**overrides):
    from workbench.native_containment.policy import ContainmentPolicy

    values = {
        "profile_id": "darwin-seatbelt-experimental-v1",
        "filesystem_mode": "sealed_readonly",
        "network_mode": "disabled",
        "process_mode": "isolated",
        "inherited_descriptors": False,
        "dependency_tree_writable": False,
        "environment_allowlist": {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        "locale": "C.UTF-8",
        "thread_count": 1,
        "budget": _budget(),
        "allow_weaker_fallback": False,
        "resource_enforcement": "observed_memory",
    }
    values.update(overrides)
    return ContainmentPolicy(**values)


def test_experimental_profile_requires_explicit_observed_memory_mode():
    policy = _experimental_policy()

    assert policy.resource_enforcement == "observed_memory"
    assert policy.content_digest


def test_experimental_profile_cannot_silently_use_hard_limits():
    from workbench.native_containment.policy import ContainmentPolicyError

    with pytest.raises(ContainmentPolicyError, match="observed_memory"):
        _experimental_policy(resource_enforcement="hard_limits")


def test_strict_profile_rejects_observed_memory_mode():
    from workbench.native_containment.policy import ContainmentPolicy, ContainmentPolicyError

    with pytest.raises(ContainmentPolicyError, match="hard_limits"):
        ContainmentPolicy(
            profile_id="strict-readonly-v1",
            filesystem_mode="sealed_readonly",
            network_mode="disabled",
            process_mode="isolated",
            inherited_descriptors=False,
            dependency_tree_writable=False,
            environment_allowlist={"LANG": "C.UTF-8"},
            locale="C.UTF-8",
            thread_count=1,
            budget=_budget(),
            allow_weaker_fallback=False,
            resource_enforcement="observed_memory",
        )


def test_policy_rejects_unknown_resource_enforcement_mode():
    from workbench.native_containment.policy import ContainmentPolicyError

    with pytest.raises(ContainmentPolicyError, match="resource_enforcement"):
        _experimental_policy(resource_enforcement="best_effort")


def test_resource_enforcement_mode_is_bound_into_policy_digest():
    from workbench.native_containment.policy import ContainmentPolicy

    hard = ContainmentPolicy(
        profile_id="strict-readonly-v1",
        filesystem_mode="sealed_readonly",
        network_mode="disabled",
        process_mode="isolated",
        inherited_descriptors=False,
        dependency_tree_writable=False,
        environment_allowlist={"LANG": "C.UTF-8"},
        locale="C.UTF-8",
        thread_count=1,
        budget=_budget(),
        allow_weaker_fallback=False,
        resource_enforcement="hard_limits",
    )

    assert hard.content_digest != _experimental_policy().content_digest
