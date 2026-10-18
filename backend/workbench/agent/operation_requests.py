"""Typed admission shared by Agent and deterministic operation adapters.

This boundary creates pending proposals only. Confirmation, risk authorization,
execution leases and idempotency remain with their existing owners.
"""
from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

from .events import AgentEventStream
from .operations import OperationRegistry
from .proposals import ProposalRevision, ProposalStore
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
) -> OperationReceipt:
    """Validate scope and the declaration before persisting the original records."""

    metadata = repository.get_metadata(session_id)
    if metadata.get("role") != "chain" or metadata.get("chain_id") != chain_id:
        raise ValueError("proposal session must be a matching chain session")
    definition = operation_registry.require(request.operation_id, request.operation_version)
    definition.validate(target=request.target, preconditions=request.preconditions, changes=request.changes)
    proposal = proposal_store.create(
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
    )
    repository.append(
        session_id,
        "custom_message",
        {
            "message_type": "operation_proposal",
            "audience": "model",
            "content": json.dumps(proposal.to_dict(), ensure_ascii=False, sort_keys=True),
            "proposal": proposal.to_dict(),
        },
    )
    events.emit(
        session_id,
        "proposal_ready",
        proposal.to_dict(),
        command_id=command_id,
    )
    events.emit(
        session_id,
        "needs_confirmation",
        {"proposal_id": proposal.proposal_id, "revision": proposal.revision},
        command_id=command_id,
    )
    return OperationReceipt(proposal=proposal)
