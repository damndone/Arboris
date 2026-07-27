from __future__ import annotations


def _case(visibility="author_visible"):
    from workbench.capability_factory.validation_contract import ValidationCase

    return ValidationCase(case_id="case.one", fixture_ref="a" * 64, fixture_visibility=visibility)


def _protocol():
    from workbench.capability_factory.validation_protocols import ValidationProtocol

    return ValidationProtocol(
        protocol_id="protocol.one",
        revision=1,
        check_kinds=("known_truth",),
        evidence_floor="E1",
        max_attempts=2,
        seed_policy_ref="b" * 64,
        threshold_policy_ref="c" * 64,
        holdout_policy_ref="d" * 64,
    )


def _sealed(adapter_ref: str = "e" * 64):
    from workbench.capability_factory.implementation_sealer import ImplementationBundleRevision

    return ImplementationBundleRevision(
        bundle_id="bundle.validation",
        revision=1,
        candidate_ref="1" * 64,
        adapter_ref=adapter_ref,
        implementation_ref="2" * 64,
        dependency_bundle_ref="3" * 64,
        runtime_policy_ref="4" * 64,
        environment_ref="5" * 64,
        source_ref="6" * 64,
        code_ref="7" * 64,
        manifest_ref="8" * 64,
    )


def test_service_assesses_author_evidence_as_experimental():
    from workbench.capability_factory.validation_contract import ValidationBundle, ValidationEvidence
    from workbench.capability_factory.validation_service import ValidationService

    case = _case()
    bundle = ValidationBundle(
        bundle_id="validation.one",
        revision=1,
        adapter_ref="e" * 64,
        cases=(case,),
        evidence=(
            ValidationEvidence(
                evidence_id="evidence.one",
                case_ref=case.content_digest,
                tier="E1",
                status="passed",
                observed_ref="f" * 64,
            ),
        ),
    )
    result = ValidationService().assess(
        sealed_bundle=_sealed(),
        validation_bundle=bundle,
        protocol=_protocol(),
        producer_ref="2" * 64,
    )
    assert result.assessment.experimental is True
    assert result.assessment.source_eligible is False


def test_service_requires_independent_provenance_for_source_eligibility():
    from workbench.capability_factory.provenance import EvidenceProvenance, ProvenanceNode
    from workbench.capability_factory.validation_contract import ValidationBundle, ValidationEvidence
    from workbench.capability_factory.validation_protocols import ValidationProtocol
    from workbench.capability_factory.validation_service import ValidationService

    case = _case()
    evidence = ValidationEvidence(
        evidence_id="evidence.two",
        case_ref=case.content_digest,
        tier="E2",
        status="passed",
        observed_ref="f" * 64,
        oracle_ref="3" * 64,
        oracle_kind="independent_implementation",
    )
    bundle = ValidationBundle(
        bundle_id="validation.two",
        revision=1,
        adapter_ref="e" * 64,
        cases=(case,),
        evidence=(evidence,),
    )
    provenance = EvidenceProvenance(
        evidence_ref=evidence.content_digest,
        author_root="author",
        oracle_root="oracle",
        nodes=(
            ProvenanceNode("author", "author", "4" * 64),
            ProvenanceNode("oracle", "oracle", "3" * 64),
        ),
    )
    result = ValidationService().assess(
        sealed_bundle=_sealed(),
        validation_bundle=bundle,
        protocol=ValidationProtocol(
            protocol_id="protocol.two",
            revision=1,
            check_kinds=("known_truth",),
            evidence_floor="E2",
            max_attempts=2,
            seed_policy_ref="b" * 64,
            threshold_policy_ref="c" * 64,
            holdout_policy_ref="d" * 64,
        ),
        producer_ref="2" * 64,
        provenance_by_evidence={evidence.content_digest: provenance},
    )
    assert result.assessment.tier == "E2"
    assert result.assessment.source_eligible is True
