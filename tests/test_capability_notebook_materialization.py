from __future__ import annotations

import pytest

from workbench.capability_factory.notebook_bridge import (
    AuthorizedCapabilityExecutionGateway,
    CapabilityExecutionCompletion,
    NotebookCapabilityBridge,
    NotebookCapabilityDispatchBinding,
)

from test_capability_execution_receipt import (
    _authorization,
    _expectations,
    _fixture,
    _terminal_reconciliation,
    _termination_proof,
    validate_artifact_contract_v11,
)
from test_capability_custom_dispatcher import _intent_and_records
from datetime import datetime, timezone


def test_notebook_bridge_prepares_one_exact_intent_without_run_side_effect(tmp_path) -> None:
    source_intent, implementation, _adapter, binding = _intent_and_records()
    now = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)
    authorization = _authorization(source_intent, binding, implementation, now=now)
    prepared = NotebookCapabilityBridge.prepare_intent(
        authorization=authorization,
        run_id="run.bridge",
        input_contract_ref="1" * 64,
        output_contract_ref="2" * 64,
        host_containment_ref="3" * 64,
        host_validity_revision=1,
        bundle_validity_revision=1,
        evidence_validity_revision=1,
        admission_validity_revision=1,
    )

    assert prepared.intent.draft_id == authorization.draft_id
    assert prepared.intent.draft_hash == authorization.draft_hash
    assert prepared.intent.run_id == "run.bridge"
    assert prepared.intent.content_digest == prepared.intent.content_digest
    assert list(tmp_path.iterdir()) == []


