"""Metadata-only CF3 validation assessment service."""

from __future__ import annotations

from dataclasses import dataclass

from ..custom_capability.canonical import domain_digest
from .admission_contract import ScopedAdmissionRecord
from .contracts import _content_digest, _digest
from .evidence_assessment import EvidenceAssessment
from .implementation_sealer import ImplementationBundleRevision
from .provenance import EvidenceProvenance
from .validation_contract import ValidationBundle
from .validation_ledger import ValidationAttempt, ValidationAttemptLedger
from .validation_protocols import ValidationProtocol


class ValidationServiceError(ValueError):
    """Raised when validation evidence cannot satisfy its frozen protocol."""


@dataclass(frozen=True, slots=True)
class ValidationServiceResult:
    assessment: EvidenceAssessment
    attempt: ValidationAttempt
    adapter_ref: str
    validation_bundle_ref: str
    verified: bool

    @property
    def execution_allowed(self) -> bool:
        """Assessment state never grants an execution primitive."""

        return False

    @property
    def promotion(self) -> "CapabilityPromotion":
        """Return the pre-admission promotion projection."""

        return CapabilityPromotion(
            adapter_ref=self.adapter_ref,
            validation_bundle_ref=self.validation_bundle_ref,
            assessment_ref=self.assessment.content_digest,
            state="verified" if self.verified else "experimental",
        )


@dataclass(frozen=True, slots=True)
class CapabilityPromotion:
    """Server-derived lifecycle projection for one validated adapter."""

    adapter_ref: str
    validation_bundle_ref: str
    assessment_ref: str
    state: str
    admission_ref: str | None = None
    approval_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "adapter_ref", _digest(self.adapter_ref, "adapter_ref"))
        object.__setattr__(self, "validation_bundle_ref", _digest(self.validation_bundle_ref, "validation_bundle_ref"))
        object.__setattr__(self, "assessment_ref", _digest(self.assessment_ref, "assessment_ref"))
        if self.state not in {"experimental", "verified", "approved"}:
            raise ValidationServiceError("unsupported capability promotion state")
        if self.admission_ref is not None:
            object.__setattr__(self, "admission_ref", _digest(self.admission_ref, "admission_ref"))
        if self.approval_ref is not None:
            object.__setattr__(self, "approval_ref", _digest(self.approval_ref, "approval_ref"))
        if self.state == "approved" and (self.admission_ref is None or self.approval_ref is None):
            raise ValidationServiceError("approved promotion requires a server admission and approval")
        if self.state != "approved" and (self.admission_ref is not None or self.approval_ref is not None):
            raise ValidationServiceError("admission approval identity is only valid for approved promotion")

    @property
    def execution_allowed(self) -> bool:
        """Promotion is descriptive control-plane state, never execution authority."""

        return False

    @property
    def source_eligible(self) -> bool:
        """Only verified or approved projections may enter source selection."""

        return self.state in {"verified", "approved"}

    @property
    def content_digest(self) -> str:
        return _content_digest(self)


