from __future__ import annotations

from dataclasses import replace

import pytest


def _records():
    from workbench.capability_factory.adapter_contract import AdapterContract
    from workbench.capability_factory.admission_contract import CapabilityAdmissionController
    from workbench.capability_factory.contracts import ImplementationRevision, SemanticProfile
    from workbench.capability_factory.evidence_assessment import EvidenceAssessment as ValidationEvidenceAssessment
    from workbench.capability_factory.implementation_sealer import ImplementationBundleRevision
    from workbench.capability_factory.validation_contract import (
        ValidationBundle,
        ValidationCase,
        ValidationEvidence,
    )

    profile = SemanticProfile(
        profile_id="profile.registration",
        revision=1,
        input_kinds=("table",),
        operations=("fit",),
        output_facets=("estimate",),
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
        implementation_id="implementation.registration",
        revision=1,
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        profile_digest=profile.content_digest,
        input_schema_digest="1" * 64,
        source_kind="generated_adapter",
        trust_tier="generated_adapter",
        operations=("fit",),
        consumer_support=dict(profile.consumers),
        artifact_ref="2" * 64,
    )
    adapter = AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.registration",
        revision=1,
        entrypoint_ref="3" * 64,
        operations=("fit",),
        consumer_support=dict(profile.consumers),
    )
    case = ValidationCase(
        case_id="case.registration",
        fixture_ref="4" * 64,
        fixture_visibility="author_visible",
    )
    bundle = ValidationBundle(bundle_id="bundle.registration", revision=1, adapter_ref=adapter.content_digest, cases=(case,))
    evidence = ValidationEvidence(
        evidence_id="evidence.registration",
        case_ref=case.content_digest,
        tier="E2",
        status="passed",
        observed_ref="5" * 64,
        oracle_ref="6" * 64,
        oracle_kind="independent_implementation",
    )
    bundle = bundle.append_evidence(evidence)
    sealed_bundle = ImplementationBundleRevision(
        bundle_id="bundle.sealed.registration",
        revision=1,
        candidate_ref="a" * 64,
        adapter_ref=adapter.content_digest,
        implementation_ref=implementation.content_digest,
        dependency_bundle_ref="b" * 64,
        runtime_policy_ref="8" * 64,
        environment_ref="c" * 64,
        source_ref="d" * 64,
        code_ref="e" * 64,
        manifest_ref="f" * 64,
    )
    validation_assessment = ValidationEvidenceAssessment(
        assessment_id="assessment.validation.registration",
        bundle_ref=sealed_bundle.bundle_ref,
        protocol_ref="1" * 64,
        attempt_ledger_ref="2" * 64,
        tier="E2",
        status="passed",
        evidence_refs=(evidence.content_digest,),
        producer_ref="3" * 64,
    )
    controller = CapabilityAdmissionController()
    admission_assessment = controller.assess(
        adapter=adapter,
        validation_bundle=bundle,
        assessment_id="assessment.registration",
        assessment_rule_ref="7" * 64,
    )
    return implementation, adapter, bundle, sealed_bundle, validation_assessment, admission_assessment, controller


def test_registration_accepts_only_the_exact_validated_revision():
    from workbench.capability_factory.registry import CapabilityRegistry

    implementation, adapter, bundle, sealed_bundle, validation_assessment, assessment, _ = _records()
    registry = CapabilityRegistry()
    receipt = registry.register_validated(
        registration_id="registration.alpha",
        implementation=implementation,
        adapter=adapter,
        validation_bundle=bundle,
        sealed_bundle=sealed_bundle,
        evidence_assessment=validation_assessment,
        assessment=assessment,
        runtime_policy_ref="8" * 64,
        host_containment_ref="9" * 64,
    )

    assert registry.get_validated(receipt.implementation_ref) == receipt
    assert receipt.adapter_ref == adapter.content_digest
    assert registry.register_validated(
        registration_id="registration.alpha",
        implementation=implementation,
        adapter=adapter,
        validation_bundle=bundle,
        sealed_bundle=sealed_bundle,
        evidence_assessment=validation_assessment,
        assessment=assessment,
        runtime_policy_ref="8" * 64,
        host_containment_ref="9" * 64,
    ) == receipt


def test_registration_rejects_rebinding_or_successor_substitution():
    from workbench.capability_factory.registry import RegistryError, CapabilityRegistry

    implementation, adapter, bundle, sealed_bundle, validation_assessment, assessment, _ = _records()
    registry = CapabilityRegistry()
    registry.register_validated(
        registration_id="registration.alpha",
        implementation=implementation,
        adapter=adapter,
        validation_bundle=bundle,
        sealed_bundle=sealed_bundle,
        evidence_assessment=validation_assessment,
        assessment=assessment,
        runtime_policy_ref="8" * 64,
        host_containment_ref="9" * 64,
    )

    with pytest.raises(RegistryError, match="immutable"):
        registry.register_validated(
            registration_id="registration.alpha",
            implementation=implementation,
            adapter=adapter,
            validation_bundle=bundle,
            sealed_bundle=sealed_bundle,
            evidence_assessment=validation_assessment,
            assessment=assessment,
            runtime_policy_ref="8" * 64,
            host_containment_ref="a" * 64,
        )

    successor = replace(implementation, artifact_ref="a" * 64)
    with pytest.raises(RegistryError, match="binding"):
        registry.register_validated(
            registration_id="registration.alpha",
            implementation=successor,
            adapter=adapter,
            validation_bundle=bundle,
            sealed_bundle=sealed_bundle,
            evidence_assessment=validation_assessment,
            assessment=assessment,
            runtime_policy_ref="8" * 64,
            host_containment_ref="9" * 64,
        )
