from __future__ import annotations

import sys

def test_darwin_canary_reports_typed_unsupported_without_backend():
    from workbench.native_containment.platform_darwin import DarwinCanaryHarness
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
    result = DarwinCanaryHarness(
        python_executable="/usr/bin/python3",
        backend_executable="/missing/sandbox-exec",
    ).run(policy)
    assert result.status == "unsupported"
    assert result.reason_code == "NATIVE_CONTAINMENT_BACKEND_UNAVAILABLE"


def test_darwin_canary_accepts_only_all_required_assertions():
    from workbench.native_containment.platform_darwin import DarwinCanaryHarness
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
    harness = DarwinCanaryHarness(
        python_executable="/usr/bin/python3",
        backend_executable="/usr/bin/sandbox-exec",
        canary_probe=lambda _policy: {case: True for case in DarwinCanaryHarness.CANARY_CASES},
        host_supported=lambda: True,
    )
    assert harness.run(policy).status == "supported"


def test_darwin_backend_identity_is_content_addressed():
    harness_module = __import__(
        "workbench.native_containment.platform_darwin",
        fromlist=["DarwinCanaryHarness"],
    )
    harness = harness_module.DarwinCanaryHarness(
        python_executable=sys.executable,
        backend_executable=sys.executable,
        host_supported=lambda: True,
        backend_available=lambda: True,
    )
    identity = harness.discover_identity()
    assert identity.backend_digest
    assert identity.backend_executable == sys.executable


def test_darwin_canary_classifies_seatbelt_apply_failure_separately_from_limits():
    from workbench.native_containment.platform_darwin import DarwinCanaryHarness

    assert (
        DarwinCanaryHarness._classify_probe_failure(
            "sandbox-exec: sandbox_apply: Operation not permitted", 71
        )
        == "NATIVE_CONTAINMENT_SANDBOX_APPLY_FAILED"
    )
    assert (
        DarwinCanaryHarness._classify_probe_failure("", 134)
        == "NATIVE_CONTAINMENT_SANDBOX_PROFILE_ABORTED"
    )
