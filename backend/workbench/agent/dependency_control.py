"""Agent-side proposal binding for high-risk dependency acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..capability_factory.contracts import _digest, _sequence, _text
from ..capability_factory.dependency_contract import DependencyLock
from ..custom_capability.canonical import domain_digest


DEPENDENCY_ACQUISITION_OPERATION = "capability.dependency.acquire"
DEPENDENCY_OPERATION_VERSION = "v1"


class DependencyControlError(ValueError):
    """Raised when dependency acquisition skips an Agent control boundary."""


@dataclass(frozen=True, slots=True)
class DependencyAcquisitionProposal:
    proposal_id: str
    lock_ref: str
    policy_ref: str
    index_snapshot_ref: str
    artifact_refs: tuple[str, ...]
    status: str = "pending_confirmation"
    confirmation_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "proposal_id", _text(self.proposal_id, "proposal_id"))
        object.__setattr__(self, "lock_ref", _digest(self.lock_ref, "lock_ref"))
        object.__setattr__(self, "policy_ref", _digest(self.policy_ref, "policy_ref"))
        object.__setattr__(
            self,
            "index_snapshot_ref",
            _digest(self.index_snapshot_ref, "index_snapshot_ref"),
        )
        refs = _sequence(self.artifact_refs, "artifact_refs")
        if any(len(item) != 64 for item in refs):
            raise DependencyControlError("artifact_refs must contain SHA-256 digests")
        object.__setattr__(self, "artifact_refs", tuple(_digest(item, "artifact_ref") for item in refs))
        if self.status not in {"pending_confirmation", "confirmed"}:
            raise DependencyControlError("unsupported dependency proposal status")
        if self.status == "confirmed":
            if self.confirmation_ref is None:
                raise DependencyControlError("confirmed proposal needs confirmation_ref")
            object.__setattr__(self, "confirmation_ref", _digest(self.confirmation_ref, "confirmation_ref"))
        elif self.confirmation_ref is not None:
            raise DependencyControlError("pending proposal cannot have confirmation_ref")

    @property
    def operation_id(self) -> str:
        return DEPENDENCY_ACQUISITION_OPERATION

    @property
    def operation_version(self) -> str:
        return DEPENDENCY_OPERATION_VERSION

    @property
    def risk_level(self) -> str:
        return "high"

    @property
    def confirmation_policy(self) -> str:
        return "required"

    @property
    def risk_authorization_policy(self) -> str:
        return "explicit_single_use"

    @property
    def user_data_access(self) -> bool:
        return False

    @property
    def execution_allowed(self) -> bool:
        """CF2 creates a binding only; no fetched code can execute here."""

        return False

    @property
    def content_digest(self) -> str:
        return domain_digest(
            "workbench.capability_factory.dependency_acquisition_proposal/v1",
            {
                "proposal_id": self.proposal_id,
                "operation_id": self.operation_id,
                "operation_version": self.operation_version,
                "lock_ref": self.lock_ref,
                "policy_ref": self.policy_ref,
                "index_snapshot_ref": self.index_snapshot_ref,
                "artifact_refs": list(self.artifact_refs),
            },
        )

    def risk_binding(self) -> dict[str, Any]:
        if self.status != "confirmed":
            raise DependencyControlError("dependency acquisition requires user confirmation")
        return {
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "proposal_id": self.proposal_id,
            "proposal_digest": self.content_digest,
            "lock_ref": self.lock_ref,
            "index_snapshot_ref": self.index_snapshot_ref,
            "risk_level": self.risk_level,
            "risk_authorization_policy": self.risk_authorization_policy,
        }


class DependencyAcquisitionControl:
    """Produce a high-risk proposal without registering an executable tool."""

    def create_proposal(
        self,
        *,
        lock: DependencyLock,
        index_snapshot_ref: str,
        proposal_id: str,
    ) -> DependencyAcquisitionProposal:
        if not isinstance(lock, DependencyLock):
            raise DependencyControlError("lock must be a DependencyLock")
        return DependencyAcquisitionProposal(
            proposal_id=proposal_id,
            lock_ref=lock.content_digest,
            policy_ref=lock.resolver_policy_digest,
            index_snapshot_ref=index_snapshot_ref,
            artifact_refs=tuple(item.artifact_digest for item in lock.requirements),
        )

    def confirm(
        self,
        proposal: DependencyAcquisitionProposal,
        *,
        confirmation_ref: str,
    ) -> DependencyAcquisitionProposal:
        if not isinstance(proposal, DependencyAcquisitionProposal):
            raise DependencyControlError("proposal must be a DependencyAcquisitionProposal")
        if proposal.status != "pending_confirmation":
            raise DependencyControlError("dependency proposal is not pending confirmation")
        try:
            confirmation_ref = _digest(confirmation_ref, "confirmation_ref")
        except ValueError as error:
            raise DependencyControlError(str(error)) from error
        return DependencyAcquisitionProposal(
            proposal_id=proposal.proposal_id,
            lock_ref=proposal.lock_ref,
            policy_ref=proposal.policy_ref,
            index_snapshot_ref=proposal.index_snapshot_ref,
            artifact_refs=proposal.artifact_refs,
            status="confirmed",
            confirmation_ref=confirmation_ref,
        )


__all__ = [
    "DEPENDENCY_ACQUISITION_OPERATION",
    "DEPENDENCY_OPERATION_VERSION",
    "DependencyAcquisitionControl",
    "DependencyAcquisitionProposal",
    "DependencyControlError",
]
