from __future__ import annotations


def _case(visibility="author_visible"):
    from workbench.capability_factory.validation_contract import ValidationCase

    return ValidationCase(case_id="case.one", fixture_ref="a" * 64, fixture_visibility=visibility)


def _protocol(evidence_floor="E1"):
    from workbench.capability_factory.validation_protocols import ValidationProtocol

    return ValidationProtocol(
        protocol_id="protocol.one",
        revision=1,
        check_kinds=("known_truth",),
        evidence_floor=evidence_floor,
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


def test_service_marks_complete_independent_e2_evidence_verified_without_holdout():
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
    assert result.verified is True
    assert result.promotion.state == "verified"


def test_service_promotes_complete_independent_e2_evidence_without_holdout():
    from workbench.capability_factory.provenance import EvidenceProvenance, ProvenanceNode
    from workbench.capability_factory.validation_contract import ValidationBundle, ValidationEvidence
    from workbench.capability_factory.validation_protocols import ValidationProtocol
    from workbench.capability_factory.validation_service import ValidationService

    case = _case()
    evidence = ValidationEvidence(
        evidence_id="evidence.verified",
        case_ref=case.content_digest,
        tier="E2",
        status="passed",
        observed_ref="f" * 64,
        oracle_ref="3" * 64,
        oracle_kind="independent_implementation",
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
        validation_bundle=ValidationBundle(
            bundle_id="validation.verified",
            revision=1,
            adapter_ref="e" * 64,
            cases=(case,),
            evidence=(evidence,),
        ),
        protocol=ValidationProtocol(
            protocol_id="protocol.verified",
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

    assert result.promotion.state == "verified"
    assert result.promotion.source_eligible is True
    assert result.promotion.execution_allowed is False


def test_service_requires_service_holdout_for_e3_verification():
    from workbench.capability_factory.provenance import EvidenceProvenance, ProvenanceNode
    from workbench.capability_factory.validation_contract import ValidationBundle, ValidationEvidence
    from workbench.capability_factory.validation_protocols import ValidationProtocol
    from workbench.capability_factory.validation_service import ValidationService

    case = _case()
    evidence = ValidationEvidence(
        evidence_id="evidence.missing-holdout",
        case_ref=case.content_digest,
        tier="E2",
        status="passed",
        observed_ref="f" * 64,
        oracle_ref="3" * 64,
        oracle_kind="independent_implementation",
    )
    result = ValidationService().assess(
        sealed_bundle=_sealed(),
        validation_bundle=ValidationBundle(
            bundle_id="validation.missing-holdout",
            revision=1,
            adapter_ref="e" * 64,
            cases=(case,),
            evidence=(evidence,),
        ),
        protocol=ValidationProtocol(
            protocol_id="protocol.holdout-required",
            revision=1,
            check_kinds=("known_truth",),
            evidence_floor="E3",
            max_attempts=2,
            seed_policy_ref="b" * 64,
            threshold_policy_ref="c" * 64,
            holdout_policy_ref="d" * 64,
        ),
        producer_ref="2" * 64,
        provenance_by_evidence={
            evidence.content_digest: EvidenceProvenance(
                evidence_ref=evidence.content_digest,
                author_root="author",
                oracle_root="oracle",
                nodes=(
                    ProvenanceNode("author", "author", "4" * 64),
                    ProvenanceNode("oracle", "oracle", "3" * 64),
                ),
            )
        },
    )

    assert result.assessment.status == "inconclusive"
    assert result.promotion.state == "experimental"
    assert result.promotion.source_eligible is False


def test_service_requires_a_bound_server_admission_fact_for_approved():
    from workbench.capability_factory.admission_contract import ScopedAdmissionRecord
    from workbench.capability_factory.provenance import EvidenceProvenance, ProvenanceNode
    from workbench.capability_factory.validation_contract import ValidationBundle, ValidationEvidence
    from workbench.capability_factory.validation_protocols import ValidationProtocol
    from workbench.capability_factory.validation_service import ValidationService

    case = _case(visibility="service_holdout")
    evidence = ValidationEvidence(
        evidence_id="evidence.approval",
        case_ref=case.content_digest,
        tier="E2",
        status="passed",
        observed_ref="f" * 64,
        oracle_ref="3" * 64,
        oracle_kind="independent_implementation",
        fixture_visibility="service_holdout",
    )
    service = ValidationService()
    bundle = ValidationBundle(
        bundle_id="validation.approval",
        revision=1,
        adapter_ref="e" * 64,
        cases=(case,),
        evidence=(evidence,),
    )
    result = service.assess(
        sealed_bundle=_sealed(),
        validation_bundle=bundle,
        protocol=ValidationProtocol(
            protocol_id="protocol.approval",
            revision=1,
            check_kinds=("known_truth",),
            evidence_floor="E2",
            max_attempts=2,
            seed_policy_ref="b" * 64,
            threshold_policy_ref="c" * 64,
            holdout_policy_ref="d" * 64,
        ),
        producer_ref="2" * 64,
        provenance_by_evidence={
            evidence.content_digest: EvidenceProvenance(
                evidence_ref=evidence.content_digest,
                author_root="author",
                oracle_root="oracle",
                nodes=(
                    ProvenanceNode("author", "author", "4" * 64),
                    ProvenanceNode("oracle", "oracle", "3" * 64),
                ),
            )
        },
    )
    admission = ScopedAdmissionRecord(
        admission_id="admission.service-approved",
        revision=1,
        adapter_ref="e" * 64,
        validation_bundle_ref=result.validation_bundle_ref,
        assessment_ref=result.assessment.content_digest,
        runtime_policy_ref="7" * 64,
        scope_kind="project",
        scope_ref="project.one",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=(),
        status="admitted",
        approver_ref="server.reviewer",
        approval_ref="8" * 64,
    )
    approved = service.promotion(result, admission=admission)

    assert approved.state == "approved"
    assert approved.source_eligible is True
    assert approved.execution_allowed is False



def test_service_does_not_pass_a_validation_bundle_with_missing_or_duplicate_case_evidence():
    from workbench.capability_factory.validation_contract import ValidationBundle, ValidationEvidence
    from workbench.capability_factory.validation_service import ValidationService

    first = _case()
    second = _case()
    second = type(second)(
        case_id="case.two",
        fixture_ref="1" * 64,
        fixture_visibility="author_visible",
    )
    evidence = ValidationEvidence(
        evidence_id="evidence.partial",
        case_ref=first.content_digest,
        tier="E1",
        status="passed",
        observed_ref="f" * 64,
    )
    partial = ValidationBundle(
        bundle_id="validation.partial",
        revision=1,
        adapter_ref="e" * 64,
        cases=(first, second),
        evidence=(evidence,),
    )
    result = ValidationService().assess(
        sealed_bundle=_sealed(),
        validation_bundle=partial,
        protocol=_protocol(),
        producer_ref="2" * 64,
    )
    assert result.assessment.status == "inconclusive"
    assert result.assessment.source_eligible is False

    duplicate = ValidationBundle(
        bundle_id="validation.duplicate",
        revision=1,
        adapter_ref="e" * 64,
        cases=(first,),
        evidence=(
            evidence,
            ValidationEvidence(
                evidence_id="evidence.duplicate",
                case_ref=first.content_digest,
                tier="E1",
                status="passed",
                observed_ref="0" * 64,
            ),
        ),
    )
    duplicate_result = ValidationService().assess(
        sealed_bundle=_sealed(),
        validation_bundle=duplicate,
        protocol=_protocol(),
        producer_ref="2" * 64,
    )
    assert duplicate_result.assessment.status == "inconclusive"


def test_service_requires_validation_case_coverage_for_every_protocol_check():
    from workbench.capability_factory.validation_contract import ValidationBundle, ValidationEvidence
    from workbench.capability_factory.validation_protocols import ValidationProtocol
    from workbench.capability_factory.validation_service import ValidationService

    case = _case()
    bundle = ValidationBundle(
        bundle_id="validation.missing-check",
        revision=1,
        adapter_ref="e" * 64,
        cases=(case,),
        evidence=(
            ValidationEvidence(
                evidence_id="evidence.only-known-truth",
                case_ref=case.content_digest,
                tier="E1",
                status="passed",
                observed_ref="f" * 64,
            ),
        ),
    )
    protocol = ValidationProtocol(
        protocol_id="protocol.requires-two-checks",
        revision=1,
        check_kinds=("known_truth", "boundary_error"),
        evidence_floor="E1",
        max_attempts=2,
        seed_policy_ref="b" * 64,
        threshold_policy_ref="c" * 64,
        holdout_policy_ref="d" * 64,
    )

    result = ValidationService().assess(
        sealed_bundle=_sealed(),
        validation_bundle=bundle,
        protocol=protocol,
        producer_ref="2" * 64,
    )

    assert result.assessment.status == "inconclusive"


def test_validation_runner_fails_closed_when_containment_is_unsupported():
    from workbench.capability_factory.validation_runner import ValidationRunner
    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.contracts import ContainmentReport, ContainmentRequest, ResourceBudget
    from workbench.native_containment.host import CanaryResult
    from workbench.native_containment.policy import ContainmentPolicy

    sealed = _sealed()
    protocol = _protocol()
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
        budget=ResourceBudget(1, 1, 1, 1, 1, 1),
        allow_weaker_fallback=False,
    )
    request = ContainmentRequest(
        request_id="request.validation",
        attempt_id="attempt.validation",
        intent_digest=sealed.bundle_ref,
        input_bundle_ref=sealed.bundle_ref,
        output_namespace_ref="9" * 64,
        policy_digest=policy.content_digest,
        harness_digest="8" * 64,
    )
    broker = ContainmentBroker(
        host_assessor=lambda _policy: CanaryResult.unsupported("NATIVE_CONTAINMENT_RESOURCE_LIMIT_UNAVAILABLE"),
        executor=lambda *_args: ContainmentReport(
            attempt_id="attempt.validation",
            request_digest=request.content_digest,
            status="completed",
            reason_code="should-not-run",
            assessment_ref="7" * 64,
            output_bundle_ref="6" * 64,
        ),
    )

    result = ValidationRunner().run(
        sealed_bundle=sealed,
        protocol=protocol,
        request=request,
        policy=policy,
        broker=broker,
    )

    assert result.status == "unsupported"
    assert result.reason_code == "NATIVE_CONTAINMENT_RESOURCE_LIMIT_UNAVAILABLE"
    assert result.output_bundle_ref is None


def test_validation_runner_rejects_a_report_bound_to_another_attempt_or_request():
    from workbench.capability_factory.validation_runner import ValidationRunner
    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.contracts import ContainmentReport, ContainmentRequest, ResourceBudget
    from workbench.native_containment.host import CanaryResult
    from workbench.native_containment.policy import ContainmentPolicy

    sealed = _sealed()
    protocol = _protocol()
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
        budget=ResourceBudget(1, 1, 1, 1, 1, 1),
        allow_weaker_fallback=False,
    )
    request = ContainmentRequest(
        request_id="request.mismatch",
        attempt_id="attempt.expected",
        intent_digest=sealed.bundle_ref,
        input_bundle_ref=sealed.bundle_ref,
        output_namespace_ref="9" * 64,
        policy_digest=policy.content_digest,
        harness_digest="8" * 64,
    )
    report = ContainmentReport(
        attempt_id="attempt.other",
        request_digest="0" * 64,
        status="completed",
        reason_code="forged_or_misrouted_report",
        assessment_ref="7" * 64,
        output_bundle_ref="6" * 64,
    )
    class MisroutingBroker(ContainmentBroker):
        def run(self, _request, _policy):
            return report

    broker = MisroutingBroker(
        host_assessor=lambda _policy: CanaryResult("supported", "canary_passed"),
        executor=None,
    )

    result = ValidationRunner().run(
        sealed_bundle=sealed,
        protocol=protocol,
        request=request,
        policy=policy,
        broker=broker,
    )

    assert result.status == "failed"
    assert result.reason_code == "NATIVE_CONTAINMENT_REPORT_MISMATCH"
    assert result.report_ref is None
    assert result.output_bundle_ref is None


def test_validation_harness_marks_e2_independent_oracle_verified_without_holdout():
    from workbench.capability_factory.validation_runner import (
        OracleObservation,
        ValidationRunner,
    )
    from workbench.capability_factory.validation_contract import ValidationBundle
    from workbench.native_containment.broker import ContainmentBroker
    from workbench.native_containment.contracts import ContainmentReport, ContainmentRequest, ResourceBudget
    from workbench.native_containment.host import CanaryResult
    from workbench.native_containment.policy import ContainmentPolicy

    sealed = _sealed()
    case = _case()
    bundle = ValidationBundle(
        bundle_id="validation.harness",
        revision=1,
        adapter_ref=sealed.adapter_ref,
        cases=(case,),
    )
    protocol = _protocol(evidence_floor="E2")
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
        budget=ResourceBudget(1, 1, 1, 1, 1, 1),
        allow_weaker_fallback=False,
    )
    request = ContainmentRequest(
        request_id="request.harness",
        attempt_id="attempt.harness",
        intent_digest=sealed.bundle_ref,
        input_bundle_ref=sealed.bundle_ref,
        output_namespace_ref="9" * 64,
        policy_digest=policy.content_digest,
        harness_digest="8" * 64,
    )
    report = ContainmentReport(
        attempt_id=request.attempt_id,
        request_digest=request.content_digest,
        status="completed",
        reason_code="contained_validation_completed",
        assessment_ref="7" * 64,
        output_bundle_ref="6" * 64,
    )
    broker = ContainmentBroker(
        host_assessor=lambda _policy: CanaryResult("supported", "canary_passed"),
        executor=lambda *_args: report,
    )

    class Oracle:
        def evaluate(self, **kwargs):
            assert kwargs["output_bundle_ref"] == report.output_bundle_ref
            return OracleObservation(
                observed_ref="5" * 64,
                oracle_ref="4" * 64,
                oracle_kind="independent_implementation",
                status="passed",
            )

    result = ValidationRunner().run_with_oracle(
        sealed_bundle=sealed,
        validation_bundle=bundle,
        protocol=protocol,
        request=request,
        policy=policy,
        broker=broker,
        oracle=Oracle(),
    )

    assert result.execution.status == "completed"
    assert len(result.validation_bundle.evidence) == 1
    assert result.validation_bundle.evidence[0].tier == "E2"
    assert result.validation_bundle.evidence[0].oracle_ref == "4" * 64
    assert result.verified is True
    assert result.assessment_ref
    assert result.promotion_state == "verified"
    assert result.execution_allowed is False


