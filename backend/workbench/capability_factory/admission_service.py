"""CF3B exact-registration and scoped-admission control service."""

from __future__ import annotations

from .adapter_contract import AdapterContract
from .admission_contract import (
    AdmissionContractError,
    CapabilityAdmissionController,
    EvidenceAssessment as AdmissionEvidenceAssessment,
    ScopedAdmissionRecord,
)
from .evidence_assessment import EvidenceAssessment as ValidationEvidenceAssessment
from .evidence_assessment import EvidenceAssessmentError, EvidenceValidityStore
from .implementation_sealer import ImplementationBundleRevision
from ..native_containment.host import HostAssessmentError, HostContainmentValidityStore
from .registry import CapabilityRegistry, RegistryError, ValidatedRegistrationReceipt
from .validation_contract import ValidationBundle


class AdmissionServiceError(ValueError):
    """Raised when registration, evidence, host, or scope facts do not bind."""


class ScopedAdmissionService:
    """Join exact validated registration facts with the existing admission FSM."""

    def __init__(
        self,
        *,
        registry: CapabilityRegistry,
        controller: CapabilityAdmissionController,
        evidence_validity: EvidenceValidityStore,
        host_validity: HostContainmentValidityStore,
    ) -> None:
        if not isinstance(registry, CapabilityRegistry):
            raise AdmissionServiceError("registry must be a CapabilityRegistry")
        if not isinstance(controller, CapabilityAdmissionController):
            raise AdmissionServiceError("controller must be a CapabilityAdmissionController")
        if not isinstance(evidence_validity, EvidenceValidityStore):
            raise AdmissionServiceError("evidence_validity must be an EvidenceValidityStore")
        if not isinstance(host_validity, HostContainmentValidityStore):
            raise AdmissionServiceError("host_validity must be a HostContainmentValidityStore")
        self.registry = registry
        self.controller = controller
        self.evidence_validity = evidence_validity
        self.host_validity = host_validity

    def propose(
        self,
        *,
        registration: ValidatedRegistrationReceipt,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        sealed_bundle: ImplementationBundleRevision,
        evidence_assessment: ValidationEvidenceAssessment,
        assessment: AdmissionEvidenceAssessment,
        host_containment_ref: str,
        admission_id: str,
        scope_kind: str,
        scope_ref: str,
        minimum_evidence_tier: str,
        allowed_operations: tuple[str, ...],
        allowed_consumers: tuple[str, ...],
    ) -> ScopedAdmissionRecord:
        self._assert_exact_facts(
            registration=registration,
            adapter=adapter,
            validation_bundle=validation_bundle,
            sealed_bundle=sealed_bundle,
            evidence_assessment=evidence_assessment,
            assessment=assessment,
            host_containment_ref=host_containment_ref,
        )
        try:
            return self.controller.propose(
                adapter=adapter,
                validation_bundle=validation_bundle,
                assessment=assessment,
                admission_id=admission_id,
                runtime_policy_ref=registration.runtime_policy_ref,
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                minimum_evidence_tier=minimum_evidence_tier,
                allowed_operations=allowed_operations,
                allowed_consumers=allowed_consumers,
            )
        except AdmissionContractError as error:
            raise AdmissionServiceError(str(error)) from error

    def admit(
        self,
        admission_id: str,
        *,
        approver_ref: str,
        approval_ref: str,
    ) -> ScopedAdmissionRecord:
        try:
            return self.controller.admit(
                admission_id,
                approver_ref=approver_ref,
                approval_ref=approval_ref,
            )
        except AdmissionContractError as error:
            raise AdmissionServiceError(str(error)) from error

    def assert_usable(
        self,
        admission: ScopedAdmissionRecord,
        *,
        registration: ValidatedRegistrationReceipt,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        sealed_bundle: ImplementationBundleRevision,
        evidence_assessment: ValidationEvidenceAssessment,
        assessment: AdmissionEvidenceAssessment,
        host_containment_ref: str,
        runtime_policy_ref: str,
        scope_kind: str,
        scope_ref: str,
        requested_operations: tuple[str, ...],
        requested_consumers: tuple[str, ...],
    ) -> None:
        self._assert_exact_facts(
            registration=registration,
            adapter=adapter,
            validation_bundle=validation_bundle,
            sealed_bundle=sealed_bundle,
            evidence_assessment=evidence_assessment,
            assessment=assessment,
            host_containment_ref=host_containment_ref,
        )
        if runtime_policy_ref != registration.runtime_policy_ref:
            raise AdmissionServiceError("runtime policy does not match registration")
        try:
            self.controller.assert_usable(
                admission,
                adapter=adapter,
                validation_bundle=validation_bundle,
                assessment=assessment,
                runtime_policy_ref=runtime_policy_ref,
                scope_kind=scope_kind,
                scope_ref=scope_ref,
                requested_operations=requested_operations,
                requested_consumers=requested_consumers,
            )
        except AdmissionContractError as error:
            raise AdmissionServiceError(str(error)) from error

    def _assert_exact_facts(
        self,
        *,
        registration: ValidatedRegistrationReceipt,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        sealed_bundle: ImplementationBundleRevision,
        evidence_assessment: ValidationEvidenceAssessment,
        assessment: AdmissionEvidenceAssessment,
        host_containment_ref: str,
    ) -> None:
        if not isinstance(registration, ValidatedRegistrationReceipt):
            raise AdmissionServiceError("registration is unavailable")
        try:
            current = self.registry.get_validated(registration.implementation_ref)
        except (RegistryError, ValueError) as error:
            raise AdmissionServiceError("registration is unavailable") from error
        if current != registration:
            raise AdmissionServiceError("registration identity is not current")
        if not isinstance(adapter, AdapterContract):
            raise AdmissionServiceError("adapter is invalid")
        if not isinstance(validation_bundle, ValidationBundle):
            raise AdmissionServiceError("validation bundle is invalid")
        if not isinstance(sealed_bundle, ImplementationBundleRevision):
            raise AdmissionServiceError("sealed bundle is invalid")
        if not isinstance(evidence_assessment, ValidationEvidenceAssessment):
            raise AdmissionServiceError("validation assessment is invalid")
        if not isinstance(assessment, AdmissionEvidenceAssessment):
            raise AdmissionServiceError("admission assessment is invalid")
        if adapter.content_digest != registration.adapter_ref:
            raise AdmissionServiceError("adapter does not match registration")
        if validation_bundle.content_digest != registration.validation_bundle_ref:
            raise AdmissionServiceError("validation bundle does not match registration")
        if sealed_bundle.bundle_ref != registration.sealed_bundle_ref:
            raise AdmissionServiceError("sealed bundle does not match registration")
        if evidence_assessment.content_digest != registration.evidence_assessment_ref:
            raise AdmissionServiceError("validation assessment does not match registration")
        if assessment.content_digest != registration.assessment_ref:
            raise AdmissionServiceError("assessment does not match registration")
        if assessment.tier != evidence_assessment.tier:
            raise AdmissionServiceError("assessment tier does not match validation evidence")
        if host_containment_ref != registration.host_containment_ref:
            raise AdmissionServiceError("host containment does not match registration")
        try:
            evidence_validity = self.evidence_validity.latest(evidence_assessment.content_digest)
        except EvidenceAssessmentError as error:
            raise AdmissionServiceError("evidence validity is unavailable") from error
        if evidence_validity.status != "valid":
            raise AdmissionServiceError("evidence validity is not current")
        try:
            self.host_validity.require_current(host_containment_ref)
        except HostAssessmentError as error:
            raise AdmissionServiceError("host containment validity is not current") from error


__all__ = ["AdmissionServiceError", "ScopedAdmissionService"]
