"""Fail-closed B1 broker orchestration without a default executor."""

from __future__ import annotations

from typing import Callable

from .contracts import ContainmentReport, ContainmentRequest
from .host import CanaryResult
from .policy import ContainmentPolicy


class ContainmentBrokerError(ValueError):
    """Raised when a request crosses the broker contract boundary."""


class ContainmentBroker:
    def __init__(
        self,
        *,
        host_assessor: Callable[[ContainmentPolicy], CanaryResult],
        executor: Callable[[ContainmentRequest, ContainmentPolicy, CanaryResult], ContainmentReport] | None,
    ) -> None:
        self.host_assessor = host_assessor
        self.executor = executor

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
        return report


__all__ = ["ContainmentBroker", "ContainmentBrokerError"]
