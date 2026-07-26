from __future__ import annotations

from dataclasses import replace

import pytest


def _adapter():
    from workbench.capability_factory.adapter_contract import AdapterContract
    from workbench.capability_factory.contracts import (
        CapabilityRequirementRevision,
        ImplementationRevision,
        SemanticProfile,
    )

    profile = SemanticProfile(
        profile_id="profile.admission",
        revision=1,
        input_kinds=("table",),
        operations=("fit", "predict"),
        output_facets=("parameters", "predictions"),
        assumptions=(),
        consumers={
            "report_projection": "report.generic.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )
    requirement = CapabilityRequirementRevision(
        requirement_id="requirement.admission",
        revision=1,
        semantic_profile=profile,
        requested_operations=("fit",),
        requested_consumers=("report_projection",),
        input_schema={"value": "table"},
    )
    implementation = ImplementationRevision(
        implementation_id="implementation.admission",
        revision=1,
        profile_id=profile.profile_id,
        profile_revision=profile.revision,
        profile_digest=profile.content_digest,
        input_schema_digest=requirement.input_schema_digest,
        source_kind="generated_adapter",
        trust_tier="generated_adapter",
        operations=("fit", "predict"),
        consumer_support={
            "report_projection": "report.generic.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
        artifact_ref="a" * 64,
    )
    return AdapterContract.from_implementation(
        implementation=implementation,
        adapter_id="adapter.admission",
        revision=1,
        entrypoint_ref="b" * 64,
        operations=("fit", "predict"),
        consumer_support={
            "report_projection": "adapter.report.v1",
            "diagnostic_adapter": None,
            "figure_provider": None,
            "compare_adapter": None,
        },
    )


def _bundle(adapter, *, independent: bool, case_count: int = 1):
    from workbench.capability_factory.validation_contract import (
        ValidationBundle,
        ValidationCase,
        ValidationEvidence,
    )

    cases = tuple(
        ValidationCase(
            case_id=f"case.admission.{index}",
            fixture_ref=(hex(index + 12)[2:] * 64)[:64],
            fixture_visibility="author_visible",
        )
        for index in range(case_count)
    )
    bundle = ValidationBundle(
        bundle_id="bundle.admission",
        revision=1,
        adapter_ref=adapter.content_digest,
        cases=cases,
    )
    for index, case in enumerate(cases):
        evidence = ValidationEvidence(
            evidence_id=f"evidence.admission.{index}",
            case_ref=case.content_digest,
            tier="E2" if independent else "E1",
            status="passed",
            observed_ref=(hex(index + 32)[2:] * 64)[:64],
            oracle_ref=((hex(index + 48)[2:] * 64)[:64] if independent else None),
            oracle_kind="independent_implementation" if independent else None,
        )
        bundle = bundle.append_evidence(evidence)
    return bundle


def test_assessment_is_server_derived_and_keeps_evidence_separate_from_admission():
    from workbench.capability_factory.admission_contract import (
        CapabilityAdmissionController,
    )

    adapter = _adapter()
    experimental_bundle = _bundle(adapter, independent=False)
    controller = CapabilityAdmissionController()
    experimental = controller.assess(
        adapter=adapter,
        validation_bundle=experimental_bundle,
        assessment_id="assessment.experimental",
        assessment_rule_ref="c" * 64,
    )
    assert experimental.tier == "E1"
    assert experimental.source_eligible is False

    verified_bundle = _bundle(adapter, independent=True, case_count=2)
    verified = controller.assess(
        adapter=adapter,
        validation_bundle=verified_bundle,
        assessment_id="assessment.verified",
        assessment_rule_ref="c" * 64,
    )
    assert verified.tier == "E2"
    assert verified.source_eligible is True
    assert verified.validation_bundle_ref == verified_bundle.content_digest
    assert len(verified.evidence_refs) == 2


def test_scoped_admission_requires_fresh_assessment_and_declared_capabilities():
    from workbench.capability_factory.admission_contract import (
        AdmissionContractError,
        CapabilityAdmissionController,
    )

    adapter = _adapter()
    bundle = _bundle(adapter, independent=True, case_count=2)
    controller = CapabilityAdmissionController()
    assessment = controller.assess(
        adapter=adapter,
        validation_bundle=bundle,
        assessment_id="assessment.scope",
        assessment_rule_ref="c" * 64,
    )
    record = controller.propose(
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission_id="admission.scope",
        runtime_policy_ref="d" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=("report_projection",),
    )
    assert record.status == "proposed"
    admitted = controller.admit(
        record.admission_id,
        approver_ref="human_ui",
        approval_ref="e" * 64,
    )
    assert admitted.status == "admitted"
    assert admitted.minimum_evidence_tier == "E2"
    controller.assert_usable(
        admitted,
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        runtime_policy_ref="d" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
        requested_operations=("fit",),
        requested_consumers=("report_projection",),
    )
    with pytest.raises(AdmissionContractError, match="scope"):
        controller.assert_usable(
            admitted,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            runtime_policy_ref="d" * 64,
            scope_kind="project",
            scope_ref="project.other",
            requested_operations=("fit",),
            requested_consumers=("report_projection",),
        )
    with pytest.raises(AdmissionContractError, match="operation"):
        controller.assert_usable(
            admitted,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            runtime_policy_ref="d" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
            requested_operations=("predict",),
            requested_consumers=(),
        )


def test_invalidated_evidence_blocks_new_admission_and_existing_use():
    from workbench.capability_factory.admission_contract import (
        AdmissionContractError,
        CapabilityAdmissionController,
    )

    adapter = _adapter()
    bundle = _bundle(adapter, independent=True, case_count=2)
    controller = CapabilityAdmissionController()
    assessment = controller.assess(
        adapter=adapter,
        validation_bundle=bundle,
        assessment_id="assessment.invalidated",
        assessment_rule_ref="c" * 64,
    )
    record = controller.propose(
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission_id="admission.invalidated",
        runtime_policy_ref="d" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=(),
    )
    admitted = controller.admit(record.admission_id, approver_ref="human_ui", approval_ref="e" * 64)
    controller.invalidate(assessment.content_digest, reason_ref="f" * 64)
    with pytest.raises(AdmissionContractError, match="validity"):
        controller.assert_usable(
            admitted,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            runtime_policy_ref="d" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
            requested_operations=("fit",),
            requested_consumers=(),
        )
    with pytest.raises(AdmissionContractError, match="validity"):
        controller.propose(
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            admission_id="admission.after-invalidity",
            runtime_policy_ref="d" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
            minimum_evidence_tier="E2",
            allowed_operations=("fit",),
            allowed_consumers=(),
        )


def test_experimental_admission_does_not_make_e1_source_eligible():
    from workbench.capability_factory.admission_contract import (
        AdmissionContractError,
        CapabilityAdmissionController,
    )

    adapter = _adapter()
    bundle = _bundle(adapter, independent=False)
    controller = CapabilityAdmissionController()
    assessment = controller.assess(
        adapter=adapter,
        validation_bundle=bundle,
        assessment_id="assessment.experimental-admission",
        assessment_rule_ref="c" * 64,
    )
    record = controller.propose(
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission_id="admission.experimental",
        runtime_policy_ref="d" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
        minimum_evidence_tier="E1",
        allowed_operations=("fit",),
        allowed_consumers=(),
    )
    admitted = controller.admit(record.admission_id, approver_ref="human_ui", approval_ref="e" * 64)
    assert admitted.status == "admitted"
    assert assessment.tier == "E1"
    assert assessment.source_eligible is False
    with pytest.raises(AdmissionContractError, match="evidence tier"):
        controller.propose(
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            admission_id="admission.experimental-as-verified",
            runtime_policy_ref="d" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
            minimum_evidence_tier="E2",
            allowed_operations=("fit",),
            allowed_consumers=(),
        )


def test_usable_admission_must_be_the_current_controller_record():
    from workbench.capability_factory.admission_contract import (
        AdmissionContractError,
        CapabilityAdmissionController,
    )

    adapter = _adapter()
    bundle = _bundle(adapter, independent=True, case_count=2)
    controller = CapabilityAdmissionController()
    assessment = controller.assess(
        adapter=adapter,
        validation_bundle=bundle,
        assessment_id="assessment.current-record",
        assessment_rule_ref="c" * 64,
    )
    proposed = controller.propose(
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission_id="admission.current-record",
        runtime_policy_ref="d" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=(),
    )
    admitted = controller.admit(
        proposed.admission_id,
        approver_ref="human_ui",
        approval_ref="e" * 64,
    )
    forged = replace(admitted, revision=admitted.revision + 1)
    with pytest.raises(AdmissionContractError, match="current"):
        controller.assert_usable(
            forged,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            runtime_policy_ref="d" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
            requested_operations=("fit",),
            requested_consumers=(),
        )


def test_usable_admission_requires_the_bound_runtime_policy():
    from workbench.capability_factory.admission_contract import (
        AdmissionContractError,
        CapabilityAdmissionController,
    )

    adapter = _adapter()
    bundle = _bundle(adapter, independent=True, case_count=2)
    controller = CapabilityAdmissionController()
    assessment = controller.assess(
        adapter=adapter,
        validation_bundle=bundle,
        assessment_id="assessment.runtime-policy",
        assessment_rule_ref="c" * 64,
    )
    proposed = controller.propose(
        adapter=adapter,
        validation_bundle=bundle,
        assessment=assessment,
        admission_id="admission.runtime-policy",
        runtime_policy_ref="d" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=(),
    )
    admitted = controller.admit(
        proposed.admission_id,
        approver_ref="human_ui",
        approval_ref="e" * 64,
    )
    with pytest.raises(AdmissionContractError, match="runtime policy"):
        controller.assert_usable(
            admitted,
            adapter=adapter,
            validation_bundle=bundle,
            assessment=assessment,
            runtime_policy_ref="f" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
            requested_operations=("fit",),
            requested_consumers=(),
        )
