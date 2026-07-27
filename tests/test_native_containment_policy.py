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
