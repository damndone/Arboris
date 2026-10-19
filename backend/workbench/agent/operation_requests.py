"""Typed admission shared by Agent and deterministic operation adapters.

This boundary creates pending proposals only. Confirmation, risk authorization,
execution leases and idempotency remain with their existing owners.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .events import AgentEventStream
from .chains import session_owns_chain
from .operations import OperationDefinition, OperationRegistry
from .proposals import ProposalInvocation, ProposalRevision, ProposalStore
from .session import JsonlSessionRepository


@dataclass(frozen=True)
class OperationRequest:
    """An operation's existing fields, without caller-owned scope authority.

    Registry validation and ProposalStore's sequence normalization retain their
    original ordering; constructing the envelope performs no new validation.
    """

    operation_id: str
    target: dict[str, Any]
    preconditions: dict[str, Any]
    changes: dict[str, Any]
    evidence_refs: Iterable[str]
    expected_effect: Iterable[str]
    risks: Iterable[str]
    operation_version: str = "v1"

    @classmethod
    def from_arguments(cls, arguments: Mapping[str, Any]) -> OperationRequest:
        """Adapt the existing tool schema without changing its wire fields."""

        return cls(
            operation_id=arguments["operation_id"],
            operation_version=arguments.get("operation_version", "v1"),
            target=arguments["target"],
            preconditions=arguments["preconditions"],
            changes=arguments["changes"],
            evidence_refs=arguments["evidence_refs"],
            expected_effect=arguments["expected_effect"],
            risks=arguments["risks"],
        )


@dataclass(frozen=True)
class OperationReceipt:
    """Admission outcome; pending never claims that execution has happened."""

    proposal: ProposalRevision
    status: Literal["pending"] = "pending"


def validate(request: OperationRequest, definition: OperationDefinition) -> None:
    """Apply an already-resolved declaration without persistence or authority."""

    definition.validate(
        target=request.target,
        preconditions=request.preconditions,
        changes=request.changes,
    )


def admit(
    request: OperationRequest,
    *,
    chain_id: str,
    session_id: str,
    command_id: str | None,
    proposal_id: str | None,
    repository: JsonlSessionRepository,
    operation_registry: OperationRegistry,
    proposal_store: ProposalStore,
    events: AgentEventStream,
    invocation: ProposalInvocation | None = None,
) -> OperationReceipt:
    """Validate scope and the declaration before persisting the original records."""

    if not session_owns_chain(repository, session_id=session_id, chain_id=chain_id):
        raise ValueError("proposal session must be a matching chain session")
    definition = operation_registry.require(request.operation_id, request.operation_version)
    validate(request, definition)
    create = proposal_store.create if invocation is None else proposal_store.create_prepared
    proposal = create(
        session_id=session_id,
        chain_id=chain_id,
        operation_id=request.operation_id,
        operation_version=request.operation_version,
        target=request.target,
        preconditions=request.preconditions,
        changes=request.changes,
        evidence_refs=request.evidence_refs,
        expected_effect=request.expected_effect,
        risks=request.risks,
        command_id=command_id,
        proposal_id=proposal_id,
        **({"invocation": invocation} if invocation is not None else {}),
    )
    proposal_content = json.dumps(proposal.to_dict(), ensure_ascii=False, sort_keys=True)
    if len(proposal_content) > 24_000:
        proposal_content = json.dumps({"proposal_id":proposal.proposal_id, "revision":proposal.revision,
            "operation_id":proposal.operation_id, "fingerprint":proposal.fingerprint, "status":"pending",
            "details_omitted":"Proposal exceeds the conversation budget; full details remain in its review card and audit record."})
    append = repository.append if invocation is None else repository.append_once
    append(
        session_id,
        "custom_message",
        {
            "message_type": "operation_proposal",
            "audience": "model",
            "content": proposal_content,
            "proposal": proposal.to_dict(),
        },
        **({"key": invocation.invocation_id, "stage": "operation_proposal"}
           if invocation is not None else {}),
    )
    events.emit(
        session_id,
        "proposal_ready",
        proposal.to_dict(),
        command_id=command_id,
        **({"event_id": _invocation_event_id(invocation, "proposal_ready")}
           if invocation is not None else {}),
    )
    events.emit(
        session_id,
        "needs_confirmation",
        {"proposal_id": proposal.proposal_id, "revision": proposal.revision},
        command_id=command_id,
        **({"event_id": _invocation_event_id(invocation, "needs_confirmation")}
           if invocation is not None else {}),
    )
    return OperationReceipt(proposal=proposal)


def _invocation_event_id(invocation: ProposalInvocation, stage: str) -> str:
    identity = json.dumps(["prepared-proposal", invocation.invocation_id, stage])
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()
