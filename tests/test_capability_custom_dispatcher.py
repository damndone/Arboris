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
        operations=("fit", "predict", "model.custom"),
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
        operations=("fit", "predict", "model.custom"),
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
        operations=("fit", "predict", "model.custom"),
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
        allowed_operations=("fit", "model.custom"),
        allowed_consumers=("notebook_option_planner", "report_projection"),
    )
    return implementation, adapter, binding


def _intent_and_records(
    *, operation_id: str = "fit"
) -> tuple[object, ImplementationRevision, AdapterContract, CapabilityResolutionBinding]:
    implementation, adapter, binding = _records()
    intent = replace(
        _intent(),
        operation_id=operation_id,
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


def test_spawn_ack_then_dispatch_reuses_one_trusted_executor_handle(tmp_path) -> None:
    from datetime import datetime, timedelta, timezone
    from types import SimpleNamespace

    from workbench.capability_factory.control import (
        ControlCursorExpectation,
        ControlSubjectCursor,
        ExecutionControlStore,
    )
    from workbench.capability_factory.execution_authorization import (
        OptionExecutionAuthorization,
        OptionExecutionAuthorizationStore,
    )
    from workbench.capability_factory.execution_receipt import CapabilityDispatchCoordinator
    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.contracts import ContainmentReport, ContainmentRequest, ResourceBudget
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
    now = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)
    authorization = OptionExecutionAuthorization(
        authorization_id="authorization.custom.sequence",
        notebook_id="notebook.custom.sequence",
        option_id="option.custom.sequence",
        option_revision=1,
        binding_revision=intent.binding_revision,
        capability_resolution_binding_ref=intent.binding_ref,
        materialization_id="materialization.custom.sequence",
        draft_id=intent.draft_id,
        draft_hash=intent.draft_hash,
        run_intent_id=intent.intent_id,
        capability_ref=implementation.content_digest,
        bundle_ref=intent.bundle_ref,
        evidence_ref=intent.evidence_ref,
        admission_ref=intent.admission_ref,
        runtime_policy_ref=intent.runtime_policy_ref,
        freshness_cursor_ref="a" * 64,
        input_graph_fingerprint=intent.input_graph_fingerprint,
        freshness_dependency_fingerprint=intent.input_graph_fingerprint,
        operation_id=intent.operation_id,
        execution_mode="confirm_and_execute",
        risk_level="low",
        artifact_contract_ref="b" * 64,
        consumer_projection_ref="c" * 64,
        idempotency_key="authorization-custom-sequence-idem",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=5),
    )
    auth_store = OptionExecutionAuthorizationStore(tmp_path, clock=lambda: now)
    auth_store.issue(authorization)
    control_store = ExecutionControlStore(clock=lambda: now)
    for kind, ref, revision, status in (
        ("authorization", authorization.authorization_id, 1, "claimed"),
        ("binding", intent.binding_ref, intent.binding_revision, "valid"),
        ("host_containment", intent.host_containment_ref, intent.host_validity_revision, "valid"),
        ("bundle", intent.bundle_ref, intent.bundle_validity_revision, "valid"),
        ("evidence", intent.evidence_ref, intent.evidence_validity_revision, "valid"),
        ("admission", intent.admission_ref, intent.admission_validity_revision, "valid"),
    ):
        control_store.publish_subject(
            ControlSubjectCursor(
                subject_kind=kind,
                subject_ref=ref,
                validity_revision=revision,
                status=status,
                effective_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(minutes=5),
                authority="server.control",
                reason="fixture",
                source_record_ref=f"source.{kind}",
            )
        )
    from workbench.capability_factory.supervisor import DurableSupervisorStore

    supervisor = DurableSupervisorStore(tmp_path)

    coordinator = CapabilityDispatchCoordinator(
        authorization_store=auth_store,
        control_store=control_store,
        supervisor_store=supervisor,
    )
    receipt = coordinator.reserve(
        authorization=authorization,
        intent=intent,
        plan=plan,
        expectations=(
            # The coordinator consumes these exact control cursors before the
            # executor is allowed to create a process.
            ControlCursorExpectation("authorization", authorization.authorization_id, 1, "claimed"),
            ControlCursorExpectation("binding", intent.binding_ref, intent.binding_revision, "valid"),
            ControlCursorExpectation("host_containment", intent.host_containment_ref, intent.host_validity_revision, "valid"),
            ControlCursorExpectation("bundle", intent.bundle_ref, intent.bundle_validity_revision, "valid"),
            ControlCursorExpectation("evidence", intent.evidence_ref, intent.evidence_validity_revision, "valid"),
            ControlCursorExpectation("admission", intent.admission_ref, intent.admission_validity_revision, "valid"),
        ),
        owner_id="supervisor.custom.sequence",
        lease_seconds=60,
        attempt_id="attempt.custom.sequence",
        lease_epoch=1,
        executor_idempotency_key="executor.custom.sequence",
        reservation_id="reservation.custom.sequence",
        reservation_idempotency_key="reservation-custom-sequence-idem",
        now=now,
    )
    policy = ContainmentPolicy(
        profile_id="darwin-seatbelt-experimental-v1",
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
        resource_enforcement="observed_memory",
    )
    request = ContainmentRequest(
        request_id="request.custom.sequence",
        attempt_id=receipt.attempt_id,
        intent_digest=intent.content_digest,
        input_bundle_ref=intent.bundle_ref,
        output_namespace_ref="d" * 64,
        policy_digest=policy.content_digest,
        harness_digest="e" * 64,
    )
    canary = CanaryResult(status="supported", reason_code="NATIVE_CONTAINMENT_CANARY_PASSED")
    calls: list[object] = []

    class StubExecutor:
        def spawn(self, current_request, current_policy, current_canary):
            calls.append(("spawn", current_request, current_policy, current_canary))
            return SimpleNamespace(handle_ref="handle.custom.sequence")

        def terminate(self, spawned):
            calls.append(("terminate", spawned))

        def __call__(self, current_request, current_policy, current_canary):
            calls.append(("collect", current_request, current_policy, current_canary))
            return ContainmentReport(
                attempt_id=current_request.attempt_id,
                request_digest=current_request.content_digest,
                status="completed",
                reason_code="NATIVE_CONTAINMENT_EXECUTION_COMPLETED",
                assessment_ref="f" * 64,
                output_bundle_ref="0" * 64,
                attestation_ref="1" * 64,
            )

    executor = StubExecutor()
    broker = ContainmentBroker(
        host_assessor=lambda _policy: canary,
        executor=executor,
        report_verifier=lambda **_kwargs: "1" * 64,
        require_authenticated_reports=True,
    )
    running = coordinator.spawn_and_acknowledge(
        receipt=receipt,
        owner_id="supervisor.custom.sequence",
        executor=executor,
        request=request,
        policy=policy,
        canary=canary,
    )
    result = CustomCapabilityDispatcher.dispatch(
        intent=intent,
        plan=plan,
        receipt=running,
        request=request,
        policy=policy,
        broker=broker,
    )

    assert result.status == "completed"
    assert [item[0] for item in calls] == ["spawn", "collect"]
    assert result.output_bundle_ref == "0" * 64
