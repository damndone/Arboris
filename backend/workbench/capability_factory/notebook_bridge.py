"""Notebook-to-dispatch bridge for the exact CF4 execution handoff."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

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


@dataclass(frozen=True, slots=True)
class PreparedCapabilityRun:
    """The pure output of the Draft/authorization preparation stage."""

    intent: PreparedRunIntent
    draft_id: str
    draft_hash: str
    run_id: str


@dataclass(frozen=True, slots=True)
class NotebookExecutionDispatch:
    """Server-owned result of one explicit CF4 dispatch request.

    This is deliberately a dispatch receipt, not an artifact/result callback.
    Only the trusted gateway may construct it; Notebook never accepts these
    fields from the Agent or browser.
    """

    authorization_id: str
    run_intent_id: str
    status: Literal["dispatch_reserved", "running", "unsupported", "dispatch_unknown"]
    run_id: str | None = None
    attempt_id: str | None = None
    receipt_ref: str | None = None

    def __post_init__(self) -> None:
        _identifier(self.authorization_id, "authorization_id")
        _identifier(self.run_intent_id, "run_intent_id")
        if self.status not in {
            "dispatch_reserved",
            "running",
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
        if self.status in {"dispatch_reserved", "running"} and not all(
            (self.run_id, self.attempt_id, self.receipt_ref)
        ):
            raise _receipt_error(
                "successful Notebook dispatch requires run, attempt, and receipt refs"
            )
        if self.status in {"unsupported", "dispatch_unknown"} and self.run_id is not None:
            raise _receipt_error(
                "unsupported or unknown Notebook dispatch cannot expose a run id"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "authorization_id": self.authorization_id,
            "run_intent_id": self.run_intent_id,
            "status": self.status,
            "run_id": self.run_id,
            "attempt_id": self.attempt_id,
            "receipt_ref": self.receipt_ref,
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
    "NotebookCapabilityBridge",
    "NotebookCapabilityExecutionGateway",
    "NotebookExecutionDispatch",
    "PreparedCapabilityRun",
]
