from __future__ import annotations

import pytest

from workbench.app import app, configure_capability_factory_runtime
from workbench.capability_factory.notebook_bridge import AuthorizedCapabilityExecutionGateway
from workbench.capability_factory.notebook_catalog import CapabilityBindingCatalog
from workbench.capability_factory.dependency_service import DependencyService
from workbench.capability_factory.runtime import (
    CapabilityFactoryRuntime,
    DependencyAdmissionGate,
)


def test_runtime_bootstrap_atomically_installs_server_owned_catalog_and_gateway() -> None:
    catalog = CapabilityBindingCatalog(verifier=lambda _binding: None)
    dependency_service = DependencyService()
    gateway = AuthorizedCapabilityExecutionGateway(
        binding_factory=lambda **_kwargs: None,
        dependency_binding_validator=DependencyAdmissionGate(dependency_service),
    )
    runtime = CapabilityFactoryRuntime(
        authority_id="authority.production",
        catalog=catalog,
        execution_gateway=gateway,
        dependency_service=dependency_service,
    )

    configure_capability_factory_runtime(runtime)
    try:
        assert app.state.capability_factory_runtime is runtime
        assert app.state.notebook_capability_bindings is catalog
        assert app.state.notebook_execution_gateway is gateway
        assert runtime.public_status() == {
            "configured": True,
            "authority_id": "authority.production",
            "catalog_configured": True,
            "execution_gateway_configured": True,
            "dependency_gate_configured": True,
        }
    finally:
        configure_capability_factory_runtime(None)


def test_runtime_rejects_execution_gateway_without_dependency_gate() -> None:
    catalog = CapabilityBindingCatalog(verifier=lambda _binding: None)
    gateway = AuthorizedCapabilityExecutionGateway(binding_factory=lambda **_kwargs: None)

    with pytest.raises(ValueError, match="server-owned dependency gate"):
        CapabilityFactoryRuntime(
            authority_id="authority.production",
            catalog=catalog,
            execution_gateway=gateway,
        )


def test_runtime_bootstrap_rejects_untrusted_runtime_type() -> None:
    with pytest.raises(TypeError, match="CapabilityFactoryRuntime"):
        configure_capability_factory_runtime(object())


def test_local_experimental_bootstrap_requires_explicit_enable() -> None:
    from workbench.app import configure_local_experimental_capability_runtime

    catalog = CapabilityBindingCatalog(verifier=lambda _binding: None)
    dependency_service = DependencyService()

    with pytest.raises(ValueError, match="enable=True"):
        configure_local_experimental_capability_runtime(
            authority_id="authority.local.experimental",
            catalog=catalog,
            dependency_service=dependency_service,
            binding_factory=lambda **_kwargs: None,
            enable=False,
        )


def test_local_experimental_bootstrap_installs_dependency_gated_gateway() -> None:
    from workbench.app import configure_local_experimental_capability_runtime

    class Scanner:
        def verify(self, *, attestation, build):
            raise AssertionError("the bootstrap test must not invoke the scanner")

    catalog = CapabilityBindingCatalog(verifier=lambda _binding: None)
    dependency_service = DependencyService(supply_chain_verifier=Scanner())
    runtime = configure_local_experimental_capability_runtime(
        authority_id="authority.local.experimental",
        catalog=catalog,
        dependency_service=dependency_service,
        binding_factory=lambda **_kwargs: None,
        enable=True,
    )

    try:
        assert app.state.capability_factory_runtime is runtime
        assert runtime.execution_enabled is True
        assert runtime.dependency_service is dependency_service
        assert isinstance(
            runtime.execution_gateway.dependency_binding_validator,
            DependencyAdmissionGate,
        )
    finally:
        configure_capability_factory_runtime(None)


def test_local_experimental_bootstrap_rejects_unconfigured_supply_chain_verifier() -> None:
    """An experimental profile may not merely appear configured without a scanner."""

    from workbench.app import configure_local_experimental_capability_runtime

    with pytest.raises(ValueError, match="supply-chain verifier"):
        configure_local_experimental_capability_runtime(
            authority_id="authority.local.experimental",
            catalog=CapabilityBindingCatalog(verifier=lambda _binding: None),
            dependency_service=DependencyService(),
            binding_factory=lambda **_kwargs: None,
            enable=True,
        )


def test_dependency_admission_gate_forwards_exact_dispatch_bundle() -> None:
    from workbench.capability_factory.dependency_service import DependencyService

    service = DependencyService()
    calls: list[str] = []
    service.assert_execution_bundle = lambda bundle_ref: calls.append(bundle_ref)  # type: ignore[method-assign]
    gate = DependencyAdmissionGate(service)
    binding = type(
        "DispatchBinding",
        (),
        {"intent": type("Intent", (), {"bundle_ref": "a" * 64})()},
    )()

    gate(binding)
    assert calls == ["a" * 64]


