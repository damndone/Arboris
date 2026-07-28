from __future__ import annotations

import pytest

from test_capability_implementation_registration import _records


def test_scoped_admission_consumes_only_registered_facts_and_rechecks_host_scope():
    from workbench.capability_factory.admission_service import AdmissionServiceError, ScopedAdmissionService
    from workbench.capability_factory.admission_contract import CapabilityAdmissionController
    from workbench.capability_factory.evidence_assessment import EvidenceValidityStore
    from workbench.capability_factory.registry import CapabilityRegistry
    from workbench.native_containment.host import (
        HostContainmentAssessment,
        HostContainmentValidityStore,
        HostIdentity,
    )

    implementation, adapter, bundle, sealed_bundle, validation_assessment, assessment, controller = _records()
    evidence_validity = EvidenceValidityStore()
    evidence_validity.append(
        assessment=validation_assessment,
        status="valid",
        reason="validation_passed",
        authority_ref="4" * 64,
    )
    host_assessment = HostContainmentAssessment(
        assessment_id="assessment.host.service",
        host=HostIdentity(
            os_name="Darwin",
            kernel_release="test-kernel",
            architecture="arm64",
            backend_executable="/usr/bin/sandbox-exec",
            backend_version="1",
            backend_digest="5" * 64,
        ),
        profile_id="strict-readonly-v1",
        canary_suite_ref="6" * 64,
        outcome="supported",
        reason_code="NATIVE_CONTAINMENT_CANARY_PASSED",
        validity_revision=1,
        control_sequence=1,
    )
    host_validity = HostContainmentValidityStore()
    host_record = host_validity.append(
        assessment=host_assessment,
        status="valid",
        reason_code="canary_passed",
        authority_ref="7" * 64,
        control_sequence=1,
    )
    host_ref = host_record.content_digest
    registry = CapabilityRegistry()
    registration = registry.register_validated(
        registration_id="registration.service",
        implementation=implementation,
        adapter=adapter,
        validation_bundle=bundle,
        sealed_bundle=sealed_bundle,
        evidence_assessment=validation_assessment,
        assessment=assessment,
        runtime_policy_ref="8" * 64,
        host_containment_ref=host_ref,
    )
    service = ScopedAdmissionService(
        registry=registry,
        controller=controller,
        evidence_validity=evidence_validity,
        host_validity=host_validity,
    )

    proposed = service.propose(
        registration=registration,
        adapter=adapter,
        validation_bundle=bundle,
        sealed_bundle=sealed_bundle,
        evidence_assessment=validation_assessment,
        assessment=assessment,
        host_containment_ref=host_ref,
        admission_id="admission.service",
        scope_kind="project",
        scope_ref="project.alpha",
        minimum_evidence_tier="E2",
        allowed_operations=("fit",),
        allowed_consumers=("report_projection",),
    )
    admitted = service.admit(proposed.admission_id, approver_ref="human.ui", approval_ref="a" * 64)
    service.assert_usable(
        admitted,
        registration=registration,
        adapter=adapter,
        validation_bundle=bundle,
        sealed_bundle=sealed_bundle,
        evidence_assessment=validation_assessment,
        assessment=assessment,
        host_containment_ref=host_ref,
        runtime_policy_ref="8" * 64,
        scope_kind="project",
        scope_ref="project.alpha",
        requested_operations=("fit",),
        requested_consumers=("report_projection",),
    )
    assert admitted.execution_allowed is False

    host_validity.append(
        assessment=host_assessment,
        status="expired",
        reason_code="lease_expired",
        authority_ref="8" * 64,
        control_sequence=2,
    )
    with pytest.raises(AdmissionServiceError, match="host containment validity"):
        service.assert_usable(
            admitted,
            registration=registration,
            adapter=adapter,
            validation_bundle=bundle,
            sealed_bundle=sealed_bundle,
            evidence_assessment=validation_assessment,
            assessment=assessment,
            host_containment_ref=host_ref,
            runtime_policy_ref="8" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
            requested_operations=("fit",),
            requested_consumers=("report_projection",),
        )

    evidence_validity.append(
        assessment=validation_assessment,
        status="invalid",
        reason="oracle_withdrawn",
        authority_ref="9" * 64,
    )
    with pytest.raises(AdmissionServiceError, match="evidence validity"):
        service.assert_usable(
            admitted,
            registration=registration,
            adapter=adapter,
            validation_bundle=bundle,
            sealed_bundle=sealed_bundle,
            evidence_assessment=validation_assessment,
            assessment=assessment,
            host_containment_ref=host_ref,
            runtime_policy_ref="8" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
            requested_operations=("fit",),
            requested_consumers=("report_projection",),
        )

    with pytest.raises(AdmissionServiceError, match="host containment"):
        service.assert_usable(
            admitted,
            registration=registration,
            adapter=adapter,
            validation_bundle=bundle,
            sealed_bundle=sealed_bundle,
            evidence_assessment=validation_assessment,
            assessment=assessment,
            host_containment_ref="b" * 64,
            runtime_policy_ref="8" * 64,
            scope_kind="project",
            scope_ref="project.alpha",
            requested_operations=("fit",),
            requested_consumers=("report_projection",),
        )


def test_scoped_admission_rejects_unregistered_or_revoked_facts():
    from workbench.capability_factory.admission_service import AdmissionServiceError, ScopedAdmissionService
    from workbench.capability_factory.admission_contract import CapabilityAdmissionController
    from workbench.capability_factory.evidence_assessment import EvidenceValidityStore
    from workbench.capability_factory.registry import CapabilityRegistry
    from workbench.native_containment.host import HostContainmentValidityStore

    implementation, adapter, bundle, sealed_bundle, validation_assessment, assessment, _ = _records()
    registry = CapabilityRegistry()
    controller = CapabilityAdmissionController()
    service = ScopedAdmissionService(
        registry=registry,
        controller=controller,
        evidence_validity=EvidenceValidityStore(),
        host_validity=HostContainmentValidityStore(),
    )
    with pytest.raises(AdmissionServiceError, match="registration"):
        service.propose(
            registration=object(),
            adapter=adapter,
            validation_bundle=bundle,
            sealed_bundle=sealed_bundle,
            evidence_assessment=validation_assessment,
            assessment=assessment,
            host_containment_ref="9" * 64,
            admission_id="admission.unregistered",
            scope_kind="project",
            scope_ref="project.alpha",
            minimum_evidence_tier="E2",
            allowed_operations=("fit",),
            allowed_consumers=(),
        )
