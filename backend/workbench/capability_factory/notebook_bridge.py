"""Notebook-to-dispatch bridge for the exact CF4 execution handoff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Mapping, Protocol

from ..custom_capability.canonical import domain_digest
from .dispatch import PreparedRunIntent
from .execution_authorization import OptionExecutionAuthorization


def _receipt_error(message: str) -> ValueError:
    """Load the aggregate error only after the notebook package is initialized.

    ``execution_receipt`` imports the notebook artifact contract.  Importing
    its error class eagerly here would re-enter ``agent.notebook.__init__``
    while that package is importing ``service``.
    """

    from .execution_receipt import ExecutionReceiptError

    return ExecutionReceiptError(message)


def _identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise _receipt_error(f"{field} must be bounded non-empty text")
    if value in {".", ".."} or "/" in value or "\\" in value:
        raise _receipt_error(f"{field} must be path-safe")
    return value


def _revision(value: Any, field: str) -> int:
    if type(value) is not int or value < 1:
        raise _receipt_error(f"{field} must be a positive integer")
    return value


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise _receipt_error(f"{field} must be a lowercase SHA-256 digest")
    return value


@dataclass(frozen=True, slots=True)
class PreparedCapabilityRun:
    """The pure output of the Draft/authorization preparation stage."""

    intent: PreparedRunIntent
    draft_id: str
    draft_hash: str
    run_id: str


@dataclass(frozen=True, slots=True)
class CapabilityExecutionCompletion:
    """Trusted server-owned inputs for the CF4 terminal commit gate.

    The adapter result is intentionally absent.  A server-owned completion
    factory must first map that result to the Workbench ArtifactContract and
    lineage/trace proofs.  The gateway then asks CF4 to reconcile those facts;
    no successful Notebook status can be manufactured from an output bundle
    reference alone.
    """

    artifact_validation: Any
    object_graph_ref: str
    termination_proof: Any
    terminal_reconciliation: Any

    def __post_init__(self) -> None:
        from .execution_receipt import (
            ArtifactContractValidationV11,
            TerminalSideEffectReconciliation,
        )

        if not isinstance(self.artifact_validation, ArtifactContractValidationV11):
            raise _receipt_error("capability completion artifact validation is invalid")
        _digest(self.object_graph_ref, "object_graph_ref")
        if not callable(getattr(self.termination_proof, "to_dict", None)):
            raise _receipt_error("capability completion termination proof is invalid")
        _digest(self.termination_proof.content_digest, "termination_proof_ref")
        if not isinstance(self.terminal_reconciliation, TerminalSideEffectReconciliation):
            raise _receipt_error("capability completion reconciliation proof is invalid")

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.capability_execution_completion/v1",
            {
                "artifact_validation_ref": self.artifact_validation.aggregate_ref,
                "object_graph_ref": self.object_graph_ref,
                "termination_proof_ref": self.termination_proof.content_digest,
                "terminal_reconciliation_ref": self.terminal_reconciliation.content_digest,
            },
        )


@dataclass(frozen=True, slots=True)
class NotebookExecutionDispatch:
    """Server-owned result of one explicit CF4 dispatch request.

    This is deliberately a server dispatch receipt plus bounded CF4 completion
    references. Only the trusted gateway may construct it; Notebook never
    accepts these fields from the Agent or browser.
    """

    authorization_id: str
    run_intent_id: str
    status: Literal[
        "dispatch_reserved",
        "running",
        "completed",
        "failed",
        "unsupported",
        "dispatch_unknown",
    ]
    run_id: str | None = None
    attempt_id: str | None = None
    receipt_ref: str | None = None
    completion_ref: str | None = None
    artifact_validation_ref: str | None = None
    object_graph_ref: str | None = None
    assessment_ref: str | None = None
    output_bundle_ref: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.authorization_id, "authorization_id")
        _identifier(self.run_intent_id, "run_intent_id")
        if self.status not in {
            "dispatch_reserved",
            "running",
            "completed",
            "failed",
            "unsupported",
            "dispatch_unknown",
        }:
            raise _receipt_error("unsupported Notebook execution dispatch status")
        if self.run_id is not None:
            _identifier(self.run_id, "run_id")
        if self.attempt_id is not None:
            _identifier(self.attempt_id, "attempt_id")
        if self.receipt_ref is not None:
            _identifier(self.receipt_ref, "receipt_ref")
        for field in (
            "completion_ref",
            "artifact_validation_ref",
            "object_graph_ref",
            "assessment_ref",
            "output_bundle_ref",
        ):
            value = getattr(self, field)
            if value is not None:
                _digest(value, field)
        if self.status in {"dispatch_reserved", "running", "completed", "failed"} and not all(
            (self.run_id, self.attempt_id, self.receipt_ref)
        ):
            raise _receipt_error(
                "successful Notebook dispatch requires run, attempt, and receipt refs"
            )
        if self.status in {"unsupported", "dispatch_unknown"} and self.run_id is not None:
            raise _receipt_error(
                "unsupported or unknown Notebook dispatch cannot expose a run id"
            )
        if self.status in {"completed", "failed"} and not all(
            (self.completion_ref, self.artifact_validation_ref, self.object_graph_ref)
        ):
            raise _receipt_error(
                "terminal Notebook dispatch requires CF4 completion refs"
            )
        if self.status == "completed" and not all(
            (self.assessment_ref, self.output_bundle_ref)
        ):
            raise _receipt_error(
                "completed Notebook dispatch requires assessment and output refs"
            )
        if self.status == "failed" and any(
            (self.assessment_ref, self.output_bundle_ref)
        ):
            raise _receipt_error("failed Notebook dispatch cannot expose output refs")

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "run_intent_id": self.run_intent_id,
            "status": self.status,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "receipt_ref": self.receipt_ref,
            "completion_ref": self.completion_ref,
            "artifact_validation_ref": self.artifact_validation_ref,
            "object_graph_ref": self.object_graph_ref,
            "assessment_ref": self.assessment_ref,
            "output_bundle_ref": self.output_bundle_ref,
        }


class NotebookCapabilityExecutionGateway(Protocol):
    """Trusted application seam for the real supervisor/broker handoff."""

    def dispatch(
        self,
        *,
        notebook_id: str,
        option_id: str,
        authorization: OptionExecutionAuthorization,
        materialization: Any,
        draft: Mapping[str, Any],
        context: Any,
    ) -> NotebookExecutionDispatch:
        """Reserve/dispatch one already-authorized capability execution."""


@dataclass(frozen=True, slots=True)
class NotebookCapabilityDispatchBinding:
    """Trusted per-attempt inputs for the explicit CF4 gateway.

    The browser, Agent, and Notebook option payload never construct this
    object.  A server-owned factory resolves the exact binding, policy,
    canary, request, and coordinator from the already-confirmed authorization.
    """

    intent: PreparedRunIntent
    plan: Any
    policy: Any
    canary: Any
    expectations: tuple[Any, ...]
    request_factory: Callable[[str], Any]
    coordinator: Any
    broker: Any
    executor: Any
    owner_id: str
    lease_seconds: int
    attempt_id: str
    lease_epoch: int
    executor_idempotency_key: str
    reservation_id: str
    reservation_idempotency_key: str
    now: Any = None
    completion_factory: Callable[..., CapabilityExecutionCompletion] | None = None

    def __post_init__(self) -> None:
        from ..native_containment.broker import ContainmentBroker
        from ..native_containment.contracts import ContainmentRequest
        from ..native_containment.policy import ContainmentPolicy
        from .custom_dispatcher import CustomDispatchPlan
        from .execution_receipt import CapabilityDispatchCoordinator
        from ..native_containment.host import CanaryResult

        if not isinstance(self.intent, PreparedRunIntent):
            raise _receipt_error("dispatch binding intent is invalid")
        if not isinstance(self.plan, CustomDispatchPlan):
            raise _receipt_error("dispatch binding plan is invalid")
        if self.plan.intent_digest != self.intent.content_digest:
            raise _receipt_error("dispatch binding plan does not match intent")
        if not isinstance(self.policy, ContainmentPolicy):
            raise _receipt_error("dispatch binding policy is invalid")
        if not isinstance(self.canary, CanaryResult):
            raise _receipt_error("dispatch binding canary is invalid")
        if not isinstance(self.expectations, (tuple, list)) or not self.expectations:
            raise _receipt_error("dispatch binding control expectations are required")
        if not callable(self.request_factory):
            raise _receipt_error("dispatch binding request factory is invalid")
        if not isinstance(self.coordinator, CapabilityDispatchCoordinator):
            raise _receipt_error("dispatch binding coordinator is invalid")
        if not isinstance(self.broker, ContainmentBroker):
            raise _receipt_error("dispatch binding broker is invalid")
        if self.broker.executor is not self.executor:
            raise _receipt_error("dispatch binding broker and executor must be identical")
        if not callable(getattr(self.executor, "spawn", None)) or not callable(
            getattr(self.executor, "terminate", None)
        ):
            raise _receipt_error("dispatch binding executor lacks lifecycle methods")
        if self.completion_factory is not None and not callable(self.completion_factory):
            raise _receipt_error("dispatch binding completion factory is invalid")
        if not isinstance(self.lease_seconds, int) or self.lease_seconds < 1:
            raise _receipt_error("dispatch binding lease_seconds is invalid")
        if not isinstance(self.lease_epoch, int) or self.lease_epoch < 1:
            raise _receipt_error("dispatch binding lease_epoch is invalid")
        for field in (
            "owner_id",
            "attempt_id",
            "executor_idempotency_key",
            "reservation_id",
            "reservation_idempotency_key",
        ):
            _identifier(getattr(self, field), field)


class AuthorizedCapabilityExecutionGateway:
    """Explicit Notebook gateway for the existing Proposal/Risk/CF4 path.

    This class is not installed as a default app gateway.  A trusted server
    configuration must provide ``binding_factory``; without it Notebook keeps
    the existing unavailable/fail-closed behavior.
    """

    def __init__(
        self,
        *,
        binding_factory: Callable[..., NotebookCapabilityDispatchBinding],
        result_sink: Callable[[Any], None] | None = None,
    ) -> None:
        if not callable(binding_factory):
            raise TypeError("binding_factory must be callable")
        if result_sink is not None and not callable(result_sink):
            raise TypeError("result_sink must be callable")
        self.binding_factory = binding_factory
        self.result_sink = result_sink

    def dispatch(
        self,
        *,
        notebook_id: str,
        option_id: str,
        authorization: OptionExecutionAuthorization,
        materialization: Any,
        draft: Mapping[str, Any],
        context: Any,
    ) -> NotebookExecutionDispatch:
        from .custom_dispatcher import CustomCapabilityDispatcher
        from .execution_receipt import CapabilityDispatchReceipt

        if not isinstance(authorization, OptionExecutionAuthorization):
            raise _receipt_error("execution gateway authorization is invalid")
        # This gateway is the only local experimental execution seam.  Keep
        # the high-risk opt-in and operation identity at the last trusted
        # boundary as well as in NotebookService, so a future server wiring
        # mistake cannot route a standard/low-risk authorization here.
        if (
            authorization.operation_id != "model.custom"
            or authorization.risk_level != "high"
            or authorization.execution_mode != "experimental_confirm_and_execute"
        ):
            raise _receipt_error(
                "experimental_confirm_and_execute is required for model.custom execution"
            )
        binding = self.binding_factory(
            notebook_id=notebook_id,
            option_id=option_id,
            authorization=authorization,
            materialization=materialization,
            draft=draft,
            context=context,
        )
        if not isinstance(binding, NotebookCapabilityDispatchBinding):
            raise _receipt_error("execution gateway binding factory returned an invalid binding")
        if binding.intent.intent_id != authorization.run_intent_id:
            raise _receipt_error("execution binding intent does not match authorization")
        if binding.intent.draft_hash != authorization.draft_hash:
            raise _receipt_error("execution binding Draft does not match authorization")
        if binding.intent.binding_ref != authorization.capability_resolution_binding_ref:
            raise _receipt_error("execution binding resolution does not match authorization")
        if binding.policy.profile_id != "darwin-seatbelt-experimental-v1":
            raise _receipt_error(
                "model.custom execution requires the darwin experimental containment profile"
            )
        if binding.policy.resource_enforcement != "observed_memory":
            raise _receipt_error(
                "model.custom execution requires observed-memory experimental enforcement"
            )

        if binding.canary.status != "supported":
            return NotebookExecutionDispatch(
                authorization_id=authorization.authorization_id,
                run_intent_id=authorization.run_intent_id,
                status="unsupported",
            )
        request = binding.request_factory(binding.attempt_id)
        from ..native_containment.contracts import ContainmentRequest

        if not isinstance(request, ContainmentRequest):
            raise _receipt_error("execution binding request factory returned an invalid request")
        if request.attempt_id != binding.attempt_id:
            raise _receipt_error("execution binding request attempt does not match reservation")
        reserved = binding.coordinator.reserve(
            authorization=authorization,
            intent=binding.intent,
            plan=binding.plan,
            expectations=binding.expectations,
            owner_id=binding.owner_id,
            lease_seconds=binding.lease_seconds,
            attempt_id=binding.attempt_id,
            lease_epoch=binding.lease_epoch,
            executor_idempotency_key=binding.executor_idempotency_key,
            reservation_id=binding.reservation_id,
            reservation_idempotency_key=binding.reservation_idempotency_key,
            now=binding.now,
        )
        if not isinstance(reserved, CapabilityDispatchReceipt):
            raise _receipt_error("execution coordinator returned an invalid reservation")
        running = binding.coordinator.spawn_and_acknowledge(
            receipt=reserved,
            owner_id=binding.owner_id,
            executor=binding.executor,
            request=request,
            policy=binding.policy,
            canary=binding.canary,
        )
        if running.status == "dispatch_unknown":
            return NotebookExecutionDispatch(
                authorization_id=authorization.authorization_id,
                run_intent_id=authorization.run_intent_id,
                status="dispatch_unknown",
            )
        if running.status != "running":
            raise _receipt_error("execution coordinator did not acknowledge a running attempt")
        try:
            result = CustomCapabilityDispatcher.dispatch(
                intent=binding.intent,
                plan=binding.plan,
                receipt=running,
                request=request,
                policy=binding.policy,
                broker=binding.broker,
            )
            if self.result_sink is not None:
                self.result_sink(result)
            if result.status != "completed":
                # A typed child failure is not a successful Notebook result,
                # and this gateway does not have the server-owned artifact
                # aggregate needed to close the CF4 journals as ``failed``.
                # Fence the unique attempt instead of reporting it as still
                # running or silently inventing an artifact validation.
                binding.coordinator.isolate_dispatch_unknown(
                    running,
                    reason="capability execution ended before artifact reconciliation",
                )
                return NotebookExecutionDispatch(
                    authorization_id=authorization.authorization_id,
                    run_intent_id=authorization.run_intent_id,
                    status="dispatch_unknown",
                )
            if binding.completion_factory is None:
                binding.coordinator.isolate_dispatch_unknown(
                    running,
                    reason="completed capability has no trusted artifact completion binding",
                )
                return NotebookExecutionDispatch(
                    authorization_id=authorization.authorization_id,
                    run_intent_id=authorization.run_intent_id,
                    status="dispatch_unknown",
                )
            completion = binding.completion_factory(
                result=result,
                receipt=running,
                binding=binding,
            )
            if not isinstance(completion, CapabilityExecutionCompletion):
                raise _receipt_error("completion factory returned an invalid completion")
            reconciled = binding.coordinator.reconcile(
                running,
                owner_id=binding.owner_id,
                artifact_validation=completion.artifact_validation,
                object_graph_ref=completion.object_graph_ref,
                termination_proof=completion.termination_proof,
                terminal_reconciliation=completion.terminal_reconciliation,
            )
            if reconciled.status not in {"consumed", "failed"}:
                raise _receipt_error("CF4 reconciliation did not reach a terminal state")
            terminal_status = "completed" if reconciled.status == "consumed" else "failed"
            return NotebookExecutionDispatch(
                authorization_id=authorization.authorization_id,
                run_intent_id=authorization.run_intent_id,
                status=terminal_status,
                run_id=binding.intent.run_id,
                attempt_id=reconciled.attempt_id,
                receipt_ref=reconciled.content_digest,
                completion_ref=completion.content_digest,
                artifact_validation_ref=completion.artifact_validation.aggregate_ref,
                object_graph_ref=completion.object_graph_ref,
                assessment_ref=result.assessment_ref if terminal_status == "completed" else None,
                output_bundle_ref=result.output_bundle_ref if terminal_status == "completed" else None,
            )
        except Exception as error:
            try:
                binding.coordinator.isolate_dispatch_unknown(
                    running,
                    reason="trusted capability result handoff failed",
                )
            except Exception as isolation_error:
                raise _receipt_error(
                    "capability result failed and dispatch_unknown isolation failed"
                ) from isolation_error
            return NotebookExecutionDispatch(
                authorization_id=authorization.authorization_id,
                run_intent_id=authorization.run_intent_id,
                status="dispatch_unknown",
            )
        raise _receipt_error("unreachable capability dispatch state")


class NotebookCapabilityBridge:
    """Construct a deterministic intent without creating a Run or directory."""

    @staticmethod
    def prepare_intent(
        *,
        authorization: OptionExecutionAuthorization,
        run_id: str,
        input_contract_ref: str,
        output_contract_ref: str,
        host_containment_ref: str,
        host_validity_revision: int,
        bundle_validity_revision: int,
        evidence_validity_revision: int,
        admission_validity_revision: int,
        namespace_derivation_revision: int = 1,
        artifact_producer_revision: int = 1,
        graph_producer_revision: int = 1,
        trace_producer_revision: int = 1,
        slot_mapping_revision: int = 1,
        harness_abi_revision: int = 1,
        protocol_revision: int = 1,
    ) -> PreparedCapabilityRun:
        if not isinstance(authorization, OptionExecutionAuthorization):
            raise _receipt_error("authorization must be an OptionExecutionAuthorization")
        if authorization.status not in {"issued", "claimed", "dispatch_reserved", "running"}:
            raise _receipt_error("authorization is not usable for intent preparation")
        run_id = _identifier(run_id, "run_id")
        draft_id = _identifier(authorization.draft_id, "draft_id")
        intent_id = _identifier(authorization.run_intent_id, "intent_id")
        namespace_prefix = f"{authorization.authorization_id}-{authorization.option_id}"
        intent = PreparedRunIntent(
            intent_id=intent_id,
            draft_id=draft_id,
            draft_hash=authorization.draft_hash,
            binding_ref=authorization.capability_resolution_binding_ref,
            binding_revision=authorization.binding_revision,
            capability_ref=authorization.capability_ref,
            bundle_ref=authorization.bundle_ref,
            evidence_ref=authorization.evidence_ref,
            admission_ref=authorization.admission_ref,
            runtime_policy_ref=authorization.runtime_policy_ref,
            host_containment_ref=host_containment_ref,
            operation_id=authorization.operation_id,
            run_id=run_id,
            input_graph_fingerprint=authorization.input_graph_fingerprint,
            input_contract_ref=input_contract_ref,
            output_contract_ref=output_contract_ref,
            consumer_projection_ref=authorization.consumer_projection_ref,
            host_validity_revision=_revision(host_validity_revision, "host_validity_revision"),
            bundle_validity_revision=_revision(bundle_validity_revision, "bundle_validity_revision"),
            evidence_validity_revision=_revision(evidence_validity_revision, "evidence_validity_revision"),
            admission_validity_revision=_revision(admission_validity_revision, "admission_validity_revision"),
            artifact_namespace=f"artifact-{namespace_prefix}",
            graph_edge_namespace=f"graph-{namespace_prefix}",
            trace_event_namespace=f"trace-{namespace_prefix}",
            namespace_derivation_revision=_revision(namespace_derivation_revision, "namespace_derivation_revision"),
            artifact_producer_revision=_revision(artifact_producer_revision, "artifact_producer_revision"),
            graph_producer_revision=_revision(graph_producer_revision, "graph_producer_revision"),
            trace_producer_revision=_revision(trace_producer_revision, "trace_producer_revision"),
            slot_mapping_revision=_revision(slot_mapping_revision, "slot_mapping_revision"),
            harness_abi_revision=_revision(harness_abi_revision, "harness_abi_revision"),
            protocol_revision=_revision(protocol_revision, "protocol_revision"),
        )
        return PreparedCapabilityRun(
            intent=intent,
            draft_id=draft_id,
            draft_hash=authorization.draft_hash,
            run_id=run_id,
        )


__all__ = [
    "AuthorizedCapabilityExecutionGateway",
    "CapabilityExecutionCompletion",
    "NotebookCapabilityBridge",
    "NotebookCapabilityDispatchBinding",
    "NotebookCapabilityExecutionGateway",
    "NotebookExecutionDispatch",
    "PreparedCapabilityRun",
]
