"""Metadata-only CF3 validation assessment service."""

from __future__ import annotations

from dataclasses import dataclass

from ..custom_capability.canonical import domain_digest
from .contracts import _digest
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
                oracle_node = next(node for node in provenance.nodes if node.node_id == provenance.oracle_root)
                if oracle_node.artifact_ref != item.oracle_ref:
                    raise ValidationServiceError("oracle provenance does not match evidence")
                if item.tier == "E3" and item.fixture_visibility != "service_holdout":
                    raise ValidationServiceError("E3 evidence requires a service holdout")

        statuses = {item.status for item in evidence}
        if not evidence:
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
        return ValidationServiceResult(assessment=assessment, attempt=attempt)


def _tier_rank(tier: str) -> int:
    return {"E0": 0, "E1": 1, "E2": 2, "E3": 3}[tier]


__all__ = ["ValidationService", "ValidationServiceError", "ValidationServiceResult"]
