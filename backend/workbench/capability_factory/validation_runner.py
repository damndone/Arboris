"""CF3 validation execution orchestration through the B1 containment broker.

This module deliberately does not know how to import an adapter or execute an
algorithm.  It creates a typed, digest-bound validation request and delegates
the actual process to the trusted containment broker.  An unsupported host or
missing executor therefore produces an explicit non-success result rather
than an uncontained fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from ..custom_capability.canonical import domain_digest
from ..native_containment.broker import ContainmentBroker, ContainmentBrokerError
from ..native_containment.contracts import ContainmentRequest, ContainmentReport
from ..native_containment.policy import ContainmentPolicy
from .contracts import _content_digest, _digest, _text
from .implementation_sealer import ImplementationBundleRevision
from .provenance import EvidenceProvenance, ProvenanceNode
from .validation_contract import ValidationBundle, ValidationEvidence
from .validation_protocols import ValidationProtocol
from .validation_service import ValidationService, ValidationServiceResult


class ValidationRunnerError(ValueError):
    """Raised when a validation request is not bound to its sealed inputs."""


@dataclass(frozen=True, slots=True)
class OracleObservation:
    """Bounded server-oracle output; it contains refs, never raw result data."""

    observed_ref: str
    oracle_ref: str
    oracle_kind: str
    status: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_ref", _digest(self.observed_ref, "observed_ref"))
        object.__setattr__(self, "oracle_ref", _digest(self.oracle_ref, "oracle_ref"))
        if self.oracle_kind not in {
            "independent_implementation",
            "trusted_fixture",
            "independent_review",
        }:
            raise ValidationRunnerError("oracle kind is unsupported")
        if self.status not in {"passed", "failed", "inconclusive"}:
            raise ValidationRunnerError("oracle status is unsupported")


class ValidationOracle(Protocol):
    def evaluate(
        self,
        *,
        case_ref: str,
        fixture_ref: str,
        output_bundle_ref: str,
        protocol_ref: str,
    ) -> OracleObservation: ...


@dataclass(frozen=True, slots=True)
class ValidationExecutionResult:
    sealed_bundle_ref: str
    protocol_ref: str
    attempt_id: str
    request_ref: str
    report_ref: str | None
    status: str
    reason_code: str
    assessment_ref: str | None = None
    output_bundle_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "sealed_bundle_ref", _digest(self.sealed_bundle_ref, "sealed_bundle_ref"))
        object.__setattr__(self, "protocol_ref", _digest(self.protocol_ref, "protocol_ref"))
        object.__setattr__(self, "attempt_id", _text(self.attempt_id, "attempt_id"))
        object.__setattr__(self, "request_ref", _digest(self.request_ref, "request_ref"))
        if self.report_ref is not None:
            object.__setattr__(self, "report_ref", _digest(self.report_ref, "report_ref"))
        if self.status not in {"completed", "failed", "unsupported", "dispatch_unknown"}:
            raise ValidationRunnerError("validation execution status is unsupported")
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        for field in ("assessment_ref", "output_bundle_ref"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, _digest(value, field))
        if self.status == "completed" and (self.report_ref is None or self.output_bundle_ref is None):
            raise ValidationRunnerError("completed validation execution requires a report and output bundle")
        if self.status != "completed" and self.output_bundle_ref is not None:
            raise ValidationRunnerError("non-completed validation execution cannot expose output")

    @property
    def content_digest(self) -> str:
        return _content_digest(self)

    @property
    def execution_allowed(self) -> bool:
        """A validation result is evidence input, never an execution grant."""

        return False


@dataclass(frozen=True, slots=True)
class ValidationHarnessResult:
    execution: ValidationExecutionResult
    validation_bundle: ValidationBundle
    outcome: str
    reason_code: str
    verified: bool = False
    assessment_ref: str | None = None
    promotion_state: str = "experimental"

    def __post_init__(self) -> None:
        if not isinstance(self.execution, ValidationExecutionResult):
            raise ValidationRunnerError("execution must be a ValidationExecutionResult")
        if not isinstance(self.validation_bundle, ValidationBundle):
            raise ValidationRunnerError("validation_bundle must be a ValidationBundle")
        if self.outcome not in {"passed", "failed", "inconclusive"}:
            raise ValidationRunnerError("validation harness outcome is unsupported")
        object.__setattr__(self, "reason_code", _text(self.reason_code, "reason_code"))
        if not isinstance(self.verified, bool):
            raise ValidationRunnerError("validation verified flag must be boolean")
        if self.verified and self.outcome != "passed":
            raise ValidationRunnerError("only a passed validation can be verified")
        if self.assessment_ref is not None:
            object.__setattr__(self, "assessment_ref", _digest(self.assessment_ref, "assessment_ref"))
        if self.promotion_state not in {"experimental", "verified", "approved"}:
            raise ValidationRunnerError("validation promotion state is unsupported")
        if self.verified and self.promotion_state != "verified":
            raise ValidationRunnerError("verified validation must expose a verified promotion state")

    @property
    def content_digest(self) -> str:
        return _content_digest(self)

    @property
    def execution_allowed(self) -> bool:
        """Verification state never grants an execution primitive."""

        return False


class ValidationRunner:
    """Run a sealed validation request only through a trusted B1 broker."""

    def run(
        self,
        *,
        sealed_bundle: ImplementationBundleRevision,
        protocol: ValidationProtocol,
        request: ContainmentRequest,
        policy: ContainmentPolicy,
        broker: ContainmentBroker,
    ) -> ValidationExecutionResult:
        if not isinstance(sealed_bundle, ImplementationBundleRevision):
            raise ValidationRunnerError("sealed_bundle must be an ImplementationBundleRevision")
        if not isinstance(protocol, ValidationProtocol):
            raise ValidationRunnerError("protocol must be a ValidationProtocol")
        if not isinstance(request, ContainmentRequest):
            raise ValidationRunnerError("request must be a ContainmentRequest")
        if not isinstance(policy, ContainmentPolicy):
            raise ValidationRunnerError("policy must be a ContainmentPolicy")
        if not isinstance(broker, ContainmentBroker):
            raise ValidationRunnerError("broker must be a ContainmentBroker")
        if request.intent_digest != sealed_bundle.bundle_ref:
            raise ValidationRunnerError("validation request is not bound to the sealed bundle")
        if request.input_bundle_ref != sealed_bundle.bundle_ref:
            raise ValidationRunnerError("validation input is not the sealed bundle")
        if request.policy_digest != policy.content_digest:
            raise ValidationRunnerError("validation request policy does not match policy")

        try:
            report = broker.run(request, policy)
        except ContainmentBrokerError as error:
            return ValidationExecutionResult(
                sealed_bundle_ref=sealed_bundle.bundle_ref,
                protocol_ref=protocol.content_digest,
                attempt_id=request.attempt_id,
                request_ref=request.content_digest,
                report_ref=None,
                status="failed",
                reason_code="NATIVE_CONTAINMENT_BROKER_FAILED",
            )
        except Exception:
            # A host assessor or executor is outside this contract.  Never
            # leak its exception into a caller that might treat dispatch as a
            # validation success; convert it to a typed terminal failure.
            return ValidationExecutionResult(
                sealed_bundle_ref=sealed_bundle.bundle_ref,
                protocol_ref=protocol.content_digest,
                attempt_id=request.attempt_id,
                request_ref=request.content_digest,
                report_ref=None,
                status="failed",
                reason_code="NATIVE_CONTAINMENT_BROKER_FAILED",
            )
        if not isinstance(report, ContainmentReport):
            raise ValidationRunnerError("containment broker returned an invalid report")
        if report.attempt_id != request.attempt_id or report.request_digest != request.content_digest:
            # The concrete B1 broker already enforces this binding. Keep the
            # check here as a second boundary so a trusted broker replacement
            # or recovery wrapper cannot accidentally route another attempt's
            # completed output into this validation run.
            return ValidationExecutionResult(
                sealed_bundle_ref=sealed_bundle.bundle_ref,
                protocol_ref=protocol.content_digest,
                attempt_id=request.attempt_id,
                request_ref=request.content_digest,
                report_ref=None,
                status="failed",
                reason_code="NATIVE_CONTAINMENT_REPORT_MISMATCH",
            )
        status = report.status
        if status == "completed":
            return ValidationExecutionResult(
                sealed_bundle_ref=sealed_bundle.bundle_ref,
                protocol_ref=protocol.content_digest,
                attempt_id=request.attempt_id,
                request_ref=request.content_digest,
                report_ref=report.content_digest,
                status="completed",
                reason_code=report.reason_code,
                assessment_ref=report.assessment_ref,
                output_bundle_ref=report.output_bundle_ref,
            )
        return ValidationExecutionResult(
            sealed_bundle_ref=sealed_bundle.bundle_ref,
            protocol_ref=protocol.content_digest,
            attempt_id=request.attempt_id,
            request_ref=request.content_digest,
            report_ref=report.content_digest,
            status=status,
            reason_code=report.reason_code,
        )

    def run_with_oracle(
        self,
        *,
        sealed_bundle: ImplementationBundleRevision,
        validation_bundle: ValidationBundle,
        protocol: ValidationProtocol,
        request: ContainmentRequest,
        policy: ContainmentPolicy,
        broker: ContainmentBroker,
        oracle: ValidationOracle | None,
        assessment_service: ValidationService | None = None,
        producer_ref: str | None = None,
    ) -> ValidationHarnessResult:
        """Run the contained suite and derive evidence from a server oracle.

        The oracle sees only content references.  It cannot submit a tier or
        an evidence id; those are derived here.  If the host, executor, or
        oracle is unavailable the original empty bundle is returned as
        inconclusive, so the caller cannot accidentally promote the candidate.
        """

        if not isinstance(validation_bundle, ValidationBundle):
            raise ValidationRunnerError("validation_bundle must be a ValidationBundle")
        if validation_bundle.adapter_ref != sealed_bundle.adapter_ref:
            raise ValidationRunnerError("validation bundle is not bound to the sealed adapter")
        service = assessment_service or ValidationService()
        if not isinstance(service, ValidationService):
            raise ValidationRunnerError("assessment_service must be a ValidationService")
        if producer_ref is None:
            producer_ref = domain_digest(
                "workbench.capability_factory.validation_runner/v1",
                {
                    "runner": "contained-oracle-runner",
                    "sealed_bundle_ref": sealed_bundle.bundle_ref,
                    "protocol_ref": protocol.content_digest,
                },
            )
        else:
            producer_ref = _digest(producer_ref, "producer_ref")

        def assess(
            bundle: ValidationBundle,
            *,
            provenance_by_evidence: dict[str, EvidenceProvenance] | None = None,
        ) -> ValidationServiceResult:
            return service.assess(
                sealed_bundle=sealed_bundle,
                validation_bundle=bundle,
                protocol=protocol,
                producer_ref=producer_ref or "",
                provenance_by_evidence=provenance_by_evidence,
            )

        execution = self.run(
            sealed_bundle=sealed_bundle,
            protocol=protocol,
            request=request,
            policy=policy,
            broker=broker,
        )
        if execution.status != "completed":
            assessed = assess(validation_bundle)
            return ValidationHarnessResult(
                execution=execution,
                validation_bundle=validation_bundle,
                outcome=assessed.assessment.status,
                reason_code=execution.reason_code,
                verified=assessed.verified,
                assessment_ref=assessed.assessment.content_digest,
                promotion_state=assessed.promotion.state,
            )
        if oracle is None:
            assessed = assess(validation_bundle)
            return ValidationHarnessResult(
                execution=execution,
                validation_bundle=validation_bundle,
                outcome=assessed.assessment.status,
                reason_code="VALIDATION_ORACLE_UNAVAILABLE",
                verified=assessed.verified,
                assessment_ref=assessed.assessment.content_digest,
                promotion_state=assessed.promotion.state,
            )

        evidence: list[ValidationEvidence] = []
        provenance_by_evidence: dict[str, EvidenceProvenance] = {}
        try:
            for case in validation_bundle.cases:
                observation = oracle.evaluate(
                    case_ref=case.content_digest,
                    fixture_ref=case.fixture_ref,
                    output_bundle_ref=execution.output_bundle_ref or "",
                    protocol_ref=protocol.content_digest,
                )
                if not isinstance(observation, OracleObservation):
                    raise ValidationRunnerError("oracle returned an invalid observation")
                tier = "E3" if (
                    protocol.evidence_floor == "E3"
                    and case.fixture_visibility == "service_holdout"
                    and all(item.fixture_visibility == "service_holdout" for item in validation_bundle.cases)
                ) else "E2"
                item = ValidationEvidence(
                    evidence_id=f"evidence.{case.case_id}.{execution.attempt_id}",
                    case_ref=case.content_digest,
                    tier=tier,
                    status=observation.status,
                    observed_ref=observation.observed_ref,
                    oracle_ref=observation.oracle_ref,
                    oracle_kind=observation.oracle_kind,
                    fixture_visibility=case.fixture_visibility,
                )
                evidence.append(item)
                author_node_id = f"author.{sealed_bundle.bundle_ref[:16]}"
                oracle_node_id = f"oracle.{case.case_id}.{execution.attempt_id}"
                provenance_by_evidence[item.content_digest] = EvidenceProvenance(
                    evidence_ref=item.content_digest,
                    author_root=author_node_id,
                    oracle_root=oracle_node_id,
                    nodes=(
                        ProvenanceNode(author_node_id, "author", sealed_bundle.bundle_ref),
                        ProvenanceNode(oracle_node_id, "oracle", observation.oracle_ref),
                    ),
                )
        except Exception as error:
            assessed = assess(validation_bundle)
            return ValidationHarnessResult(
                execution=execution,
                validation_bundle=validation_bundle,
                outcome=assessed.assessment.status,
                reason_code="VALIDATION_ORACLE_FAILED",
                verified=assessed.verified,
                assessment_ref=assessed.assessment.content_digest,
                promotion_state=assessed.promotion.state,
            )
        enriched = ValidationBundle(
            bundle_id=validation_bundle.bundle_id,
            revision=validation_bundle.revision + 1,
            adapter_ref=validation_bundle.adapter_ref,
            cases=validation_bundle.cases,
            evidence=tuple(evidence),
        )
        assessed = assess(enriched, provenance_by_evidence=provenance_by_evidence)
        return ValidationHarnessResult(
            execution=execution,
            validation_bundle=enriched,
            outcome=assessed.assessment.status,
            reason_code="VALIDATION_SERVICE_ASSESSED",
            verified=assessed.verified,
            assessment_ref=assessed.assessment.content_digest,
            promotion_state=assessed.promotion.state,
        )


__all__ = [
    "OracleObservation",
    "ValidationExecutionResult",
    "ValidationHarnessResult",
    "ValidationOracle",
    "ValidationRunner",
    "ValidationRunnerError",
]
