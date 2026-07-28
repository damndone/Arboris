"""Trusted deployment composition for signed custom-capability execution.

The product never creates, exports, or stores signing material.  A deployment
supplies an authority port backed by its own key provider plus the exact source
of B1 execution attestations.  This module only verifies those attestations,
creates the server-owned catalog, and refuses to enable a gateway without a
real supply-chain verifier.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Protocol

from ..custom_capability.contracts import (
    AttestationEnvelope,
    AuthorityTrustSnapshot,
    VerificationContext,
)
from ..custom_capability.verifier import AuthenticationVerifier, Verifier
from ..native_containment.contracts import ContainmentReport, ContainmentRequest
from ..native_containment.host import CanaryResult
from ..native_containment.policy import ContainmentPolicy
from .contracts import _digest, _text
from .dependency_service import DependencyService
from .notebook_binding import CapabilityResolutionBinding
from .notebook_bridge import AuthorizedCapabilityExecutionGateway
from .notebook_catalog import CapabilityBindingCatalog
from .runtime import CapabilityFactoryRuntime, DependencyAdmissionGate


class DeploymentAuthorityError(ValueError):
    """Raised when a deployment cannot prove its authority dependencies."""


@dataclass(frozen=True, slots=True)
class AttestationVerificationState:
    """Dynamic authority facts supplied at each verification boundary."""

    now: datetime
    minimum_control_sequence: int = 0
    consumed_nonces: frozenset[str] = frozenset()
    revoked_nonces: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.now, datetime) or self.now.tzinfo is None:
            raise DeploymentAuthorityError("verification state requires an aware clock")
        if (
            not isinstance(self.minimum_control_sequence, int)
            or isinstance(self.minimum_control_sequence, bool)
            or self.minimum_control_sequence < 0
        ):
            raise DeploymentAuthorityError("minimum_control_sequence is invalid")
        for values, field in (
            (self.consumed_nonces, "consumed_nonces"),
            (self.revoked_nonces, "revoked_nonces"),
        ):
            if not isinstance(values, frozenset) or any(
                not isinstance(item, str) or not item for item in values
            ):
                raise DeploymentAuthorityError(f"{field} is invalid")


class AttestationAuthorityPort(Protocol):
    """Deployment-owned key/trust access; no signing material crosses this API."""

    def authentication_verifier(self) -> AuthenticationVerifier: ...

    def trust_snapshot(self) -> AuthorityTrustSnapshot: ...

    def verification_state(self) -> AttestationVerificationState: ...

    def verify_capability_binding(self, binding: CapabilityResolutionBinding) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionResultAttestationBinding:
    """Deployment constants required by the generic B0 execution-result claim."""

    operation_id: str
    backend_subject_id: str
    protocol_digest: str

    def __post_init__(self) -> None:
        try:
            object.__setattr__(self, "operation_id", _text(self.operation_id, "operation_id"))
            object.__setattr__(
                self,
                "backend_subject_id",
                _text(self.backend_subject_id, "backend_subject_id"),
            )
            object.__setattr__(
                self,
                "protocol_digest",
                _digest(self.protocol_digest, "protocol_digest"),
            )
        except ValueError as error:
            raise DeploymentAuthorityError(str(error)) from error


class ExecutionResultAttestationSource(Protocol):
    """Read one signed B1 result envelope from the trusted execution service."""

    def execution_result_attestation(
        self,
        *,
        report: ContainmentReport,
        request: ContainmentRequest,
        policy: ContainmentPolicy,
        canary: CanaryResult,
        binding: ExecutionResultAttestationBinding,
    ) -> AttestationEnvelope: ...


class AuthenticatedContainmentReportVerifier:
    """Verify an external B1 execution-result envelope at the broker seam."""

    def __init__(
        self,
        *,
        authority: AttestationAuthorityPort,
        source: ExecutionResultAttestationSource,
        binding: ExecutionResultAttestationBinding,
    ) -> None:
        _authority_components(authority)
        if not callable(getattr(source, "execution_result_attestation", None)):
            raise DeploymentAuthorityError(
                "a trusted execution-result attestation source is required"
            )
        if not isinstance(binding, ExecutionResultAttestationBinding):
            raise DeploymentAuthorityError("execution-result attestation binding is invalid")
        self._authority = authority
        self._source = source
        self._binding = binding

    def __call__(
        self,
        *,
        report: ContainmentReport,
        request: ContainmentRequest,
        policy: ContainmentPolicy,
        canary: CanaryResult,
    ) -> str:
        if not isinstance(report, ContainmentReport) or not isinstance(
            request, ContainmentRequest
        ) or not isinstance(policy, ContainmentPolicy) or not isinstance(canary, CanaryResult):
            raise DeploymentAuthorityError("containment report verification input is invalid")
        if report.status != "completed" or report.output_bundle_ref is None:
            raise DeploymentAuthorityError(
                "only a completed report with an output bundle can carry an execution-result attestation"
            )
        if report.attempt_id != request.attempt_id or report.request_digest != request.content_digest:
            raise DeploymentAuthorityError("containment report is not bound to the request")
        if request.policy_digest != policy.content_digest:
            raise DeploymentAuthorityError("containment request policy is not bound")
        snapshot, authenticator, state = _authority_components(self._authority)
        try:
            envelope = self._source.execution_result_attestation(
                report=report,
                request=request,
                policy=policy,
                canary=canary,
                binding=self._binding,
            )
        except Exception as error:
            raise DeploymentAuthorityError(
                "trusted execution-result attestation source failed"
            ) from error
        if not isinstance(envelope, AttestationEnvelope):
            raise DeploymentAuthorityError(
                "trusted execution-result attestation source returned an invalid envelope"
            )
        expected_bindings = {
            "intent_digest": request.intent_digest,
            "attempt_id": request.attempt_id,
            "input_bundle_digest": request.input_bundle_ref,
            "operation_id": self._binding.operation_id,
            "output_bundle_digest": report.output_bundle_ref,
            "policy_digest": policy.content_digest,
            "backend_subject_id": self._binding.backend_subject_id,
            "protocol_digest": self._binding.protocol_digest,
        }
        try:
            verified = Verifier(authenticator).verify(
                envelope,
                VerificationContext(
                    trust_snapshot=snapshot,
                    expected_bindings=expected_bindings,
                    now=state.now,
                    minimum_control_sequence=state.minimum_control_sequence,
                    consumed_nonces=state.consumed_nonces,
                    revoked_nonces=state.revoked_nonces,
                ),
            )
        except Exception as error:
            raise DeploymentAuthorityError(
                "trusted execution-result attestation did not verify"
            ) from error
        return verified.signing_digest


def build_deployment_capability_factory_runtime(
    *,
    authority: AttestationAuthorityPort,
    dependency_service: DependencyService,
    binding_factory: Callable[..., Any],
    report_attestation_source: ExecutionResultAttestationSource,
    attestation_binding: ExecutionResultAttestationBinding,
    result_sink: Callable[[Any], None] | None = None,
) -> CapabilityFactoryRuntime:
    """Build, but do not install, a production-wired factory runtime.

    The deployment must supply a current authority and scanner verifier.  The
    generated catalog delegates every registration and lookup to that authority
    instead of accepting a route-supplied lambda or a product-default key.
    """

    snapshot, _authenticator, _state = _authority_components(authority)
    if not isinstance(dependency_service, DependencyService):
        raise DeploymentAuthorityError("dependency_service must be a DependencyService")
    if not callable(getattr(dependency_service.supply_chain_verifier, "verify", None)):
        raise DeploymentAuthorityError(
            "deployment runtime requires an external supply-chain verifier"
        )
    if not callable(binding_factory):
        raise DeploymentAuthorityError("binding_factory must be callable")
    if result_sink is not None and not callable(result_sink):
        raise DeploymentAuthorityError("result_sink must be callable or None")
    report_verifier = AuthenticatedContainmentReportVerifier(
        authority=authority,
        source=report_attestation_source,
        binding=attestation_binding,
    )
    catalog = CapabilityBindingCatalog(verifier=authority.verify_capability_binding)

    def deployment_binding_factory(**kwargs: Any) -> Any:
        return binding_factory(authority_report_verifier=report_verifier, **kwargs)

    gateway = AuthorizedCapabilityExecutionGateway(
        binding_factory=deployment_binding_factory,
        result_sink=result_sink,
        dependency_binding_validator=DependencyAdmissionGate(dependency_service),
    )
    return CapabilityFactoryRuntime(
        authority_id=snapshot.authority_id,
        catalog=catalog,
        execution_gateway=gateway,
        dependency_service=dependency_service,
    )


def _authority_components(
    authority: AttestationAuthorityPort,
) -> tuple[AuthorityTrustSnapshot, AuthenticationVerifier, AttestationVerificationState]:
    if authority is None:
        raise DeploymentAuthorityError("a deployment authority port is required")
    for name in (
        "authentication_verifier",
        "trust_snapshot",
        "verification_state",
        "verify_capability_binding",
    ):
        if not callable(getattr(authority, name, None)):
            raise DeploymentAuthorityError(
                "deployment authority port does not provide required verification methods"
            )
    try:
        snapshot = authority.trust_snapshot()
        authenticator = authority.authentication_verifier()
        state = authority.verification_state()
    except Exception as error:
        raise DeploymentAuthorityError("deployment authority port is unavailable") from error
    if not isinstance(snapshot, AuthorityTrustSnapshot):
        raise DeploymentAuthorityError("deployment authority returned an invalid trust snapshot")
    if not callable(getattr(authenticator, "verify", None)):
        raise DeploymentAuthorityError(
            "deployment authority returned an invalid authentication verifier"
        )
    if not isinstance(state, AttestationVerificationState):
        raise DeploymentAuthorityError("deployment authority returned an invalid verification state")
    return snapshot, authenticator, state


__all__ = [
    "AttestationAuthorityPort",
    "AttestationVerificationState",
    "AuthenticatedContainmentReportVerifier",
    "DeploymentAuthorityError",
    "ExecutionResultAttestationBinding",
    "ExecutionResultAttestationSource",
    "build_deployment_capability_factory_runtime",
]
