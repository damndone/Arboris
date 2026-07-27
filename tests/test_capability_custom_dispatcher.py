from __future__ import annotations

from dataclasses import replace

import pytest

from workbench.capability_factory.adapter_contract import AdapterContract
from workbench.capability_factory.contracts import ImplementationRevision, SemanticProfile
from workbench.capability_factory.notebook_binding import CapabilityResolutionBinding
from workbench.capability_factory.custom_dispatcher import (
    CustomCapabilityDispatcher,
    CustomDispatchPreflightError,
    CustomDispatchPlan,
)
from test_capability_dispatch_contract import _intent


def _records() -> tuple[ImplementationRevision, AdapterContract, CapabilityResolutionBinding]:
    profile = SemanticProfile(
        profile_id="profile.dispatch",
        revision=1,
        input_kinds=("table",),
        operations=("fit", "predict"),
        output_facets=("parameters",),
        assumptions=(),
        consumers={
            "notebook_option_planner": "planner.v1",
            "report_projection": "report.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    implementation = ImplementationRevision(
        implementation_id="implementation.dispatch",
        revision=1,
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        profile_digest=profile.content_digest,
        input_schema_digest="1" * 64,
        source_kind="generated_adapter",
        trust_tier="generated_adapter",
        operations=("fit", "predict"),
        consumer_support={
            "notebook_option_planner": "planner.v1",
            "report_projection": "report.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref="2" * 64,
    )
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.dispatch",
        revision=1,
        entrypoint_ref="3" * 64,
        operations=("fit", "predict"),
        consumer_support={
            "notebook_option_planner": "planner.v1",
            "report_projection": "report.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    binding = CapabilityResolutionBinding(
        resolution_binding_ref="4" * 64,
        implementation_ref=implementation.content_digest,
        adapter_ref=adapter.content_digest,
        validation_bundle_ref="5" * 64,
        assessment_ref="6" * 64,
        admission_id="admission.dispatch",
        admission_ref="7" * 64,
        runtime_policy_ref="8" * 64,
        validity_cursor_ref="9" * 64,
        scope_kind="project",
        scope_ref="project.dispatch",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=("notebook_option_planner", "report_projection"),
    )
    return implementation, adapter, binding


def _intent_and_records() -> tuple[object, ImplementationRevision, AdapterContract, CapabilityResolutionBinding]:
    implementation, adapter, binding = _records()
    intent = replace(
        _intent(),
        binding_ref=binding.resolution_binding_ref,
        admission_ref=binding.admission_ref,
        runtime_policy_ref=binding.runtime_policy_ref,
    )
    return intent, implementation, adapter, binding


def test_preflight_joins_exact_records_and_keeps_execution_closed() -> None:
    intent, implementation, adapter, binding = _intent_and_records()
    plan = CustomCapabilityDispatcher.prepare(
        intent=intent,
        binding=binding,
        adapter=adapter,
        implementation=implementation,
        operation_id="fit",
        requested_consumers=("notebook_option_planner", "report_projection"),
    )

    assert isinstance(plan, CustomDispatchPlan)
    assert plan.execution_allowed is False
    assert plan.requires_user_confirmation is True
    assert plan.reservation_required is True
    assert plan.consumer_support["report_projection"] == "report.v1"
    assert not hasattr(CustomCapabilityDispatcher, "run")
    assert not hasattr(CustomCapabilityDispatcher, "spawn")
    assert plan.content_digest == CustomDispatchPlan.from_dict(plan.to_dict()).content_digest


def test_preflight_rejects_mismatched_identity_or_undeclared_consumer() -> None:
    intent, implementation, adapter, binding = _intent_and_records()
    with pytest.raises(CustomDispatchPreflightError, match="binding"):
        CustomCapabilityDispatcher.prepare(
            intent=replace(intent, binding_ref="a" * 64),
            binding=binding,
            adapter=adapter,
            implementation=implementation,
            operation_id="fit",
            requested_consumers=("notebook_option_planner",),
        )

    with pytest.raises(CustomDispatchPreflightError, match="consumer"):
        CustomCapabilityDispatcher.prepare(
            intent=intent,
            binding=binding,
            adapter=adapter,
            implementation=implementation,
            operation_id="fit",
            requested_consumers=("diagnostic_adapter",),
        )


def test_preflight_rejects_operation_and_adapter_implementation_mismatch() -> None:
    intent, implementation, adapter, binding = _intent_and_records()
    with pytest.raises(CustomDispatchPreflightError, match="operation"):
        CustomCapabilityDispatcher.prepare(
            intent=intent,
            binding=binding,
            adapter=adapter,
            implementation=implementation,
            operation_id="predict",
            requested_consumers=("notebook_option_planner",),
        )

    forged = replace(implementation, implementation_id="implementation.other")
    with pytest.raises(CustomDispatchPreflightError, match="implementation"):
        CustomCapabilityDispatcher.prepare(
            intent=intent,
            binding=binding,
            adapter=adapter,
            implementation=forged,
            operation_id="fit",
            requested_consumers=("notebook_option_planner",),
        )


def test_dispatch_only_delegates_a_running_attempt_to_b1_and_preserves_unsupported() -> None:
    from workbench.capability_factory.execution_receipt import CapabilityDispatchReceipt
    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.contracts import ContainmentRequest, ResourceBudget
    from workbench.native_containment.host import CanaryResult
    from workbench.native_containment.policy import ContainmentPolicy

    intent, implementation, adapter, binding = _intent_and_records()
    plan = CustomCapabilityDispatcher.prepare(
        intent=intent,
        binding=binding,
        adapter=adapter,
        implementation=implementation,
        operation_id="fit",
        requested_consumers=("notebook_option_planner", "report_projection"),
    )
    receipt = CapabilityDispatchReceipt(
        authorization_id="authorization.dispatch",
        authorization_payload_digest="1" * 64,
        intent_digest=intent.content_digest,
        reservation_id="reservation.dispatch",
        attempt_id="attempt.dispatch",
        lease_epoch=1,
        status="running",
        plan_digest=plan.content_digest,
    )
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
        budget=ResourceBudget(10_000, 8_000, 64 * 1024 * 1024, 8, 1_000_000, 100_000),
        allow_weaker_fallback=False,
    )
    request = ContainmentRequest(
        request_id="request.dispatch",
        attempt_id=receipt.attempt_id,
        intent_digest=intent.content_digest,
        input_bundle_ref=intent.bundle_ref,
        output_namespace_ref="9" * 64,
        policy_digest=policy.content_digest,
        harness_digest="a" * 64,
    )
    broker = ContainmentBroker(
        host_assessor=lambda _policy: CanaryResult.unsupported(
            "NATIVE_CONTAINMENT_RESOURCE_LIMIT_UNAVAILABLE"
        ),
        executor=None,
    )

    result = CustomCapabilityDispatcher.dispatch(
        intent=intent,
        plan=plan,
        receipt=receipt,
        request=request,
        policy=policy,
        broker=broker,
    )

    assert result.status == "unsupported"
    assert result.output_bundle_ref is None
    assert result.attempt_id == receipt.attempt_id

    with pytest.raises(CustomDispatchPreflightError, match="running"):
        CustomCapabilityDispatcher.dispatch(
            intent=intent,
            plan=plan,
            receipt=replace(receipt, status="dispatch_reserved"),
            request=request,
            policy=policy,
            broker=broker,
        )
