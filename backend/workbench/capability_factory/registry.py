"""Content-addressed registration of exact implementation revisions."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .adapter_contract import AdapterContract
from .admission_contract import EvidenceAssessment as AdmissionEvidenceAssessment
from .contracts import (
    CandidateSet,
    CapabilityRequirementRevision,
    ImplementationCandidate,
    ImplementationRevision,
    _content_digest,
    _digest,
    _text,
)
from .store import ContentAddressedStore
from .evidence_assessment import EvidenceAssessment as ValidationEvidenceAssessment
from .implementation_sealer import ImplementationBundleRevision
from .validation_contract import ValidationBundle


class RegistryError(ValueError):
    """Raised when registration would replace an immutable implementation."""


@dataclass(frozen=True, slots=True)
class RegistrationReceipt:
    implementation_ref: str


@dataclass(frozen=True, slots=True)
class ValidatedRegistrationReceipt:
    """The exact immutable registration consumed by scoped admission."""

    registration_id: str
    implementation_ref: str
    adapter_ref: str
    validation_bundle_ref: str
    evidence_assessment_ref: str
    assessment_ref: str
    sealed_bundle_ref: str
    runtime_policy_ref: str
    host_containment_ref: str

    def __post_init__(self) -> None:
        registration_id = _text(self.registration_id, "registration_id")
        if registration_id in {".", ".."} or "/" in registration_id or "\\" in registration_id:
            raise RegistryError("registration_id must be path-safe")
        object.__setattr__(self, "registration_id", registration_id)
        for field in (
            "implementation_ref",
            "adapter_ref",
            "validation_bundle_ref",
            "evidence_assessment_ref",
            "assessment_ref",
            "sealed_bundle_ref",
            "runtime_policy_ref",
            "host_containment_ref",
        ):
            object.__setattr__(self, field, _digest(getattr(self, field), field))

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


@dataclass(frozen=True, slots=True)
class _RegisteredImplementation:
    implementation: ImplementationRevision
    validity_refs: Mapping[str, str]

    @property
    def content_digest(self) -> str:
        return self.implementation.content_digest


class CapabilityRegistry:
    """Registry with one immutable record per implementation id/revision."""

    def __init__(self) -> None:
        self._store: ContentAddressedStore[_RegisteredImplementation] = ContentAddressedStore()
        self._by_identity: dict[tuple[str, int], str] = {}
        self._validated: dict[str, ValidatedRegistrationReceipt] = {}

    def register(
        self,
        implementation: ImplementationRevision,
        *,
        validity_refs: Mapping[str, str],
    ) -> RegistrationReceipt:
        if not isinstance(implementation, ImplementationRevision):
            raise RegistryError("only an ImplementationRevision can be registered")
        if implementation.source_kind == "native_pack":
            raise RegistryError("trusted native projections must use the native registration path")
        if implementation.trust_tier != "registered_third_party":
            raise RegistryError("this registration path assigns only registered_third_party trust")
        if not isinstance(validity_refs, Mapping):
            raise RegistryError("validity_refs must be an object")
        normalized = MappingProxyType({
            _text(key, "validity domain"): _digest(value, "validity reference")
            for key, value in validity_refs.items()
        })
        identity = (implementation.implementation_id, implementation.revision)
        previous_ref = self._by_identity.get(identity)
        if previous_ref is not None:
            previous = self._store.get(previous_ref)
            if previous.implementation != implementation or dict(previous.validity_refs) != dict(normalized):
                raise RegistryError("implementation revision identity is immutable")
            return RegistrationReceipt(previous_ref)
        record = _RegisteredImplementation(implementation, normalized)
        reference = self._store.put(record)
        self._by_identity[identity] = reference
        return RegistrationReceipt(reference)

    def register_validated(
        self,
        *,
        registration_id: str,
        implementation: ImplementationRevision,
        adapter: AdapterContract,
        validation_bundle: ValidationBundle,
        sealed_bundle: ImplementationBundleRevision,
        evidence_assessment: ValidationEvidenceAssessment,
        assessment: AdmissionEvidenceAssessment,
        runtime_policy_ref: str,
        host_containment_ref: str,
    ) -> ValidatedRegistrationReceipt:
        """Register one exact, server-assessed implementation revision.

        This method records metadata only.  It never imports an entrypoint or
        turns a registration into an execution grant.
        """

        if not isinstance(implementation, ImplementationRevision):
            raise RegistryError("implementation must be an ImplementationRevision")
        if implementation.source_kind == "native_pack":
            raise RegistryError("native packs use the trusted native registration path")
        if not isinstance(adapter, AdapterContract):
            raise RegistryError("adapter must be an AdapterContract")
        if not isinstance(validation_bundle, ValidationBundle):
            raise RegistryError("validation_bundle must be a ValidationBundle")
        if not isinstance(sealed_bundle, ImplementationBundleRevision):
            raise RegistryError("sealed_bundle must be an ImplementationBundleRevision")
        if not isinstance(evidence_assessment, ValidationEvidenceAssessment):
            raise RegistryError("evidence_assessment must be a CF3 EvidenceAssessment")
        if not isinstance(assessment, AdmissionEvidenceAssessment):
            raise RegistryError("assessment must be an admission EvidenceAssessment")
        try:
            adapter.validate_against(implementation)
        except ValueError as error:
            raise RegistryError(str(error)) from error
        if validation_bundle.adapter_ref != adapter.content_digest:
            raise RegistryError("validation bundle is bound to another adapter")
        if sealed_bundle.adapter_ref != adapter.content_digest:
            raise RegistryError("sealed bundle is bound to another adapter")
        if sealed_bundle.implementation_ref != implementation.content_digest:
            raise RegistryError("sealed bundle is bound to another implementation")
        if evidence_assessment.bundle_ref != sealed_bundle.bundle_ref:
            raise RegistryError("validation assessment is bound to another sealed bundle")
        if not evidence_assessment.source_eligible:
            raise RegistryError("registration requires source-eligible validation evidence")
        if assessment.adapter_ref != adapter.content_digest:
            raise RegistryError("assessment is bound to another adapter")
        if assessment.validation_bundle_ref != validation_bundle.content_digest:
            raise RegistryError("assessment is bound to another validation bundle")
        if not assessment.source_eligible:
            raise RegistryError("registration requires source-eligible evidence")
        if assessment.tier != evidence_assessment.tier:
            raise RegistryError("admission assessment tier does not match validation evidence")

        receipt = ValidatedRegistrationReceipt(
            registration_id=registration_id,
            implementation_ref=implementation.content_digest,
            adapter_ref=adapter.content_digest,
            validation_bundle_ref=validation_bundle.content_digest,
            evidence_assessment_ref=evidence_assessment.content_digest,
            assessment_ref=assessment.content_digest,
            sealed_bundle_ref=sealed_bundle.bundle_ref,
            runtime_policy_ref=runtime_policy_ref,
            host_containment_ref=host_containment_ref,
        )
        previous = self._validated.get(receipt.implementation_ref)
        if previous is not None:
            if previous != receipt:
                raise RegistryError("validated registration identity is immutable")
            return previous

        identity = (implementation.implementation_id, implementation.revision)
        previous_ref = self._by_identity.get(identity)
        if previous_ref is not None and previous_ref != implementation.content_digest:
            raise RegistryError("implementation identity is immutable")
        validity_refs = MappingProxyType(
            {
                "implementation": implementation.content_digest,
                "evidence": evidence_assessment.content_digest,
                "runtime_policy": receipt.runtime_policy_ref,
                "host_containment": receipt.host_containment_ref,
            }
        )
        if previous_ref is not None:
            previous_record = self._store.get(previous_ref)
            if previous_record.implementation != implementation:
                raise RegistryError("implementation identity is immutable")
            if dict(previous_record.validity_refs) != dict(validity_refs):
                raise RegistryError("implementation revision control refs are immutable")
        self._store.put(_RegisteredImplementation(implementation, validity_refs))
        self._by_identity[identity] = implementation.content_digest
        self._validated[receipt.implementation_ref] = receipt
        return receipt

    def get_validated(self, implementation_ref: str) -> ValidatedRegistrationReceipt:
        implementation_ref = _digest(implementation_ref, "implementation_ref")
        try:
            return self._validated[implementation_ref]
        except KeyError as error:
            raise RegistryError("validated registration is unavailable") from error

    def get(self, implementation_ref: str) -> ImplementationRevision:
        return self._store.get(implementation_ref).implementation

    def candidate_set(self, requirement: CapabilityRequirementRevision) -> CandidateSet:
        candidates = []
        for record in sorted(
            (self._store.get(reference) for reference in self._by_identity.values()),
            key=lambda item: (item.implementation.implementation_id, item.implementation.revision),
        ):
            implementation = record.implementation
            candidates.append(
                ImplementationCandidate(
                    candidate_id=f"{implementation.implementation_id}@{implementation.revision}",
                    implementation=implementation,
                    feasible=True,
                    available=True,
                    validity_refs=record.validity_refs,
                )
            )
        return CandidateSet(requirement.content_digest, tuple(candidates))


__all__ = [
    "CapabilityRegistry",
    "RegistryError",
    "RegistrationReceipt",
    "ValidatedRegistrationReceipt",
]
