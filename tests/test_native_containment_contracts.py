from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest


def test_resource_budget_is_bounded_and_immutable():
    from workbench.native_containment.contracts import ResourceBudget, ResourceBudgetError

    budget = ResourceBudget(
        cpu_millis=10_000,
        wall_millis=8_000,
        memory_bytes=64 * 1024 * 1024,
        pid_count=8,
        stdout_bytes=1_000_000,
        stderr_bytes=100_000,
    )
    assert budget.content_digest
    with pytest.raises(FrozenInstanceError):
        budget.pid_count = 2
    with pytest.raises(ResourceBudgetError, match="positive"):
        ResourceBudget(0, 1, 1, 1, 1, 1)


def test_request_binds_only_refs_and_attempt_identity():
    from workbench.native_containment.contracts import ContainmentRequest

    request = ContainmentRequest(
        request_id="request.alpha",
        attempt_id="attempt.alpha",
        intent_digest="a" * 64,
        input_bundle_ref="b" * 64,
        output_namespace_ref="c" * 64,
        policy_digest="d" * 64,
        harness_digest="e" * 64,
        preopened_handle_refs=("handle.input",),
    )
    assert request.content_digest
    assert not hasattr(request, "host_path")


def test_unknown_request_handle_is_rejected():
    from workbench.native_containment.contracts import ContainmentRequest, ContainmentRequestError

    with pytest.raises(ContainmentRequestError, match="handle"):
        ContainmentRequest(
            request_id="request.bad",
            attempt_id="attempt.bad",
            intent_digest="a" * 64,
            input_bundle_ref="b" * 64,
            output_namespace_ref="c" * 64,
            policy_digest="d" * 64,
            harness_digest="e" * 64,
            preopened_handle_refs=("../escape",),
        )


def test_report_binds_the_exact_request_digest():
    from workbench.native_containment.contracts import ContainmentReport

    report = ContainmentReport(
        attempt_id="attempt.alpha",
        request_digest="a" * 64,
        status="unsupported",
        reason_code="NATIVE_CONTAINMENT_HOST_UNSUPPORTED",
    )
    assert report.request_digest == "a" * 64


def test_completed_report_requires_a_host_assessment_reference():
    from workbench.native_containment.contracts import ContainmentReport, ContainmentReportError

    with pytest.raises(ContainmentReportError, match="assessment"):
        ContainmentReport(
            attempt_id="attempt.alpha",
            request_digest="a" * 64,
            status="completed",
            reason_code="NATIVE_CONTAINMENT_COMPLETED",
            output_bundle_ref="b" * 64,
        )
