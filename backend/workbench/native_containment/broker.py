"""Fail-closed B1 broker orchestration without a default executor."""

from __future__ import annotations

from typing import Callable

from .contracts import ContainmentReport, ContainmentRequest
from .host import CanaryResult
from .policy import ContainmentPolicy


class ContainmentBrokerError(ValueError):
    """Raised when a request crosses the broker contract boundary."""


ReportVerifier = Callable[..., str]


class ContainmentBroker:
    def __init__(
        self,
        *,
        host_assessor: Callable[[ContainmentPolicy], CanaryResult],
        executor: Callable[[ContainmentRequest, ContainmentPolicy, CanaryResult], ContainmentReport] | None,
        report_verifier: ReportVerifier | None = None,
        require_authenticated_reports: bool = False,
    ) -> None:
        if not callable(host_assessor):
            raise ContainmentBrokerError("host_assessor must be callable")
        if executor is not None and not callable(executor):
            raise ContainmentBrokerError("executor must be callable or None")
        if report_verifier is not None and not callable(report_verifier):
            raise ContainmentBrokerError("report_verifier must be callable or None")
        if type(require_authenticated_reports) is not bool:
            raise ContainmentBrokerError("require_authenticated_reports must be boolean")
        self.host_assessor = host_assessor
        self.executor = executor
        self.report_verifier = report_verifier
        self.require_authenticated_reports = require_authenticated_reports

    def run(self, request: ContainmentRequest, policy: ContainmentPolicy) -> ContainmentReport:
        if not isinstance(request, ContainmentRequest):
            raise ContainmentBrokerError("request must be a ContainmentRequest")
        if not isinstance(policy, ContainmentPolicy):
            raise ContainmentBrokerError("policy must be a ContainmentPolicy")
        if request.policy_digest != policy.content_digest:
            raise ContainmentBrokerError("request policy digest does not match policy")
        result = self.host_assessor(policy)
        if not isinstance(result, CanaryResult):
            raise ContainmentBrokerError("host assessor must return a CanaryResult")
        if result.status != "supported":
            return ContainmentReport(
                attempt_id=request.attempt_id,
                request_digest=request.content_digest,
                status="unsupported",
                reason_code=result.reason_code,
            )
        if self.executor is None:
            return ContainmentReport(
                attempt_id=request.attempt_id,
                request_digest=request.content_digest,
                status="unsupported",
                reason_code="NATIVE_CONTAINMENT_EXECUTOR_UNAVAILABLE",
            )
        try:
            report = self.executor(request, policy, result)
        except Exception as error:
            raise ContainmentBrokerError("trusted executor failed before a typed report") from error
        if (
            not isinstance(report, ContainmentReport)
            or report.attempt_id != request.attempt_id
            or report.request_digest != request.content_digest
        ):
            raise ContainmentBrokerError("executor returned an unbound containment report")
        if self.require_authenticated_reports:
            if self.report_verifier is None:
                return ContainmentReport(
                    attempt_id=request.attempt_id,
                    request_digest=request.content_digest,
                    status="unsupported",
                    reason_code="NATIVE_CONTAINMENT_AUTHORITY_UNAVAILABLE",
                )
            try:
                attestation_ref = self.report_verifier(
                    report=report,
                    request=request,
                    policy=policy,
                    canary=result,
                )
            except Exception as error:
                raise ContainmentBrokerError(
                    "trusted containment report verification failed"
                ) from error
            try:
                from ..capability_factory.contracts import _digest

                attestation_ref = _digest(attestation_ref, "attestation_ref")
            except (TypeError, ValueError) as error:
                raise ContainmentBrokerError(
                    "trusted containment report verifier returned an invalid reference"
                ) from error
            report = ContainmentReport(
                attempt_id=report.attempt_id,
                request_digest=report.request_digest,
                status=report.status,
                reason_code=report.reason_code,
                assessment_ref=report.assessment_ref,
                output_bundle_ref=report.output_bundle_ref,
                attestation_ref=attestation_ref,
            )
        return report


__all__ = ["ContainmentBroker", "ContainmentBrokerError", "ReportVerifier"]