def test_deployment_runtime_binds_external_authority_scanner_and_signed_report_source() -> None:
    """The product composes trusted deployment ports without shipping a key."""

    from datetime import datetime, timedelta, timezone

    from workbench.app import (
        app,
        configure_capability_factory_runtime,
        configure_deployment_capability_factory_runtime,
    )
    from workbench.capability_factory.dependency_service import (
        DependencyService,
        SupplyChainVerification,
    )
    from workbench.capability_factory.deployment_authority import (
        AttestationVerificationState,
        AuthenticatedContainmentReportVerifier,
        ExecutionResultAttestationBinding,
    )
    from workbench.custom_capability.contracts import (
        AttestationEnvelope,
        AuthorityTrustSnapshot,
        SCHEMA_VERSION,
    )
    from workbench.native_containment.contracts import ContainmentReport, ContainmentRequest, ResourceBudget
    from workbench.native_containment.host import CanaryResult
    from workbench.native_containment.policy import ContainmentPolicy

    now = datetime(2026, 7, 28, 9, 0, tzinfo=timezone.utc)

    class KeyProvider:
        def verify(self, payload, authentication, *, scheme, key_id, authority_id):
            assert payload
            return (
                authentication == "signed-by-external-provider"
                and scheme == "external-v1"
                and key_id == "external-key"
                and authority_id == "deployment-authority"
            )

    class Authority:
        authority_id = "deployment-authority"

        def authentication_verifier(self):
            return KeyProvider()

        def trust_snapshot(self):
            return AuthorityTrustSnapshot(
                snapshot_id="deployment-snapshot",
                authority_id=self.authority_id,
                allowed_kinds=frozenset({"execution_result"}),
                allowed_key_ids=frozenset({"external-key"}),
                allowed_auth_schemes=frozenset({"external-v1"}),
                valid_from=now - timedelta(minutes=1),
                valid_until=now + timedelta(minutes=5),
            )

        def verification_state(self):
            return AttestationVerificationState(
                now=now,
                minimum_control_sequence=7,
            )

        def verify_capability_binding(self, binding):
            assert binding is not None

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
        request_id="request.deployment",
        attempt_id="attempt.deployment",
        intent_digest="a" * 64,
        input_bundle_ref="b" * 64,
        output_namespace_ref="c" * 64,
        policy_digest=policy.content_digest,
        harness_digest="d" * 64,
    )
    report = ContainmentReport(
        attempt_id=request.attempt_id,
        request_digest=request.content_digest,
        status="completed",
        reason_code="NATIVE_CONTAINMENT_COMPLETED",
        assessment_ref="e" * 64,
        output_bundle_ref="f" * 64,
    )
    attestation_binding = ExecutionResultAttestationBinding(
        operation_id="model.custom",
        backend_subject_id="darwin-seatbelt",
        protocol_digest="1" * 64,
    )

    class SignedReportSource:
        def execution_result_attestation(self, *, report, request, policy, canary, binding):
            assert canary.status == "supported"
            return AttestationEnvelope(
                schema_version=SCHEMA_VERSION,
                attestation_kind="execution_result",
                authority_id="deployment-authority",
                key_id="external-key",
                auth_scheme="external-v1",
                issued_at=now,
                expires_at=now + timedelta(minutes=1),
                nonce="deployment-nonce",
                control_sequence=7,
                claims={
                    "binding": {
                        "intent_digest": request.intent_digest,
                        "attempt_id": request.attempt_id,
                        "input_bundle_digest": request.input_bundle_ref,
                        "operation_id": binding.operation_id,
                        "output_bundle_digest": report.output_bundle_ref,
                        "policy_digest": policy.content_digest,
                        "backend_subject_id": binding.backend_subject_id,
                        "protocol_digest": binding.protocol_digest,
                    },
                    "payload": {"status": report.status},
                },
                authentication="signed-by-external-provider",
            )

    authority = Authority()
    verifier = AuthenticatedContainmentReportVerifier(
        authority=authority,
        source=SignedReportSource(),
        binding=attestation_binding,
    )
    assert len(
        verifier(
            report=report,
            request=request,
            policy=policy,
            canary=CanaryResult(status="supported", reason_code="NATIVE_CONTAINMENT_CANARY_PASSED"),
        )
    ) == 64

    class Scanner:
        def verify(self, *, attestation, build):
            return SupplyChainVerification(
                authority_ref=attestation.authority_ref,
                decision_ref="2" * 64,
                status="passed",
                attestation_ref=attestation.content_digest,
                build_ref=build.content_digest,
                issued_at="2020-01-01T00:00:00Z",
                valid_until="2099-01-01T00:00:00Z",
                advisory_snapshot_ref="3" * 64,
            )

    received = {}

    def binding_factory(*, authority_report_verifier, **kwargs):
        received.update(kwargs)
        received["authority_report_verifier"] = authority_report_verifier
        return object()

    runtime = configure_deployment_capability_factory_runtime(
        authority=authority,
        dependency_service=DependencyService(supply_chain_verifier=Scanner()),
        binding_factory=binding_factory,
        report_attestation_source=SignedReportSource(),
        attestation_binding=attestation_binding,
    )
    try:
        assert runtime.authority_id == "deployment-authority"
        assert runtime.execution_enabled is True
        assert runtime.catalog.__class__.__name__ == "CapabilityBindingCatalog"
        assert runtime.execution_gateway.binding_factory(
            notebook_id="notebook-deployment",
            option_id="option-deployment",
            authorization=object(),
            materialization=object(),
            draft={},
            context=object(),
        ) is not None
        assert isinstance(
            received["authority_report_verifier"],
            AuthenticatedContainmentReportVerifier,
        )
    finally:
        configure_capability_factory_runtime(None)

    with pytest.raises(ValueError, match="supply-chain verifier"):
        configure_deployment_capability_factory_runtime(
            authority=authority,
            dependency_service=DependencyService(),
            binding_factory=binding_factory,
            report_attestation_source=SignedReportSource(),
            attestation_binding=attestation_binding,
        )


