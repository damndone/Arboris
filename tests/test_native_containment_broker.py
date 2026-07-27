from __future__ import annotations

from dataclasses import replace


def _policy():
    from workbench.native_containment.contracts import ResourceBudget
    from workbench.native_containment.policy import ContainmentPolicy

    return ContainmentPolicy(
        profile_id="strict-readonly-v1",
        filesystem_mode="sealed_readonly",
        network_mode="disabled",
        process_mode="isolated",
        inherited_descriptors=False,
        dependency_tree_writable=False,
        environment_allowlist={"LANG": "C.UTF-8"},
        locale="C.UTF-8",
        thread_count=1,
        budget=ResourceBudget(10_000, 8_000, 64 * 1024 * 1024, 8, 1_000_000, 100_000),
        allow_weaker_fallback=False,
    )


def _request():
    from workbench.native_containment.contracts import ContainmentRequest

    return ContainmentRequest(
        request_id="request.alpha",
        attempt_id="attempt.alpha",
        intent_digest="a" * 64,
        input_bundle_ref="b" * 64,
        output_namespace_ref="c" * 64,
        policy_digest=_policy().content_digest,
        harness_digest="d" * 64,
    )


def test_broker_fails_closed_without_supported_host_and_does_not_execute():
    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.host import CanaryResult

    called = []

    def assess(_policy):
        return CanaryResult.unsupported("NATIVE_CONTAINMENT_BACKEND_UNAVAILABLE")

    def executor(*_args):
        called.append(True)

    result = ContainmentBroker(host_assessor=assess, executor=executor).run(_request(), _policy())
    assert result.status == "unsupported"
    assert called == []


def test_broker_rejects_policy_digest_mismatch_before_host_probe():
    import pytest
    from workbench.native_containment.broker import ContainmentBroker, ContainmentBrokerError

    with pytest.raises(ContainmentBrokerError, match="policy"):
        ContainmentBroker(host_assessor=lambda _policy: None, executor=lambda *_args: None).run(
            _request(),
            replace(_policy(), profile_id="other"),
        )