def test_authorized_notebook_gateway_runs_the_single_cf4_lifecycle(tmp_path) -> None:
    from types import SimpleNamespace

    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.contracts import ContainmentReport, ContainmentRequest, ResourceBudget
    from workbench.native_containment.host import CanaryResult
    from workbench.native_containment.policy import ContainmentPolicy

    intent, authorization, plan, coordinator, _control_store, auth_store, supervisor, now = _fixture(
        tmp_path,
        operation_id="model.custom",
        execution_mode="experimental_confirm_and_execute",
        risk_level="high",
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
    canary = CanaryResult(status="supported", reason_code="NATIVE_CONTAINMENT_CANARY_PASSED")
    calls: list[str] = []

    class StubExecutor:
        def spawn(self, *_args):
            calls.append("spawn")
            return SimpleNamespace(handle_ref="handle.notebook.gateway")

        def terminate(self, _spawned):
            calls.append("terminate")

        def __call__(self, request, _policy, _canary):
            calls.append("collect")
            return ContainmentReport(
                attempt_id=request.attempt_id,
                request_digest=request.content_digest,
                status="completed",
                reason_code="NATIVE_CONTAINMENT_COMPLETED",
                assessment_ref="1" * 64,
                output_bundle_ref="2" * 64,
                attestation_ref="8" * 64,
            )

    executor = StubExecutor()
    def completion_factory(*, result, receipt, binding):
        from workbench.contracts.agent.notebook_option import ArtifactContract, ExpectedArtifact
        from workbench.capability_factory.execution_receipt import validate_artifact_contract_v11

        attempt = binding.coordinator.supervisor_store.read(receipt.attempt_id)
        artifact = {
            "artifact_id": "custom.parameters",
            "artifact_type": "custom_json",
            "step": "fit",
            "lineage_ref": "5" * 64,
            "consumer_projection_ref": authorization.consumer_projection_ref,
            "run_attempt_ref": attempt.content_digest,
            "option_revision_ref": authorization.artifact_contract_ref,
            "artifact_ref": "6" * 64,
            "facet": "parameters",
        }
        validation = validate_artifact_contract_v11(
            ArtifactContract(expected=(ExpectedArtifact("custom.parameters", "custom_json", step="fit"),)),
            [artifact],
            option_revision_ref=authorization.artifact_contract_ref,
            run_attempt_ref=attempt.content_digest,
            consumer_projection_ref=authorization.consumer_projection_ref,
            lineage_ref="5" * 64,
            allowed_facets=("parameters",),
        )
        termination = _termination_proof(attempt, authorization.authorization_id)
        reconciliation = _terminal_reconciliation(
            attempt,
            authorization.authorization_id,
            validation,
            "7" * 64,
        )
        return CapabilityExecutionCompletion(
            artifact_validation=validation,
            object_graph_ref="7" * 64,
            termination_proof=termination,
            terminal_reconciliation=reconciliation,
        )

    binding = NotebookCapabilityDispatchBinding(
        intent=intent,
        plan=plan,
        policy=policy,
        canary=canary,
        expectations=_expectations(intent, authorization.authorization_id),
        request_factory=lambda attempt_id: ContainmentRequest(
            request_id="request.notebook.gateway",
            attempt_id=attempt_id,
            intent_digest=intent.content_digest,
            input_bundle_ref=intent.bundle_ref,
            output_namespace_ref="3" * 64,
            policy_digest=policy.content_digest,
            harness_digest="4" * 64,
        ),
        coordinator=coordinator,
        broker=ContainmentBroker(
            host_assessor=lambda _policy: canary,
            executor=executor,
            report_verifier=lambda **_kwargs: "8" * 64,
            require_authenticated_reports=True,
        ),
        executor=executor,
        owner_id="supervisor.notebook.gateway",
        lease_seconds=60,
        attempt_id="attempt.notebook.gateway",
        lease_epoch=1,
        executor_idempotency_key="executor.notebook.gateway",
        reservation_id="reservation.notebook.gateway",
        reservation_idempotency_key="reservation-notebook-gateway-idem",
        now=now,
        completion_factory=completion_factory,
    )
    results = []
    dependency_checks = []
    gateway = AuthorizedCapabilityExecutionGateway(
        binding_factory=lambda **_kwargs: binding,
        result_sink=results.append,
        dependency_binding_validator=lambda dispatch_binding: dependency_checks.append(
            dispatch_binding.intent.bundle_ref
        ),
    )

    dispatch = gateway.dispatch(
        notebook_id="notebook.gateway",
        option_id="option.gateway",
        authorization=authorization,
        materialization={},
        draft={},
        context=None,
    )

    assert dispatch.status == "completed"
    assert dispatch.run_id == intent.run_id
    assert dispatch.attempt_id == "attempt.notebook.gateway"
    assert dispatch.receipt_ref
    assert dispatch.completion_ref
    assert calls == ["spawn", "collect"]
    assert dependency_checks == [intent.bundle_ref]
    assert results and results[0].status == "completed"
    assert auth_store.read(authorization.authorization_id).status == "consumed"
    assert supervisor.read("attempt.notebook.gateway").status == "consumed"


def test_authorized_notebook_gateway_fences_completed_child_without_completion_binding(tmp_path) -> None:
    from types import SimpleNamespace

    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.contracts import ContainmentReport, ContainmentRequest, ResourceBudget
    from workbench.native_containment.host import CanaryResult
    from workbench.native_containment.policy import ContainmentPolicy

    intent, authorization, plan, coordinator, _control_store, auth_store, supervisor, now = _fixture(
        tmp_path,
        operation_id="model.custom",
        execution_mode="experimental_confirm_and_execute",
        risk_level="high",
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
    canary = CanaryResult(status="supported", reason_code="NATIVE_CONTAINMENT_CANARY_PASSED")

    class StubExecutor:
        def spawn(self, *_args):
            return SimpleNamespace(handle_ref="handle.notebook.no-completion")

        def terminate(self, _spawned):
            return None

        def __call__(self, request, _policy, _canary):
            return ContainmentReport(
                attempt_id=request.attempt_id,
                request_digest=request.content_digest,
                status="completed",
                reason_code="NATIVE_CONTAINMENT_COMPLETED",
                assessment_ref="1" * 64,
                output_bundle_ref="2" * 64,
            )

    executor = StubExecutor()
    binding = NotebookCapabilityDispatchBinding(
        intent=intent,
        plan=plan,
        policy=policy,
        canary=canary,
        expectations=_expectations(intent, authorization.authorization_id),
        request_factory=lambda attempt_id: ContainmentRequest(
            request_id="request.notebook.no-completion",
            attempt_id=attempt_id,
            intent_digest=intent.content_digest,
            input_bundle_ref=intent.bundle_ref,
            output_namespace_ref="3" * 64,
            policy_digest=policy.content_digest,
            harness_digest="4" * 64,
        ),
        coordinator=coordinator,
        broker=ContainmentBroker(
            host_assessor=lambda _policy: canary,
            executor=executor,
            report_verifier=lambda **_kwargs: "9" * 64,
            require_authenticated_reports=True,
        ),
        executor=executor,
        owner_id="supervisor.notebook.no-completion",
        lease_seconds=60,
        attempt_id="attempt.notebook.no-completion",
        lease_epoch=1,
        executor_idempotency_key="executor.notebook.no-completion",
        reservation_id="reservation.notebook.no-completion",
        reservation_idempotency_key="reservation-notebook-no-completion-idem",
        now=now,
    )
    dispatch = AuthorizedCapabilityExecutionGateway(
        binding_factory=lambda **_kwargs: binding,
    ).dispatch(
        notebook_id="notebook.gateway",
        option_id="option.gateway",
        authorization=authorization,
        materialization={},
        draft={},
        context=None,
    )

    assert dispatch.status == "dispatch_unknown"
    assert auth_store.read(authorization.authorization_id).status == "dispatch_unknown"
    assert supervisor.read("attempt.notebook.no-completion").status == "dispatch_unknown"


def test_authorized_notebook_gateway_rejects_non_experimental_authorization(tmp_path) -> None:
    _intent, authorization, _plan, _coordinator, _control_store, _auth_store, _supervisor, _now = _fixture(tmp_path)
    gateway = AuthorizedCapabilityExecutionGateway(
        binding_factory=lambda **_kwargs: pytest.fail("binding must not be resolved")
    )

    with pytest.raises(ValueError, match="experimental_confirm_and_execute"):
        gateway.dispatch(
            notebook_id="notebook.gateway",
            option_id="option.gateway",
            authorization=authorization,
            materialization={},
            draft={},
            context=None,
        )
