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

    catalog = CapabilityBindingCatalog(verifier=lambda _binding: None)
    dependency_service = DependencyService()
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
