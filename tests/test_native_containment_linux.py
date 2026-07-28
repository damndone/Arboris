from __future__ import annotations


def test_linux_canary_is_independently_typed():
    from workbench.native_containment.platform_linux import LinuxCanaryHarness
    from workbench.native_containment.policy import ContainmentPolicy
    from workbench.native_containment.contracts import ResourceBudget

    policy = ContainmentPolicy(
        profile_id="strict-readonly-v1",
        filesystem_mode="sealed_readonly",
        network_mode="disabled",
        process_mode="isolated",
        inherited_descriptors=False,
        dependency_tree_writable=False,
        environment_allowlist={"LANG": "C.UTF-8"},
        locale="C.UTF-8",
        thread_count=1,
        budget=ResourceBudget(1, 1, 1, 1, 1, 1),
        allow_weaker_fallback=False,
    )
    result = LinuxCanaryHarness(
        python_executable="/usr/bin/python3",
        backend_executable="/missing/bwrap",
        host_supported=lambda: True,
    ).run(policy)
    assert result.status == "unsupported"