def test_controlled_fixture_promotes_generated_adapter_through_verified_to_approved(
    tmp_path,
) -> None:
    """Keep the local promotion proof independent of host containment availability."""

    from test_capability_adapter_contract import _consumer_support, _implementation
    from workbench.capability_factory.adapter_contract import (
        AdapterCandidateFactory,
        AdapterSourceGenerator,
    )
    from workbench.capability_factory.admission_contract import ScopedAdmissionRecord
    from workbench.capability_factory.implementation_sealer import ImplementationSealer
    from workbench.capability_factory.provenance import EvidenceProvenance, ProvenanceNode
    from workbench.capability_factory.validation_contract import ValidationCase, ValidationEvidence
    from workbench.capability_factory.validation_protocols import ValidationProtocol
    from workbench.capability_factory.validation_service import ValidationService

    implementation = _implementation()
    source = AdapterSourceGenerator().generate(
        implementation=implementation,
        provider=lambda _context: (
            "def fit(document):\n"
            "    values = document['payload']['values']\n"
            "    return {'count': len(values), 'total': sum(values)}\n"
        ),
        output_root=tmp_path / "generated-source",
    )
    generated = AdapterCandidateFactory().generate(
        implementation=implementation,
        adapter_id="adapter.fixture",
        adapter_revision=1,
        entrypoint_ref=source.entrypoint_ref,
        operations=("fit",),
        consumer_support=_consumer_support(),
        candidate_id="candidate.fixture",
        capability_kind="custom.model",
        source_ref=source.source_ref,
        author_lineage_ref="1" * 64,
        validation_bundle_id="validation.fixture",
        validation_cases=(
            ValidationCase(
                case_id="case.fixture.known_truth",
                fixture_ref="2" * 64,
                fixture_visibility="author_visible",
            ),
        ),
        source_artifact=source,
    )
    sealed = ImplementationSealer().seal(
        candidate=generated.candidate,
        adapter=generated.adapter,
        dependency_bundle_ref="3" * 64,
        runtime_policy_ref="4" * 64,
        environment_ref="5" * 64,
        source_ref=source.source_ref,
        code_ref=source.source_ref,
        manifest_ref="6" * 64,
    )
    case = generated.validation_bundle.cases[0]
    evidence = ValidationEvidence(
        evidence_id="evidence.fixture.oracle",
        case_ref=case.content_digest,
        tier="E2",
        status="passed",
        observed_ref="7" * 64,
        oracle_ref="8" * 64,
        oracle_kind="independent_implementation",
    )
    validation_bundle = generated.validation_bundle.append_evidence(evidence)
    provenance = EvidenceProvenance(
        evidence_ref=evidence.content_digest,
        author_root="author.fixture",
        oracle_root="oracle.fixture",
        nodes=(
            ProvenanceNode("author.fixture", "author", sealed.source_ref),
            ProvenanceNode("oracle.fixture", "oracle", evidence.oracle_ref),
        ),
    )
    protocol = ValidationProtocol(
        protocol_id="protocol.fixture",
        revision=1,
        check_kinds=("known_truth",),
        evidence_floor="E2",
        max_attempts=1,
        seed_policy_ref="9" * 64,
        threshold_policy_ref="a" * 64,
        holdout_policy_ref="b" * 64,
    )

    service = ValidationService()
    result = service.assess(
        sealed_bundle=sealed,
        validation_bundle=validation_bundle,
        protocol=protocol,
        producer_ref="c" * 64,
        provenance_by_evidence={evidence.content_digest: provenance},
    )
    assert generated.promotion_state == "experimental"
    assert generated.source_eligible is False
    assert result.promotion.state == "verified"
    assert result.promotion.source_eligible is True

    admission = ScopedAdmissionRecord(
        admission_id="admission.fixture",
        revision=1,
        adapter_ref=generated.adapter.content_digest,
        validation_bundle_ref=validation_bundle.content_digest,
        assessment_ref=result.assessment.content_digest,
        runtime_policy_ref="4" * 64,
        scope_kind="project",
        scope_ref="fixture-project",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=("report_projection",),
        status="admitted",
        approver_ref="human.fixture-review",
        approval_ref="d" * 64,
    )
    approved = service.promotion(result, admission=admission)
    assert approved.state == "approved"
    assert approved.source_eligible is True
    assert approved.execution_allowed is False