class ValidationService:
    """Assess references produced by a trusted validation runner.

    The service consumes bounded references and provenance.  It does not run
    author code, resolve fixtures, calculate statistical thresholds, or admit
    an implementation.
    """

    def __init__(self, *, ledger: ValidationAttemptLedger | None = None) -> None:
        self.ledger = ledger or ValidationAttemptLedger()

    def assess(
        self,
        *,
        sealed_bundle: ImplementationBundleRevision,
        validation_bundle: ValidationBundle,
        protocol: ValidationProtocol,
        producer_ref: str,
        provenance_by_evidence: dict[str, EvidenceProvenance] | None = None,
    ) -> ValidationServiceResult:
        if not isinstance(validation_bundle, ValidationBundle):
            raise ValidationServiceError("validation_bundle must be a ValidationBundle")
        if not isinstance(sealed_bundle, ImplementationBundleRevision):
            raise ValidationServiceError("sealed_bundle must be an ImplementationBundleRevision")
        if not isinstance(protocol, ValidationProtocol):
            raise ValidationServiceError("protocol must be a ValidationProtocol")
        if validation_bundle.adapter_ref != sealed_bundle.adapter_ref:
            raise ValidationServiceError("validation bundle is bound to another sealed adapter")
        evidence = validation_bundle.evidence
        provenance_by_evidence = provenance_by_evidence or {}
        tier = "E0"
        if any(item.tier == "E3" for item in evidence):
            tier = "E3"
        elif any(item.tier == "E2" for item in evidence):
            tier = "E2"
        elif any(item.tier == "E1" for item in evidence):
            tier = "E1"

        for item in evidence:
            if item.tier in {"E2", "E3"}:
                provenance = provenance_by_evidence.get(item.content_digest)
                if not isinstance(provenance, EvidenceProvenance) or provenance.evidence_ref != item.content_digest:
                    raise ValidationServiceError("independent evidence requires bound provenance")
                if not provenance.independent_oracle or provenance.oracle_root is None:
                    raise ValidationServiceError("independent evidence requires an independent oracle lineage")
                if item.oracle_ref is None:
                    raise ValidationServiceError("independent evidence requires oracle_ref")
                oracle_node = next(
                    (node for node in provenance.nodes if node.node_id == provenance.oracle_root),
                    None,
                )
                if oracle_node is None:
                    raise ValidationServiceError("oracle provenance root is missing")
                if oracle_node.artifact_ref != item.oracle_ref:
                    raise ValidationServiceError("oracle provenance does not match evidence")
                if item.tier == "E3" and item.fixture_visibility != "service_holdout":
                    raise ValidationServiceError("E3 evidence requires a service holdout")

        case_refs = {item.content_digest for item in validation_bundle.cases}
        evidence_case_refs = tuple(item.case_ref for item in evidence)
        evidence_is_complete = (
            len(evidence_case_refs) == len(case_refs)
            and len(set(evidence_case_refs)) == len(evidence_case_refs)
            and set(evidence_case_refs) == case_refs
        )
        protocol_checks = set(protocol.check_kinds)
        covered_checks = {item.check_kind for item in validation_bundle.cases}
        protocol_coverage_is_complete = protocol_checks <= covered_checks
        all_evidence_is_independent = bool(evidence) and all(
            item.source_eligible for item in evidence
        )
        holdout_requirement_is_satisfied = (
            protocol.evidence_floor != "E3"
            or all(item.fixture_visibility == "service_holdout" for item in evidence)
        )
        verification_requirements_are_complete = (
            evidence_is_complete
            and protocol_coverage_is_complete
            and all_evidence_is_independent
            and holdout_requirement_is_satisfied
        )
        statuses = {item.status for item in evidence}
        if (
            not evidence
            or not evidence_is_complete
            or not protocol_coverage_is_complete
        ):
            outcome = "inconclusive"
        elif "failed" in statuses:
            outcome = "failed"
        elif "inconclusive" in statuses:
            outcome = "inconclusive"
        elif _tier_rank(tier) < _tier_rank(protocol.evidence_floor):
            outcome = "inconclusive"
        else:
            outcome = "passed"

        sealed_ref = sealed_bundle.bundle_ref
        protocol_ref = protocol.content_digest
        producer_ref = _digest(producer_ref, "producer_ref")
        result_ref = domain_digest(
            "workbench.capability_factory.validation_run/v1",
            {
                "sealed_bundle_ref": sealed_ref,
                "validation_bundle_ref": validation_bundle.content_digest,
                "protocol_ref": protocol_ref,
                "producer_ref": producer_ref,
                "outcome": outcome,
            },
        )
        attempt_number = len(self.ledger.history(sealed_ref, protocol_ref)) + 1
        attempt = self.ledger.append(
            bundle_ref=sealed_ref,
            protocol_ref=protocol_ref,
            attempt_number=attempt_number,
            outcome=outcome,
            result_ref=result_ref,
            max_attempts=protocol.max_attempts,
        )
        assessment = EvidenceAssessment(
            assessment_id=f"assessment.{result_ref[:24]}",
            bundle_ref=sealed_ref,
            protocol_ref=protocol_ref,
            attempt_ledger_ref=self.ledger.stream_digest(sealed_ref, protocol_ref),
            tier=tier,
            status=outcome,
            evidence_refs=tuple(item.content_digest for item in evidence) or (result_ref,),
            producer_ref=producer_ref,
        )
        verified = (
            outcome == "passed"
            and _tier_rank(tier) >= _tier_rank("E2")
            and verification_requirements_are_complete
        )
        return ValidationServiceResult(
            assessment=assessment,
            attempt=attempt,
            adapter_ref=sealed_bundle.adapter_ref,
            validation_bundle_ref=validation_bundle.content_digest,
            verified=verified,
        )

    def promotion(
        self,
        result: ValidationServiceResult,
        *,
        admission: ScopedAdmissionRecord | None = None,
    ) -> CapabilityPromotion:
        """Project validation plus server admission into explicit lifecycle state.

        ``approved`` is only a projection of an admitted server record with
        approver and approval identities bound to this exact adapter and
        validation bundle.  Neither validation nor admission exposes execution
        authority; the returned state is descriptive control-plane data.
        """

        if not isinstance(result, ValidationServiceResult):
            raise ValidationServiceError("result must be a ValidationServiceResult")
        if admission is not None and not isinstance(admission, ScopedAdmissionRecord):
            raise ValidationServiceError("admission must be a server admission record")
        if admission is not None:
            if admission.adapter_ref != result.adapter_ref:
                raise ValidationServiceError("admission is bound to another adapter")
            if admission.validation_bundle_ref != result.validation_bundle_ref:
                raise ValidationServiceError("admission is bound to another validation bundle")
            if admission.assessment_ref != result.assessment.content_digest:
                raise ValidationServiceError("admission is bound to another validation assessment")
            if admission.status == "admitted" and not result.verified:
                raise ValidationServiceError("an unverified capability cannot be approved")

        if not result.verified:
            return CapabilityPromotion(
                adapter_ref=result.adapter_ref,
                validation_bundle_ref=result.validation_bundle_ref,
                assessment_ref=result.assessment.content_digest,
                state="experimental",
            )
        if admission is None or admission.status != "admitted":
            return CapabilityPromotion(
                adapter_ref=result.adapter_ref,
                validation_bundle_ref=result.validation_bundle_ref,
                assessment_ref=result.assessment.content_digest,
                state="verified",
            )
        if admission.approver_ref is None or admission.approval_ref is None:
            raise ValidationServiceError("admitted capability is missing server approval identity")
        if _tier_rank(result.assessment.tier) < _tier_rank(admission.minimum_evidence_tier):
            raise ValidationServiceError("server admission evidence floor is not met")
        return CapabilityPromotion(
            adapter_ref=result.adapter_ref,
            validation_bundle_ref=result.validation_bundle_ref,
            assessment_ref=result.assessment.content_digest,
            state="approved",
            admission_ref=admission.content_digest,
            approval_ref=admission.approval_ref,
        )


def _tier_rank(tier: str) -> int:
    return {"E0": 0, "E1": 1, "E2": 2, "E3": 3}[tier]


__all__ = [
    "CapabilityPromotion",
    "ValidationService",
    "ValidationServiceError",
    "ValidationServiceResult",
]
