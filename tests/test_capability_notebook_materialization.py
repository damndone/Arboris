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
    _store_subjects,
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


def test_authorized_notebook_gateway_runs_real_local_darwin_adapter(tmp_path) -> None:
    """Exercise the opt-in Darwin path with the real adapter harness.

    This is intentionally a host-conditional acceptance test. Linux and a
    Darwin host without the experimental Seatbelt capability remain explicit
    skips; they must never be converted into a fake green result.
    """

    import sys
    from dataclasses import replace
    from pathlib import Path

    from workbench.capability_factory.adapter_contract import (
        AdapterContract,
        AdapterSourceGenerator,
        PythonAdapterExecutionBinding,
        PythonAdapterExecutionGateway,
    )
    from workbench.capability_factory.control import ExecutionControlStore
    from workbench.capability_factory.custom_dispatcher import CustomCapabilityDispatcher
    from workbench.capability_factory.execution_authorization import (
        OptionExecutionAuthorizationStore,
    )
    from workbench.capability_factory.execution_receipt import CapabilityDispatchCoordinator
    from workbench.capability_factory.notebook_bridge import NotebookCapabilityDispatchBinding
    from workbench.capability_factory.runtime import DependencyAdmissionGate
    from workbench.capability_factory.dependency_service import DependencyService
    from workbench.capability_factory.supervisor import DurableSupervisorStore
    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.contracts import ContainmentRequest, ResourceBudget
    from workbench.native_containment.executor_darwin import DarwinExperimentalExecutor
    from workbench.native_containment.platform_darwin import DarwinCanaryHarness
    from workbench.native_containment.policy import ContainmentPolicy

    if sys.platform != "darwin":
        pytest.skip("real local Darwin containment is only available on macOS")

    from test_capability_custom_dispatcher import _records
    from test_capability_dispatch_contract import _intent

    implementation, adapter_template, binding_template = _records()
    source_root = (tmp_path / "adapter-source").resolve()
    source = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=lambda _context: (
            "def adapter(document):\n"
            "    value = document['payload']['value']\n"
            "    return {'status': 'ok', 'value': value}\n"
        ),
        output_root=source_root,
    )
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.local.darwin",
        revision=1,
        entrypoint_ref=source.entrypoint_ref,
        operations=("fit", "model.custom"),
        consumer_support=dict(adapter_template.consumer_support),
    )
    binding_record = replace(binding_template, adapter_ref=adapter.content_digest)
    intent = replace(
        _intent(),
        binding_ref=binding_record.resolution_binding_ref,
        admission_ref=binding_record.admission_ref,
        runtime_policy_ref=binding_record.runtime_policy_ref,
        operation_id="model.custom",
    )

    now = datetime(2026, 7, 27, 9, 0, tzinfo=timezone.utc)
    authorization = _authorization(
        intent,
        binding_record,
        implementation,
        now=now,
        execution_mode="experimental_confirm_and_execute",
        risk_level="high",
    )
    auth_store = OptionExecutionAuthorizationStore(tmp_path, clock=lambda: now)
    auth_store.issue(authorization)
    control_store = ExecutionControlStore(clock=lambda: now)
    _store_subjects(control_store, intent, authorization.authorization_id, now)
    supervisor = DurableSupervisorStore(tmp_path)
    plan = CustomCapabilityDispatcher.prepare(
        intent=intent,
        binding=binding_record,
        adapter=adapter,
        implementation=implementation,
        operation_id="model.custom",
        requested_consumers=("notebook_option_planner", "report_projection"),
    )
    coordinator = CapabilityDispatchCoordinator(
        authorization_store=auth_store,
        control_store=control_store,
        supervisor_store=supervisor,
    )
    policy = ContainmentPolicy(
        profile_id="darwin-seatbelt-experimental-v1",
        filesystem_mode="sealed_readonly",
        network_mode="disabled",
        process_mode="isolated",
        inherited_descriptors=False,
        dependency_tree_writable=False,
        environment_allowlist={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"},
        locale="C.UTF-8",
        thread_count=1,
        budget=ResourceBudget(
            10_000,
            8_000,
            64 * 1024 * 1024,
            8,
            1_000_000,
            100_000,
        ),
        allow_weaker_fallback=False,
        resource_enforcement="observed_memory",
    )
    python_executable = Path("/usr/bin/python3")
    if not python_executable.is_file():
        pytest.skip("canonical Darwin Python interpreter is unavailable")
    canary = DarwinCanaryHarness(
        python_executable=str(python_executable),
        backend_executable="/usr/bin/sandbox-exec",
    ).run(policy)
    if canary.status != "supported":
        pytest.skip(f"Darwin experimental canary unavailable: {canary.reason_code}")

    input_root = (tmp_path / "adapter-input").resolve()
    output_root = (tmp_path / "adapter-output").resolve()
    adapter_binding = PythonAdapterExecutionBinding(
        bundle_ref=intent.bundle_ref,
        output_namespace_ref="3" * 64,
        adapter=adapter,
        source_artifact=source,
        operation="fit",
        payload={"value": 42},
        input_root=input_root,
        output_root=output_root,
        interpreter=python_executable,
    )
    darwin_executor = DarwinExperimentalExecutor(
        resolver=adapter_binding.prepare,
        assessment_ref="9" * 64,
        backend_executable="/usr/bin/sandbox-exec",
    )
    adapter_executor = PythonAdapterExecutionGateway(
        binding=adapter_binding,
        executor=darwin_executor,
    )
    requests: dict[str, ContainmentRequest] = {}
    reports: dict[str, object] = {}

    class CapturingAdapterExecutor:
        def spawn(self, request, current_policy, current_canary):
            return adapter_executor.spawn(request, current_policy, current_canary)

        def terminate(self, spawned):
            return adapter_executor.terminate(spawned)

        def __call__(self, request, current_policy, current_canary):
            report = adapter_executor(request, current_policy, current_canary)
            reports[request.attempt_id] = report
            return report

    executor = CapturingAdapterExecutor()

    def request_factory(attempt_id: str) -> ContainmentRequest:
        request = ContainmentRequest(
            request_id="request.local.darwin",
            attempt_id=attempt_id,
            intent_digest=intent.content_digest,
            input_bundle_ref=intent.bundle_ref,
            output_namespace_ref="3" * 64,
            policy_digest=policy.content_digest,
            harness_digest="4" * 64,
        )
        requests[attempt_id] = request
        return request

    def completion_factory(*, result, receipt, binding):
        from workbench.capability_factory.execution_receipt import validate_artifact_contract_v11
        from workbench.contracts.agent.notebook_option import ArtifactContract, ExpectedArtifact

        payload = adapter_binding.read_result(
            requests[receipt.attempt_id], reports[receipt.attempt_id]
        )
        assert payload == {"status": "ok", "value": 42}
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
            ArtifactContract(
                expected=(ExpectedArtifact("custom.parameters", "custom_json", step="fit"),)
            ),
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

    dependency_service = DependencyService()
    dependency_checks: list[str] = []
    dependency_service.assert_execution_bundle = (  # type: ignore[method-assign]
        lambda bundle_ref: dependency_checks.append(bundle_ref)
    )
    dependency_gate = DependencyAdmissionGate(dependency_service)
    gateway = AuthorizedCapabilityExecutionGateway(
        binding_factory=lambda **_kwargs: NotebookCapabilityDispatchBinding(
            intent=intent,
            plan=plan,
            policy=policy,
            canary=canary,
            expectations=_expectations(intent, authorization.authorization_id),
            request_factory=request_factory,
            coordinator=coordinator,
            broker=ContainmentBroker(
                host_assessor=lambda _policy: canary,
                executor=executor,
                report_verifier=lambda **_kwargs: "a" * 64,
                require_authenticated_reports=True,
            ),
            executor=executor,
            owner_id="supervisor.local.darwin",
            lease_seconds=60,
            attempt_id="attempt.local.darwin",
            lease_epoch=1,
            executor_idempotency_key="executor.local.darwin",
            reservation_id="reservation.local.darwin",
            reservation_idempotency_key="reservation-local-darwin-idem",
            now=now,
            completion_factory=completion_factory,
        ),
        dependency_binding_validator=dependency_gate,
    )

    dispatch = gateway.dispatch(
        notebook_id="notebook.local.darwin",
        option_id="option.local.darwin",
        authorization=authorization,
        materialization={},
        draft={},
        context=None,
    )

    assert dispatch.status == "completed"
    assert dispatch.attempt_id == "attempt.local.darwin"
    assert dependency_checks == [intent.bundle_ref]
    assert auth_store.read(authorization.authorization_id).status == "consumed"
    assert supervisor.read("attempt.local.darwin").status == "consumed"
    assert adapter_binding.result_path.read_text(encoding="utf-8") == '{"status":"ok","value":42}'


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