def test_validation_e2_with_independent_oracle_is_verified_without_holdout():
    from workbench.capability_factory.provenance import EvidenceProvenance, ProvenanceNode
    from workbench.capability_factory.validation_contract import ValidationBundle, ValidationEvidence
    from workbench.capability_factory.validation_protocols import ValidationProtocol
    from workbench.capability_factory.validation_service import ValidationService

    case = _case(visibility="author_visible")
    evidence = ValidationEvidence(
        evidence_id="evidence.no-holdout",
        case_ref=case.content_digest,
        tier="E2",
        status="passed",
        observed_ref="f" * 64,
        oracle_ref="3" * 64,
        oracle_kind="independent_implementation",
    )
    bundle = ValidationBundle(
        bundle_id="validation.no-holdout",
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
            protocol_id="protocol.e2-without-holdout",
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

    assert result.verified is True
    assert result.promotion.state == "verified"
    assert result.promotion.source_eligible is True


def test_approved_is_derived_only_from_server_admission_and_remains_execution_closed():
    from workbench.capability_factory.admission_contract import ScopedAdmissionRecord
    from workbench.capability_factory.provenance import EvidenceProvenance, ProvenanceNode
    from workbench.capability_factory.validation_contract import ValidationBundle, ValidationEvidence
    from workbench.capability_factory.validation_protocols import ValidationProtocol
    from workbench.capability_factory.validation_service import ValidationService

    case = _case(visibility="service_holdout")
    evidence = ValidationEvidence(
        evidence_id="evidence.approved",
        case_ref=case.content_digest,
        tier="E2",
        status="passed",
        observed_ref="f" * 64,
        oracle_ref="3" * 64,
        oracle_kind="independent_implementation",
        fixture_visibility="service_holdout",
    )
    bundle = ValidationBundle(
        bundle_id="validation.approved",
        revision=1,
        adapter_ref="e" * 64,
        cases=(case,),
        evidence=(evidence,),
    )
    protocol = ValidationProtocol(
        protocol_id="protocol.approved",
        revision=1,
        check_kinds=("known_truth",),
        evidence_floor="E2",
        max_attempts=2,
        seed_policy_ref="b" * 64,
        threshold_policy_ref="c" * 64,
        holdout_policy_ref="d" * 64,
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
    service = ValidationService()
    result = service.assess(
        sealed_bundle=_sealed(),
        validation_bundle=bundle,
        protocol=protocol,
        producer_ref="2" * 64,
        provenance_by_evidence={evidence.content_digest: provenance},
    )
    admission = ScopedAdmissionRecord(
        admission_id="admission.approved",
        revision=1,
        adapter_ref="e" * 64,
        validation_bundle_ref=bundle.content_digest,
        assessment_ref=result.assessment.content_digest,
        runtime_policy_ref="7" * 64,
        scope_kind="project",
        scope_ref="project.one",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=(),
        status="admitted",
        approver_ref="human.review",
        approval_ref="8" * 64,
    )

    promotion = service.promotion(result, admission=admission)

    assert result.verified is True
    assert promotion.state == "approved"
    assert promotion.approval_ref == "8" * 64
    assert promotion.execution_allowed is False
